import streamlit as st

st.header("Checkout")

PRICES = {"Widget": 12, "Gadget": 20, "Gizmo": 8}

item = st.selectbox("Item", list(PRICES), key="item")
qty = st.number_input("Quantity", min_value=1, max_value=100, value=1, key="qty")
disc = st.slider("Discount %", min_value=0, max_value=50, value=0, key="discount")

subtotal = PRICES[item] * qty
total = round(subtotal * (1 - disc / 100), 2)
st.markdown(f"Subtotal: ${subtotal}. Total after discount: ${total}.")
