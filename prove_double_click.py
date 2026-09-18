"""The double-click proof: two POSTs fired at the same instant.

    python prove_double_click.py            # against http://localhost:8000
    python prove_double_click.py --reset    # first delete all existing reports

Expected: both answers carry the SAME id (one is 201, the other 200) and
reports/ gains exactly ONE new file. Then a POST with {"force": true} makes a
fresh one. Standard library only, so it runs anywhere.
"""

import argparse
import json
import sqlite3
import threading
import urllib.request
from pathlib import Path

import db

REPORTS_DIR = Path(__file__).parent / "reports"


def post(base: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(f"{base}/reports", data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status, json.load(resp)


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
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    if args.reset:
        reset()

    before = pdfs()
    results: list[tuple[int, dict]] = [None, None]  # type: ignore[list-item]
    barrier = threading.Barrier(2)  # release both requests at the same moment

    def fire(i: int) -> None:
        barrier.wait()
        results[i] = post(args.base)

    threads = [threading.Thread(target=fire, args=(i,)) for i in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    print("two simultaneous POSTs:")
    for i, (status, body) in enumerate(results, start=1):
        print(f"  request {i}: HTTP {status}  {body}")
    created = pdfs() - before
    same_id = results[0][1]["id"] == results[1][1]["id"]
    print(f"  same id in both answers: {same_id}")
    print(f"  new files in reports/:   {len(created)} {sorted(created)}")

    status, body = post(args.base, {"force": True})
    print(f'\nPOST with {{"force": true}}: HTTP {status}  {body}')
    forced_is_new = body["id"] not in {r[1]["id"] for r in results}
    print(f"  a new id, on purpose: {forced_is_new}")

    ok = same_id and len(created) == 1 and forced_is_new
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
