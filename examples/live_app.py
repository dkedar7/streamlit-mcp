"""Live human-in-the-loop example — an agent edits this over MCP and a browser updates live.

Run both at once, pointed at the same file:

    streamlit run examples/live_app.py            # the human's browser
    streamlit-mcp serve examples/live_app.py      # the agent, over MCP

`live(...)` syncs the widget state through a shared store keyed by name, so the agent's edits
appear live — no manual refresh, no browser automation.
Docs: https://dkedar7.github.io/streamlit-mcp/live/
"""
import streamlit as st

from streamlit_mcp.live import live

st.set_page_config(page_title="streamlit-mcp · live", page_icon="🤖")

with live("signup", defaults={"name": "Ada", "plan": "Free", "experience": 5,
                              "subscribe": True, "created": False}):
    st.title("🤖 Agent Signup — live")
    st.caption("An agent edits this over MCP. Your browser updates live — no refresh, no browser automation.")

    st.text_input("Name", key="name")
    st.selectbox("Plan", ["Free", "Pro", "Team"], key="plan")
    st.slider("Years of experience", 0, 30, key="experience")
    st.checkbox("Email me product updates", key="subscribe")
    if st.button("Create account"):
        st.session_state["created"] = True

    if st.session_state["created"]:
        st.subheader(f"✅ Welcome, {st.session_state['name']}!")
        st.markdown(f"Your **{st.session_state['plan']}** account is ready "
                    f"({st.session_state['experience']} yrs experience).")
