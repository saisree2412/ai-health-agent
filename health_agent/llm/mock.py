"""Deterministic mock LLM client for offline tests and demos.

Drives the agent loop through a scripted "2 slices pepperoni pizza" scenario:

    Turn 1 (executor)   →  3 parallel tool_calls: log_meal, check_food_against_profile,
                           get_today_macros
    Turn 2 (executor)   →  Suggestion JSON describing the meal + warnings
    Turn 3 (verifier)   →  SafetyVerdict JSON via response_format=json_schema

The mock picks a response by inspecting the *latest* message in the history,
not by counting turns — so the agent loop can replay it deterministically.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from health_agent.llm.types import (
    ChatResponse,
    Message,
    ReasoningLevel,
    ToolCall,
    ToolDef,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class MockClient:
    """Scripted offline client. Same interface as V2Client."""

    def __init__(self) -> None:
        self._suggestion_emitted = False  # so the next "tool" turn doesn't loop

    async def chat(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDef] | None = None,
        cache_system: bool = False,
        reasoning: ReasoningLevel = "off",
        response_format: dict[str, Any] | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> ChatResponse:
        # ── Verifier branch — json_schema response_format means "be the verifier" ─
        if response_format and response_format.get("type") == "json_schema":
            return self._verifier_response(messages, response_format)

        # ── Executor branch ────────────────────────────────────────────────────
        last_user = next(
            (m for m in reversed(messages) if m.role == "user" and m.content), None
        )
        user_text = (last_user.content if last_user else "") or ""
        has_tool_results = any(m.role == "tool" for m in messages)

        # First executor turn: emit 3 parallel tool_calls for the pizza scenario.
        if "pizza" in user_text.lower() and not has_tool_results:
            return ChatResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id=_new_id("call"),
                        name="log_meal",
                        arguments={
                            "food_name": "pepperoni pizza slice",
                            "servings": 2.0,
                            "slot": "lunch",
                        },
                    ),
                    ToolCall(
                        id=_new_id("call"),
                        name="check_food_against_profile",
                        arguments={"food_name": "pepperoni pizza slice"},
                    ),
                    ToolCall(
                        id=_new_id("call"),
                        name="get_today_macros",
                        arguments={},
                    ),
                ],
                provider_used="mock",
                raw={"mock_branch": "executor_initial_tools"},
            )

        # Second executor turn: emit a Suggestion JSON.
        if has_tool_results and not self._suggestion_emitted:
            self._suggestion_emitted = True
            suggestion = {
                "action": "suggest",
                "message": (
                    "Logged 2 slices of pepperoni pizza for lunch. That alone is about "
                    "1,366 mg of sodium — already two-thirds of your 2,000 mg/day target."
                ),
                "recommendations": [
                    {
                        "text": "For the next meal, aim for a low-sodium, fiber-rich option (e.g., grilled chicken + brown rice + steamed broccoli).",
                        "rationale": "You have hypertension and a 2,000 mg sodium goal; the rest of today should stay well under 700 mg.",
                        "reasoning_type": "inference",
                    }
                ],
                "warnings": [
                    "Today's sodium intake is on track to exceed the 2,000 mg target.",
                ],
            }
            return ChatResponse(
                content=json.dumps(suggestion),
                tool_calls=[],
                provider_used="mock",
                raw={"mock_branch": "executor_suggestion"},
            )

        # Fallback: small acknowledgment.
        return ChatResponse(
            content=json.dumps(
                {
                    "action": "confirm",
                    "what_was_done": "Noted.",
                    "summary": None,
                }
            ),
            provider_used="mock",
            raw={"mock_branch": "fallback_confirm"},
        )

    def _verifier_response(
        self, messages: list[Message], response_format: dict[str, Any]
    ) -> ChatResponse:
        """Mock verifier — flags pizza for sodium-vs-hypertension."""
        # Look for the candidate suggestion in the latest assistant content.
        candidate = ""
        for m in reversed(messages):
            if m.role == "assistant" and m.content:
                candidate = m.content
                break

        looks_high_sodium = "sodium" in candidate.lower() or "pizza" in candidate.lower()
        verdict = {
            "ok": True,
            "flags": (
                [
                    {
                        "severity": "warning",
                        "code": "sodium_vs_hypertension",
                        "message": (
                            "Today's logged sodium is high given the user's hypertension; "
                            "the suggested follow-up meal correctly steers low-sodium."
                        ),
                        "profile_evidence": "Condition: Hypertension; Goal: reduce_sodium to 2000 mg/day.",
                    }
                ]
                if looks_high_sodium
                else []
            ),
            "reason": (
                "Suggestion acknowledges the high-sodium intake and recommends a low-sodium "
                "follow-up consistent with the user's hypertension and sodium goal."
            ),
            "reasoning_type": "logic",
        }
        return ChatResponse(
            content=json.dumps(verdict),
            tool_calls=[],
            provider_used="mock",
            raw={"mock_branch": "verifier"},
        )

    async def aclose(self) -> None:
        return None
