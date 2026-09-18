"""Numbers in, PDF out.

You never draw a PDF: you write a web page and ask a real (headless)
browser to print it.

    python render.py        # writes reports/test.pdf
"""

from datetime import date
from html import escape
from pathlib import Path

from playwright.sync_api import sync_playwright

import report_data

REPORTS_DIR = Path(__file__).parent / "reports"

CSS = """
  * { box-sizing: border-box; }
  body { font-family: "Segoe UI", Arial, sans-serif; color: #1f2937; margin: 0; font-size: 11px; }
  h1 { font-size: 24px; margin: 0 0 2px; }
  h2 { font-size: 14px; margin: 26px 0 8px; padding-bottom: 4px; border-bottom: 2px solid #e5e7eb; }
  .subtitle { color: #6b7280; margin-bottom: 18px; }
  .tiles { display: flex; gap: 12px; }
  .tile { flex: 1; background: #f3f4f6; border-radius: 8px; padding: 12px 14px; }
  .tile .label { color: #6b7280; font-size: 10px; text-transform: uppercase; letter-spacing: .04em; }
  .tile .value { font-size: 22px; font-weight: 700; margin-top: 2px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 5px 8px; text-align: left; border-bottom: 1px solid #e5e7eb; }
  th { background: #111827; color: #fff; font-weight: 600; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .bar { display: inline-block; height: 8px; background: #10b981; border-radius: 4px; vertical-align: middle; }

  /* --- The classic page-break trap ---------------------------------------
     A long table crosses a page boundary. Without these two rules a row can
     be sliced in half, and the header only appears on page 1. */
  tr    { break-inside: avoid; }
  thead { display: table-header-group; }   /* repeat the header on every page */
"""


def money(value: float) -> str:
    return f"${value:,.2f}"


def build_html(report: dict, orders: list[dict]) -> str:
    top = "".join(
        f"<tr><td>{i}</td><td>{escape(p['product'])}</td>"
        f"<td class='num'>{p['orders']}</td><td class='num'>{money(p['revenue'])}</td></tr>"
        for i, p in enumerate(report["top_products"], start=1)
    )
    peak = max((d["orders"] for d in report["orders_per_day"]), default=0) or 1
    per_day = "".join(
        f"<tr><td>{d['day']}</td><td class='num'>{d['orders']}</td>"
        f"<td><span class='bar' style='width:{int(d['orders'] / peak * 160)}px'></span></td></tr>"
        for d in report["orders_per_day"]
    )
    rows = "".join(
        f"<tr><td class='num'>{o['id']}</td><td>{escape(o['customer'])}</td>"
        f"<td>{escape(o['product'])}</td><td class='num'>{money(o['amount'])}</td>"
        f"<td>{o['created_at']}</td></tr>"
        for o in orders
    )
    generated = date.fromisoformat(report["generated_on"]).strftime("%B %d, %Y").replace(" 0", " ")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Sales report {report['generated_on']}</title>
<style>{CSS}</style></head>
<body>
  <h1>Sales report</h1>
  <div class="subtitle">Generated {generated}</div>

  <div class="tiles">
    <div class="tile"><div class="label">Total orders</div><div class="value">{report['total_orders']:,}</div></div>
    <div class="tile"><div class="label">Total revenue</div><div class="value">{money(report['total_revenue'])}</div></div>
  </div>

  <h2>Top 5 products by revenue</h2>
  <table>
    <thead><tr><th>#</th><th>Product</th><th class="num">Orders</th><th class="num">Revenue</th></tr></thead>
    <tbody>{top}</tbody>
  </table>

  <h2>Orders per day, last 7 days</h2>
  <table>
    <thead><tr><th>Day</th><th class="num">Orders</th><th></th></tr></thead>
    <tbody>{per_day}</tbody>
  </table>

  <h2>All orders ({len(orders)})</h2>
  <table>
    <thead><tr><th class="num">ID</th><th>Customer</th><th>Product</th><th class="num">Amount</th><th>Date</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body></html>"""


FOOTER = (
    '<div style="font-size:9px;color:#6b7280;width:100%;text-align:center;">'
    'Page <span class="pageNumber"></span> of <span class="totalPages"></span></div>'
)


def html_to_pdf(html: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html)
            page.pdf(
                path=str(path),
                format="A4",
                print_background=True,
                margin={"top": "18mm", "bottom": "18mm", "left": "14mm", "right": "14mm"},
                display_header_footer=True,
                header_template="<div></div>",
                footer_template=FOOTER,
            )
        finally:
            browser.close()


def generate_pdf(path: Path) -> None:
    """The whole pipeline: query -> HTML -> PDF at `path`."""
    html_to_pdf(build_html(report_data.get_report_data(), report_data.list_orders()), path)


if __name__ == "__main__":
    out = REPORTS_DIR / "test.pdf"
    generate_pdf(out)
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")
