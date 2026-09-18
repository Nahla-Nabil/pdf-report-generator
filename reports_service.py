"""Generating a report and remembering where it went.

Two ways to make one:
  * in the request  -> create_report() / get_or_create_report()      (Stages 4-5)
  * as a background job -> request_background_report() + the job_*
    steps below, run by Inngest                                       (stretch)
"""

import os
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import db
import render
import report_data

BASE_DIR = Path(__file__).parent

# A background report that has been "pending" longer than this is given up on.
# It has to outlast a job that is legitimately retrying (Inngest backs off for a
# couple of minutes), but not wait forever for a job that never started, e.g.
# because its event was lost or the Inngest dev server was restarted.
PENDING_TIMEOUT_SECONDS = int(os.getenv("REPORT_PENDING_TIMEOUT_SECONDS", "300"))


def file_link(report_id: int) -> str:
    return f"/reports/{report_id}/file"


def to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "path": row["path"] or None,
        "created_at": row["created_at"],
        "status": row["status"],
        "error": row["error"],
        # A link only makes sense once there is a file behind it.
        "file": file_link(row["id"]) if row["status"] == "done" else None,
    }


def expire_stale_pending(conn: sqlite3.Connection) -> None:
    """Turn pending reports that are older than the timeout into failed ones."""
    cutoff = (datetime.now() - timedelta(seconds=PENDING_TIMEOUT_SECONDS)).isoformat(timespec="seconds")
    conn.execute(
        "UPDATE reports SET status = 'failed', error = ? WHERE status = 'pending' AND created_at < ?",
        (f"Timed out: the background job did not finish within {PENDING_TIMEOUT_SECONDS} seconds.", cutoff),
    )
    conn.commit()


def get_report(report_id: int) -> dict | None:
    conn = db.connect()
    try:
        expire_stale_pending(conn)
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return to_dict(row) if row else None
    finally:
        conn.close()


def report_from_today() -> dict | None:
    """The newest report requested today (local date) that is done or still
    being generated. A failed one doesn't count: asking again should retry."""
    conn = db.connect()
    try:
        expire_stale_pending(conn)
        row = conn.execute(
            "SELECT * FROM reports WHERE substr(created_at, 1, 10) = ? AND status != 'failed' "
            "ORDER BY id DESC LIMIT 1",
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
            "INSERT INTO reports (path, created_at, status) VALUES ('', ?, 'done')",
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
    """The PDF on disk for a report, or None if there isn't one (yet)."""
    if not report["path"]:
        return None
    path = BASE_DIR / report["path"]
    return path if path.is_file() else None


# --- Background job (stretch) ------------------------------------------------


def request_background_report(force: bool = False) -> tuple[dict, bool]:
    """Claim a report id *instantly* and leave the real work to a job.

    This is where being a background job pays off twice: the request returns
    in milliseconds, and the double-click race from Stage 5 mostly disappears,
    because the only thing done under the lock is one fast INSERT (a pending
    row that the next request will see straight away).

    Returns (report, created), same meaning as get_or_create_report().
    """
    with _generate_lock:
        if not force:
            existing = report_from_today()
            if existing:
                return existing, False
        conn = db.connect()
        try:
            cur = conn.execute(
                "INSERT INTO reports (path, created_at, status) VALUES ('', ?, 'pending')",
                (datetime.now().isoformat(timespec="seconds"),),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM reports WHERE id = ?", (cur.lastrowid,)).fetchone()
            return to_dict(row), True
        finally:
            conn.close()


def _job_tmp_path(report_id: int) -> Path:
    # Deterministic per report, so a retried step overwrites its own leftovers
    # instead of piling up files.
    return render.REPORTS_DIR / f".tmp-job-{report_id}.pdf"


def job_load(report_id: int) -> dict | None:
    """Job step 0: is there still a pending report to work on?"""
    report = get_report(report_id)
    return report if report and report["status"] == "pending" else None


def job_query() -> dict:
    """Job step 1: query. The output is stored by Inngest, so it stays small
    (numbers and rows, never bytes of a file)."""
    return {"report": report_data.get_report_data(), "orders": report_data.list_orders()}


def job_render(report_id: int, data: dict) -> str:
    """Job step 2: render the PDF to a temp file and return where it is."""
    tmp = _job_tmp_path(report_id)
    render.html_to_pdf(render.build_html(data["report"], data["orders"]), tmp)
    return tmp.relative_to(BASE_DIR).as_posix()


def job_save(report_id: int, tmp_rel: str) -> str:
    """Job step 3: move the file into place and mark the report done."""
    final = render.REPORTS_DIR / f"{report_id}.pdf"
    os.replace(BASE_DIR / tmp_rel, final)
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE reports SET path = ?, status = 'done', error = NULL WHERE id = ?",
            (final.relative_to(BASE_DIR).as_posix(), report_id),
        )
        conn.commit()
    finally:
        conn.close()
    return final.relative_to(BASE_DIR).as_posix()


def mark_failed(report_id: int, message: str) -> None:
    """Record that the job gave up, and clean up its temp file."""
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE reports SET status = 'failed', error = ? WHERE id = ? AND status = 'pending'",
            (message[:500], report_id),
        )
        conn.commit()
    finally:
        conn.close()
    _job_tmp_path(report_id).unlink(missing_ok=True)
