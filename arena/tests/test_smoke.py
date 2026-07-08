"""Smoke tests: the oracle solves every task, and no agent ever *crashes* streamlit-mcp.

Run from the repo root:  uv run python -m pytest arena/tests -q
The second test is the dogfooding gate — driving apps (even with garbage values) must only ever
produce clean tool errors, never an unexpected exception from the library.
"""

from arena.agents import RandomAgent, ScriptedAgent
from arena.registry import load_tasks
from arena.runner import run_episode


def test_oracle_solves_every_task_without_crashing():
    tasks = load_tasks()
    assert tasks, "no tasks discovered"
    for task in tasks:
        result = run_episode(task, ScriptedAgent(task.solution))
        assert result.solved, f"{task.id} unsolved by its own oracle: {result.error}"
        assert not result.crashed, f"{task.id} crashed streamlit-mcp: {result.crash_details}"


def test_random_agent_never_crashes_streamlit_mcp():
    tasks = load_tasks()
    for seed in range(3):
        for task in tasks:
            result = run_episode(task, RandomAgent(seed=seed, budget=task.max_steps))
            assert not result.crashed, (
                f"{task.id} (seed {seed}) crashed streamlit-mcp: {result.crash_details}"
            )
