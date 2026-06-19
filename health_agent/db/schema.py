"""SQLite schema + connection helper.

One file, simple DDL. Macros are flattened into columns on `food_catalog` and
`meal_log` so daily totals are `SELECT SUM(...)` rather than a JSON unpack.
List-valued fields (tags, active_ingredients, interaction_tags) are JSON.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    id              INTEGER PRIMARY KEY CHECK (id = 1),   -- singleton row
    name            TEXT    NOT NULL,
    date_of_birth   TEXT    NOT NULL,
    sex             TEXT    NOT NULL,
    height_cm       REAL    NOT NULL,
    weight_kg       REAL    NOT NULL,
    activity_level  TEXT    NOT NULL,
    timezone        TEXT    NOT NULL DEFAULT 'UTC'
);

CREATE TABLE IF NOT EXISTS conditions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    icd10        TEXT,
    severity     TEXT    NOT NULL,
    diagnosed_on TEXT,
    tags         TEXT    NOT NULL DEFAULT '[]',
    notes        TEXT,
    active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS medications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    dose         REAL    NOT NULL,
    unit         TEXT    NOT NULL,
    frequency    TEXT    NOT NULL,
    indication   TEXT,
    taken_since  TEXT,
    active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS allergies (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    allergen  TEXT    NOT NULL,
    reaction  TEXT,
    severity  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS goals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT    NOT NULL,
    target_value REAL,
    target_unit  TEXT,
    target_date  TEXT,
    notes        TEXT,
    active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS food_catalog (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    brand           TEXT,
    serving_size    REAL    NOT NULL,
    serving_unit    TEXT    NOT NULL,
    calories        REAL    NOT NULL DEFAULT 0,
    protein_g       REAL    NOT NULL DEFAULT 0,
    carbs_g         REAL    NOT NULL DEFAULT 0,
    fat_g           REAL    NOT NULL DEFAULT 0,
    saturated_fat_g REAL    NOT NULL DEFAULT 0,
    fiber_g         REAL    NOT NULL DEFAULT 0,
    sugar_g         REAL    NOT NULL DEFAULT 0,
    sodium_mg       REAL    NOT NULL DEFAULT 0,
    iron_mg         REAL    NOT NULL DEFAULT 0,
    calcium_mg      REAL    NOT NULL DEFAULT 0,
    magnesium_mg    REAL    NOT NULL DEFAULT 0,
    potassium_mg    REAL    NOT NULL DEFAULT 0,
    zinc_mg         REAL    NOT NULL DEFAULT 0,
    vitamin_d_iu    REAL    NOT NULL DEFAULT 0,
    folate_mcg      REAL    NOT NULL DEFAULT 0,
    vitamin_b12_mcg REAL    NOT NULL DEFAULT 0,
    vitamin_c_mg    REAL    NOT NULL DEFAULT 0,
    omega3_g        REAL    NOT NULL DEFAULT 0,
    tags            TEXT    NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_food_catalog_name ON food_catalog(name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS meal_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    eaten_at        TEXT    NOT NULL,
    slot            TEXT    NOT NULL,
    food_name       TEXT    NOT NULL,
    food_catalog_id INTEGER REFERENCES food_catalog(id),
    servings        REAL    NOT NULL,
    calories        REAL    NOT NULL DEFAULT 0,
    protein_g       REAL    NOT NULL DEFAULT 0,
    carbs_g         REAL    NOT NULL DEFAULT 0,
    fat_g           REAL    NOT NULL DEFAULT 0,
    saturated_fat_g REAL    NOT NULL DEFAULT 0,
    fiber_g         REAL    NOT NULL DEFAULT 0,
    sugar_g         REAL    NOT NULL DEFAULT 0,
    sodium_mg       REAL    NOT NULL DEFAULT 0,
    iron_mg         REAL    NOT NULL DEFAULT 0,
    calcium_mg      REAL    NOT NULL DEFAULT 0,
    magnesium_mg    REAL    NOT NULL DEFAULT 0,
    potassium_mg    REAL    NOT NULL DEFAULT 0,
    zinc_mg         REAL    NOT NULL DEFAULT 0,
    vitamin_d_iu    REAL    NOT NULL DEFAULT 0,
    folate_mcg      REAL    NOT NULL DEFAULT 0,
    vitamin_b12_mcg REAL    NOT NULL DEFAULT 0,
    vitamin_c_mg    REAL    NOT NULL DEFAULT 0,
    omega3_g        REAL    NOT NULL DEFAULT 0,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_meal_log_eaten_at ON meal_log(eaten_at);

CREATE TABLE IF NOT EXISTS supplements (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT    NOT NULL,
    kind                TEXT    NOT NULL,
    typical_dose        REAL    NOT NULL,
    typical_unit        TEXT    NOT NULL,
    active_ingredients  TEXT    NOT NULL DEFAULT '[]',
    interaction_tags    TEXT    NOT NULL DEFAULT '[]',
    started_on          TEXT,
    active              INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS supplement_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at        TEXT    NOT NULL,
    supplement_name TEXT    NOT NULL,
    supplement_id   INTEGER REFERENCES supplements(id),
    dose            REAL    NOT NULL,
    unit            TEXT    NOT NULL,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_supplement_log_taken_at ON supplement_log(taken_at);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with sane defaults.

    Notes:
        - Row factory so columns are accessible by name.
        - Foreign keys enforced (off by default in SQLite).
        - busy_timeout so concurrent connections wait briefly instead of
          immediately erroring with SQLITE_BUSY.
        - WAL mode is set ONCE in init_db(); switching journal_mode requires
          an exclusive lock, so doing it on every connect() deadlocks under
          concurrent fan-out (e.g., 3 parallel MCP tool calls).
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables/indexes if they don't exist. Also set WAL mode once."""
    # WAL is persistent at the DB level — set it here, never in connect().
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.executescript(SCHEMA)
    conn.commit()
