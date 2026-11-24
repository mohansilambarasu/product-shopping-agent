import json
import os
import tempfile

import streamlit as st

from shopping_agent import agent, place_order

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="AI Shopping Assistant", page_icon="🛒", layout="wide")

st.title("🛒 AI Shopping Assistant")
st.caption(
    "Tell me what you want — I'll search, rate, and order the best match for you."
)

# ---------------------------------------------------------------------------
# Chat state (initialised first: the sidebar below writes to it)
# ---------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_order" not in st.session_state:
    st.session_state.pending_order = None


def find_pending_order(result):
    """Return this turn's pending order from the checkout tool result, or None."""
    for m in reversed(result["messages"]):
        if m.type == "human":
            break  # reached the start of this turn
        if m.type == "tool":
            try:
                data = json.loads(m.content)
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict) and data.get("status") == "pending_approval":
                return data
    return None


# ---------------------------------------------------------------------------
# Sidebar — shop by image
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Shop by Image")
    st.caption("Upload a photo of a product and I'll find similar items in our store.")

    uploaded_file = st.file_uploader(
        "Upload product image", type=["jpg", "jpeg", "png", "webp"]
    )

    if uploaded_file:
        st.image(uploaded_file, width="stretch")

    if uploaded_file and st.button("Find similar products", width="stretch"):
        suffix = os.path.splitext(uploaded_file.name)[1] or ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            image_path = tmp.name

        prompt = f"I uploaded a product image. Please analyze it and find similar products in the store. Image path: {image_path}"
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.pending_image = uploaded_file.name
        st.rerun()

# Render history — show a friendlier label for image-search messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "user" and msg["content"].startswith(
            "I uploaded a product image"
        ):
            filename = msg["content"].split("Image path:")[-1].strip()
            st.markdown(f"Searching by image: **{os.path.basename(filename)}**")
        else:
            st.markdown(msg["content"].replace("$", r"\$"))

# ---------------------------------------------------------------------------
# Run agent if there's an unprocessed message (image upload triggers this)
# ---------------------------------------------------------------------------
if (
    st.session_state.messages
    and st.session_state.messages[-1]["role"] == "user"
    and "pending_image" in st.session_state
):
    with st.chat_message("assistant"):
        with st.spinner("Analyzing image and searching…"):
            result = agent.invoke({"messages": st.session_state.messages})
            response = result["messages"][-1].content.replace("`", "")
            st.session_state.pending_order = find_pending_order(result)
        st.markdown(response.replace("$", r"\$"))

    st.session_state.messages.append({"role": "assistant", "content": response})
    del st.session_state.pending_image
    st.rerun()

# ---------------------------------------------------------------------------
# Text input
# ---------------------------------------------------------------------------
if prompt := st.chat_input("e.g. I want organic honey under $15 with 4+ rating"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            result = agent.invoke({"messages": st.session_state.messages})
            response = result["messages"][-1].content.replace("`", "")
            st.session_state.pending_order = find_pending_order(result)
        st.markdown(response.replace("$", r"\$"))

    st.session_state.messages.append({"role": "assistant", "content": response})
    st.rerun()

# ---------------------------------------------------------------------------
# Order approval: the only code path that writes an order
# ---------------------------------------------------------------------------
pending = st.session_state.get("pending_order")
if pending:
    with st.container(border=True):
        st.markdown(f"**Confirm order:** {pending['name']} — \\${pending['price']:.2f}")
        col1, col2 = st.columns(2)
        if col1.button("Approve", type="primary"):
            order = place_order(pending["product_id"])
            st.session_state.pending_order = None
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": f"Order #{order['order_id']} placed: {order['name']}, ${order['price']:.2f}.",
                }
            )
            st.rerun()
        if col2.button("Cancel"):
            st.session_state.pending_order = None
            st.session_state.messages.append(
                {"role": "assistant", "content": "Order cancelled."}
            )
            st.rerun()
