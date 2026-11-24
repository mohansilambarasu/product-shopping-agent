# import base64
# import json
# import os
# import sqlite3
# from typing import Optional

# from dotenv import load_dotenv
# from langchain.agents import create_agent
# from langchain.tools import tool
# from langchain_core.messages import HumanMessage
# from langchain_groq import ChatGroq

# from reviews_api import get_product_rating

# load_dotenv()

# DB_PATH = os.path.join(os.path.dirname(__file__), "store.db")

# llm = ChatGroq(
#     model="openai/gpt-oss-120b", temperature=0
# )  # orchestrator: picks tools, writes answers
# vision_llm = ChatGroq(
#     model="qwen/qwen3.8-27b", temperature=0
# )  # reads the product image

# # ---------------------------------------------------------------------------
# # Tools
# # ---------------------------------------------------------------------------


# @tool
# def search_products(
#     query: str, max_price: Optional[float] = None, is_organic: Optional[bool] = None
# ) -> str:
#     """
#     Search the product database by keyword (matched against name, description, and category).
#     Optionally filter by maximum price and/or organic status.
#     Returns a JSON array of matching products, each with: id, name, category, price,
#     description, is_organic.
#     """
#     conn = sqlite3.connect(DB_PATH)
#     cursor = conn.cursor()

#     sql = "SELECT id, name, category, price, description, is_organic FROM products WHERE 1=1"
#     params: list = []

#     if query:
#         sql += " AND (name LIKE ? OR description LIKE ? OR category LIKE ?)"
#         like = f"%{query}%"
#         params.extend([like, like, like])

#     if max_price is not None:
#         sql += " AND price <= ?"
#         params.append(max_price)

#     if is_organic is not None:
#         sql += " AND is_organic = ?"
#         params.append(1 if is_organic else 0)

#     cursor.execute(sql, params)
#     rows = cursor.fetchall()
#     conn.close()

#     products = [
#         {
#             "id": row[0],
#             "name": row[1],
#             "category": row[2],
#             "price": row[3],
#             "description": row[4],
#             "is_organic": bool(row[5]),
#         }
#         for row in rows
#     ]
#     return json.dumps(products)


# @tool
# def get_rating(product_id: int) -> str:
#     """
#     Get the average customer rating and total review count for a product by its ID.
#     Returns a JSON object with: product_id, average_rating, review_count.
#     """
#     result = get_product_rating(product_id)
#     return json.dumps(result)


# @tool
# def checkout(product_id: int) -> str:
#     """
#     Prepare an order for the given product ID. This does NOT place the order:
#     the user must press Approve in the app. Returns the product awaiting approval.
#     """
#     conn = sqlite3.connect(DB_PATH)
#     cursor = conn.cursor()
#     cursor.execute("SELECT name, price FROM products WHERE id = ?", (product_id,))
#     row = cursor.fetchone()
#     conn.close()

#     if not row:
#         return f"Error: product with ID {product_id} not found."

#     name, price = row
#     return json.dumps(
#         {
#             "status": "pending_approval",
#             "product_id": product_id,
#             "name": name,
#             "price": price,
#         }
#     )


# def place_order(product_id: int) -> dict:
#     """Write the order. Called only by the app's Approve button. Not a tool, so the model can't call it."""
#     conn = sqlite3.connect(DB_PATH)
#     cursor = conn.cursor()
#     cursor.execute("SELECT name, price FROM products WHERE id = ?", (product_id,))
#     row = cursor.fetchone()
#     if not row:
#         conn.close()
#         raise ValueError(f"Product {product_id} not found")

#     name, price = row  # price re-read from the DB at the moment of approval
#     cursor.execute(
#         "INSERT INTO orders (product_id, product_name, price) VALUES (?, ?, ?)",
#         (product_id, name, price),
#     )
#     order_id = cursor.lastrowid
#     conn.commit()
#     conn.close()
#     return {"order_id": order_id, "name": name, "price": price}


# @tool
# def describe_product_image(image_path: str) -> str:
#     """
#     Analyze a product image and return its key attributes as a JSON object.
#     Use this when the user uploads a photo of a product they are interested in.
#     The returned attributes can be used directly with search_products.
#     """
#     with open(image_path, "rb") as f:
#         image_data = base64.b64encode(f.read()).decode()

#     ext = os.path.splitext(image_path)[1].lower().lstrip(".")
#     mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"

#     message = HumanMessage(
#         content=[
#             {
#                 "type": "image_url",
#                 "image_url": {"url": f"data:{mime};base64,{image_data}"},
#             },
#             {
#                 "type": "text",
#                 "text": (
#                     "Look at this product image and extract its key attributes. "
#                     "Return ONLY a JSON object with these fields:\n"
#                     "- product_type: what kind of product it is (e.g. honey, olive oil, almonds)\n"
#                     "- search_query: a short keyword to search for it (e.g. 'honey', 'olive oil')\n"
#                     "- is_organic: true if the label says organic, false if not, null if unclear\n"
#                     "- description: one sentence describing the product"
#                 ),
#             },
#         ]
#     )

