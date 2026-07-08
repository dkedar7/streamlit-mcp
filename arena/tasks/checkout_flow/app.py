import streamlit as st

st.title("Place your order")

st.text_input("Full name", key="name")
st.text_input("Shipping address", key="address")
st.selectbox("Shipping speed", ["Standard", "Express", "Overnight"], key="speed")
st.checkbox("I agree to the terms", key="agree")

c1, c2 = st.columns(2)
if c1.button("Cancel"):
    st.session_state["order_cancelled"] = True
if c2.button("Place order"):
    if st.session_state.get("agree"):
        st.session_state["order_placed"] = True
    else:
        st.warning("You must agree to the terms before placing the order.")

if st.session_state.get("order_placed"):
    st.subheader("Order confirmed!")
