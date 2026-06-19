"""LLM clients.

Three flavors, all behind the same `LLMClient` Protocol:

    OpenAICompatClient   — talks the OpenAI chat-completions wire format. Works
                           with Groq, OpenRouter, Ollama, OpenAI, Gemini's
                           OpenAI-compat endpoint, etc. This is the default.

    V2Client             — talks the llm_gatewayV2 native wire format
                           (cache_system, reasoning, response_format fields
                           passed through directly). Use when you have the
                           Session-5 gateway running on :8100.

    MockClient           — deterministic scripted responses for offline tests.

Pick via LLM_MODE env:  openai | v2 | mock  (default: openai).
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
from typing import Any, Protocol

import httpx

from health_agent.llm.types import (
    ChatResponse,
    Message,
    ReasoningLevel,
    ToolCall,
    ToolDef,
)


class LLMClient(Protocol):
    """Minimal interface implemented by all three clients."""

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
    ) -> ChatResponse: ...

    async def aclose(self) -> None: ...


# Status codes worth retrying with backoff.
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
DEFAULT_MAX_RETRIES = 3
# Cap on how long we'll wait for a single retry — protects against rogue
# Retry-After values telling us to sleep for minutes.
MAX_SINGLE_RETRY_S = 45.0


# Gemini & some Google APIs put the retry hint inside the JSON body, not the
# Retry-After header. Two shapes we know about:
#   1. message text: "Please retry in 21.398133084s."
#   2. retryInfo.retryDelay: "21s"
_RETRY_BODY_PATTERNS = (
    re.compile(r"retry in ([0-9.]+)\s*s", re.IGNORECASE),
    re.compile(r'"retryDelay"\s*:\s*"([0-9.]+)s?"'),
)


def _parse_retry_after_body(text: str) -> float | None:
    """Pull a retry-delay (seconds) out of the response body text, if present."""
    for pat in _RETRY_BODY_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


async def _post_with_retry(
    http: httpx.AsyncClient,
    url: str,
    body: dict[str, Any],
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> httpx.Response:
    """POST with exponential-backoff retry on 429 / 5xx-ish errors.

    Retry-delay source order:
      1. Retry-After header (RFC standard; honored by most providers).
      2. Body hints — Gemini's "retry in Xs" and retryDelay JSON fields.
      3. Exponential fallback: 1s → 2s → 4s with up to 0.5s jitter.

    All delays are capped at MAX_SINGLE_RETRY_S. Non-retryable status codes
    return immediately.
    """
    backoffs = [1.0, 2.0, 4.0]
    last_resp: httpx.Response | None = None
    for attempt in range(max_retries + 1):
        last_resp = await http.post(url, json=body)
        if last_resp.status_code not in RETRYABLE_STATUS_CODES or attempt == max_retries:
            return last_resp

        # 1. RFC Retry-After header
        delay: float | None = None
        retry_after = last_resp.headers.get("retry-after")
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = None

        # 2. Body hint (Gemini-style)
        if delay is None:
            delay = _parse_retry_after_body(last_resp.text)

        # 3. Exponential fallback
        if delay is None:
            delay = backoffs[min(attempt, len(backoffs) - 1)] + random.uniform(0, 0.5)

        delay = min(delay, MAX_SINGLE_RETRY_S)
        await asyncio.sleep(delay)
    assert last_resp is not None
    return last_resp


# ────────────────────────── OpenAI-compatible client ──────────────────────


# Providers that accept the OpenAI `reasoning_effort` field. Strict providers
# (HF, Mistral, …) 400 on unknown fields, so we omit it for them.
PROVIDERS_SUPPORTING_REASONING_EFFORT = {"openai", "openrouter", "gemini"}

# Providers that accept response_format={"type":"json_schema", ...}. Others
# only honor {"type":"json_object"}; we downgrade for them and rely on the
# schema embedded in the system prompt + Pydantic validation on our side.
PROVIDERS_SUPPORTING_JSON_SCHEMA = {"openai", "groq", "gemini"}

# Providers whose underlying routes commonly reject `response_format` outright
# (HF router → Novita/Together etc., some Together direct models). For these
# we omit the field entirely; the prompt + Pydantic validation handle JSON
# shape on our side.
PROVIDERS_REJECTING_RESPONSE_FORMAT = {"huggingface", "hf", "together"}


# Provider → (default base URL, default model). Override per-call or via env.
PROVIDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "groq":        ("https://api.groq.com/openai/v1",                "llama-3.3-70b-versatile"),
    "openrouter":  ("https://openrouter.ai/api/v1",                  "meta-llama/llama-3.3-70b-instruct"),
    "openai":      ("https://api.openai.com/v1",                     "gpt-4o-mini"),
    "gemini":      ("https://generativelanguage.googleapis.com/v1beta/openai",
                                                                     "gemini-2.0-flash"),
    "ollama":      ("http://localhost:11434/v1",                     "llama3.1"),
    "cerebras":    ("https://api.cerebras.ai/v1",                    "llama-3.3-70b"),
    # Hugging Face Inference Providers — routes to Together/Fireworks/Novita/etc.
    "huggingface": ("https://router.huggingface.co/v1",              "meta-llama/Llama-3.3-70B-Instruct"),
    "hf":          ("https://router.huggingface.co/v1",              "meta-llama/Llama-3.3-70B-Instruct"),
    "mistral":     ("https://api.mistral.ai/v1",                     "mistral-large-latest"),
    "together":    ("https://api.together.xyz/v1",                   "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
}


def _provider_config(provider: str | None) -> tuple[str, str, str | None]:
    """Resolve (base_url, model, api_key) from env, falling back to defaults."""
    name = (provider or os.getenv("LLM_PROVIDER") or "groq").lower()
    base, default_model = PROVIDER_DEFAULTS.get(name, PROVIDER_DEFAULTS["groq"])
    base_url = os.getenv("LLM_BASE_URL", base).rstrip("/")
    model = os.getenv("LLM_MODEL", default_model)
    # API key resolution — try in this order:
    #   1. LLM_API_KEY (override for any provider)
    #   2. <PROVIDER>_API_KEY (e.g., GROQ_API_KEY)
    #   3. Provider-specific aliases for the ones with non-standard env names.
    aliases: dict[str, list[str]] = {
        "huggingface": ["HF_TOKEN", "HF_API_KEY", "HUGGINGFACE_TOKEN"],
        "hf":          ["HF_TOKEN", "HF_API_KEY", "HUGGINGFACE_TOKEN", "HUGGINGFACE_API_KEY"],
    }
    candidates = ["LLM_API_KEY", f"{name.upper()}_API_KEY", *aliases.get(name, [])]
    api_key = next((os.getenv(k) for k in candidates if os.getenv(k)), None)
    return base_url, model, api_key


def _to_openai_tools(tools: list[ToolDef]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def _to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Translate our internal Message shape to OpenAI's wire format."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            out.append({
                "role": "tool",
                "tool_call_id": m.tool_call_id,
                "content": m.content or "",
            })
        elif m.role == "assistant" and m.tool_calls:
            out.append({
                "role": "assistant",
                "content": m.content,  # may be None — that's fine
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in m.tool_calls
                ],
            })
        else:
            out.append({"role": m.role, "content": m.content or ""})
    return out


def _from_openai_tool_calls(raw: list[dict[str, Any]] | None) -> list[ToolCall]:
    """Normalize the provider's tool_calls into our typed ToolCall list.

    Quirks we handle:
      * arguments may be null, "", "null", or already a dict — all → {}/{} or dict.
      * arguments may be a JSON string (OpenAI/Groq) or a dict (some providers).
      * malformed JSON in arguments is treated as no-args rather than crashing.
    """
    if not raw:
        return []
    parsed: list[ToolCall] = []
    for tc in raw:
        fn = tc.get("function", {}) or {}
        args_raw = fn.get("arguments")
        args: dict[str, Any]
        if args_raw is None or args_raw == "" or args_raw == "null":
            args = {}
        elif isinstance(args_raw, dict):
            args = args_raw
        elif isinstance(args_raw, str):
            try:
                loaded = json.loads(args_raw)
                args = loaded if isinstance(loaded, dict) else {}
            except json.JSONDecodeError:
                args = {}
        else:
            args = {}
        parsed.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))
    return parsed


class OpenAICompatClient:
    """OpenAI chat-completions wire format. Works with Groq, OpenRouter, Ollama,
    OpenAI, Gemini's openai-compat endpoint, etc.

    cache_system  — no-op here; OpenAI-compat providers do implicit prefix caching.
    reasoning     — only honored by providers that expose `reasoning_effort`.
    """

    def __init__(self, provider: str | None = None, timeout_s: float = 120.0) -> None:
        base_url, model, api_key = _provider_config(provider)
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.provider = (provider or os.getenv("LLM_PROVIDER") or "groq").lower()
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        # OpenRouter wants extra identifying headers; harmless elsewhere.
        if self.provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/local/health-agent"
            headers["X-Title"] = "health-agent"
        # SSL verification — default on, but allow disabling for corporate
        # networks that MITM TLS with a self-signed root. Also accepts a path
        # to a custom CA bundle (LLM_CA_BUNDLE).
        verify_env = (os.getenv("LLM_VERIFY_SSL") or "true").lower()
        ca_bundle = os.getenv("LLM_CA_BUNDLE")
        verify: bool | str
        if ca_bundle:
            verify = ca_bundle
        elif verify_env in ("false", "0", "no"):
            verify = False
        else:
            verify = True
        self._http = httpx.AsyncClient(timeout=timeout_s, headers=headers, verify=verify)

    async def chat(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDef] | None = None,
        cache_system: bool = False,  # implicit at the provider level
        reasoning: ReasoningLevel = "off",
        response_format: dict[str, Any] | None = None,
        provider: str | None = None,  # ignored (single-provider per client)
        model: str | None = None,  # per-call override (e.g., lighter verifier model)
    ) -> ChatResponse:
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": _to_openai_messages(messages),
        }
        if tools:
            body["tools"] = _to_openai_tools(tools)
            body["tool_choice"] = "auto"
        if response_format and response_format.get("type") == "json_schema":
            if self.provider in PROVIDERS_REJECTING_RESPONSE_FORMAT:
                # Skip the field entirely; prompt + Pydantic do the work.
                pass
            elif self.provider in PROVIDERS_SUPPORTING_JSON_SCHEMA:
                # OpenAI shape: {"type":"json_schema","json_schema":{"name":..,"schema":{..},"strict":...}}
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_format.get("name", "response"),
                        "schema": response_format["schema"],
                        "strict": False,  # our schemas use unions/anyOf — strict mode is fussy
                    },
                }
            else:
                # Mistral/Cerebras and friends: only `json_object` is supported.
                # Schema is inlined in the verifier prompt; Pydantic validates.
                body["response_format"] = {"type": "json_object"}
        elif response_format:
            body["response_format"] = response_format
        if (
            reasoning in ("low", "medium", "high")
            and self.provider in PROVIDERS_SUPPORTING_REASONING_EFFORT
        ):
            # Honored by providers that expose it. Others 400 on unknown fields.
            body["reasoning_effort"] = reasoning

        resp = await _post_with_retry(self._http, f"{self.base_url}/chat/completions", body)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            # Surface the provider's error body — much more useful than just the status.
            raise RuntimeError(
                f"{self.provider} returned {resp.status_code}: {resp.text[:500]}"
            ) from None
        data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        return ChatResponse(
            content=msg.get("content"),
            tool_calls=_from_openai_tool_calls(msg.get("tool_calls")),
            provider_used=self.provider,
            raw=data,
        )

    async def aclose(self) -> None:
        await self._http.aclose()


# ────────────────────────── V2 (llm_gatewayV2) client ─────────────────────


class V2Client:
    """Async HTTP client for llm_gatewayV2 @ :8100. Use only if V2 is running."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("LLM_GATEWAY_URL", "http://localhost:8100")).rstrip("/")
        self._http = httpx.AsyncClient(timeout=timeout_s)

    async def chat(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDef] | None = None,
        cache_system: bool = False,
        reasoning: ReasoningLevel = "off",
        response_format: dict[str, Any] | None = None,
        provider: str | None = None,
        model: str | None = None,  # V2 picks model per provider; ignored here
    ) -> ChatResponse:
        body: dict[str, Any] = {
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "cache_system": cache_system,
            "reasoning": reasoning,
        }
        if tools:
            body["tools"] = [t.model_dump() for t in tools]
        if response_format:
            body["response_format"] = response_format
        if provider:
            body["provider"] = provider
        if model:
            body["model"] = model

        resp = await _post_with_retry(self._http, f"{self.base_url}/v1/chat", body)
        resp.raise_for_status()
        data = resp.json()

        return ChatResponse(
            content=data.get("content"),
            tool_calls=[ToolCall.model_validate(tc) for tc in data.get("tool_calls") or []],
            provider_used=data.get("provider_used") or data.get("provider"),
            raw=data,
        )

    async def aclose(self) -> None:
        await self._http.aclose()


# ────────────────────────── factory ───────────────────────────────────────


def make_client(mode: str | None = None) -> LLMClient:
    """Factory keyed by LLM_MODE env var.

    LLM_MODE values:
        openai (default)  → OpenAICompatClient (uses LLM_PROVIDER, default groq)
        v2                → V2Client (requires llm_gatewayV2 on :8100)
        mock              → MockClient (deterministic, offline)
    """
    mode = (mode or os.getenv("LLM_MODE") or "openai").lower()
    if mode == "mock":
        from health_agent.llm.mock import MockClient  # lazy to avoid cycle

        return MockClient()
    if mode == "v2":
        return V2Client()
    return OpenAICompatClient()
