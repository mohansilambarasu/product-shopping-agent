"""
Automated check of the shopping agent, with PASS / FAIL for each prompt.

For every prompt this script:
  1. works out the correct answer straight from store.db with SQL (no model),
  2. asks the real agent the same question (the model is used here),
  3. compares the two.

Run all 10:      uv run python eval_agent.py
Run some:        uv run python eval_agent.py 3 5     (case numbers)

It waits 40 seconds between model calls to stay under the free-tier rate limit,
so a full run takes about 8-9 minutes. The agent can never write orders by itself,
so the script also checks the orders table is untouched.
"""

import json
import os
import re
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "store.db")
PAUSE_SECONDS = 40

# Phrases the agent must never use: only the Approve button places orders.
FORBIDDEN = [
    "has been placed",
    "placed successfully",
    "shipped",
    "business days",
    "will arrive",
]


# ---------------------------------------------------------------------------
# Part 1: the correct answers, straight from the database
# ---------------------------------------------------------------------------
def db(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def order_count():
    return db("SELECT COUNT(*) FROM orders")[0][0]


def expected(
    category=None,
    name_like=None,
    organic=None,
    min_price=None,
    max_price=None,
    min_rating=None,
    order_by=None,
    limit=None,
):
    """Returns [(id, name, price, avg_rating), ...] from SQL."""
    sql = (
        "SELECT p.id, p.name, p.price, ROUND(AVG(r.rating), 2) "
        "FROM products p JOIN reviews r ON r.product_id = p.id WHERE 1=1"
    )
    params = []
    if category:
        sql += " AND p.category = ?"
        params.append(category)
    if name_like:
        sql += " AND p.name LIKE ?"
        params.append(f"%{name_like}%")
    if organic is not None:
        sql += " AND p.is_organic = ?"
        params.append(1 if organic else 0)
    if min_price is not None:
        sql += " AND p.price >= ?"
        params.append(min_price)
    if max_price is not None:
        sql += " AND p.price <= ?"
        params.append(max_price)
    sql += " GROUP BY p.id"
    if min_rating is not None:
        sql += " HAVING AVG(r.rating) >= ?"
        params.append(min_rating)
    sql += " ORDER BY " + (
        order_by or "p.id"
    )  # order_by only comes from the cases below
    if limit:
        sql += f" LIMIT {int(limit)}"
    return db(sql, params)


# ---------------------------------------------------------------------------
# The 10 cases
# ---------------------------------------------------------------------------
CASES = [
    {
        "n": 1,
        "prompts": ["any organic tea?"],
        "kind": "search",
        "expect": dict(category="tea", organic=True),
    },
    {
        "n": 2,
        "prompts": ["show me oils under $10"],
        "kind": "search",
        "expect": dict(category="oil", max_price=10),
    },
    {
        "n": 3,
        "prompts": ["organic products under $8"],
        "kind": "search",
        "expect": dict(organic=True, max_price=8),
    },
    {
        "n": 4,
        "prompts": ["organic products rated 4.7 or higher"],
        "kind": "search",
        "expect": dict(organic=True, min_rating=4.7),
    },
    {
        "n": 5,
        "prompts": ["what is the most expensive honey?"],
        "kind": "search",
        "expect": dict(name_like="honey", order_by="p.price DESC", limit=1),
    },
    {
        "n": 6,
        "prompts": ["cheapest coffee you have"],
        "kind": "search",
        "expect": dict(category="coffee", order_by="p.price ASC", limit=1),
    },
    {
        "n": 7,
        "prompts": ["honey priced between $12 and $16"],
        "kind": "search",
        "expect": dict(name_like="honey", min_price=12, max_price=16),
    },
    {
        "n": 8,
        "prompts": ["show me grains that are not organic"],
        "kind": "search",
        "expect": dict(category="grains", organic=False),
    },
    {
        "n": 9,
        "prompts": ["show me coffee", "order the Dark Roast Espresso Blend"],
        "kind": "order",
        "product_name": "Dark Roast Espresso Blend",
    },
    {"n": 10, "prompts": ["show me coffee", "I'll take one"], "kind": "no_order"},
]


# ---------------------------------------------------------------------------
# Part 2: reading what the agent said
# ---------------------------------------------------------------------------
ITEM = re.compile(r"\(ID:\s*(\d+)\)[^\n]*?\$\s*([\d.]+)\s*★\s*([\d.]+)?")


def parse_items(text):
    """[(id, price, rating)] from lines like '#1. Name (ID:1) — $14.99 ★4.63 — organic'."""
    return [
        (int(i), float(p), float(r) if r else None) for i, p, r in ITEM.findall(text)
    ]


def this_turn(result):
    turn = []
    for m in reversed(result["messages"]):
        if m.type == "human":
            break
        turn.append(m)
    return list(reversed(turn))


def find_pending(turn):
    """Same logic as find_pending_order in app.py."""
    for m in reversed(turn):
        if m.type == "tool":
            try:
                data = json.loads(m.content)
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict) and data.get("status") == "pending_approval":
                return data
    return None


