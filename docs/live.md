# Live / human-in-the-loop

streamlit-mcp drives apps **headlessly** — the agent gets the rendered element tree, and a human
watching `streamlit run` in a browser normally doesn't see those edits, because **Streamlit
sessions are isolated** (each connection has its own `session_state`). So "the human watches the
agent's edits appear live" isn't a connection trick — it needs **shared state the app re-reads**.

Here's a small pattern that does exactly that. An agent edits over MCP from one process; a browser
updates live in another — no manual refresh, and no browser automation:

![A browser updating live as an agent edits the app over MCP](assets/live-demo.gif)

## How it works

1. **A shared store is the single source of truth.** The app keeps its state in a JSON file (use
   Redis or a DB for multi-node) and renders from it. Each write bumps a **version**.
2. **The agent's writes land in the store.** `streamlit-mcp serve` runs the same app via `AppTest`;
   when the agent calls `set_widget`/`click`, the script reruns and persists to the store —
   the *existing* tools, no new API.
3. **The browser polls and reruns.** `st.fragment(run_every="1s")` re-reads the version; when it
   changed (because the agent wrote), it calls `st.rerun(scope="app")`. On rerun, the app re-seeds
   its widgets from the store **at the top of the script** (the one place Streamlit lets you
   overwrite a widget's `session_state`), so the new values show up.

The version field is what prevents an echo loop: the app only re-seeds when the store changed
externally, and only writes when a widget actually changed locally.

## Run it

Point both at the same file:

```bash
# 1) the human's browser
streamlit run examples/live_app.py

# 2) the agent, over MCP (or from the CLI, same engine)
streamlit-mcp serve examples/live_app.py
# ...or drive it directly to see the browser update:
streamlit-mcp call examples/live_app.py --set "Name=Grace" --set "Plan=Pro" \
    --set "Years of experience=12" --click "Create account" --read
```

The browser running step 1 updates within a second of the agent's edit in step 2.

## The app

The full example is [`examples/live_app.py`](https://github.com/dkedar7/streamlit-mcp/blob/main/examples/live_app.py).
The load-bearing parts:

```python
store_v, store_fields = load()

# Adopt an external change (agent / another browser) BEFORE any widget is created.
if st.session_state.get("_v") != store_v:
    for k in FIELDS:
        st.session_state[k] = store_fields[k]
    st.session_state["_v"] = store_v

name = st.text_input("Name", key="name")
# ...other widgets...

# A local edit (human or the agent's AppTest run) publishes a new version.
cur = {"name": name, ...}
if cur != store_fields:
    save(cur, store_v + 1)
    st.session_state["_v"] = store_v + 1

@st.fragment(run_every="1s")
def _live():
    v, _ = load()
    if v != st.session_state.get("_v"):
        st.rerun(scope="app")   # adopt the agent's edit
_live()
```

## Caveats

- It's a **pattern, not a built-in** — the app opts in by reading/writing the shared store.
- A **file store** is fine for one machine; use a shared store (Redis/DB) across servers.
- It's last-writer-wins on a coarse version; fine for human-in-the-loop, not a concurrent CRDT.
