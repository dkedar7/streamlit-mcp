"""Fixture app that raises an uncaught exception (for the stdout-cleanliness test, #27)."""

import streamlit as st

st.title("Boom")
raise RuntimeError("kaboom")
