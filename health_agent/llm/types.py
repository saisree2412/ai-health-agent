"""Canonical request/response shapes for the LLM gateway.

These are *gateway-shaped* (not provider-shaped) — V2 normalizes all 7 free
providers to this same set of fields. The V2 client just maps Python → JSON;
the mock client uses the same shapes for offline tests.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Role = Literal["system", "user", "assistant", "tool"]
ReasoningLevel = Literal["off", "low", "medium", "high"]


class _Loose(BaseModel):
    """Tolerant config — gateway sometimes adds fields we don't model yet."""

    model_config = ConfigDict(extra="ignore")


class ToolDef(_Loose):
    """One tool advertised to the model in the `tools` field."""

    name: str
    description: str
    input_schema: dict[str, Any] = Field(
        description="JSON Schema describing the tool's arguments."
    )


class ToolCall(_Loose):
    """One tool invocation the model wants the agent to dispatch."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(_Loose):
    """One message in the chat history.

    `role='tool'` requires `tool_call_id` so the gateway can pair the result
    back to the call. `role='assistant'` may carry `tool_calls` (when the model
    is asking for tools) instead of `content`.
    """

    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


class ChatResponse(_Loose):
    """What the LLM gateway returned for a single chat() call."""

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    provider_used: str | None = None
    raw: dict[str, Any] | None = Field(
        default=None,
        description="Original gateway payload — kept for tracing/debugging.",
    )

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)
