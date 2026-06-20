"""Fixture app exercising all ten v1-supported widget kinds (plus state + output)."""

import datetime

import streamlit as st

if "saves" not in st.session_state:
    st.session_state.saves = 0

name = st.text_input("Name", value="world", key="name")
age = st.number_input("Age", min_value=0, max_value=120, value=30, key="age")
bio = st.text_area("Bio", value="", key="bio")
level = st.slider("Level", min_value=1, max_value=10, value=5, key="level")
color = st.selectbox("Color", ["red", "green", "blue"], key="color")
tags = st.multiselect("Tags", ["a", "b", "c"], key="tags")
agree = st.checkbox("Agree", value=False, key="agree")
plan = st.radio("Plan", ["free", "pro"], key="plan")
when = st.date_input("When", value=datetime.date(2026, 1, 1), key="when")

if st.button("Save", key="save"):
    st.session_state.saves += 1

st.markdown(f"Hello, {name}!")
st.markdown(f"saves = {st.session_state.saves}")
