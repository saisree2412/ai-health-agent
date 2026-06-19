"""Food-domain models: macros, catalog items, meal log.

`Macros` is a small value object so it's composable — every catalog item carries
its macros, every meal log produces resolved macros, and `compute_today_macros`
sums a list of them. Defaults are zero so `Macros()` is the additive identity.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from health_agent.models.medical import _StrictModel


MealSlot = Literal["breakfast", "lunch", "dinner", "snack"]


# Free-form tag list, but these are the values analysis tools look for.
# Documented here so seed data and prompts can stay aligned.
FOOD_TAG_VOCAB = (
    "high_sodium",
    "high_sugar",
    "high_saturated_fat",
    "high_potassium",
    "high_protein",
    "high_fiber",
    "refined_carb",
    "processed",
    "fried",
    "whole_grain",
    "leafy_green",
    "lean_protein",
    "added_sugar",
    "contains_gluten",
    "contains_dairy",
    "contains_nuts",
    "contains_soy",
    "contains_eggs",
    "contains_shellfish",
    "contains_fish",
)


class Macros(_StrictModel):
    """Macros + key micronutrients for a single quantity of food.

    All fields default to 0 so an empty `Macros()` acts as the additive identity
    — useful for summing a day's meals with `sum(macro_list, Macros())`.

    Micros included here are the ones that materially shape recommendations
    for women's health: iron / calcium / magnesium / zinc / vit D / folate /
    B12 / vit C / omega-3 / potassium / saturated fat. The verifier and the
    analysis rules read these directly.
    """

    # ── macros ───────────────────────────────────────────────────────────
    calories: float = Field(default=0.0, ge=0, description="Energy in kcal.")
    protein_g: float = Field(default=0.0, ge=0, description="Protein in grams.")
    carbs_g: float = Field(default=0.0, ge=0, description="Total carbohydrates in grams.")
    fat_g: float = Field(default=0.0, ge=0, description="Total fat in grams.")
    saturated_fat_g: float = Field(default=0.0, ge=0, description="Saturated fat in grams.")
    fiber_g: float = Field(default=0.0, ge=0, description="Dietary fiber in grams.")
    sugar_g: float = Field(default=0.0, ge=0, description="Total sugars in grams.")
    sodium_mg: float = Field(default=0.0, ge=0, description="Sodium in milligrams.")

    # ── women's-health micros ────────────────────────────────────────────
    iron_mg: float = Field(default=0.0, ge=0, description="Iron (mg). Critical for menstruating women.")
    calcium_mg: float = Field(default=0.0, ge=0, description="Calcium (mg).")
    magnesium_mg: float = Field(default=0.0, ge=0, description="Magnesium (mg). PMS, sleep, recovery.")
    potassium_mg: float = Field(default=0.0, ge=0, description="Potassium (mg).")
    zinc_mg: float = Field(default=0.0, ge=0, description="Zinc (mg). Skin / acne support.")
    vitamin_d_iu: float = Field(default=0.0, ge=0, description="Vitamin D (IU).")
    folate_mcg: float = Field(default=0.0, ge=0, description="Folate / B9 (mcg).")
    vitamin_b12_mcg: float = Field(default=0.0, ge=0, description="Vitamin B12 (mcg).")
    vitamin_c_mg: float = Field(default=0.0, ge=0, description="Vitamin C (mg). Boosts iron absorption.")
    omega3_g: float = Field(default=0.0, ge=0, description="Omega-3 fatty acids (g, ALA+EPA+DHA).")

    # ── ops ──────────────────────────────────────────────────────────────

    @classmethod
    def fields(cls) -> tuple[str, ...]:
        """Numeric field names in declaration order — single source of truth
        for arithmetic, DB columns, and JSON serialization."""
        return tuple(cls.model_fields.keys())

    def __add__(self, other: "Macros") -> "Macros":
        if not isinstance(other, Macros):
            return NotImplemented
        return Macros(**{f: getattr(self, f) + getattr(other, f) for f in self.fields()})

    def __radd__(self, other: object) -> "Macros":
        if other == 0:
            return self
        return NotImplemented  # type: ignore[return-value]

    def scaled(self, factor: float) -> "Macros":
        """Multiply every component by `factor` (e.g., scaling per-serving to total)."""
        if factor < 0:
            raise ValueError("scale factor must be non-negative")
        return Macros(**{f: getattr(self, f) * factor for f in self.fields()})


class FoodCatalogItem(_StrictModel):
    """A row in the food reference catalog. Macros are per one serving."""

    id: int | None = Field(
        default=None,
        description="Catalog row id. Server-assigned on insert.",
    )
    name: str = Field(description="Common food name, e.g., 'pepperoni pizza slice'.")
    brand: str | None = Field(
        default=None,
        description="Brand or restaurant if applicable, e.g., 'Domino\\'s'.",
    )
    serving_size: float = Field(
        gt=0,
        description="Numeric size of one serving, e.g., 1 (slice), 100 (grams).",
    )
    serving_unit: str = Field(
        description="Unit for the serving size, e.g., 'slice', 'g', 'cup', 'piece'.",
    )
    macros: Macros = Field(description="Macros per ONE serving as defined above.")
    tags: list[str] = Field(
        default_factory=list,
        description=(
            "Domain tags used by analysis tools to match foods against conditions "
            "and allergies. See FOOD_TAG_VOCAB for the canonical set."
        ),
    )


class MealLog(_StrictModel):
    """A logged meal entry. Append-only — never updated after insert."""

    id: int | None = Field(
        default=None,
        description="Log row id. Server-assigned on insert; do not provide when logging.",
    )
    eaten_at: datetime = Field(
        description="When the meal was eaten (timezone-aware ISO 8601)."
    )
    slot: MealSlot = Field(description="Which meal slot this entry belongs to.")
    food_name: str = Field(
        description=(
            "The food as the user described it. If it matches a catalog row, "
            "the server resolves food_catalog_id and macros automatically."
        )
    )
    food_catalog_id: int | None = Field(
        default=None,
        description="Catalog row id if matched. Server-set.",
    )
    servings: float = Field(
        gt=0,
        description="Number of servings (multiplies catalog macros).",
    )
    macros: Macros = Field(
        default_factory=Macros,
        description=(
            "Resolved macros for the entire entry (servings * catalog per-serving "
            "macros, or user-provided override). Server-computed when possible."
        ),
    )
    notes: str | None = Field(default=None, description="Free-text notes.")
