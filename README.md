# PDF report generator

(README in progress. The finished version lands in Stage 6.)

## Serving the report (Stage 4)

`POST /reports` runs the whole pipeline inside the request (query, render, save the PDF to disk, remember its path) and answers `201` with a link. `GET /reports/{id}` returns the record, and `GET /reports/{id}/file` streams the PDF from disk. JSON responses only ever carry the link, never the file's bytes.

**When would I move this work out of the request?** Today the wait is about 2 seconds for 200 rows, which is fine for one person clicking one button. I would move it out of the request once it takes more than roughly 10 seconds, or as soon as several people can ask at once: every request launches its own Chromium (about 2 s of CPU and a lot of memory each), so a handful of concurrent reports would exhaust the server's workers, and a slow request risks hitting a proxy or browser timeout and being retried into a second, duplicate report.

## Ask twice, get one (Stage 5)

`POST /reports` returns the report already generated today (`200`) instead of making another (`201`). Send `{"force": true}` to generate a fresh one anyway.

**What the check protects against:** a double-click, a page refresh, or a client or proxy that retries a slow request would otherwise produce a duplicate report each time, and every duplicate costs about two seconds of CPU and a Chromium launch. A real-world example where a missing check costs money is a customer being charged, or emailed an invoice, twice because a "Pay" button was clicked twice or a request was retried, which means a refund, a support ticket, and a customer who trusts you a little less.

**The naive version is broken, and I watched it break.** My first implementation was "check whether today's report exists, and if not, generate one". Firing two simultaneous requests with `prove_double_click.py` produced two files (ids 1 and 2): the second request checks while the first is still rendering, finds nothing in the database yet, and generates its own. The fix is a lock around check and generate, so the second request waits, then finds the first one's report.

```
python prove_double_click.py --reset
  request 1: HTTP 201  {'id': 1, 'file': '/reports/1/file'}
  request 2: HTTP 200  {'id': 1, 'file': '/reports/1/file'}
  new files in reports/: 1 ['1.pdf']
  POST with {"force": true}: HTTP 201  {'id': 2, ...}
```

**Limit:** a `threading.Lock` only protects one server process. With several workers or instances the database has to referee instead, for example by inserting a "claimed" row first under a unique constraint, or using a database-level lock, and only then rendering.
