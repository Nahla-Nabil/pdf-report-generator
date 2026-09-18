"""Generating a report and remembering where it went."""

import os
import sqlite3
from datetime import datetime
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
