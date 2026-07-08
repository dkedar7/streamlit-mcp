import streamlit as st

st.title("Auction")
st.markdown("This item is hot — bidding closes in 2 minutes.")

st.number_input("Your bid", min_value=0, max_value=250, value=0, step=5, key="bid")
