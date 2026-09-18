from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

import db
import reports_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect()
    db.init_db(conn)  # make sure the tables exist before the first request
    conn.close()
    yield


app = FastAPI(title="PDF report generator", lifespan=lifespan)


class CreateReport(BaseModel):
    force: bool = False  # true = skip the "already generated today" check


@app.get("/health")
def health():
    return {"status": "ok"}


# These are plain `def` routes on purpose: FastAPI runs them in a worker
# thread, so the few seconds a render takes don't freeze the whole server.


@app.post("/reports", status_code=201)
def create_report(response: Response, body: CreateReport | None = None):
    """Runs the whole pipeline inside the request. Yes, it takes a few
    seconds. See the README for when that stops being acceptable.

    Idempotent per day: if a report was already generated today, return that
    one (200) instead of making another (201). Send {"force": true} to
    generate a fresh one anyway."""
    report, created = reports_service.get_or_create_report(force=bool(body and body.force))
    if not created:
        response.status_code = 200  # same request twice -> the existing report, no new file
    return {"id": report["id"], "file": report["file"]}


@app.get("/reports/{report_id}")
def get_report(report_id: int):
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
    path = reports_service.report_file(report)
    if path is None:
        raise HTTPException(status_code=404, detail=f"The file for report {report_id} is missing on disk")
    return FileResponse(path, media_type="application/pdf", filename=f"report-{report_id}.pdf")
