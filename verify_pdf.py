"""Stage 3 checkpoint, automated: does the PDF have >= 2 pages, the table
header on every page that has order rows, and every order row intact?

    python verify_pdf.py [reports/test.pdf]

Needs PyMuPDF (pip install -r requirements-dev.txt) — a checking tool, not
something the app itself uses.

How: read each page's text back as visual lines, then look for each of the
200 orders as one complete line "id customer product $amount date". A row
that a page break had sliced in half would not appear as a complete line.
"""

import sys
from collections import Counter
from pathlib import Path

import pymupdf

import db
from report_data import list_orders

HEADER_LINE = "ID Customer Product Amount Date"


def page_lines(page) -> list[str]:
    """Words grouped into visual lines (same baseline), left to right."""
    lines: dict[int, list[tuple[float, str]]] = {}
    for x0, y0, _x1, _y1, word, *_ in page.get_text("words"):
        lines.setdefault(round(y0 / 3), []).append((x0, word))
    return [" ".join(w for _, w in sorted(ws)) for _, ws in sorted(lines.items())]


def expected_line(o: dict) -> str:
    return f"{o['id']} {o['customer']} {o['product']} ${o['amount']:,.2f} {o['created_at']}"


def main(path: str) -> int:
    doc = pymupdf.open(path)
    orders = list_orders(db.connect())
    wanted = {expected_line(o): 0 for o in orders}

    pages_with_rows = 0
    pages_missing_header = []
    for number, page in enumerate(doc, start=1):
        lines = page_lines(page)
        found = [ln for ln in lines if ln in wanted]
        for ln in found:
            wanted[ln] += 1
        if found:
            pages_with_rows += 1
            if HEADER_LINE not in lines:
                pages_missing_header.append(number)

    seen = Counter(wanted.values())
    checks = {
        f"at least 2 pages (got {len(doc)})": len(doc) >= 2,
        f"order rows span {pages_with_rows} pages": pages_with_rows >= 2,
        f"table header on every page that has order rows (missing on: {pages_missing_header or 'none'})": not pages_missing_header,
        f"all {len(orders)} orders found as one complete line, none cut in half ({seen[1]} intact)": seen[1] == len(orders),
        f"no order duplicated (times seen: {dict(seen)})": set(seen) == {1},
    }
    for name, ok in checks.items():
        print(("PASS" if ok else "FAIL"), "-", name)
    for line, n in list(wanted.items()):
        if n != 1:
            print(f"    seen {n}x: {line}")
            break
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent / "reports" / "test.pdf")))
