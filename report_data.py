"""Turns 200 rows into the handful of numbers a report is made of."""

import sqlite3
from datetime import date

import db

# --- The aggregation queries (also pasted into the README) -------------------

TOTALS_SQL = """
SELECT COUNT(*)                          AS total_orders,
       ROUND(COALESCE(SUM(amount), 0), 2) AS total_revenue
FROM orders
"""

TOP_PRODUCTS_SQL = """
SELECT product,
       COUNT(*)              AS orders,
       ROUND(SUM(amount), 2) AS revenue
FROM orders
GROUP BY product
ORDER BY revenue DESC
LIMIT 5
"""

# One row per calendar day for the last 7 days, *including days with no
# orders* (a plain GROUP BY on orders would silently skip those). The
# recursive CTE builds the 7 days; the LEFT JOIN counts orders on each.
ORDERS_PER_DAY_SQL = """
WITH RECURSIVE days(day) AS (
    SELECT date(:today, '-6 days')
    UNION ALL
    SELECT date(day, '+1 day') FROM days WHERE day < date(:today)
)
SELECT days.day AS day, COUNT(orders.id) AS orders
FROM days
LEFT JOIN orders ON orders.created_at = days.day
GROUP BY days.day
ORDER BY days.day
"""

ALL_ORDERS_SQL = """
SELECT id, customer, product, ROUND(amount, 2) AS amount, created_at
FROM orders
ORDER BY created_at DESC, id DESC
"""


def get_report_data(conn: sqlite3.Connection | None = None, today: date | None = None) -> dict:
    """One dict with the four things the report needs."""
    today = today or date.today()
    own_conn = conn is None
    conn = conn or db.connect()
    try:
        totals = conn.execute(TOTALS_SQL).fetchone()
        top_products = [dict(r) for r in conn.execute(TOP_PRODUCTS_SQL)]
        per_day = [dict(r) for r in conn.execute(ORDERS_PER_DAY_SQL, {"today": today.isoformat()})]
        return {
            "generated_on": today.isoformat(),
            "total_orders": totals["total_orders"],
            "total_revenue": totals["total_revenue"],
            "top_products": top_products,
            "orders_per_day": per_day,
        }
    finally:
        if own_conn:
            conn.close()


def list_orders(conn: sqlite3.Connection | None = None) -> list[dict]:
    """Every order — the deliberately long table at the bottom of the PDF."""
    own_conn = conn is None
    conn = conn or db.connect()
    try:
        return [dict(r) for r in conn.execute(ALL_ORDERS_SQL)]
    finally:
        if own_conn:
            conn.close()
