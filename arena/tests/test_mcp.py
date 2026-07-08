"""Full-stack tests: drive streamlit-mcp over a REAL fastmcp stdio subprocess (transport='mcp').

Each spawns `streamlit-mcp serve <app>` and talks JSON-RPC to it — slower than the Engine env, but
exercises the whole product surface (server, schemas, guardrail flags, @mcp_tool registration,
error propagation). These aren't in the library's CI; run with:
    uv run --with pytest python -m pytest arena/tests/test_mcp.py -q
"""

from pathlib import Path

from arena.agents import ScriptedAgent
from arena.mcp_env import McpEnv
from arena.registry import load_tasks
from arena.runner import run_episode

FIXTURES = Path(__file__).parent / "fixtures"


def _task(task_id):
    return next(t for t in load_tasks() if t.id == task_id)


def test_scripted_solves_over_mcp_transport():
    task = _task("signup_flow")
    result = run_episode(task, ScriptedAgent(task.solution), transport="mcp")
    assert result.solved and not result.crashed


def test_mcp_read_only_refuses_writes_full_stack():
    # the --read-only guardrail must block set_widget over the real transport, cleanly (no crash)
    task = _task("signup_flow")
    env = McpEnv(task.app, server_args=["--read-only"], max_steps=10)
    try:
        out = env.set_widget("Name", "Bob")
        assert "error" in out and "read-only" in out["error"].lower()
        assert not env.crashed                       # a guardrail block is a clean error, not a crash
        assert env.get_state().get("name") != "Bob"  # the write really was refused
    finally:
        env.close()


def test_mcp_semantic_tool_listed_callable_and_guarded():
    app = str(FIXTURES / "semantic_app.py")
    env = McpEnv(app, max_steps=10)
    try:
        assert "reset_count" in env.tool_names()     # @mcp_tool exposed over the real serve (#14)
        env.invoke("reset_count", {})
        assert not env.crashed
    finally:
        env.close()
    # ...and --read-only blocks the semantic tool too (the #26 guarantee), full-stack
    guarded = McpEnv(app, server_args=["--read-only"], max_steps=10)
    try:
        out = guarded.invoke("reset_count", {})
        assert "error" in out and "read-only" in out["error"].lower()
        assert not guarded.crashed
    finally:
        guarded.close()
