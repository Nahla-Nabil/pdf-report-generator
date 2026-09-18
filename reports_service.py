"""Generating a report and remembering where it went."""

import os
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

import db
import render

BASE_DIR = Path(__file__).parent


def file_link(report_id: int) -> str:
    return f"/reports/{report_id}/file"


def to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "path": row["path"],
        "created_at": row["created_at"],
        "file": file_link(row["id"]),
    }


def get_report(report_id: int) -> dict | None:
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return to_dict(row) if row else None
    finally:
        conn.close()


def report_from_today() -> dict | None:
    """The newest report generated today (local date), if there is one."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT * FROM reports WHERE substr(created_at, 1, 10) = ? ORDER BY id DESC LIMIT 1",
            (date.today().isoformat(),),
        ).fetchone()
        return to_dict(row) if row else None
    finally:
        conn.close()


# "Check whether today's report exists, then generate it" is two steps, and a
# double-click lands the second request *between* them: it checks while the
# first is still rendering (nothing in the database yet) and generates a
# duplicate. The lock makes check+generate one atomic step, so the second
# request waits, then finds the first one's report.
#
# Limit: a threading.Lock only protects ONE server process. With several
# workers or instances you need the database to referee instead (see README).
_generate_lock = threading.Lock()


def get_or_create_report(force: bool = False) -> tuple[dict, bool]:
    """Returns (report, created). created=False means an existing report from
    today was reused instead of generating another."""
    with _generate_lock:
        if not force:
            existing = report_from_today()
            if existing:
                return existing, False
        return create_report(), True


def create_report() -> dict:
    """The whole pipeline, run right here in the request:
    query -> render -> store the PDF on disk -> remember its path.

    The (slow) render goes to a temp file first, and only then do we take a
    short database transaction to claim an id, move the file into place and
    record its path. So a slow render never holds a database lock, and a
    failed render leaves neither a stray row nor a half-written file.
    """
    tmp = render.REPORTS_DIR / f".tmp-{uuid4().hex}.pdf"
    final: Path | None = None
    conn = db.connect()
    try:
        render.generate_pdf(tmp)

        cur = conn.execute(
            "INSERT INTO reports (path, created_at) VALUES ('', ?)",
            (datetime.now().isoformat(timespec="seconds"),),
        )
        report_id = cur.lastrowid
        final = render.REPORTS_DIR / f"{report_id}.pdf"
        os.replace(tmp, final)
        conn.execute(
            "UPDATE reports SET path = ? WHERE id = ?",
            (final.relative_to(BASE_DIR).as_posix(), report_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return to_dict(row)
    except BaseException:
        conn.rollback()
        tmp.unlink(missing_ok=True)
        if final is not None:
            final.unlink(missing_ok=True)
        raise
    finally:
        conn.close()


def report_file(report: dict) -> Path | None:
    """The PDF on disk for a report, or None if it has gone missing."""
    path = BASE_DIR / report["path"]
    return path if path.is_file() else None
