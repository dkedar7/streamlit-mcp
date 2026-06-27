"""Fixture app that defines a @mcp_tool semantic tool in the app file (the intuitive place)."""

import streamlit as st

from streamlit_mcp import mcp_tool


@mcp_tool
def reset_all():
    """Reset everything to defaults."""
    return {"ok": True}


st.title("Semantic App")
st.text_input("Name")
