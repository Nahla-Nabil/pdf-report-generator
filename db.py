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

-- Bookkeeping for generated files: the PDF itself lives on disk, the
-- database only remembers where (store and link, don't pass the bytes around).
CREATE TABLE IF NOT EXISTS reports (
    id         INTEGER PRIMARY KEY,
    path       TEXT NOT NULL,     -- relative to the project root, e.g. reports/3.pdf ('' until generated)
    created_at TEXT NOT NULL,     -- ISO timestamp, local time
    status     TEXT NOT NULL DEFAULT 'done',   -- pending | done | failed (background jobs)
    error      TEXT                            -- why it failed, when it did
);
"""

# Columns added after the first version of the table. `CREATE TABLE IF NOT
# EXISTS` never alters a table that already exists, so a report.db created
# before the background-job stretch gets them added here.
_REPORTS_MIGRATIONS = {
    "status": "ALTER TABLE reports ADD COLUMN status TEXT NOT NULL DEFAULT 'done'",
    "error": "ALTER TABLE reports ADD COLUMN error TEXT",
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["amount"]
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(reports)")}
    for column, statement in _REPORTS_MIGRATIONS.items():
        if column not in existing:
            conn.execute(statement)
    conn.commit()
