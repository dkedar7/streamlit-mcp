"""Dynamic / agent-driven layout — the agent adds components and rearranges the layout, live.

The app's *structure* is a function of state the agent controls: `rows` (how many fields) and
`cols` (how many columns). Streamlit reruns the whole script per interaction, so when the agent
changes those (over MCP), the rerun renders a different layout. `live(...)` syncs that controlling
state, so a human watching `streamlit run` sees the form grow and re-flow.

Run both, pointed at the same file:

    streamlit run examples/dynamic_app.py            # the human's browser
    streamlit-mcp serve examples/dynamic_app.py      # the agent, over MCP

    # the agent builds the form:
    streamlit-mcp call examples/dynamic_app.py --set "Rows=4" --set "Columns=2" --read
"""
import streamlit as st

from streamlit_mcp.live import live

st.set_page_config(page_title="streamlit-mcp · dynamic", page_icon="🧱")

# Sync only the *controlling* state (the structure), not each generated field — a static,
# declared key set is all live() needs to make the layout follow.
with live("dynamic", defaults={"rows": 1, "cols": 1}):
    st.title("🧱 Agent-built form — live")
    st.caption("The agent adds fields and rearranges the layout over MCP; your browser follows.")

    rows = int(st.number_input("Rows", min_value=1, max_value=6, key="rows"))
    cols = int(st.number_input("Columns", min_value=1, max_value=3, key="cols"))

    columns = st.columns(cols)
    for i in range(rows):
        with columns[i % cols]:
            st.text_input(f"Field {i + 1}", key=f"field_{i}")

    st.markdown(f"**{rows}** field(s) across **{cols}** column(s)")