#     response = vision_llm.invoke([message])
#     return response.content


# # ---------------------------------------------------------------------------
# # Agent
# # ---------------------------------------------------------------------------

# agent = create_agent(
#     tools=[search_products, get_rating, checkout, describe_product_image],
#     model=llm,
#     system_prompt=(
#         "You are a helpful shopping assistant. Follow these rules strictly.\n\n"
#         "IMAGE SEARCH — when the user provides an image path:\n"
#         "1. Call describe_product_image with the path to identify the product.\n"
#         "2. Use the returned search_query and is_organic to call search_products.\n"
#         "3. Continue with the BROWSING flow from step 2 onwards.\n\n"
#         "BROWSING — when the user describes what they want to buy:\n"
#         "1. Call search_products to find matching items (apply any price/organic filters given).\n"
#         "2. For each candidate, call get_rating to retrieve its average rating.\n"
#         "3. Filter by the user's minimum rating if specified.\n"
#         "4. Present qualifying products as a numbered list. For each item use this exact format "
#         "   (plain text, no backticks, no code blocks, no bold, no italic):\n\n"
#         "   #<number>. <name> (ID:<product_id>) — $<price> ★<rating> — <organic or non-organic>\n\n"
#         "   Add a blank line between each product entry for readability. "
#         "   Always include (ID:X) so you can reference it later.\n"
#         "5. If only one product qualifies, still show it in the list and ask: "
#         "   'Would you like to order it? Just say yes or give me the number.'\n"
#         "6. Do NOT call checkout at this stage.\n\n"
#         "ORDERING — when the user says they want to buy a product (e.g. 'yes', 'sure', "
#         "'go ahead', 'order number 2', 'the first one', 'get me #3'):\n"
#         "1. Look at your previous product list to find the (ID:X) for the chosen product "
#         "   (if only one was listed and the user says 'yes', use that product's ID).\n"
#         "2. If it is unclear which product the user means, ask which one BEFORE calling "
#         "   checkout. Do not guess.\n"
#         "3. Call checkout with that product_id (the number from (ID:X)). checkout only "
#         "   PREPARES the order; it does not place it.\n"
#         "4. Then tell the user, in one short plain-text sentence, which product and price "
#         "   are ready, and ask them to press the Approve button below the chat.\n"
#         "5. Never say an order is placed, confirmed or shipped, and never mention delivery "
#         "   times or anything about shipping.\n\n"
#         "Call checkout only when the user clearly picks a product. "
#         "Never guess a product_id — always take it from the (ID:X) in your own previous message."
#     ),
# )


# if __name__ == "__main__":
#     result = agent.invoke(
#         {
#             "messages": [
#                 {
#                     "role": "user",
#                     "content": (
#                         "I want to buy organic honey with 4.5+ rating and less than $20 price."
#                     ),
#                 }
#             ]
#         }
#     )
#     print(result["messages"][-1].content)

import base64
import json
import os
import sqlite3
from typing import Optional

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq

from reviews_api import get_product_rating

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), "store.db")

llm = ChatGroq(
    model="openai/gpt-oss-120b", temperature=0
)  # orchestrator: picks tools, writes answers
vision_llm = ChatGroq(
    model="qwen/qwen3.8-27b", temperature=0
)  # reads the product image

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool
def search_products(
    query: str,
    max_price: Optional[float] = None,
    is_organic: Optional[bool] = None,
    min_rating: Optional[float] = None,
) -> str:
    """
    Search the product database by keyword (matched against name, description, and category).
    Optionally filter by maximum price, organic status, and minimum average rating.
    Returns a JSON array of matching products, each with: id, name, category, price,
    is_organic, average_rating (null if the product has no reviews), review_count.
    Ratings are already included, so no separate rating lookup is needed.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    sql = (
        "SELECT p.id, p.name, p.category, p.price, p.is_organic, "
        "ROUND(AVG(r.rating), 2), COUNT(r.id) "
        "FROM products p LEFT JOIN reviews r ON r.product_id = p.id "
        "WHERE 1=1"
    )
    params: list = []

    if query:
        sql += " AND (p.name LIKE ? OR p.description LIKE ? OR p.category LIKE ?)"
        like = f"%{query}%"
        params.extend([like, like, like])

    if max_price is not None:
        sql += " AND p.price <= ?"
        params.append(max_price)

    if is_organic is not None:
        sql += " AND p.is_organic = ?"
        params.append(1 if is_organic else 0)

    sql += " GROUP BY p.id"

    if min_rating is not None:
        sql += " HAVING AVG(r.rating) >= ?"
        params.append(min_rating)

    sql += " ORDER BY p.id"

    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()

    products = [
        {
            "id": row[0],
            "name": row[1],
            "category": row[2],
            "price": row[3],
            "is_organic": bool(row[4]),
            "average_rating": row[5],
            "review_count": row[6],
        }
        for row in rows
    ]
    return json.dumps(products)


@tool
def get_rating(product_id: int) -> str:
    """
    Get the average customer rating and total review count for ONE product by its ID.
    Only use this when the user asks about the rating of a single specific product;
    search_products already returns ratings for its results.
    Returns a JSON object with: product_id, average_rating, review_count.
    """
    result = get_product_rating(product_id)
    return json.dumps(result)


@tool
def checkout(product_id: int) -> str:
    """
    Prepare an order for the given product ID. This does NOT place the order:
    the user must press Approve in the app. Returns the product awaiting approval.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, price FROM products WHERE id = ?", (product_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return f"Error: product with ID {product_id} not found."

    name, price = row
    return json.dumps(
        {
            "status": "pending_approval",
            "product_id": product_id,
            "name": name,
            "price": price,
        }
    )


