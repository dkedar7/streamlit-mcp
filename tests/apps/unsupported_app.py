"""Fixture app with a supported widget plus an unsupported element (file_uploader)."""

import streamlit as st

name = st.text_input("Name", value="world", key="name")
st.file_uploader("Upload a file")  # unsupported in v1 — must be reported, never dropped

st.markdown(f"Hello, {name}!")
