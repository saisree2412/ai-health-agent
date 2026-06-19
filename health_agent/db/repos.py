"""Typed repositories — one per domain. Every method takes/returns Pydantic models.

Conversion between Pydantic and SQLite rows lives here and only here. Outside
this module, no code should touch sqlite3.Row or JSON-encoded list columns.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from typing import cast

from health_agent.models import (
    Profile,
    Condition,
    Medication,
    Allergy,
    Goal,
    FoodCatalogItem,
    Macros,
    MealLog,
    Supplement,
    SupplementLog,
)


# --- small helpers ------------------------------------------------------------


def _b(v: object) -> bool:
    return bool(v) and v != 0


def _jl(v: object) -> list[str]:
    """JSON-encoded list column → list[str]."""
    return json.loads(cast(str, v)) if v else []


def _iso_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _iso_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


# Reuse the Macros field order as the single source of truth — saves repeating
# the column list every time we read a row or build an INSERT statement.
_MACRO_FIELDS = Macros.fields()


def _macros_from_row(r: sqlite3.Row) -> Macros:
    return Macros(**{f: r[f] for f in _MACRO_FIELDS})


def _macros_values(m: Macros) -> tuple[float, ...]:
    return tuple(getattr(m, f) for f in _MACRO_FIELDS)


def _macros_columns_sql() -> str:
    return ", ".join(_MACRO_FIELDS)


def _macros_placeholders_sql() -> str:
    return ", ".join(["?"] * len(_MACRO_FIELDS))


def _macros_sum_sql() -> str:
    return ", ".join(f"COALESCE(SUM({f}), 0) AS {f}" for f in _MACRO_FIELDS)


# --- profile ------------------------------------------------------------------


class ProfileRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self) -> Profile | None:
        r = self.conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
        if r is None:
            return None
        return Profile(
            name=r["name"],
            date_of_birth=date.fromisoformat(r["date_of_birth"]),
            sex=r["sex"],
            height_cm=r["height_cm"],
            weight_kg=r["weight_kg"],
            activity_level=r["activity_level"],
            timezone=r["timezone"],
        )

    def set(self, p: Profile) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO profile "
            "(id, name, date_of_birth, sex, height_cm, weight_kg, activity_level, timezone) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
            (
                p.name,
                p.date_of_birth.isoformat(),
                p.sex,
                p.height_cm,
                p.weight_kg,
                p.activity_level,
                p.timezone,
            ),
        )
        self.conn.commit()


# --- conditions ---------------------------------------------------------------


class ConditionRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_active(self) -> list[Condition]:
        rows = self.conn.execute("SELECT * FROM conditions WHERE active = 1").fetchall()
        return [self._row(r) for r in rows]

    def list_all(self) -> list[Condition]:
        rows = self.conn.execute("SELECT * FROM conditions").fetchall()
        return [self._row(r) for r in rows]

    def add(self, c: Condition) -> None:
        self.conn.execute(
            "INSERT INTO conditions "
            "(name, icd10, severity, diagnosed_on, tags, notes, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                c.name,
                c.icd10,
                c.severity,
                c.diagnosed_on.isoformat() if c.diagnosed_on else None,
                json.dumps(c.tags),
                c.notes,
                int(c.active),
            ),
        )
        self.conn.commit()

    @staticmethod
    def _row(r: sqlite3.Row) -> Condition:
        return Condition(
            name=r["name"],
            icd10=r["icd10"],
            severity=r["severity"],
            diagnosed_on=_iso_date(r["diagnosed_on"]),
            tags=_jl(r["tags"]),
            notes=r["notes"],
            active=_b(r["active"]),
        )


# --- medications --------------------------------------------------------------


class MedicationRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_active(self) -> list[Medication]:
        rows = self.conn.execute("SELECT * FROM medications WHERE active = 1").fetchall()
        return [self._row(r) for r in rows]

    def add(self, m: Medication) -> None:
        self.conn.execute(
            "INSERT INTO medications "
            "(name, dose, unit, frequency, indication, taken_since, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                m.name,
                m.dose,
                m.unit,
                m.frequency,
                m.indication,
                m.taken_since.isoformat() if m.taken_since else None,
                int(m.active),
            ),
        )
        self.conn.commit()

    @staticmethod
    def _row(r: sqlite3.Row) -> Medication:
        return Medication(
            name=r["name"],
            dose=r["dose"],
            unit=r["unit"],
            frequency=r["frequency"],
            indication=r["indication"],
            taken_since=_iso_date(r["taken_since"]),
            active=_b(r["active"]),
        )


# --- allergies ----------------------------------------------------------------


class AllergyRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_all(self) -> list[Allergy]:
        rows = self.conn.execute("SELECT * FROM allergies").fetchall()
        return [
            Allergy(allergen=r["allergen"], reaction=r["reaction"], severity=r["severity"])
            for r in rows
        ]

    def add(self, a: Allergy) -> None:
        self.conn.execute(
            "INSERT INTO allergies (allergen, reaction, severity) VALUES (?, ?, ?)",
            (a.allergen, a.reaction, a.severity),
        )
        self.conn.commit()


# --- goals --------------------------------------------------------------------


class GoalRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_active(self) -> list[Goal]:
        rows = self.conn.execute("SELECT * FROM goals WHERE active = 1").fetchall()
        return [self._row(r) for r in rows]

    def add(self, g: Goal) -> None:
        self.conn.execute(
            "INSERT INTO goals "
            "(kind, target_value, target_unit, target_date, notes, active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                g.kind,
                g.target_value,
                g.target_unit,
                g.target_date.isoformat() if g.target_date else None,
                g.notes,
                int(g.active),
            ),
        )
        self.conn.commit()

    @staticmethod
    def _row(r: sqlite3.Row) -> Goal:
        return Goal(
            kind=r["kind"],
            target_value=r["target_value"],
            target_unit=r["target_unit"],
            target_date=_iso_date(r["target_date"]),
            notes=r["notes"],
            active=_b(r["active"]),
        )


# --- food catalog -------------------------------------------------------------


class FoodCatalogRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, id_: int) -> FoodCatalogItem | None:
        r = self.conn.execute("SELECT * FROM food_catalog WHERE id = ?", (id_,)).fetchone()
        return self._row(r) if r else None

    def find_by_name(self, query: str) -> FoodCatalogItem | None:
        """Loose name match. Returns the best-scoring single hit (LIKE %query%).

        Good enough for v0 — for production, replace with FTS or trigram search.
        """
        like = f"%{query.strip().lower()}%"
        r = self.conn.execute(
            "SELECT * FROM food_catalog "
            "WHERE LOWER(name) LIKE ? "
            "ORDER BY LENGTH(name) ASC LIMIT 1",
            (like,),
        ).fetchone()
        return self._row(r) if r else None

    def search(self, query: str, limit: int = 5) -> list[FoodCatalogItem]:
        like = f"%{query.strip().lower()}%"
        rows = self.conn.execute(
            "SELECT * FROM food_catalog WHERE LOWER(name) LIKE ? "
            "ORDER BY LENGTH(name) ASC LIMIT ?",
            (like, limit),
        ).fetchall()
        return [self._row(r) for r in rows]

    def insert(self, item: FoodCatalogItem) -> FoodCatalogItem:
        cols = _macros_columns_sql()
        ph = _macros_placeholders_sql()
        cur = self.conn.execute(
            f"INSERT INTO food_catalog "
            f"(name, brand, serving_size, serving_unit, {cols}, tags) "
            f"VALUES (?, ?, ?, ?, {ph}, ?)",
            (
                item.name,
                item.brand,
                item.serving_size,
                item.serving_unit,
                *_macros_values(item.macros),
                json.dumps(item.tags),
            ),
        )
        self.conn.commit()
        return item.model_copy(update={"id": cur.lastrowid})

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS n FROM food_catalog").fetchone()["n"]

    def list_all(self) -> list[FoodCatalogItem]:
        rows = self.conn.execute("SELECT * FROM food_catalog").fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(r: sqlite3.Row) -> FoodCatalogItem:
        return FoodCatalogItem(
            id=r["id"],
            name=r["name"],
            brand=r["brand"],
            serving_size=r["serving_size"],
            serving_unit=r["serving_unit"],
            macros=_macros_from_row(r),
            tags=_jl(r["tags"]),
        )


# --- meal log -----------------------------------------------------------------


class MealLogRepo:
    """Append-only log of meals. Resolves catalog + scales macros on insert."""

    def __init__(self, conn: sqlite3.Connection, catalog: FoodCatalogRepo) -> None:
        self.conn = conn
        self.catalog = catalog

    def log(self, entry: MealLog) -> MealLog:
        """Insert and return the canonical MealLog (id set, macros resolved)."""
        catalog_id = entry.food_catalog_id
        macros = entry.macros

        # Resolve catalog if not provided AND no user-supplied macros.
        if catalog_id is None and macros == Macros():
            match = self.catalog.find_by_name(entry.food_name)
            if match is not None:
                catalog_id = match.id
                macros = match.macros.scaled(entry.servings)

        cols = _macros_columns_sql()
        ph = _macros_placeholders_sql()
        cur = self.conn.execute(
            f"INSERT INTO meal_log "
            f"(eaten_at, slot, food_name, food_catalog_id, servings, {cols}, notes) "
            f"VALUES (?, ?, ?, ?, ?, {ph}, ?)",
            (
                entry.eaten_at.isoformat(),
                entry.slot,
                entry.food_name,
                catalog_id,
                entry.servings,
                *_macros_values(macros),
                entry.notes,
            ),
        )
        self.conn.commit()
        return entry.model_copy(
            update={"id": cur.lastrowid, "food_catalog_id": catalog_id, "macros": macros}
        )

    def recent(self, limit: int = 10) -> list[MealLog]:
        rows = self.conn.execute(
            "SELECT * FROM meal_log ORDER BY eaten_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row(r) for r in rows]

    def for_date(self, d: date) -> list[MealLog]:
        rows = self.conn.execute(
            "SELECT * FROM meal_log WHERE date(eaten_at) = ? ORDER BY eaten_at ASC",
            (d.isoformat(),),
        ).fetchall()
        return [self._row(r) for r in rows]

    def delete(self, meal_id: int) -> bool:
        """Delete a meal log entry by id. Returns True if a row was removed."""
        cur = self.conn.execute("DELETE FROM meal_log WHERE id = ?", (meal_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def sum_macros_for_date(self, d: date) -> Macros:
        r = self.conn.execute(
            f"SELECT {_macros_sum_sql()} FROM meal_log WHERE date(eaten_at) = ?",
            (d.isoformat(),),
        ).fetchone()
        return _macros_from_row(r)

    @staticmethod
    def _row(r: sqlite3.Row) -> MealLog:
        return MealLog(
            id=r["id"],
            eaten_at=_iso_dt(r["eaten_at"]),
            slot=r["slot"],
            food_name=r["food_name"],
            food_catalog_id=r["food_catalog_id"],
            servings=r["servings"],
            macros=_macros_from_row(r),
            notes=r["notes"],
        )


# --- supplements --------------------------------------------------------------


class SupplementRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_active(self) -> list[Supplement]:
        rows = self.conn.execute(
            "SELECT * FROM supplements WHERE active = 1"
        ).fetchall()
        return [self._row(r) for r in rows]

    def find_by_name(self, name: str) -> Supplement | None:
        r = self.conn.execute(
            "SELECT * FROM supplements WHERE LOWER(name) = LOWER(?)", (name.strip(),)
        ).fetchone()
        return self._row(r) if r else None

    def add(self, s: Supplement) -> Supplement:
        cur = self.conn.execute(
            "INSERT INTO supplements "
            "(name, kind, typical_dose, typical_unit, "
            " active_ingredients, interaction_tags, started_on, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                s.name,
                s.kind,
                s.typical_dose,
                s.typical_unit,
                json.dumps(s.active_ingredients),
                json.dumps(s.interaction_tags),
                s.started_on,
                int(s.active),
            ),
        )
        self.conn.commit()
        return s.model_copy(update={"id": cur.lastrowid})

    @staticmethod
    def _row(r: sqlite3.Row) -> Supplement:
        return Supplement(
            id=r["id"],
            name=r["name"],
            kind=r["kind"],
            typical_dose=r["typical_dose"],
            typical_unit=r["typical_unit"],
            active_ingredients=_jl(r["active_ingredients"]),
            interaction_tags=_jl(r["interaction_tags"]),
            started_on=r["started_on"],
            active=_b(r["active"]),
        )


class SupplementLogRepo:
    def __init__(self, conn: sqlite3.Connection, supplements: SupplementRepo) -> None:
        self.conn = conn
        self.supplements = supplements

    def log(self, entry: SupplementLog) -> SupplementLog:
        sup_id = entry.supplement_id
        if sup_id is None:
            match = self.supplements.find_by_name(entry.supplement_name)
            if match is not None:
                sup_id = match.id

        cur = self.conn.execute(
            "INSERT INTO supplement_log "
            "(taken_at, supplement_name, supplement_id, dose, unit, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                entry.taken_at.isoformat(),
                entry.supplement_name,
                sup_id,
                entry.dose,
                entry.unit,
                entry.notes,
            ),
        )
        self.conn.commit()
        return entry.model_copy(update={"id": cur.lastrowid, "supplement_id": sup_id})

    def recent(self, limit: int = 10) -> list[SupplementLog]:
        rows = self.conn.execute(
            "SELECT * FROM supplement_log ORDER BY taken_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row(r) for r in rows]

    def for_date(self, d: date) -> list[SupplementLog]:
        rows = self.conn.execute(
            "SELECT * FROM supplement_log WHERE date(taken_at) = ? ORDER BY taken_at ASC",
            (d.isoformat(),),
        ).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(r: sqlite3.Row) -> SupplementLog:
        return SupplementLog(
            id=r["id"],
            taken_at=_iso_dt(r["taken_at"]),
            supplement_name=r["supplement_name"],
            supplement_id=r["supplement_id"],
            dose=r["dose"],
            unit=r["unit"],
            notes=r["notes"],
        )


# --- bundle -------------------------------------------------------------------


class Repos:
    """One-stop accessor for every repo, sharing one sqlite3.Connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.profile = ProfileRepo(conn)
        self.conditions = ConditionRepo(conn)
        self.medications = MedicationRepo(conn)
        self.allergies = AllergyRepo(conn)
        self.goals = GoalRepo(conn)
        self.food_catalog = FoodCatalogRepo(conn)
        self.meal_log = MealLogRepo(conn, self.food_catalog)
        self.supplements = SupplementRepo(conn)
        self.supplement_log = SupplementLogRepo(conn, self.supplements)
