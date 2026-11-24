"""
Runs the 11 reference queries against store.db and prints each answer.
Next to each answer is the question to ask in the app, so you can compare.

Run:  uv run python sql_checks.py
No model, no API calls.
"""

import os
import sqlite3

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "store.db")

# Every query returns: id, name, price, average rating (rating is rounded to 2 decimals)
RATED = (
    "select p.id, p.name, p.price, round(avg(r.rating), 2) "
    "from products p join reviews r on r.product_id = p.id "
)

CHECKS = [
    (
        "Q1",
        "I want organic honey",
        RATED + "where p.name like ? and p.is_organic = 1 group by p.id order by p.id",
        ("%honey%",),
    ),
    (
        "Q2",
        "I want organic honey with 4.5+ rating and less than $20",
        RATED + "where p.name like ? and p.is_organic = 1 and p.price <= 20 "
        "group by p.id having avg(r.rating) >= 4.5 order by p.id",
        ("%honey%",),
    ),
    (
        "Q3",
        "honey under $10",
        RATED + "where p.name like ? and p.price <= 10 group by p.id order by p.id",
        ("%honey%",),
    ),
    (
        "Q4",
        "show me non-organic honey",
        RATED + "where p.name like ? and p.is_organic = 0 group by p.id order by p.id",
        ("%honey%",),
    ),
    (
        "Q5",
        "honey with 4.7+ rating",
        RATED
        + "where p.name like ? group by p.id having avg(r.rating) >= 4.7 order by p.id",
        ("%honey%",),
    ),
    (
        "Q6",
        "what is the cheapest organic honey?",
        RATED
        + "where p.name like ? and p.is_organic = 1 group by p.id order by p.price limit 1",
        ("%honey%",),
    ),
    (
        "Q7",
        "which honey has the best rating?",
        RATED + "where p.name like ? group by p.id order by avg(r.rating) desc limit 1",
        ("%honey%",),
    ),
    (
        "Q8",
        "I want oats",
        RATED + "where p.name like ? group by p.id order by p.id",
        ("%oats%",),
    ),
    (
        "Q9",
        "I want organic unicorn meat   (expected: nothing)",
        "select p.id, p.name, p.price from products p where p.name like ?",
        ("%unicorn%",),
    ),
    (
        "Q10",
        "show me organic products under $15",
        RATED
        + "where p.is_organic = 1 and p.price <= 15 group by p.id order by p.price",
        (),
    ),
    (
        "Q11",
        "show me coffee",
        RATED + "where p.category = ? group by p.id order by p.id",
        ("coffee",),
    ),
]


def main():
    conn = sqlite3.connect(DB)
    for qid, app_question, sql, params in CHECKS:
        rows = conn.execute(sql, params).fetchall()
        print(f"\n{qid}   ask the app: {app_question}")
        if not rows:
            print("      -> (no rows)")
        for row in rows:
            pid, name, price, *rest = row
            rating = f"  ★{rest[0]}" if rest else ""
            print(f"      -> ID {pid:>2}  {name:<32} ${price:<6}{rating}")
    conn.close()


if __name__ == "__main__":
    main()
