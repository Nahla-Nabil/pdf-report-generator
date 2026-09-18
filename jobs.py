"""The background job: Inngest runs query -> render -> save as separate,
individually retried and remembered steps.

The API only claims a report id and sends an event; this function does the
slow part. Inngest calls it over HTTP at /api/inngest (see main.py).
"""

import os

import inngest

import reports_service

# Dev mode is the default so `uvicorn main:app` + the Inngest dev server just
# work locally. Set INNGEST_PRODUCTION=1 (plus Inngest's event and signing
# keys) when running against Inngest Cloud.
client = inngest.Inngest(
    app_id="pdf-report-generator",
    is_production=os.getenv("INNGEST_PRODUCTION") == "1",
)

GENERATE_REQUESTED = "reports/generate.requested"


def _report_id_of(ctx: inngest.ContextSync) -> int:
    return int(ctx.event.data["report_id"])


def _on_failure(ctx: inngest.ContextSync) -> None:
    """Runs once the job has used up its retries (or hit a non-retriable
    error): the report is marked failed so a client polling it stops waiting
    and can see why."""
    data = ctx.event.data or {}
    report_id = (((data.get("event") or {}).get("data")) or {}).get("report_id")
    message = ((data.get("error") or {}).get("message")) or "The report job failed."
    if report_id is not None:
        reports_service.mark_failed(int(report_id), message)


@client.create_function(
    fn_id="generate-report",
    trigger=inngest.TriggerEvent(event=GENERATE_REQUESTED),
    retries=2,
    on_failure=_on_failure,
)
def generate_report(ctx: inngest.ContextSync) -> dict:
    report_id = _report_id_of(ctx)

    # Each step below is remembered once it succeeds: if `render` fails and is
    # retried, `query` is NOT run again, its stored result is reused.
    if not ctx.step.run("check-report", reports_service.job_load, report_id):
        raise inngest.NonRetriableError(f"Report {report_id} is not waiting to be generated.")

    data = ctx.step.run("query", reports_service.job_query)
    tmp = ctx.step.run("render", reports_service.job_render, report_id, data)
    path = ctx.step.run("save", reports_service.job_save, report_id, tmp)
    return {"report_id": report_id, "path": path}
