"""FastMCP server exposing read / mutation / analysis tools for the health agent.

The agent loop spawns this as a subprocess and talks over stdio. The tool
surface is intentionally narrow (~15 tools), each one a thin wrapper over a
typed repo call or a pure analysis function.

Concurrency model
-----------------
FastMCP dispatches sync tool handlers on a thread pool, so multiple tool calls
in the same parallel batch run on different threads. sqlite3 connections are
not safe for concurrent use across threads, so each tool call opens a fresh
connection and closes it on exit. SQLite WAL mode (set in schema.connect())
makes that cheap and concurrency-friendly.

Pydantic on every boundary:
    Tool args are simple typed parameters; datetimes flow as ISO strings.
    Tool returns are Pydantic models; FastMCP serializes them to JSON.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime
from typing import Annotated, Iterator

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from health_agent.db.repos import Repos
from health_agent.db.schema import connect, init_db
from health_agent.domain import analysis
from health_agent.external.usda import search_usda
from health_agent.models import (
    Allergy,
    Condition,
    FoodCatalogItem,
    Goal,
    Macros,
    MealLog,
    Medication,
    SafetyFlag,
    Supplement,
    SupplementLog,
)


load_dotenv()

mcp = FastMCP("health-agent")


_DB_INIT_DONE = False


def _ensure_init() -> None:
    """Run DDL once per process. Idempotent."""
    global _DB_INIT_DONE
    if _DB_INIT_DONE:
        return
    db_path = os.getenv("DB_PATH", "./health_agent.db")
    conn = connect(db_path)
    try:
        init_db(conn)
    finally:
        conn.close()
    _DB_INIT_DONE = True


@contextmanager
def _repos() -> Iterator[Repos]:
    """One connection per call — safe across FastMCP's thread-pool dispatch."""
    _ensure_init()
    conn = connect(os.getenv("DB_PATH", "./health_agent.db"))
    try:
        yield Repos(conn)
    finally:
        conn.close()


def _now() -> datetime:
    return datetime.now().astimezone()


# ───────────────────────── READ TOOLS ──────────────────────────────────────


@mcp.tool()
def get_profile_summary() -> dict:
    """Return the user's static profile plus active conditions, medications,
    allergies, goals, and supplements — everything the agent needs for the
    cached system-prompt prefix. One-shot to minimize round-trips."""
    with _repos() as r:
        p = r.profile.get()
        return {
            "profile": p.model_dump(mode="json") if p else None,
            "conditions": [c.model_dump(mode="json") for c in r.conditions.list_active()],
            "medications": [m.model_dump(mode="json") for m in r.medications.list_active()],
            "allergies": [a.model_dump(mode="json") for a in r.allergies.list_all()],
            "goals": [g.model_dump(mode="json") for g in r.goals.list_active()],
            "supplements": [s.model_dump(mode="json") for s in r.supplements.list_active()],
        }


@mcp.tool()
def get_today_macros() -> Macros:
    """Sum of macros for every meal logged on today's date (local time).
    Use this to compare against the user's daily targets (e.g., sodium <= 2000 mg)."""
    with _repos() as r:
        return r.meal_log.sum_macros_for_date(date.today())


@mcp.tool()
def get_recent_meals(
    limit: Annotated[int, Field(ge=1, le=50, description="How many recent meals to return.")] = 5,
) -> list[MealLog]:
    """Most recent meal log entries (newest first). Each entry includes resolved
    macros and (when matched) the food catalog id."""
    with _repos() as r:
        return r.meal_log.recent(limit)


@mcp.tool()
def list_active_conditions() -> list[Condition]:
    """All active conditions in the user's profile."""
    with _repos() as r:
        return r.conditions.list_active()


@mcp.tool()
def list_allergies() -> list[Allergy]:
    """All allergies on file (none are time-bound)."""
    with _repos() as r:
        return r.allergies.list_all()


@mcp.tool()
def list_active_meds() -> list[Medication]:
    """All active medications the user currently takes."""
    with _repos() as r:
        return r.medications.list_active()


@mcp.tool()
def list_supplements() -> list[Supplement]:
    """All active supplements the user is taking."""
    with _repos() as r:
        return r.supplements.list_active()


@mcp.tool()
def list_active_goals() -> list[Goal]:
    """All active health goals (e.g., 'reduce_sodium to 2000 mg/day')."""
    with _repos() as r:
        return r.goals.list_active()


