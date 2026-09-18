from contextlib import asynccontextmanager

import inngest
import inngest.fast_api
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

import db
import jobs
import reports_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect()
    db.init_db(conn)  # make sure the tables exist (and are up to date) before the first request
    conn.close()
    yield


app = FastAPI(title="PDF report generator", lifespan=lifespan)

# Lets Inngest call the background job at /api/inngest (stretch).
inngest.fast_api.serve(app, jobs.client, [jobs.generate_report])


class CreateReport(BaseModel):
    force: bool = False  # true = skip the "already generated today" check


def summary(report: dict) -> dict:
    """What POST /reports answers with: enough to find the report again."""
    return {
        "id": report["id"],
        "status": report["status"],
        "file": report["file"],  # a link once done, null while still pending
        "status_url": f"/reports/{report['id']}",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


# These are plain `def` routes on purpose: FastAPI runs them in a worker
# thread, so the few seconds a render takes don't freeze the whole server.


@app.post("/reports", status_code=201)
def create_report(response: Response, body: CreateReport | None = None, background: bool = False):
    """Generate a report.

    Default: runs the whole pipeline inside the request and answers `201` when
    the PDF exists (a few seconds). See the README for when that stops being
    acceptable.

    `?background=true`: answers `202` in milliseconds with a pending report,
    and an Inngest job does the work; poll `status_url` until it says `done`.

    Either way it is idempotent per day: if a report was already requested
    today, that one is returned (`200`) instead of making another. Send
    `{"force": true}` to generate a fresh one anyway.
    """
    force = bool(body and body.force)

    if background:
        report, created = reports_service.request_background_report(force=force)
        if created:
            try:
                # Event id = idempotency key: sending the same one twice starts one run.
                # It includes the creation time, not just the row id: ids can be
                # reused (e.g. after the table is emptied), and Inngest silently drops
                # an event whose id it has already seen in the last 24 hours.
                jobs.client.send_sync(
                    inngest.Event(
                        name=jobs.GENERATE_REQUESTED,
                        id=f"generate-report-{report['id']}-{report['created_at']}",
                        data={"report_id": report["id"]},
                    )
                )
            except Exception as exc:
                # Don't leave a "pending" report that nothing will ever finish.
                reports_service.mark_failed(report["id"], f"Could not reach Inngest: {exc}")
                raise HTTPException(
                    status_code=502,
                    detail="Could not reach Inngest, so the report was not started. "
                    "Is the Inngest dev server running? (see the README)",
                ) from exc
        response.status_code = 202 if created else 200
        return summary(report)

    report, created = reports_service.get_or_create_report(force=force)
    if not created:
        response.status_code = 200  # same request twice -> the existing report, no new file
    return {"id": report["id"], "file": report["file"], "status": report["status"]}


@app.get("/reports/{report_id}")
def get_report(report_id: int):
    """The record. `status` is `pending`, `done` or `failed`; `file` is a link once done."""
    report = reports_service.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    return report


@app.get("/reports/{report_id}/file")
def get_report_file(report_id: int):
    """The only route that moves megabytes; everything else is a few bytes of JSON."""
    report = reports_service.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    if report["status"] == "pending":
        raise HTTPException(status_code=409, detail=f"Report {report_id} is still being generated")
    if report["status"] == "failed":
        raise HTTPException(status_code=409, detail=f"Report {report_id} failed: {report['error']}")
    path = reports_service.report_file(report)
    if path is None:
        raise HTTPException(status_code=404, detail=f"The file for report {report_id} is missing on disk")
    return FileResponse(path, media_type="application/pdf", filename=f"report-{report_id}.pdf")
