"""Rule-based analysis used by MCP tools and the verifier.

Pure functions over Pydantic models — no DB access here. Each function returns
SafetyFlag lists when it spots a concern. Rules are intentionally explicit and
auditable: the verifier LLM should be able to *quote* a rule when it flags.

Adding a new rule = adding one branch + one SafetyFlag construction.
"""

from __future__ import annotations

from health_agent.models import (
    Allergy,
    Condition,
    FoodCatalogItem,
    Medication,
    SafetyFlag,
    Supplement,
)


# ---------------------------------------------------------------------------
# Allergen + tag matching helpers
# ---------------------------------------------------------------------------


# Map allergen → food-catalog tag that *implies* containment.
ALLERGEN_TAG: dict[str, str] = {
    "peanuts": "contains_nuts",
    "tree nuts": "contains_nuts",
    "nuts": "contains_nuts",
    "lactose": "contains_dairy",
    "dairy": "contains_dairy",
    "milk": "contains_dairy",
    "gluten": "contains_gluten",
    "wheat": "contains_gluten",
    "soy": "contains_soy",
    "eggs": "contains_eggs",
    "shellfish": "contains_shellfish",
    "fish": "contains_fish",
}


def _matches_allergen(food: FoodCatalogItem, allergen: str) -> bool:
    a = allergen.strip().lower()
    name = food.name.lower()
    if a in name:
        return True
    tag = ALLERGEN_TAG.get(a)
    if tag and tag in food.tags:
        return True
    return False


# ---------------------------------------------------------------------------
# Food vs profile
# ---------------------------------------------------------------------------


def _condition_problem_tags(conditions: list[Condition]) -> set[str]:
    """Which food tags are concerning given the user's active conditions."""
    problems: set[str] = set()
    for c in conditions:
        if not c.active:
            continue
        cn = c.name.lower()
        tags = {t.lower() for t in c.tags}
        if "hypertension" in cn or "high blood pressure" in cn:
            problems |= {"high_sodium"}
        if "diabetes" in cn or "a1c" in cn:
            problems |= {"added_sugar", "high_sugar", "refined_carb"}
        if "hyperlipidemia" in cn or "high cholesterol" in cn:
            problems |= {"high_saturated_fat", "fried"}
        if "kidney" in cn or "renal" in cn:
            problems |= {"high_potassium", "high_sodium"}
        # Acne — insulin spikes + dairy + high-glycemic foods drive sebum/inflammation.
        if "acne" in cn or "dermatologic" in tags:
            problems |= {"added_sugar", "high_sugar", "refined_carb", "high_saturated_fat"}
        # Irregular periods / PCOS / hormonal — insulin resistance and chronic
        # inflammation are common drivers; bias toward low-GI foods.
        if (
            "irregular period" in cn
            or "pcos" in cn
            or "hormonal" in tags
            or "reproductive" in tags
        ):
            problems |= {"added_sugar", "high_sugar", "refined_carb"}
    return problems


def check_food_against_profile(
    food: FoodCatalogItem,
    conditions: list[Condition],
    allergies: list[Allergy],
) -> list[SafetyFlag]:
    """Flag foods that conflict with stated allergies / conditions."""
    flags: list[SafetyFlag] = []

    # ── allergens (BLOCK) ────────────────────────────────────────────────
    for a in allergies:
        if _matches_allergen(food, a.allergen):
            flags.append(
                SafetyFlag(
                    severity="block",
                    code="allergen_in_food",
                    message=(
                        f"{food.name} contains or may contain {a.allergen}, "
                        f"which the user is allergic to ({a.severity})."
                    ),
                    profile_evidence=f"Allergy: {a.allergen} — reaction: {a.reaction or 'unknown'}",
                )
            )

    # ── condition-tag rules (WARNING) ────────────────────────────────────
    problem_tags = _condition_problem_tags(conditions)
    matched = sorted(problem_tags & set(food.tags))
    if matched:
        cond_names = ", ".join(c.name for c in conditions if c.active)
        flags.append(
            SafetyFlag(
                severity="warning",
                code="condition_tag_conflict",
                message=(
                    f"{food.name} has tags {matched} that are concerning given "
                    f"the user's active conditions ({cond_names})."
                ),
                profile_evidence=f"Active conditions: {cond_names}",
            )
        )

    # ── absolute thresholds — single-item sodium (INFO) ──────────────────
    if food.macros.sodium_mg >= 800:
        flags.append(
            SafetyFlag(
                severity="info",
                code="high_sodium_item",
                message=(
                    f"One serving of {food.name} delivers "
                    f"{food.macros.sodium_mg:.0f} mg sodium — a large share of a "
                    "2,000 mg daily target."
                ),
                profile_evidence="Threshold rule: >= 800 mg sodium per serving.",
            )
        )
    return flags


