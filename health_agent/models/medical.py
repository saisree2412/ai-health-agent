"""Medical-domain models: profile, conditions, medications, allergies, goals.

These models form the *stable prefix* of the cached system prompt — they change
infrequently, so we want the LLM to see them as a structured, easy-to-quote block.

Every field has a description; descriptions show up in the JSON Schema the LLM
sees when these are used as MCP tool inputs/outputs.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# --- Enums kept as Literal for clean JSON Schema output -----------------------

Severity = Literal["mild", "moderate", "severe"]
Sex = Literal["male", "female", "other"]
ActivityLevel = Literal[
    "sedentary",  # desk job, minimal walking
    "light",  # light exercise 1-3 days/week
    "moderate",  # moderate exercise 3-5 days/week
    "active",  # hard exercise 6-7 days/week
    "very_active",  # physical job + training
]
GoalKind = Literal[
    "weight_loss",
    "weight_gain",
    "muscle_gain",
    "reduce_sodium",
    "reduce_sugar",
    "increase_protein",
    "lower_a1c",
    "lower_ldl",
    "improve_sleep",
    "other",
]


class _StrictModel(BaseModel):
    """Shared config: strict types, no unknown keys, deterministic dumps."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
    )


# --- Models -------------------------------------------------------------------


class Profile(_StrictModel):
    """Static-ish facts about the user. Lives in the cached prompt prefix."""

    name: str = Field(description="User's preferred name.")
    date_of_birth: date = Field(
        description="Used to compute age and contextualize lab/risk ranges."
    )
    sex: Sex = Field(description="Biological sex — affects macro targets and risk factors.")
    height_cm: float = Field(
        gt=0,
        le=275,
        description="Height in centimeters.",
    )
    weight_kg: float = Field(
        gt=0,
        le=500,
        description="Current weight in kilograms.",
    )
    activity_level: ActivityLevel = Field(
        description="Typical activity level — drives daily calorie/macro estimates."
    )
    timezone: str = Field(
        default="UTC",
        description="IANA timezone, e.g., 'America/Denver'.",
    )


class Condition(_StrictModel):
    """A chronic or active medical condition the user has been diagnosed with."""

    name: str = Field(description="Plain-English condition name, e.g., 'Type 2 diabetes'.")
    icd10: str | None = Field(
        default=None,
        description="ICD-10 code if known, e.g., 'E11.9'. Optional.",
    )
    severity: Severity = Field(description="Severity classification.")
    diagnosed_on: date | None = Field(
        default=None,
        description="Approximate diagnosis date.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description=(
            "Free-form domain tags used by analysis tools to match foods/supplements "
            "against the condition. Examples: 'metabolic', 'cardiovascular', "
            "'autoimmune', 'renal', 'hepatic'."
        ),
    )
    notes: str | None = Field(default=None, description="Any free-text context.")
    active: bool = Field(
        default=True,
        description="False if the condition is in remission or no longer relevant.",
    )


class Medication(_StrictModel):
    """A medication the user currently takes (or has taken)."""

    name: str = Field(description="Drug name, e.g., 'metformin'.")
    dose: float = Field(gt=0, description="Numeric dose per administration.")
    unit: str = Field(description="Unit for the dose, e.g., 'mg' or 'mcg'.")
    frequency: str = Field(
        description="Plain-English frequency, e.g., 'twice daily', 'as needed'."
    )
    indication: str | None = Field(
        default=None,
        description="What this medication is for, e.g., 'blood sugar', 'blood pressure'.",
    )
    taken_since: date | None = Field(
        default=None,
        description="When the user started this medication.",
    )
    active: bool = Field(
        default=True,
        description="False if no longer taken.",
    )


class Allergy(_StrictModel):
    """A food or substance allergy/intolerance the agent must respect."""

    allergen: str = Field(description="What the user reacts to, e.g., 'peanuts', 'lactose'.")
    reaction: str | None = Field(
        default=None,
        description="Typical reaction, e.g., 'hives', 'anaphylaxis', 'GI upset'.",
    )
    severity: Severity = Field(description="Severity classification.")


class Goal(_StrictModel):
    """A user-defined health goal that shapes recommendations."""

    kind: GoalKind = Field(description="Goal category.")
    target_value: float | None = Field(
        default=None,
        description="Numeric target if applicable (e.g., target weight, target A1C).",
    )
    target_unit: str | None = Field(
        default=None,
        description="Unit for the target value, e.g., 'kg', '%', 'g/day'.",
    )
    target_date: date | None = Field(
        default=None,
        description="When the user wants to hit the target.",
    )
    notes: str | None = Field(default=None, description="Free-text context.")
    active: bool = Field(
        default=True,
        description="False if abandoned or achieved.",
    )
