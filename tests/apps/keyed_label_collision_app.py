import streamlit as st

st.text_input("Search", key="q")

if st.button("Search"):
    st.session_state["search_count"] = st.session_state.get("search_count", 0) + 1
