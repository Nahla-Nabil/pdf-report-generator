# PDF report generator

(README in progress. The finished version lands in Stage 6.)

## Serving the report (Stage 4)

`POST /reports` runs the whole pipeline inside the request (query, render, save the PDF to disk, remember its path) and answers `201` with a link. `GET /reports/{id}` returns the record, and `GET /reports/{id}/file` streams the PDF from disk. JSON responses only ever carry the link, never the file's bytes.

**When would I move this work out of the request?** Today the wait is about 2 seconds for 200 rows, which is fine for one person clicking one button. I would move it out of the request once it takes more than roughly 10 seconds, or as soon as several people can ask at once: every request launches its own Chromium (about 2 s of CPU and a lot of memory each), so a handful of concurrent reports would exhaust the server's workers, and a slow request risks hitting a proxy or browser timeout and being retried into a second, duplicate report.
