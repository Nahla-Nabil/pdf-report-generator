"""The only place that knows where the database lives and what its tables look like."""

import sqlite3
from pathlib import Path

# Next to this file, not the current directory, so the app and the scripts
# always open the same database no matter where they are started from.
DB_PATH = Path(__file__).parent / "report.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id         INTEGER PRIMARY KEY,
    customer   TEXT    NOT NULL,
    product    TEXT    NOT NULL,
    amount     REAL    NOT NULL,
    created_at TEXT    NOT NULL   -- ISO date, e.g. 2026-09-18
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["amount"]
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
