"""Live human-in-the-loop example: an agent edits this over MCP and a browser updates live.

Run it two ways at once, pointed at the same file:

    streamlit run examples/live_app.py            # the human's browser (port 8501)
    streamlit-mcp serve examples/live_app.py      # the agent, over MCP

State lives in a shared JSON store next to this file (the single source of truth). streamlit-mcp
drives this same app headlessly via AppTest; its writes bump a version. A `st.fragment(run_every=...)`
polls the version and reruns the page when it changes, so edits made by the agent appear in the
browser live — no manual refresh, and no browser automation.

For a single node a JSON file is fine; for multiple servers use a shared store (e.g. Redis).
"""
import json
import pathlib

import streamlit as st

STORE = pathlib.Path(__file__).parent / "live_state.json"
PLANS = ["Free", "Pro", "Team"]
FIELDS = {"name": "Ada", "plan": "Free", "experience": 5, "subscribe": True, "created": False}


def load():
    try:
        d = json.loads(STORE.read_text())
        return int(d.get("v", 0)), {**FIELDS, **d.get("fields", {})}
    except Exception:
        return 0, dict(FIELDS)


def save(fields, v):
    STORE.write_text(json.dumps({"v": v, "fields": fields}))


store_v, store_fields = load()

# Adopt an external change (the agent, or another browser) BEFORE any widget is created — that
# is the only point at which Streamlit lets you overwrite a widget's session_state value.
if st.session_state.get("_v") != store_v:
    for k in FIELDS:
        st.session_state[k] = store_fields[k]
    st.session_state["_v"] = store_v

st.set_page_config(page_title="streamlit-mcp · live", page_icon="🤖")
st.title("🤖 Agent Signup — live")
st.caption("An agent edits this over MCP. Your browser updates live — no refresh, no browser automation.")

name = st.text_input("Name", key="name")
plan = st.selectbox("Plan", PLANS, key="plan")
experience = st.slider("Years of experience", 0, 30, key="experience")
subscribe = st.checkbox("Email me product updates", key="subscribe")
clicked = st.button("Create account")

cur = {"name": name, "plan": plan, "experience": experience,
       "subscribe": subscribe, "created": bool(clicked) or store_fields["created"]}

# A local edit (a widget the human — or the agent's AppTest run — changed) publishes a new version.
if cur != store_fields:
    store_v += 1
    save(cur, store_v)
    st.session_state["_v"] = store_v
    store_fields = cur

if store_fields["created"]:
    st.subheader(f"✅ Welcome, {store_fields['name']}!")
    st.markdown(f"Your **{store_fields['plan']}** account is ready "
                f"({store_fields['experience']} yrs experience).")


@st.fragment(run_every="1s")
def _live():
    """Poll the store; if another process changed it, rerun the whole app to adopt it."""
    v, _ = load()
    if v != st.session_state.get("_v"):
        st.rerun(scope="app")


_live()
