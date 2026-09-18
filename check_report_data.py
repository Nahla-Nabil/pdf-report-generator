"""Do the SQL numbers make sense? Recompute everything in plain Python from the
raw rows and compare — if a query is wrong, the two disagree.

    python check_report_data.py
"""

from collections import Counter, defaultdict
from datetime import date, timedelta

import db
from report_data import get_report_data, list_orders


def main() -> None:
    conn = db.connect()
    rows = list_orders(conn)
    report = get_report_data(conn)
    today = date.today()

    revenue = defaultdict(float)
    count = Counter()
    for r in rows:
        revenue[r["product"]] += r["amount"]
        count[r["product"]] += 1

    checks = {
        "total_orders matches row count": report["total_orders"] == len(rows),
        "total_revenue matches sum": abs(report["total_revenue"] - sum(revenue.values())) < 0.01,
        "top 5 has 5 products": len(report["top_products"]) == 5,
        "top 5 sorted by revenue desc": [p["revenue"] for p in report["top_products"]]
        == sorted((p["revenue"] for p in report["top_products"]), reverse=True),
        "top 5 revenues match plain Python": all(
            abs(p["revenue"] - revenue[p["product"]]) < 0.01 and p["orders"] == count[p["product"]]
            for p in report["top_products"]
        ),
        "no product bigger than the total": all(
            p["revenue"] <= report["total_revenue"] for p in report["top_products"]
        ),
        "7 days, oldest first, ending today": [d["day"] for d in report["orders_per_day"]]
        == [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)],
        "per-day counts match plain Python": all(
            d["orders"] == sum(1 for r in rows if r["created_at"] == d["day"])
            for d in report["orders_per_day"]
        ),
    }
    for name, ok in checks.items():
        print(("PASS" if ok else "FAIL"), "-", name)
    raise SystemExit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
