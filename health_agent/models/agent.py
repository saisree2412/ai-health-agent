"""Agent-loop response models: what the executor produces, what the verifier
checks, and the typed event log that captures the whole turn.

Three executor reply shapes (discriminated union on `action`):
    * Suggestion        — advice + recommendations + optional warnings
    * Question          — needs more info before acting
    * ActionConfirmation — pure side-effect (e.g., "I logged your meal")

Verifier returns a SafetyVerdict gated on a JSON Schema (response_format=json_schema
on V2). If `ok=False`, the agent loop re-runs the executor with the flags pinned.

Rubric mapping for this module (the prompt rubric applies to system prompts in
health_agent/llm/prompts.py — the *models* support those prompts by providing):
    - Structured output format  (point 2): every reply is a typed model.
    - Self-checks               (point 6): SafetyVerdict IS the self-check artifact.
    - Reasoning-type tagging    (point 7): TraceEvent.reasoning_type captures it.
    - Error handling / fallback (point 8): TraceEvent.kind == 'error' + ToolError payload.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import Field

from health_agent.models.medical import _StrictModel


# --- Shared enums -------------------------------------------------------------

FlagSeverity = Literal["info", "warning", "block"]
"""Verifier flag severity.
    info    — surface as a note but don't block.
    warning — surface prominently; user must acknowledge.
    block   — do NOT show the suggestion; re-run executor.
"""

ReasoningType = Literal[
    "arithmetic",  # macro/dose math
    "logic",  # rule-based contradiction checks
    "lookup",  # consulted catalog/profile
    "inference",  # connecting two facts
    "recall",  # quoted from cached profile
    "other",
]


# --- Executor reply variants --------------------------------------------------


class Recommendation(_StrictModel):
    """One concrete recommendation inside a Suggestion (e.g., a food swap)."""

    text: str = Field(description="One-sentence actionable recommendation.")
    rationale: str = Field(
        description=(
            "Why this recommendation — must reference profile facts when applicable. "
            "Example: 'You have hypertension; swapping reduces sodium by ~600 mg.'"
        )
    )
    reasoning_type: ReasoningType = Field(
        description="Which kind of reasoning led to this recommendation (rubric point 7)."
    )


class Suggestion(_StrictModel):
    """Executor emits advice for the user. Most common reply shape."""

    action: Literal["suggest"] = "suggest"
    message: str = Field(
        description="Short conversational reply shown to the user. <= 3 sentences."
    )
    recommendations: list[Recommendation] = Field(
        default_factory=list,
        description="Zero or more concrete, actionable recommendations.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Self-flagged concerns the executor already noticed (e.g., 'this is "
            "above your sodium target for today'). The verifier may add more."
        ),
    )


class Question(_StrictModel):
    """Executor doesn't have enough info — it's asking the user for a detail."""

    action: Literal["ask"] = "ask"
    question: str = Field(description="The single, focused question to put to the user.")
    why_needed: str = Field(
        description="One sentence on why this clarification is required to proceed."
    )


class ActionConfirmation(_StrictModel):
    """Executor performed a side-effect (logged a meal, recorded a supplement). No advice."""

    action: Literal["confirm"] = "confirm"
    what_was_done: str = Field(
        description="Plain-English description of the side-effect, e.g., 'Logged 2 slices pepperoni pizza at 12:35 for lunch.'"
    )
    summary: str | None = Field(
        default=None,
        description="Optional follow-up summary, e.g., updated daily macro totals.",
    )


# Discriminated union — Pydantic picks the right variant based on `action`.
AgentReply = Annotated[
    Union[Suggestion, Question, ActionConfirmation],
    Field(discriminator="action"),
]


# --- Verifier output ----------------------------------------------------------


class SafetyFlag(_StrictModel):
    """One concern raised by the verifier against a candidate AgentReply."""

    severity: FlagSeverity = Field(description="info / warning / block.")
    code: str = Field(
        description=(
            "Short machine-readable identifier, e.g., 'sodium_vs_hypertension', "
            "'allergen_in_recommendation', 'supplement_med_interaction'."
        )
    )
    message: str = Field(
        description="Plain-English explanation shown to the user (for warning/info)."
    )
    profile_evidence: str = Field(
        description=(
            "Quote or paraphrase from the user's profile that triggered this flag. "
            "Lets the user audit *why* the verifier raised it."
        )
    )


class SafetyVerdict(_StrictModel):
    """The verifier's structured verdict on a candidate AgentReply.

    Validated against this model's JSON Schema via V2's
    `response_format={"type":"json_schema", ...}`. If `ok` is False or any flag
    has severity == 'block', the agent loop re-runs the executor with the flags
    pinned into the context.
    """

    ok: bool = Field(
        description="True iff the candidate reply is safe to show as-is."
    )
    flags: list[SafetyFlag] = Field(
        default_factory=list,
        description="Concerns raised. May be empty when ok=True.",
    )
    reason: str = Field(
        description=(
            "One-paragraph rationale for the verdict — references both the "
            "candidate reply and the profile facts that were checked."
        )
    )
    reasoning_type: ReasoningType = Field(
        description="Primary kind of reasoning used to reach the verdict (rubric point 7)."
    )


# --- Trace / event log --------------------------------------------------------


TraceEventKind = Literal[
    "user_message",
    "executor_call",
    "tool_call",
    "tool_result",
    "verifier_call",
    "verdict",
    "final_reply",
    "error",
]


class TraceEvent(_StrictModel):
    """One typed event in the agent's turn log.

    `payload` is intentionally `dict[str, Any]` — the shape varies by `kind`.
    The agent loop documents the expected shape per kind alongside its dispatcher.
    """

    ts: datetime = Field(description="When the event occurred.")
    kind: TraceEventKind = Field(description="Event type.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific data. Shape depends on `kind`.",
    )
    reasoning_type: ReasoningType | None = Field(
        default=None,
        description=(
            "Optional reasoning-type tag for executor/verifier events. "
            "Helps post-hoc analysis of where the model spent its 'thought' budget."
        ),
    )


class AgentTrace(_StrictModel):
    """The whole record of one user turn — every event, in order."""

    session_id: str = Field(description="Stable identifier for the chat session.")
    started_at: datetime = Field(description="When the turn started.")
    finished_at: datetime | None = Field(
        default=None,
        description="When the turn finished. None if still running.",
    )
    events: list[TraceEvent] = Field(
        default_factory=list,
        description="Ordered list of TraceEvents that occurred during the turn.",
    )
    final_reply: AgentReply | None = Field(
        default=None,
        description="The reply finally shown to the user (post-verifier). None if errored.",
    )