# ---------------------------------------------------------------------------
# Supplement / medication interactions
# ---------------------------------------------------------------------------


# Med-indication → supplement-interaction-tag that conflicts.
MED_VS_SUPPLEMENT: dict[str, str] = {
    "thyroid": "reduces_thyroid_meds_absorption",
    "blood thinner": "blood_thinner",
    "anticoagulant": "blood_thinner",
    "warfarin": "blood_thinner",
}


def check_supplement_interactions(
    supplements: list[Supplement],
    medications: list[Medication],
) -> list[SafetyFlag]:
    """Walk supplements x supplements and supplements x meds for known conflicts."""
    flags: list[SafetyFlag] = []
    active_sups = [s for s in supplements if s.active]
    active_meds = [m for m in medications if m.active]

    # ── additive supplement effects (same interaction tag, 2+ supplements) ─
    by_tag: dict[str, list[str]] = {}
    for s in active_sups:
        for t in s.interaction_tags:
            by_tag.setdefault(t, []).append(s.name)

    for tag, names in by_tag.items():
        if len(names) >= 2:
            flags.append(
                SafetyFlag(
                    severity="warning",
                    code=f"additive_{tag}",
                    message=(
                        f"Multiple supplements share the '{tag}' interaction tag: "
                        f"{', '.join(names)}. Effects may stack."
                    ),
                    profile_evidence=f"Active supplements: {', '.join(names)}",
                )
            )

    # ── supplement vs medication ─────────────────────────────────────────
    for s in active_sups:
        for m in active_meds:
            indication = (m.indication or "").lower()
            mname = m.name.lower()
            for needle, sup_tag in MED_VS_SUPPLEMENT.items():
                if (needle in indication or needle in mname) and sup_tag in s.interaction_tags:
                    flags.append(
                        SafetyFlag(
                            severity="warning",
                            code="supplement_med_interaction",
                            message=(
                                f"{s.name} has interaction tag '{sup_tag}', which "
                                f"may conflict with {m.name} ({m.indication or 'unspecified'})."
                            ),
                            profile_evidence=f"Medication: {m.name} {m.dose}{m.unit} — {m.frequency}",
                        )
                    )
    return flags


# ---------------------------------------------------------------------------
# Grocery swap suggestions
# ---------------------------------------------------------------------------


def suggest_swaps(
    food: FoodCatalogItem,
    catalog: list[FoodCatalogItem],
    conditions: list[Condition],
    limit: int = 3,
) -> list[FoodCatalogItem]:
    """Pick catalog items that avoid the problem tags this food has.

    Naive heuristic for v0: items without any of the food's problem tags,
    prefer items that share at least one *positive* tag (leafy_green, high_protein,
    whole_grain, high_fiber, lean_protein) with the original.
    """
    problem_tags = _condition_problem_tags(conditions)
    food_problems = set(food.tags) & problem_tags
    if not food_problems:
        return []

    positive_tags = {"leafy_green", "high_protein", "whole_grain", "high_fiber", "lean_protein"}
    food_positive = set(food.tags) & positive_tags

    def score(item: FoodCatalogItem) -> int:
        item_tags = set(item.tags)
        # Hard filter: must not share any of the food's problem tags
        if item_tags & food_problems:
            return -1
        # Prefer items with positive overlap, then with any positive tag.
        return 3 * len(item_tags & food_positive) + len(item_tags & positive_tags)

    ranked = sorted(
        (i for i in catalog if i.name != food.name and score(i) >= 0),
        key=lambda i: (-score(i), i.macros.calories),
    )
    return ranked[:limit]