def ask_agent(history, tries=4):
    from shopping_agent import (
        agent,
    )  # imported here so the SQL parts work without a key

    for attempt in range(1, tries + 1):
        try:
            return agent.invoke({"messages": history})
        except Exception as e:
            text = str(e).lower()
            rate_limited = "429" in text or "rate limit" in text or "rate_limit" in text
            if not rate_limited or attempt == tries:
                raise
            wait = 30 * attempt
            print(f"   (rate limited, waiting {wait}s)")
            time.sleep(wait)


# ---------------------------------------------------------------------------
# Part 3: compare
# ---------------------------------------------------------------------------
def compare_search(reply, want):
    errs = []
    got = parse_items(reply)
    got_ids = [i for i, _, _ in got]
    want_ids = [r[0] for r in want]
    if set(got_ids) != set(want_ids):
        errs.append(f"expected IDs {sorted(want_ids)}, agent listed {sorted(got_ids)}")
    truth = {r[0]: r for r in want}
    for pid, price, rating in got:
        if pid in truth:
            _, _, true_price, true_rating = truth[pid]
            if abs(price - true_price) > 0.005:
                errs.append(f"ID {pid}: price {price} vs database {true_price}")
            if rating is None or abs(rating - true_rating) > 0.011:
                errs.append(f"ID {pid}: rating {rating} vs database {true_rating}")
    return errs


def run_case(case):
    before = order_count()
    history, replies, pending = [], [], None
    errs = []
    try:
        for i, text in enumerate(case["prompts"]):
            history.append({"role": "user", "content": text})
            result = ask_agent(history)
            reply = result["messages"][-1].content.replace("`", "")
            history.append({"role": "assistant", "content": reply})
            replies.append(reply)
            pending = find_pending(this_turn(result))
            if i < len(case["prompts"]) - 1:
                time.sleep(PAUSE_SECONDS)

        if case["kind"] == "search":
            errs += compare_search(replies[-1], expected(**case["expect"]))
        elif case["kind"] == "order":
            want_id = db(
                "SELECT id FROM products WHERE name = ?", (case["product_name"],)
            )[0][0]
            if not pending:
                errs.append("no order was prepared")
            elif pending["product_id"] != want_id:
                errs.append(
                    f"prepared product {pending['product_id']}, expected {want_id}"
                )
        elif case["kind"] == "no_order":
            if pending:
                errs.append(
                    f"an order was prepared for product {pending['product_id']}; it should have asked which one"
                )
    except Exception as e:
        errs.append(f"crashed: {type(e).__name__}: {str(e)[:200]}")

    if order_count() != before:
        errs.append("orders table changed: the agent wrote an order on its own")
    joined = " ".join(replies).lower()
    for phrase in FORBIDDEN:
        if phrase in joined:
            errs.append(f"forbidden phrase in reply: '{phrase}'")

    return {
        "n": case["n"],
        "prompts": case["prompts"],
        "passed": not errs,
        "errors": errs,
        "reply": replies[-1] if replies else "",
    }


def main():
    only = {int(a) for a in sys.argv[1:]}
    cases = [c for c in CASES if not only or c["n"] in only]
    results = []
    for k, case in enumerate(cases):
        print(f"\n[{case['n']}] {' -> '.join(case['prompts'])}")
        if case["kind"] == "search":
            want = expected(**case["expect"])
            print(f"    correct answer (SQL): IDs {[r[0] for r in want]}")
        res = run_case(case)
        results.append(res)
        print(f"    {'PASS' if res['passed'] else 'FAIL'}")
        for e in res["errors"]:
            print(f"      - {e}")
        if k < len(cases) - 1:
            time.sleep(PAUSE_SECONDS)

    print("\n" + "=" * 60)
    for r in results:
        print(f"  {'PASS' if r['passed'] else 'FAIL'}  [{r['n']}] {r['prompts'][-1]}")
    passed = sum(r["passed"] for r in results)
    print(f"\nscore: {passed}/{len(results)}")
    with open(os.path.join(HERE, "eval_results.json"), "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("saved eval_results.json")


if __name__ == "__main__":
    main()
