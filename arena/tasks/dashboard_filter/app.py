import streamlit as st

st.header("Sales dashboard")

region = st.selectbox("Region", ["North", "South", "East", "West"], key="region")
top_n = st.slider("Top N", 1, 10, 3, key="top_n")

st.markdown(f"Showing the top {top_n} products for {region}.")
