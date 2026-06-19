"""Agent loop — executor + verifier with parallel tool dispatch.

Per-turn flow:

    1. Build messages: [system(executor_prompt + cached_prefix),
                        user(volatile_suffix),
                        ...history,
                        user(actual_input)]

    2. EXECUTOR loop (up to MAX_TOOL_ROUNDS rounds):
         - call LLM with tools advertised
         - if tool_calls returned → dispatch in parallel via TaskGroup,
           append results, repeat
         - if content returned → parse as AgentReply (Suggestion/Question/Confirmation)

    3. VERIFIER call:
         - response_format=json_schema(SafetyVerdict)
         - cheaper provider is fine (e.g., Groq)

    4. If verdict has any severity="block" flag → re-run executor with
       flags pinned into context (up to MAX_VERIFIER_RETRIES).

    5. Return AgentTrace with every TraceEvent in order plus final_reply.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import TypeAdapter, ValidationError

from health_agent.db.repos import Repos
from health_agent.llm.client import LLMClient
from health_agent.llm.prompts import executor_system_prompt, verifier_system_prompt
from health_agent.llm.types import Message, ToolCall, ToolDef
from health_agent.models import (
    AgentReply,
    AgentTrace,
    SafetyFlag,
    SafetyVerdict,
    Suggestion,
    TraceEvent,
)
from health_agent.core.profile_builder import ProfileBuilder


MAX_TOOL_ROUNDS = 6
MAX_VERIFIER_RETRIES = 2


# ─────────────────────────── tool result helpers ───────────────────────────


def _extract_tool_result(result: Any) -> Any:
    """Pull the structured payload out of an MCP CallToolResult.

    MCP wraps list returns as {"result": [...]} because JSON Schema requires
    an object root. We unwrap that here so the rest of the agent (and the
    LLM that sees the tool result) gets the underlying value directly.
    """
    sc = getattr(result, "structuredContent", None)
    if sc is not None:
        if isinstance(sc, dict) and list(sc.keys()) == ["result"]:
            return sc["result"]
        return sc
    content = getattr(result, "content", None) or []
    texts: list[str] = []
    for c in content:
        text = getattr(c, "text", None)
        if text is None:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            texts.append(text)
    if len(texts) == 1:
        return texts[0]
    return texts or None


# ─────────────────────────── AgentLoop ─────────────────────────────────────


class AgentLoop:
    """One instance per chat session. Call start() once, run_turn() per turn,
    stop() when done."""

    def __init__(
        self,
        repos: Repos,
        llm: LLMClient,
        executor_provider: str | None = None,
        verifier_provider: str | None = None,
    ) -> None:
        self.repos = repos
        self.llm = llm
        self.profile_builder = ProfileBuilder(repos)
        self.executor_provider = executor_provider
        self.verifier_provider = verifier_provider

        self._stdio_ctx: Any = None
        self._session_ctx: Any = None
        self._session: ClientSession | None = None
        self._tools: list[ToolDef] = []

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def start(self, mcp_command: list[str] | None = None) -> None:
        """Spawn the MCP server as a subprocess and enumerate tools.

        Note: StdioServerParameters' default env is a minimal sanitized subset
        that strips custom vars like DB_PATH. We pass the full parent env so
        the subprocess sees our config.
        """
        import os as _os

        cmd = mcp_command or [sys.executable, "-m", "health_agent.mcp.server"]
        params = StdioServerParameters(
            command=cmd[0],
            args=cmd[1:],
            env=dict(_os.environ),
        )

        self._stdio_ctx = stdio_client(params)
        read, write = await self._stdio_ctx.__aenter__()
        self._session_ctx = ClientSession(read, write)
        self._session = await self._session_ctx.__aenter__()
        await self._session.initialize()
        listed = await self._session.list_tools()
        self._tools = [
            ToolDef(
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema,
            )
            for t in listed.tools
        ]

    async def stop(self) -> None:
        if self._session_ctx is not None:
            await self._session_ctx.__aexit__(None, None, None)
            self._session_ctx = None
        if self._stdio_ctx is not None:
            await self._stdio_ctx.__aexit__(None, None, None)
            self._stdio_ctx = None
        await self.llm.aclose()

    # ── per turn ──────────────────────────────────────────────────────────

    async def run_turn(self, user_input: str, session_id: str | None = None) -> AgentTrace:
        sid = session_id or uuid.uuid4().hex[:8]
        trace = AgentTrace(session_id=sid, started_at=datetime.now())
        trace.events.append(
            TraceEvent(ts=datetime.now(), kind="user_message", payload={"text": user_input})
        )

        sys_prompt = executor_system_prompt() + "\n\n" + self.profile_builder.cached_prefix()
        messages: list[Message] = [
            Message(role="system", content=sys_prompt),
            Message(role="user", content=self.profile_builder.volatile_suffix()),
            Message(role="user", content=user_input),
        ]

        pinned_flags: list[SafetyFlag] = []

        for attempt in range(MAX_VERIFIER_RETRIES + 1):
            if pinned_flags:
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "PREVIOUS VERIFIER FLAGS — your prior reply was blocked. "
                            "Revise to address these and reply again:\n"
                            + json.dumps([f.model_dump() for f in pinned_flags], indent=2)
                        ),
                    )
                )
                pinned_flags = []

            candidate = await self._run_executor(messages, trace, attempt)
            if candidate is None:
                continue  # executor failed; loop & retry

            verdict = await self._run_verifier(candidate, trace)

            blocking = [f for f in verdict.flags if f.severity == "block"]
            if verdict.ok and not blocking:
                # Attach non-blocking warnings/info to a Suggestion before returning.
                if isinstance(candidate, Suggestion) and verdict.flags:
                    candidate.warnings.extend(
                        f.message for f in verdict.flags if f.severity in ("warning", "info")
                    )
                trace.final_reply = candidate
                trace.events.append(
                    TraceEvent(
                        ts=datetime.now(),
                        kind="final_reply",
                        payload=candidate.model_dump(mode="json"),
                    )
                )
                trace.finished_at = datetime.now()
                return trace

            pinned_flags = blocking or verdict.flags

        trace.events.append(
            TraceEvent(
                ts=datetime.now(),
                kind="error",
                payload={"stage": "verifier_retries_exhausted"},
            )
        )
        trace.finished_at = datetime.now()
        return trace

    # ── executor inner loop ──────────────────────────────────────────────

    async def _run_executor(
        self, messages: list[Message], trace: AgentTrace, attempt: int
    ) -> AgentReply | None:
        """Call the executor, dispatch tools in parallel until content is returned,
        validate it as an AgentReply. Returns None on persistent failure."""
        for tool_round in range(MAX_TOOL_ROUNDS):
            trace.events.append(
                TraceEvent(
                    ts=datetime.now(),
                    kind="executor_call",
                    payload={"round": tool_round, "verifier_attempt": attempt},
                )
            )
            resp = await self.llm.chat(
                messages,
                tools=self._tools,
                cache_system=True,
                # First round can use medium budget; later rounds are tighter.
                reasoning="medium" if tool_round == 0 else "low",
                provider=self.executor_provider,
            )

            if resp.tool_calls:
                messages.append(
                    Message(role="assistant", tool_calls=resp.tool_calls, content=resp.content)
                )
                results = await self._dispatch_tool_calls(resp.tool_calls, trace)
                for tc, result in zip(resp.tool_calls, results):
                    messages.append(
                        Message(
                            role="tool",
                            tool_call_id=tc.id,
                            content=json.dumps(result, default=str),
                        )
                    )
                continue

            # No tool_calls — must be the final content (an AgentReply JSON).
            if not resp.content:
                trace.events.append(
                    TraceEvent(
                        ts=datetime.now(),
                        kind="error",
                        payload={"stage": "executor_empty_reply"},
                    )
                )
                return None

            try:
                return TypeAdapter(AgentReply).validate_json(resp.content)
            except ValidationError as e:
                trace.events.append(
                    TraceEvent(
                        ts=datetime.now(),
                        kind="error",
                        payload={
                            "stage": "parse_executor_reply",
                            "errors": e.errors(),
                            "preview": resp.content[:500],
                        },
                    )
                )
                # Push the failure back into the conversation so executor can fix.
                messages.append(Message(role="assistant", content=resp.content))
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "Your reply did not validate against the AgentReply schema. "
                            "Return ONLY a JSON object matching the schema. "
                            f"Validation errors: {e.errors()}"
                        ),
                    )
                )
                continue

        return None  # MAX_TOOL_ROUNDS exhausted

    # ── verifier ──────────────────────────────────────────────────────────

    async def _run_verifier(self, candidate: AgentReply, trace: AgentTrace) -> SafetyVerdict:
        trace.events.append(TraceEvent(ts=datetime.now(), kind="verifier_call", payload={}))

        verifier_messages: list[Message] = [
            Message(
                role="system",
                content=(
                    verifier_system_prompt()
                    + "\n\n"
                    + self.profile_builder.cached_prefix()
                ),
            ),
            Message(
                role="user",
                content=(
                    "VOLATILE CONTEXT (today's state):\n"
                    + self.profile_builder.volatile_suffix()
                    + "\n\nCANDIDATE REPLY to verify:\n"
                    + candidate.model_dump_json()
                ),
            ),
        ]

        import os as _os

        verifier_model = _os.getenv("LLM_VERIFIER_MODEL")
        v_resp = await self.llm.chat(
            verifier_messages,
            cache_system=True,
            reasoning="medium",
            response_format={
                "type": "json_schema",
                "name": "SafetyVerdict",
                "schema": SafetyVerdict.model_json_schema(),
            },
            provider=self.verifier_provider,
            model=verifier_model,
        )

        try:
            verdict = SafetyVerdict.model_validate_json(v_resp.content or "{}")
        except ValidationError as e:
            verdict = SafetyVerdict(
                ok=False,
                flags=[
                    SafetyFlag(
                        severity="block",
                        code="verifier_malformed",
                        message=f"Verifier returned non-conforming JSON: {e.errors()[:1]}",
                        profile_evidence="n/a",
                    )
                ],
                reason="Verifier output failed schema validation.",
                reasoning_type="logic",
            )

        trace.events.append(
            TraceEvent(
                ts=datetime.now(),
                kind="verdict",
                payload=verdict.model_dump(mode="json"),
                reasoning_type=verdict.reasoning_type,
            )
        )
        return verdict

    # ── parallel tool dispatch via TaskGroup ─────────────────────────────

    async def _dispatch_tool_calls(
        self, tool_calls: list[ToolCall], trace: AgentTrace
    ) -> list[Any]:
        assert self._session is not None
        for tc in tool_calls:
            trace.events.append(
                TraceEvent(
                    ts=datetime.now(),
                    kind="tool_call",
                    payload={"id": tc.id, "name": tc.name, "arguments": tc.arguments},
                )
            )

        async def call_one(tc: ToolCall) -> Any:
            assert self._session is not None
            result = await self._session.call_tool(tc.name, tc.arguments)
            return _extract_tool_result(result)

        # asyncio.gather is the portable fan-out. On 3.11+ this could be
        # asyncio.TaskGroup for slightly tighter cancellation semantics, but
        # gather is equivalent for our all-or-fail dispatch.
        results: list[Any] = await asyncio.gather(*(call_one(tc) for tc in tool_calls))

        for tc, r in zip(tool_calls, results):
            trace.events.append(
                TraceEvent(
                    ts=datetime.now(),
                    kind="tool_result",
                    payload={"id": tc.id, "name": tc.name, "result": r},
                )
            )
        return results
