"""The double-click proof: two POSTs fired at the same instant.

    python prove_double_click.py                       # against http://127.0.0.1:8000
    python prove_double_click.py --reset               # first delete all existing reports
    python prove_double_click.py --reset --background  # same, for the Inngest background mode

Expected: both answers carry the SAME id (one is 201, the other 200) and
reports/ gains exactly ONE new file. Then a POST with {"force": true} makes a
fresh one. In --background mode the answers are 202 and 200, and the script
waits for the job to finish before counting files. Standard library only.
"""

import argparse
import json
import sqlite3
import threading
import time
import urllib.request
from pathlib import Path

import db

REPORTS_DIR = Path(__file__).parent / "reports"


def post(base: str, body: dict | None = None, background: bool = False) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    url = f"{base}/reports" + ("?background=true" if background else "")
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status, json.load(resp)


def wait_until_done(base: str, report_id: int, timeout: float = 60) -> str:
    """Poll a background report until it stops being pending."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with urllib.request.urlopen(f"{base}/reports/{report_id}", timeout=30) as resp:
            status = json.load(resp)["status"]
        if status != "pending":
            return status
        time.sleep(0.2)
    return "pending"


def pdfs() -> set[str]:
    return {p.name for p in REPORTS_DIR.glob("*.pdf") if p.name != "test.pdf"}


def reset() -> None:
    conn = sqlite3.connect(db.DB_PATH)
    conn.execute("DELETE FROM reports")
    conn.commit()
    conn.close()
    for name in pdfs():
        (REPORTS_DIR / name).unlink()
    print("reset: all reports deleted\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")  # 127.0.0.1: on Windows "localhost" can stall ~2s on IPv6
    parser.add_argument("--background", action="store_true", help="use POST /reports?background=true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    if args.reset:
        reset()

    before = pdfs()
    results: list[tuple[int, dict]] = [None, None]  # type: ignore[list-item]
    barrier = threading.Barrier(2)  # release both requests at the same moment

    def fire(i: int) -> None:
        barrier.wait()
        results[i] = post(args.base, background=args.background)

    threads = [threading.Thread(target=fire, args=(i,)) for i in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    print("two simultaneous POSTs:")
    for i, (status, body) in enumerate(results, start=1):
        print(f"  request {i}: HTTP {status}  {body}")
    if args.background:
        for report_id in {r[1]["id"] for r in results}:
            print(f"  waiting for background job of report {report_id}: {wait_until_done(args.base, report_id)}")
    created = pdfs() - before
    same_id = results[0][1]["id"] == results[1][1]["id"]
    print(f"  same id in both answers: {same_id}")
    print(f"  new files in reports/:   {len(created)} {sorted(created)}")

    status, body = post(args.base, {"force": True}, background=args.background)
    print(f'\nPOST with {{"force": true}}: HTTP {status}  {body}')
    if args.background:
        print(f"  waiting for its job: {wait_until_done(args.base, body['id'])}")
    forced_is_new = body["id"] not in {r[1]["id"] for r in results}
    print(f"  a new id, on purpose: {forced_is_new}")

    ok = same_id and len(created) == 1 and forced_is_new
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
