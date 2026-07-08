# StreamlitArena

**A reproducible benchmark for whether an AI agent can *operate* a Streamlit app** — filling forms,
navigating branching wizards, configuring dashboards — driving purely through
[streamlit-mcp](../README.md)'s semantic interface. No browser. No screenshots. No vision model.

Think WebArena / AppWorld, but for Streamlit apps reached over MCP: the agent sees the widget tree
and rendered output as structured data, acts with `set_widget` / `click`, and is scored
automatically on whether it reached the goal.

It also serves as streamlit-mcp's heaviest **dogfooding** vehicle. Every episode drives a real app
through the exact tools an agent uses over MCP, so multi-step flows, dynamic layouts, every widget
kind, and the atomicity / ordering / identifier guarantees all get stress-tested — and any
*unexpected* exception is flagged as a **crash** (a library bug), so running the suite is a
structured regression test of streamlit-mcp itself.

## Quickstart

```bash
uv run python -m arena list                     # list tasks
uv run python -m arena run --agent scripted     # run the oracle (no API) — proves solvability
uv run python -m arena run --agent random --seed 1   # fuzz baseline — stresses the library
uv run python -m arena run --agent scripted --json   # also write arena/results/scripted.json
```

Example (oracle):

```
# StreamlitArena — scripted agent

**3/3 solved** (100%) · avg 3.33 actions · **0 streamlit-mcp crash(es)**

| task             | tier | solved | actions | crash |
|------------------|------|:------:|--------:|:-----:|
| dashboard_filter | easy |   ✅   |       2 |       |
| signup_flow      | easy |   ✅   |       5 |       |
| wizard_branching | hard |   ✅   |       3 |       |
```

## How it works

```
task (app.py + goal + checker + oracle)
        │
        ▼
   ArenaEnv ──► streamlit_mcp.Engine ──► AppTest (headless Streamlit)
   (6 MCP tools: list_widgets / get_layout / read_output / get_state / set_widget / click)
        │  records a trace, enforces a step budget, flags unexpected exceptions as crashes
        ▼
   agent.solve(env, goal)          # scripted | random | llm
        │
        ▼
   checker(final_state, output) ──► EpisodeResult ──► report (markdown + json)
```

- **`env.py`** — `ArenaEnv` wraps the streamlit-mcp `Engine` (the same code the MCP server
  dispatches to — the parity guarantee makes in-process driving representative). It exposes exactly
  the six core tools, counts only *actions* against the budget, and separates an **expected tool
  error** (bad value / not found / guardrail block — a signal the agent adapts to) from an
  **unexpected exception** (a streamlit-mcp bug → `crash`).
- **`task.py` / `tasks/`** — each task is a folder with `app.py` (a self-contained Streamlit app)
  and `task.py` (goal, a pure `check(state, output)` checker, difficulty tier, and an oracle
  `solution` the ScriptedAgent replays).
- **`agents.py`** — `ScriptedAgent` (oracle replay, deterministic, CI-safe), `RandomAgent` (seeded
  fuzz baseline), `LLMAgent` (Milestone 2).
- **`runner.py` / `report.py` / `cli.py`** — episode loop, scoring, reports, `python -m arena`.

## Adding a task

```
arena/tasks/my_task/
  app.py     # a normal Streamlit app
  task.py    # exports TASK = Task(id, app, goal, check, solution, tier, tags)
```

`check(state, output)` is a pure function of the finished episode's `get_state()` dict and
`read_output()` dict — keep it deterministic. `solution` is the oracle: a list of
`("set", identifier, value)` / `("click", identifier)` actions that solves it (this both documents
the intended path and lets the ScriptedAgent prove the task is solvable).

## Interpreting results

- **solve rate** — did the agent reach the goal? (The oracle should be 100%; a random agent near 0%
  confirms the tasks actually discriminate skill.)
- **actions** — efficiency (fewer is better).
- **crashes** — **should always be 0.** A non-zero count means a streamlit-mcp tool raised an
  unexpected exception while being driven — a library bug the benchmark just found. `python -m arena
  run` exits non-zero if any episode crashed, so it works as a dogfood gate in CI.

## Roadmap

- **M1 (done)** — env, task format, scripted + random agents, runner, report, 3 seed tasks.
- **M2** — `LLMAgent`: an Anthropic tool-use loop over the six tools; run real models and build a
  leaderboard.
- **M3** — drive via a real `fastmcp` stdio client (full-stack fidelity, not just the Engine);
  guardrail tasks (a `--read-only` task that must be refused), semantic-tool tasks.
- **M4** — a wider task corpus across tiers; a Streamlit leaderboard viewer (which streamlit-mcp can
  itself drive — meta-dogfooding).