def place_order(product_id: int) -> dict:
    """Write the order. Called only by the app's Approve button. Not a tool, so the model can't call it."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, price FROM products WHERE id = ?", (product_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Product {product_id} not found")

    name, price = row  # price re-read from the DB at the moment of approval
    cursor.execute(
        "INSERT INTO orders (product_id, product_name, price) VALUES (?, ?, ?)",
        (product_id, name, price),
    )
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"order_id": order_id, "name": name, "price": price}


@tool
def describe_product_image(image_path: str) -> str:
    """
    Analyze a product image and return its key attributes as a JSON object.
    Use this when the user uploads a photo of a product they are interested in.
    The returned attributes can be used directly with search_products.
    """
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode()

    ext = os.path.splitext(image_path)[1].lower().lstrip(".")
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"

    message = HumanMessage(
        content=[
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{image_data}"},
            },
            {
                "type": "text",
                "text": (
                    "Look at this product image and extract its key attributes. "
                    "Return ONLY a JSON object with these fields:\n"
                    "- product_type: what kind of product it is (e.g. honey, olive oil, almonds)\n"
                    "- search_query: a short keyword to search for it (e.g. 'honey', 'olive oil')\n"
                    "- is_organic: true if the label says organic, false if not, null if unclear\n"
                    "- description: one sentence describing the product"
                ),
            },
        ]
    )

    response = vision_llm.invoke([message])
    return response.content


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

agent = create_agent(
    tools=[search_products, get_rating, checkout, describe_product_image],
    model=llm,
    system_prompt=(
        "You are a helpful shopping assistant. Follow these rules strictly.\n\n"
        "IMAGE SEARCH — when the user provides an image path:\n"
        "1. Call describe_product_image with the path to identify the product.\n"
        "2. Use the returned search_query and is_organic to call search_products.\n"
        "3. Continue with the BROWSING flow from step 3 onwards.\n\n"
        "BROWSING — when the user describes what they want to buy:\n"
        "1. Call search_products to find matching items. Apply any price, organic and "
        "   minimum-rating filters the user gave (use the min_rating argument for a "
        "   minimum rating).\n"
        "2. Every search result already includes average_rating and review_count. "
        "   Do NOT call get_rating for products from a search. Use get_rating only if "
        "   the user asks about the rating of one specific product.\n"
        "3. If the user asks for a single best item (the cheapest, the best rated, etc.), "
        "   pick that one product from the results and present only it. Otherwise present "
        "   all matching products.\n"
        "4. Present products as a numbered list. For each item use this exact format "
        "   (plain text, no backticks, no code blocks, no bold, no italic):\n\n"
        "   #<number>. <name> (ID:<product_id>) — $<price> ★<average_rating> — <organic or non-organic>\n\n"
        "   If average_rating is null, write 'no ratings' instead of the number. "
        "   Add a blank line between each product entry for readability. "
        "   Always include (ID:X) so you can reference it later.\n"
        "5. If only one product qualifies, still show it in the list and ask: "
        "   'Would you like to order it? Just say yes or give me the number.'\n"
        "6. If nothing matches, say so plainly and do not list any products.\n"
        "7. Do NOT call checkout at this stage.\n\n"
        "ORDERING — when the user says they want to buy a product (e.g. 'yes', 'sure', "
        "'go ahead', 'order number 2', 'the first one', 'get me #3'):\n"
        "1. Look at your previous product list to find the (ID:X) for the chosen product "
        "   (if only one was listed and the user says 'yes', use that product's ID).\n"
        "2. If it is unclear which product the user means, ask which one BEFORE calling "
        "   checkout. Do not guess.\n"
        "3. Call checkout with that product_id (the number from (ID:X)). checkout only "
        "   PREPARES the order; it does not place it.\n"
        "4. Then tell the user, in one short plain-text sentence, which product and price "
        "   are ready, and ask them to press the Approve button below the chat.\n"
        "5. Never say an order is placed, confirmed or shipped, and never mention delivery "
        "   times or anything about shipping.\n\n"
        "Call checkout only when the user clearly picks a product. "
        "Never guess a product_id — always take it from the (ID:X) in your own previous message."
    ),
)


if __name__ == "__main__":
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "I want to buy organic honey with 4.5+ rating and less than $20 price."
                    ),
                }
            ]
        }
    )
    print(result["messages"][-1].content)
