import streamlit as st

st.header("Budget planner")
st.markdown("Total budget: $1200.")

eng = st.number_input("Engineering", min_value=0, max_value=1200, value=0, step=10, key="engineering")
mkt = st.number_input("Marketing", min_value=0, max_value=1200, value=0, step=10, key="marketing")
dsn = st.number_input("Design", min_value=0, max_value=1200, value=0, step=10, key="design")

st.markdown(f"Allocated: ${eng + mkt + dsn} of $1200.")
