"""Seed the SQLite database with a realistic sample profile and ~40-item food
catalog. Run as: `python -m health_agent.seed`.

The sample profile is intentionally rich enough to exercise every verifier rule:
hypertension (sodium check), T2 diabetes (sugar/refined-carb check), shellfish
allergy (allergen check), fish oil + turmeric (blood-thinner additive check).
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from health_agent.db.schema import connect, init_db
from health_agent.db.repos import Repos
from health_agent.models import (
    Profile,
    Condition,
    Medication,
    Allergy,
    Goal,
    FoodCatalogItem,
    Macros,
    Supplement,
)


# ---------------------------------------------------------------------------
# Sample profile
# ---------------------------------------------------------------------------

SAMPLE_PROFILE = Profile(
    name="Sai",
    date_of_birth=date(1998, 6, 1),     # age ~28 in mid-2026
    sex="female",
    height_cm=160.0,                    # 5'3" = ~160 cm
    weight_kg=55.0,
    activity_level="moderate",          # 40-min strength training 3-4×/week
    timezone="Asia/Kolkata",
)

SAMPLE_CONDITIONS = [
    Condition(
        name="Irregular periods",
        severity="moderate",
        tags=["hormonal", "reproductive", "metabolic"],
        notes=(
            "Cycle length and timing inconsistent. Possible hormonal driver — "
            "agent should bias toward low-glycemic, anti-inflammatory foods."
        ),
    ),
    Condition(
        name="Acne",
        severity="mild",
        tags=["dermatologic", "hormonal", "inflammatory"],
        notes="Skin clarity is a stated goal — see Goals.",
    ),
]

SAMPLE_MEDICATIONS = []  # none currently

SAMPLE_ALLERGIES = [
    Allergy(
        allergen="milk",
        reaction="reported worsening of menstrual irregularity; also potential acne trigger",
        severity="moderate",
    ),
]

SAMPLE_GOALS = [
    Goal(
        kind="other",
        notes="Maintain current weight while improving body composition (recomposition).",
    ),
    Goal(
        kind="muscle_gain",
        notes=(
            "Build lean muscle — 'fit body' goal. "
            "Current routine: 40-min strength training, 3-4 sessions/week."
        ),
    ),
    Goal(
        kind="weight_loss",
        notes="Specifically reduce belly fat / visceral fat. Recomp focus.",
    ),
    Goal(
        kind="reduce_sugar",
        target_value=25,
        target_unit="g/day added sugar",
        notes="Lower added sugar to support skin clarity and hormonal balance.",
    ),
    Goal(
        kind="other",
        notes="Improve skin: clearer complexion, fewer acne flares.",
    ),
]

SAMPLE_SUPPLEMENTS = [
    Supplement(
        name="Vitamin D3",
        kind="vitamin",
        typical_dose=1000,
        typical_unit="IU",
        active_ingredients=["cholecalciferol"],
        interaction_tags=[],
    ),
]

# (older sample supplements retained below but commented for reference)
_LEGACY_SAMPLE_SUPPLEMENTS_UNUSED = [
    Supplement(
        name="Magnesium glycinate",
        kind="mineral",
        typical_dose=400,
        typical_unit="mg",
        active_ingredients=["magnesium"],
        interaction_tags=["reduces_thyroid_meds_absorption"],
    ),
    Supplement(
        name="Omega-3 fish oil",
        kind="omega",
        typical_dose=1000,
        typical_unit="mg",
        active_ingredients=["EPA", "DHA"],
        interaction_tags=["blood_thinner"],
    ),
    Supplement(
        name="Turmeric (curcumin)",
        kind="herbal",
        typical_dose=500,
        typical_unit="mg",
        active_ingredients=["curcumin"],
        interaction_tags=["blood_thinner", "CYP3A4_inhibitor"],
    ),
]


# ---------------------------------------------------------------------------
# Food catalog (~40 items). Macros are per ONE serving.
# Tags use the FOOD_TAG_VOCAB in models/food.py.
# ---------------------------------------------------------------------------


def _item(
    name: str,
    serving_size: float,
    serving_unit: str,
    calories: float,
    protein_g: float = 0,
    carbs_g: float = 0,
    fat_g: float = 0,
    fiber_g: float = 0,
    sugar_g: float = 0,
    sodium_mg: float = 0,
    tags: list[str] | None = None,
    brand: str | None = None,
) -> FoodCatalogItem:
    return FoodCatalogItem(
        name=name,
        brand=brand,
        serving_size=serving_size,
        serving_unit=serving_unit,
        macros=Macros(
            calories=calories,
            protein_g=protein_g,
            carbs_g=carbs_g,
            fat_g=fat_g,
            fiber_g=fiber_g,
            sugar_g=sugar_g,
            sodium_mg=sodium_mg,
        ),
        tags=tags or [],
    )


SAMPLE_CATALOG: list[FoodCatalogItem] = [
    # Breakfast
    _item("scrambled eggs", 2, "eggs", 180, protein_g=12, fat_g=14, sodium_mg=180,
          tags=["high_protein", "contains_eggs"]),
    _item("oatmeal (plain, cooked)", 1, "cup", 158, protein_g=6, carbs_g=27, fat_g=3,
          fiber_g=4, sodium_mg=115, tags=["whole_grain", "high_fiber", "contains_gluten"]),
    _item("greek yogurt (plain, nonfat)", 170, "g", 100, protein_g=17, carbs_g=6,
          sugar_g=4, sodium_mg=60, tags=["high_protein", "contains_dairy"]),
    _item("banana", 1, "medium", 105, protein_g=1.3, carbs_g=27, fiber_g=3, sugar_g=14,
          tags=["high_potassium", "high_fiber"]),
    _item("apple", 1, "medium", 95, protein_g=0.5, carbs_g=25, fiber_g=4.4, sugar_g=19,
          tags=["high_fiber"]),
    _item("blueberries", 1, "cup", 84, protein_g=1.1, carbs_g=21, fiber_g=3.6, sugar_g=15,
          tags=["high_fiber"]),
    _item("whole-wheat toast", 1, "slice", 80, protein_g=4, carbs_g=15, fiber_g=2,
          sodium_mg=170, tags=["whole_grain", "contains_gluten"]),
    _item("bagel with cream cheese", 1, "bagel", 430, protein_g=12, carbs_g=58, fat_g=16,
          sugar_g=8, sodium_mg=580, tags=["refined_carb", "high_sodium", "contains_gluten",
                                          "contains_dairy"]),
    _item("bacon strip", 1, "strip", 43, protein_g=3, fat_g=3.3, sodium_mg=185,
          tags=["high_sodium", "processed", "high_saturated_fat"]),

    # Lunch / proteins
    _item("grilled chicken breast", 100, "g", 165, protein_g=31, fat_g=3.6, sodium_mg=74,
          tags=["lean_protein", "high_protein"]),
    _item("salmon fillet (baked)", 100, "g", 208, protein_g=22, fat_g=13, sodium_mg=59,
          tags=["high_protein", "contains_fish"]),
    _item("tuna salad sandwich", 1, "sandwich", 380, protein_g=22, carbs_g=36, fat_g=16,
          sodium_mg=720, tags=["high_sodium", "contains_fish", "contains_gluten"]),
    _item("turkey sandwich", 1, "sandwich", 350, protein_g=24, carbs_g=40, fat_g=10,
          sodium_mg=940, tags=["high_sodium", "contains_gluten"]),
    _item("cheeseburger", 1, "burger", 535, protein_g=27, carbs_g=40, fat_g=29, sugar_g=8,
          sodium_mg=1080, tags=["high_sodium", "high_saturated_fat", "processed",
                                "contains_gluten", "contains_dairy"]),
    _item("mixed green salad (no dressing)", 1, "bowl", 80, protein_g=3, carbs_g=10,
          fat_g=4, fiber_g=4, sodium_mg=45, tags=["leafy_green", "high_fiber"]),
    _item("caesar salad with chicken", 1, "bowl", 470, protein_g=33, carbs_g=18, fat_g=28,
          sodium_mg=1050, tags=["leafy_green", "high_sodium", "contains_dairy",
                                "contains_eggs"]),
    _item("hummus", 2, "tbsp", 70, protein_g=2, carbs_g=4, fat_g=5, fiber_g=2,
          sodium_mg=130, tags=["high_fiber"]),

    # Dinner / sides
    _item("brown rice (cooked)", 1, "cup", 216, protein_g=5, carbs_g=45, fiber_g=3.5,
          sodium_mg=10, tags=["whole_grain", "high_fiber"]),
    _item("white rice (cooked)", 1, "cup", 205, protein_g=4, carbs_g=45, fiber_g=0.6,
          sodium_mg=2, tags=["refined_carb"]),
    _item("quinoa (cooked)", 1, "cup", 222, protein_g=8, carbs_g=39, fiber_g=5,
          sodium_mg=13, tags=["whole_grain", "high_fiber", "high_protein"]),
    _item("pasta with marinara", 1, "cup", 320, protein_g=12, carbs_g=58, fat_g=4,
          sodium_mg=620, tags=["refined_carb", "high_sodium", "contains_gluten"]),
    _item("baked potato (plain)", 1, "medium", 161, protein_g=4, carbs_g=37, fiber_g=4,
          sodium_mg=17, tags=["high_potassium", "high_fiber"]),
    _item("sweet potato (baked)", 1, "medium", 112, protein_g=2, carbs_g=26, fiber_g=4,
          sugar_g=5.4, sodium_mg=72, tags=["high_fiber", "high_potassium"]),
    _item("steamed broccoli", 1, "cup", 55, protein_g=4, carbs_g=11, fiber_g=5,
          sodium_mg=64, tags=["high_fiber", "leafy_green"]),
    _item("kale (sauteed)", 1, "cup", 50, protein_g=3, carbs_g=7, fat_g=2, fiber_g=2.6,
          sodium_mg=180, tags=["leafy_green", "high_fiber"]),

    # Restaurant / fast food
    _item("pepperoni pizza slice", 1, "slice", 298, protein_g=13, carbs_g=34, fat_g=12,
          sugar_g=4, sodium_mg=683, tags=["high_sodium", "high_saturated_fat",
                                          "refined_carb", "processed", "contains_gluten",
                                          "contains_dairy"]),
    _item("cheese pizza slice", 1, "slice", 272, protein_g=12, carbs_g=34, fat_g=10,
          sugar_g=4, sodium_mg=551, tags=["high_sodium", "refined_carb", "processed",
                                          "contains_gluten", "contains_dairy"]),
    _item("McDonald's Big Mac", 1, "burger", 563, protein_g=26, carbs_g=44, fat_g=33,
          sugar_g=9, sodium_mg=1010, brand="McDonald's",
          tags=["high_sodium", "high_saturated_fat", "processed", "contains_gluten",
                "contains_dairy"]),
    _item("McDonald's fries (medium)", 1, "order", 320, protein_g=4, carbs_g=43, fat_g=15,
          sodium_mg=260, brand="McDonald's",
          tags=["high_sodium", "fried", "processed", "refined_carb"]),
    _item("chicken nuggets (6 pc)", 6, "pieces", 270, protein_g=15, carbs_g=16, fat_g=17,
          sodium_mg=540, tags=["high_sodium", "fried", "processed"]),
    _item("chipotle burrito bowl (chicken, rice, beans, salsa)", 1, "bowl", 685,
          protein_g=45, carbs_g=78, fat_g=20, fiber_g=14, sodium_mg=1530,
          brand="Chipotle",
          tags=["high_sodium", "high_protein", "high_fiber"]),
    _item("ramen bowl (tonkotsu)", 1, "bowl", 660, protein_g=24, carbs_g=80, fat_g=24,
          sodium_mg=1890, tags=["high_sodium", "refined_carb", "contains_gluten"]),

    # Snacks
    _item("potato chips", 28, "g", 152, protein_g=2, carbs_g=15, fat_g=10, sodium_mg=170,
          tags=["high_sodium", "fried", "processed", "refined_carb"]),
    _item("almonds", 28, "g", 164, protein_g=6, carbs_g=6, fat_g=14, fiber_g=3.5,
          sodium_mg=0, tags=["high_protein", "contains_nuts"]),
    _item("dark chocolate (70%)", 28, "g", 170, protein_g=2, carbs_g=13, fat_g=12,
          sugar_g=7, sodium_mg=6, tags=["added_sugar"]),
    _item("protein bar", 1, "bar", 220, protein_g=20, carbs_g=22, fat_g=8, sugar_g=4,
          sodium_mg=210, tags=["high_protein", "processed"]),
    _item("granola bar", 1, "bar", 190, protein_g=4, carbs_g=29, fat_g=7, sugar_g=12,
          sodium_mg=110, tags=["added_sugar", "processed"]),
    _item("vanilla ice cream", 0.5, "cup", 137, protein_g=2, carbs_g=16, fat_g=7,
          sugar_g=14, sodium_mg=53, tags=["added_sugar", "high_saturated_fat",
                                          "contains_dairy"]),
    _item("glazed donut", 1, "donut", 269, protein_g=4, carbs_g=31, fat_g=15, sugar_g=12,
          sodium_mg=232, tags=["added_sugar", "fried", "refined_carb", "contains_gluten"]),

    # Beverages
    _item("black coffee", 240, "ml", 2, sodium_mg=5, tags=[]),
    _item("latte (whole milk)", 360, "ml", 190, protein_g=10, carbs_g=18, fat_g=10,
          sugar_g=17, sodium_mg=150, tags=["contains_dairy", "added_sugar"]),
    _item("Coca-Cola can", 355, "ml", 140, carbs_g=39, sugar_g=39, sodium_mg=45,
          brand="Coca-Cola", tags=["added_sugar", "high_sugar", "processed"]),
    _item("orange juice", 240, "ml", 110, protein_g=2, carbs_g=26, sugar_g=22,
          tags=["high_sugar"]),
    _item("beer (lager, 12oz)", 355, "ml", 153, carbs_g=13, sugar_g=0, sodium_mg=14,
          tags=["contains_gluten"]),
]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def seed(db_path: str | None = None, reset: bool = True) -> None:
    """Initialize the DB and load all sample data.

    Args:
        db_path: SQLite path. Defaults to DB_PATH env or ./health_agent.db.
        reset:   If True and the file exists, delete it first (clean reseed).
    """
    load_dotenv()
    target = Path(db_path or os.getenv("DB_PATH", "./health_agent.db"))

    if reset and target.exists():
        target.unlink()

    conn = connect(target)
    init_db(conn)
    r = Repos(conn)

    r.profile.set(SAMPLE_PROFILE)
    for c in SAMPLE_CONDITIONS:
        r.conditions.add(c)
    for m in SAMPLE_MEDICATIONS:
        r.medications.add(m)
    for a in SAMPLE_ALLERGIES:
        r.allergies.add(a)
    for g in SAMPLE_GOALS:
        r.goals.add(g)
    for s in SAMPLE_SUPPLEMENTS:
        r.supplements.add(s)
    for item in SAMPLE_CATALOG:
        r.food_catalog.insert(item)

    print(
        f"Seeded {target}\n"
        f"  profile:      {SAMPLE_PROFILE.name}\n"
        f"  conditions:   {len(SAMPLE_CONDITIONS)}\n"
        f"  medications:  {len(SAMPLE_MEDICATIONS)}\n"
        f"  allergies:    {len(SAMPLE_ALLERGIES)}\n"
        f"  goals:        {len(SAMPLE_GOALS)}\n"
        f"  supplements:  {len(SAMPLE_SUPPLEMENTS)}\n"
        f"  food catalog: {r.food_catalog.count()} items"
    )
    # Release the file lock before the test/agent process opens its own.
    conn.close()


if __name__ == "__main__":
    seed()
