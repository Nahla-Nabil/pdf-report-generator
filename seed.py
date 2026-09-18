"""Fill report.db with ~200 invented orders.

    python seed.py

Safe to run twice: it starts by deleting every order, so you always end up
with exactly one clean copy.
"""

import random
from datetime import date, timedelta

import db

ORDER_COUNT = 200
PRODUCTS = [
    "Espresso Machine",
    "Coffee Grinder",
    "Pour-over Kettle",
    "Ceramic Mug Set",
    "Cold Brew Bottle",
    "Whole Bean Sampler",
]
CUSTOMERS = [
    "Amal", "Bilal", "Carmen", "Dina", "Elias", "Farah", "Gabriel", "Hana",
    "Ibrahim", "Jana", "Karim", "Layla", "Mona", "Nadim", "Omar", "Rania",
]


def make_orders(count: int = ORDER_COUNT, today: date | None = None) -> list[tuple]:
    today = today or date.today()
    return [
        (
            random.choice(CUSTOMERS),
            random.choice(PRODUCTS),
            round(random.uniform(5, 200), 2),
            (today - timedelta(days=random.randint(0, 29))).isoformat(),
        )
        for _ in range(count)
    ]


def seed() -> int:
    conn = db.connect()
    try:
        db.init_db(conn)
        conn.execute("DELETE FROM orders")  # the "safe to run twice" part
        conn.executemany(
            "INSERT INTO orders (customer, product, amount, created_at) VALUES (?, ?, ?, ?)",
            make_orders(),
        )
        conn.commit()
        return conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    finally:
        conn.close()


if __name__ == "__main__":
    print(f"seeded {seed()} orders into {db.DB_PATH.name}")
