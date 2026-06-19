"""USDA FoodData Central client.

Free API: https://fdc.nal.usda.gov/api-guide.html
Sign-up:  https://fdc.nal.usda.gov/api-key-signup.html

Without a key the API still works via the public DEMO_KEY but throttles hard
(30 calls/hour, 50 calls/day). Set USDA_API_KEY in .env for sane limits.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from health_agent.models import FoodCatalogItem, Macros


USDA_BASE_URL = "https://api.nal.usda.gov/fdc/v1"


# Nutrient IDs we care about (USDA FoodData Central nutrient numbers).
# https://fdc.nal.usda.gov/portal-data/external/dataDictionary
_NUTRIENT_IDS = {
    "calories":         1008,  # Energy (kcal)
    "protein_g":        1003,  # Protein
    "carbs_g":          1005,  # Carbohydrate, by difference
    "fat_g":            1004,  # Total lipid (fat)
    "saturated_fat_g":  1258,  # Fatty acids, total saturated
    "fiber_g":          1079,  # Fiber, total dietary
    "sugar_g":          2000,  # Sugars, total
    "sodium_mg":        1093,  # Sodium, Na
    "iron_mg":          1089,  # Iron, Fe
    "calcium_mg":       1087,  # Calcium, Ca
    "magnesium_mg":     1090,  # Magnesium, Mg
    "potassium_mg":     1092,  # Potassium, K
    "zinc_mg":          1095,  # Zinc, Zn
    "vitamin_d_iu":     1114,  # Vitamin D (D2 + D3) IU
    "folate_mcg":       1177,  # Folate, total
    "vitamin_b12_mcg":  1178,  # Vitamin B-12
    "vitamin_c_mg":     1162,  # Vitamin C, total ascorbic acid
}

# Some entries use different nutrient IDs for sugar.
_SUGAR_FALLBACKS = (2000, 1063, 1235)
# Vitamin D fallbacks: 1114 (IU), 1110 (mcg → ×40 to get IU).
_VITAMIN_D_MCG_ID = 1110
# Omega-3 fallbacks: 1404 (PUFA n-3 sum), else ALA + EPA + DHA.
_OMEGA3_TOTAL_ID = 1404
_OMEGA3_COMPONENT_IDS = (1404, 1278, 1272)  # ALA, EPA, DHA


def _macros_from_usda(food: dict[str, Any]) -> Macros:
    """Pull macros + micros out of a USDA `food` payload. USDA macros are per 100 g."""
    nutrients = {n.get("nutrientId"): n for n in food.get("foodNutrients", [])}

    def amount(nutrient_id: int) -> float:
        n = nutrients.get(nutrient_id)
        if not n:
            return 0.0
        # foundationFoods use `amount`; branded/search results use `value`.
        return float(n.get("amount") or n.get("value") or 0.0)

    sugar = 0.0
    for sid in _SUGAR_FALLBACKS:
        sugar = amount(sid)
        if sugar:
            break

    # Vitamin D: prefer IU; fall back to mcg × 40.
    vit_d_iu = amount(_NUTRIENT_IDS["vitamin_d_iu"])
    if vit_d_iu == 0:
        vit_d_iu = amount(_VITAMIN_D_MCG_ID) * 40

    # Omega-3: use total PUFA n-3 if present; else sum ALA + EPA + DHA (in g).
    total_n3 = amount(_OMEGA3_TOTAL_ID)
    if total_n3:
        omega3_g = total_n3
    else:
        omega3_g = sum(amount(nid) for nid in _OMEGA3_COMPONENT_IDS)

    return Macros(
        calories=amount(_NUTRIENT_IDS["calories"]),
        protein_g=amount(_NUTRIENT_IDS["protein_g"]),
        carbs_g=amount(_NUTRIENT_IDS["carbs_g"]),
        fat_g=amount(_NUTRIENT_IDS["fat_g"]),
        saturated_fat_g=amount(_NUTRIENT_IDS["saturated_fat_g"]),
        fiber_g=amount(_NUTRIENT_IDS["fiber_g"]),
        sugar_g=sugar,
        sodium_mg=amount(_NUTRIENT_IDS["sodium_mg"]),
        iron_mg=amount(_NUTRIENT_IDS["iron_mg"]),
        calcium_mg=amount(_NUTRIENT_IDS["calcium_mg"]),
        magnesium_mg=amount(_NUTRIENT_IDS["magnesium_mg"]),
        potassium_mg=amount(_NUTRIENT_IDS["potassium_mg"]),
        zinc_mg=amount(_NUTRIENT_IDS["zinc_mg"]),
        vitamin_d_iu=vit_d_iu,
        folate_mcg=amount(_NUTRIENT_IDS["folate_mcg"]),
        vitamin_b12_mcg=amount(_NUTRIENT_IDS["vitamin_b12_mcg"]),
        vitamin_c_mg=amount(_NUTRIENT_IDS["vitamin_c_mg"]),
        omega3_g=omega3_g,
    )


def _tags_from_usda(food: dict[str, Any]) -> list[str]:
    """Heuristic tag inference from category + macros. Keeps the analysis
    pipeline (which keys off tags like 'high_sodium') working for fetched foods."""
    tags: list[str] = []
    cat = (food.get("foodCategory") or "").lower()
    macros = _macros_from_usda(food)

    if macros.sodium_mg >= 400:
        tags.append("high_sodium")
    if macros.sugar_g >= 15:
        tags.append("high_sugar")
        tags.append("added_sugar")
    if macros.fiber_g >= 5:
        tags.append("high_fiber")
    if macros.protein_g >= 20:
        tags.append("high_protein")
    if macros.fat_g >= 15:
        tags.append("high_saturated_fat")  # rough proxy

    if "vegetable" in cat or "leafy" in cat:
        tags.append("leafy_green")
    if "grain" in cat and "whole" in cat:
        tags.append("whole_grain")
    if "snack" in cat or "fast food" in cat or "prepared" in cat:
        tags.append("processed")

    return tags


def _to_catalog_item(food: dict[str, Any]) -> FoodCatalogItem:
    description = food.get("description") or food.get("lowercaseDescription") or "unknown food"
    brand = food.get("brandOwner") or food.get("brandName")
    return FoodCatalogItem(
        name=description.strip(),
        brand=brand,
        serving_size=100.0,
        serving_unit="g",
        macros=_macros_from_usda(food),
        tags=_tags_from_usda(food),
    )


async def search_usda(
    query: str,
    limit: int = 3,
    api_key: str | None = None,
    page_size_multiplier: int = 4,
) -> list[FoodCatalogItem]:
    """Search USDA FoodData Central. Returns up to `limit` catalog items.

    We over-fetch (`limit * page_size_multiplier`) then filter to entries that
    actually have calorie data — many USDA rows are sparse.
    """
    key = api_key or os.getenv("USDA_API_KEY") or "DEMO_KEY"
    params = {
        "query": query,
        "pageSize": max(limit * page_size_multiplier, 10),
        "api_key": key,
        # Prefer Foundation/SR Legacy (most reliable macros), fall back to Survey + Branded.
        "dataType": ["Foundation", "SR Legacy", "Survey (FNDDS)", "Branded"],
    }
    async with httpx.AsyncClient(timeout=20.0) as http:
        resp = await http.get(f"{USDA_BASE_URL}/foods/search", params=params)
        resp.raise_for_status()
        data = resp.json()

    items: list[FoodCatalogItem] = []
    for food in data.get("foods", []):
        item = _to_catalog_item(food)
        if item.macros.calories == 0 and item.macros.protein_g == 0:
            continue  # skip empty rows
        items.append(item)
        if len(items) >= limit:
            break
    return items