@mcp.tool()
def search_food_catalog(
    query: Annotated[str, Field(description="Search string; loose substring match on food name.")],
    limit: Annotated[int, Field(ge=1, le=20, description="Max results.")] = 5,
) -> list[FoodCatalogItem]:
    """Find foods in the local catalog by name. Returns the best matches with
    macros and tags. Use this before logging if you're unsure the name matches
    a catalog entry."""
    with _repos() as r:
        return r.food_catalog.search(query, limit)


# ───────────────────────── MUTATION TOOLS ──────────────────────────────────


@mcp.tool()
def log_meal(
    food_name: Annotated[str, Field(description="Food name as the user said it.")],
    servings: Annotated[float, Field(gt=0, description="Number of servings.")],
    slot: Annotated[str, Field(description="One of: breakfast, lunch, dinner, snack.")],
    eaten_at_iso: Annotated[
        str | None,
        Field(description="ISO 8601 datetime, e.g., '2026-06-18T12:35:00'. Defaults to now."),
    ] = None,
    notes: Annotated[str | None, Field(description="Optional free-text notes.")] = None,
) -> MealLog:
    """Append a meal to the log. If `food_name` matches the catalog, macros are
    resolved automatically (per-serving × servings). Otherwise the entry is
    stored with zero macros — call search_food_catalog first to verify the
    match if precision matters."""
    eaten_at = datetime.fromisoformat(eaten_at_iso) if eaten_at_iso else _now()
    entry = MealLog(
        eaten_at=eaten_at,
        slot=slot,  # type: ignore[arg-type]
        food_name=food_name,
        servings=servings,
        notes=notes,
    )
    with _repos() as r:
        return r.meal_log.log(entry)


@mcp.tool()
def log_supplement_taken(
    supplement_name: Annotated[str, Field(description="Name as the user reported it.")],
    dose: Annotated[float, Field(gt=0, description="Dose actually taken.")],
    unit: Annotated[str, Field(description="Unit, e.g., 'IU', 'mg', 'mcg', 'g'.")],
    taken_at_iso: Annotated[
        str | None,
        Field(description="ISO 8601 datetime. Defaults to now."),
    ] = None,
    notes: Annotated[str | None, Field(description="Optional notes.")] = None,
) -> SupplementLog:
    """Record that the user took a supplement dose. The server resolves the
    supplement_id by name if it matches a Supplement on file."""
    taken_at = datetime.fromisoformat(taken_at_iso) if taken_at_iso else _now()
    entry = SupplementLog(
        taken_at=taken_at,
        supplement_name=supplement_name,
        dose=dose,
        unit=unit,
        notes=notes,
    )
    with _repos() as r:
        return r.supplement_log.log(entry)


@mcp.tool()
def delete_meal(
    meal_id: Annotated[
        int,
        Field(ge=1, description="The id of the meal_log row to delete (from get_recent_meals)."),
    ],
) -> dict:
    """Delete a meal log entry. Use this to undo a mistaken log_meal call.
    Get the id from get_recent_meals first."""
    with _repos() as r:
        deleted = r.meal_log.delete(meal_id)
    return {"deleted": deleted, "meal_id": meal_id}


@mcp.tool()
def add_condition(
    name: Annotated[str, Field(description="Plain-English condition name.")],
    severity: Annotated[str, Field(description="One of: mild, moderate, severe.")],
    tags: Annotated[
        list[str] | None,
        Field(description="Optional domain tags, e.g., ['metabolic', 'cardiovascular']."),
    ] = None,
    icd10: Annotated[str | None, Field(description="Optional ICD-10 code.")] = None,
    notes: Annotated[str | None, Field(description="Optional free-text notes.")] = None,
) -> Condition:
    """Add a new active condition to the user's profile. Use ONLY when the user
    explicitly tells you they've been diagnosed with something; never infer."""
    c = Condition(
        name=name,
        severity=severity,  # type: ignore[arg-type]
        tags=tags or [],
        icd10=icd10,
        notes=notes,
    )
    with _repos() as r:
        r.conditions.add(c)
    return c


# ───────────────────────── EXTERNAL LOOKUP TOOLS ───────────────────────────


@mcp.tool()
async def lookup_food_usda(
    query: Annotated[
        str,
        Field(description="Free-text food query, e.g., 'spinach rice', 'pho with beef brisket'."),
    ],
    limit: Annotated[int, Field(ge=1, le=5, description="Max results.")] = 3,
) -> list[FoodCatalogItem]:
    """Search USDA FoodData Central for foods not in the local catalog.
    Returns up to `limit` matches with per-100g macros and inferred tags.

    Use this when:
      - search_food_catalog returns nothing for the user's described food, OR
      - the user describes a homemade/regional dish the catalog doesn't have.

    After picking the right match, call add_to_catalog() to persist it locally
    so future logs match by name, then call log_meal() with the catalog name."""
    return await search_usda(query, limit=limit)


