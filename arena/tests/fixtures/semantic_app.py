import streamlit as st

from streamlit_mcp import mcp_tool

st.title("Counter")
st.number_input("Count", min_value=0, max_value=100, value=0, key="count")


@mcp_tool
def reset_count() -> str:
    """Reset the counter to zero."""
    return "reset"
