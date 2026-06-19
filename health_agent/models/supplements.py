"""Supplement-domain models: catalog and intake log."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from health_agent.models.medical import _StrictModel


SupplementType = Literal[
    "vitamin",
    "mineral",
    "amino_acid",
    "omega",
    "herbal",
    "probiotic",
    "fiber",
    "protein_powder",
    "other",
]


class Supplement(_StrictModel):
    """A supplement the user is taking. Stored once; doses are logged separately."""

    id: int | None = Field(
        default=None,
        description="Row id. Server-assigned on insert.",
    )
    name: str = Field(description="Supplement name, e.g., 'Vitamin D3', 'Magnesium glycinate'.")
    kind: SupplementType = Field(description="Supplement category.")
    typical_dose: float = Field(
        gt=0,
        description="Typical per-administration dose, e.g., 2000.",
    )
    typical_unit: str = Field(
        description="Unit for the typical dose, e.g., 'IU', 'mg', 'mcg', 'g'.",
    )
    active_ingredients: list[str] = Field(
        default_factory=list,
        description=(
            "Canonical active-ingredient names used by interaction analysis. "
            "Examples: ['cholecalciferol'] for Vitamin D3, ['curcumin'] for Turmeric."
        ),
    )
    interaction_tags: list[str] = Field(
        default_factory=list,
        description=(
            "Tags consulted by the interaction checker. Examples: "
            "'blood_thinner', 'serotonergic', 'photosensitizing', 'CYP3A4_inhibitor', "
            "'iron_absorption_blocker', 'reduces_thyroid_meds_absorption'."
        ),
    )
    started_on: str | None = Field(
        default=None,
        description="ISO date string for when the user started taking this.",
    )
    active: bool = Field(default=True, description="False if no longer taken.")


class SupplementLog(_StrictModel):
    """A single 'I took my supplement' event. Append-only."""

    id: int | None = Field(
        default=None,
        description="Log row id. Server-assigned on insert.",
    )
    taken_at: datetime = Field(description="When the user took the supplement.")
    supplement_name: str = Field(
        description="Name as the user reported it (resolved to a Supplement by the server)."
    )
    supplement_id: int | None = Field(
        default=None,
        description="Resolved Supplement row id if matched. Server-set.",
    )
    dose: float = Field(
        gt=0,
        description="Dose actually taken (may differ from the supplement's typical dose).",
    )
    unit: str = Field(description="Unit for the dose taken.")
    notes: str | None = Field(default=None, description="Free-text notes.")