@mcp.tool()
def add_to_catalog(
    name: Annotated[str, Field(description="Food name to store in the local catalog.")],
    serving_size: Annotated[float, Field(gt=0, description="Numeric serving size, e.g., 1, 100.")],
    serving_unit: Annotated[
        str,
        Field(description="Unit ONE serving is measured in, e.g., 'baby carrot', 'slice', 'cup', 'mug', 'g'."),
    ],
    calories: Annotated[float, Field(ge=0, description="Calories PER ONE serving (not per 100g).")],
    protein_g: Annotated[float, Field(ge=0)] = 0.0,
    carbs_g: Annotated[float, Field(ge=0)] = 0.0,
    fat_g: Annotated[float, Field(ge=0)] = 0.0,
    fiber_g: Annotated[float, Field(ge=0)] = 0.0,
    sugar_g: Annotated[float, Field(ge=0)] = 0.0,
    sodium_mg: Annotated[float, Field(ge=0)] = 0.0,
    tags: Annotated[
        list[str] | None,
        Field(description="Domain tags (e.g., 'high_sodium', 'leafy_green')."),
    ] = None,
    brand: Annotated[str | None, Field(description="Optional brand or restaurant.")] = None,
) -> FoodCatalogItem:
    """Persist a food into the local catalog.

    CRITICAL: Macros must be PER ONE SERVING as defined by `serving_size` +
    `serving_unit`, NOT per 100g. If you got the data from lookup_food_usda
    (which returns per-100g values), you MUST first scale them to whatever
    "one serving" naturally means for the user.

    Examples:
      • Baby carrot: USDA per-100g says 35 kcal, 70 mg Na. One baby carrot
        is ~10 g, so call: serving_size=1, serving_unit='baby carrot',
        calories=3.5, sodium_mg=7.
      • Mug of ragi malt drink: USDA per-100g of ragi *flour* is ~320 kcal,
        but a mug of the drink uses ~30 g flour in liquid. So:
        serving_size=1, serving_unit='mug', calories≈96, sodium_mg≈3.
      • Pizza slice (already per-slice in real data): serving_size=1,
        serving_unit='slice', macros directly.

    After this, log_meal(food_name=..., servings=N) gives N × per-serving macros."""
    item = FoodCatalogItem(
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
    with _repos() as r:
        return r.food_catalog.insert(item)


# ───────────────────────── ANALYSIS TOOLS ──────────────────────────────────


@mcp.tool()
def check_food_against_profile(
    food_name: Annotated[str, Field(description="Food to check (resolved against the catalog).")],
) -> list[SafetyFlag]:
    """Return rule-based safety flags for the named food against the user's
    active conditions and allergies. An empty list means no automatic concerns;
    it does NOT mean the food is universally safe — the verifier may add more."""
    with _repos() as r:
        match = r.food_catalog.find_by_name(food_name)
        if match is None:
            return []
        return analysis.check_food_against_profile(
            match,
            r.conditions.list_active(),
            r.allergies.list_all(),
        )


@mcp.tool()
def check_supplement_interactions() -> list[SafetyFlag]:
    """Walk the user's active supplements x supplements and supplements x
    medications for known interaction tags. Returns any flags found."""
    with _repos() as r:
        return analysis.check_supplement_interactions(
            r.supplements.list_active(),
            r.medications.list_active(),
        )


@mcp.tool()
def suggest_swaps_for(
    food_name: Annotated[str, Field(description="The food the user wants swapped out.")],
    limit: Annotated[int, Field(ge=1, le=10, description="Max swap suggestions.")] = 3,
) -> list[FoodCatalogItem]:
    """Suggest catalog alternatives that avoid the food's problem tags given
    the user's active conditions. Returns [] if the food has no condition-relevant
    problem tags (i.e., it's already fine)."""
    with _repos() as r:
        match = r.food_catalog.find_by_name(food_name)
        if match is None:
            return []
        return analysis.suggest_swaps(
            match,
            r.food_catalog.list_all(),
            r.conditions.list_active(),
            limit,
        )


# ───────────────────────── entry point ────────────────────────────────────


def run() -> None:
    """Console-script entry. The agent loop launches this over stdio."""
    mcp.run()


if __name__ == "__main__":
    run()
