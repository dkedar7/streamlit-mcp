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

# real model eval — Anthropic directly (needs ANTHROPIC_API_KEY + the anthropic SDK):
uv run --with anthropic python -m arena run --agent llm --model claude-sonnet-4-6 --json

# ...or ANY model via OpenRouter (needs OPENROUTER_API_KEY + the openai SDK) — Claude, GPT,
# Gemini, DeepSeek, Llama, … behind one API:
uv run --with openai python -m arena run --agent llm --provider openrouter \
    --model "openai/gpt-4o-mini" --json
uv run --with openai python -m arena run --agent llm --provider openrouter \
    --model "anthropic/claude-opus-4" --json

uv run python -m arena leaderboard              # compare every run in arena/results/
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
- **`agents.py` / `llm.py`** — `ScriptedAgent` (oracle replay, deterministic, CI-safe),
  `RandomAgent` (seeded fuzz baseline), and `LLMAgent` — an LLM tool-use loop that inspects with
  `list_widgets`/`read_output`, acts with `set_widget`/`click`, and calls `finish` when done. The
  provider-specific bits live in a small `Backend`: `AnthropicBackend` (Messages API) and
  `OpenAIBackend` (any OpenAI-compatible endpoint; used for **OpenRouter**, which proxies Claude /
  GPT / Gemini / DeepSeek / Llama behind one API). The client is injectable, so the loop is
  unit-tested with a fake client (no network). `arena leaderboard` compares runs across models.
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

## First results (2026-07-08, via OpenRouter)

Seven models across five providers, each driving all three seed tasks:

| agent | solved | solve rate | crashes | avg actions |
|---|---:|---:|---:|---:|
| anthropic/claude-opus-4 | 3/3 | 100% | 0 | 3.33 |
| anthropic/claude-haiku-4.5 | 3/3 | 100% | 0 | 3.33 |
| openai/gpt-4o | 3/3 | 100% | 0 | 3.33 |
| openai/gpt-4o-mini | 3/3 | 100% | 0 | 3.33 |
| google/gemini-2.5-flash | 3/3 | 100% | 0 | 3.33 |
| deepseek/deepseek-chat-v3.1 | 3/3 | 100% | 0 | 3.33 |
| meta-llama/llama-3.3-70b-instruct | 3/3 | 100% | 0 | 3.33 |
| scripted (oracle) | 3/3 | 100% | 0 | 3.33 |
| random (fuzz) | 0/3 | 0% | 0 | 30.0 |

Two takeaways:

1. **Dogfooding: clean.** Seven real models generated dozens of tool calls (their own choice of
   identifiers and values) against streamlit-mcp with **zero crashes** — the strongest evidence yet
   that the driving surface is robust.
2. **The seed corpus is saturated.** Every capable model — from `gpt-4o-mini` to `opus-4` — solves
   all three at the *oracle-optimal* action count, so the benchmark can't yet discriminate among
   strong models (only the random floor fails). **Harder tasks are the next priority** (see
   Roadmap): longer horizons, larger widget trees, deceptive/near-miss goals, and error-recovery.

## Interpreting results

- **solve rate** — did the agent reach the goal? (The oracle should be 100%; a random agent near 0%
  confirms the tasks actually discriminate skill.)
- **actions** — efficiency (fewer is better).
- **crashes** — **should always be 0.** A non-zero count means a streamlit-mcp tool raised an
  unexpected exception while being driven — a library bug the benchmark just found. `python -m arena
  run` exits non-zero if any episode crashed, so it works as a dogfood gate in CI.

## Roadmap

- **M1 (done)** — env, task format, scripted + random agents, runner, report, 3 seed tasks.
- **M2 (done)** — `LLMAgent` tool-use loop over the six tools (injectable client, fake-client
  tests); `--provider anthropic|openrouter`, `--model`, per-model result files, `arena leaderboard`.
  Verified live: 7 models across 5 providers via OpenRouter, 0 streamlit-mcp crashes.
- **M4, pulled forward (next)** — a wider, HARDER task corpus. The seed tasks are saturated (every
  strong model scores 100% at optimal efficiency), so the benchmark needs longer horizons, larger
  widget trees, near-miss/deceptive goals, and error-recovery tasks to have signal.
- **M3** — drive via a real `fastmcp` stdio client (full-stack fidelity, not just the Engine);
  guardrail tasks (a `--read-only` task that must be refused), semantic-tool tasks.
- **later** — a Streamlit leaderboard viewer (which streamlit-mcp can itself drive — meta-dogfooding).
