import streamlit as st

st.title("Rate limiter")
st.markdown("Configure the request throttle for this endpoint.")

st.number_input("Requests per second", min_value=1, max_value=100, value=1, key="rps")
