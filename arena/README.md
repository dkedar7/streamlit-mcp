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

# drive over the REAL MCP transport (spawns `streamlit-mcp serve`, talks JSON-RPC) instead of the
# in-process engine — full-stack fidelity:
uv run --with fastmcp python -m arena run --agent scripted --transport mcp
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

- **`env.py` / `mcp_env.py`** — two interchangeable environments behind the same six-tool interface,
  chosen with `--transport`:
  - `ArenaEnv` (**engine**, default) wraps the streamlit-mcp `Engine` in-process — fast, and
    representative thanks to the parity guarantee.
  - `McpEnv` (**mcp**) spawns `streamlit-mcp serve <app>` and drives it through a `fastmcp` stdio
    client — full-stack fidelity (JSON-RPC over pipes, the real server, tool schemas, guardrail
    flags, `@mcp_tool` registration). Since FastMCP wraps every server exception into an error, it
    classifies by message: a known clean-error phrasing is a tool error, anything else is a `crash`.

  Both count only *actions* against the budget and separate an **expected tool error** (bad value /
  not found / guardrail block — a signal the agent adapts to) from an **unexpected exception** (a
  streamlit-mcp bug → `crash`).
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

## Results (2026-07-08, via OpenRouter — 9 tasks)

A snapshot across the full corpus (2 easy, 2 medium, 5 hard):

| agent | solved | solve rate | crashes | avg actions |
|---|---:|---:|---:|---:|
| anthropic/claude-opus-4 | 9/9 | 100% | 0 | 3.0 |
| anthropic/claude-haiku-4.5 | 9/9 | 100% | 0 | 3.0 |
| google/gemini-2.5-flash | 9/9 | 100% | 0 | 3.0 |
| openai/gpt-4o | 9/9 | 100% | 0 | 3.11 |
| openai/gpt-4o-mini | 9/9 | 100% | 0 | 3.11 |
| scripted (oracle) | 9/9 | 100% | 0 | 3.11 |
| mistralai/ministral-3b | 8/9 | 89% | 0 | 3.78 |
| google/gemini-2.5-flash-lite | 6/9 | 67% | 0 | 1.89 |
| qwen/qwen-2.5-7b | 6/9 | 67% | 0 | 4.22 |
| meta-llama/llama-3.1-8b | 3/9 | 33% | 0 | 1.56 |
| meta-llama/llama-3.2-3b | 0/9 | 0% | 0 | 0.0 |
| random (fuzz) | 0/9 | 0% | 0 | 30.0 |

Three takeaways:

1. **The corpus now discriminates — at the small end.** Solve rate spreads cleanly from 0% to 89%
   across sub-8B models, so the harder tasks (arithmetic constraints, read-the-output reasoning,
   large trees with distractors, error-recovery) do separate weaker agents.
2. **Frontier models still saturate it.** Every capable model — `gpt-4o-mini` through `opus-4` —
   still scores 100% at near-optimal efficiency. Bounded single-app operation is *easy* for them;
   separating the top will need much longer horizons, real ambiguity, or adversarial traps.
3. **The benchmark found a real streamlit-mcp bug.** Driving with `llama-3.1-8b` produced a
   **crash** (`TypeError` from a `None` identifier) — an *unexpected* library exception, not a tool
   error. It was fixed in streamlit-mcp **0.3.12**; the table above (post-fix) is back to 0 crashes.
   This is exactly the dual purpose: a benchmark that also hardens the library.

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
- **M4 (done, ongoing)** — corpus expanded 3 → 9 across easy/medium/hard. It discriminates among
  sub-8B models and already found + fixed a library crash (0.3.12). Still needs *expert*-tier tasks
  (long horizons, real ambiguity, adversarial traps) to separate frontier models.
- **M3 (done)** — `McpEnv`: drive via a real `fastmcp` stdio client (`--transport mcp`), spawning
  `streamlit-mcp serve`. The oracle solves all 9 full-stack, 0 crashes; full-stack tests cover
  `--read-only` enforcement and `@mcp_tool` exposure/blocking over the real transport
  (`arena/tests/test_mcp.py`). Crash-detection over MCP is by error-message classification, since
  FastMCP wraps server exceptions.
- **later** — a Streamlit leaderboard viewer (which streamlit-mcp can itself drive — meta-dogfooding).
