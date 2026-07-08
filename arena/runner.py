"""Run one task (an episode) or a whole suite, and collect results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .agents import BaseAgent
from .env import ArenaEnv, StepBudgetExceeded
from .task import Task


@dataclass
class EpisodeResult:
    task_id: str
    tier: str
    agent: str
    solved: bool
    steps: int
    crashed: bool                    # a streamlit-mcp internal error occurred while driving
    tool_errors: int                 # expected tool errors (bad value / not found / blocked)
    crash_details: list[str] = field(default_factory=list)
    error: Optional[str] = None      # harness-level: budget exceeded, agent raised, checker raised


def run_episode(task: Task, agent: BaseAgent, *, guard: Any = None) -> EpisodeResult:
    env = ArenaEnv(task.app, guard=guard, max_steps=task.max_steps)
    err: Optional[str] = None
    try:
        agent.solve(env, task.goal)
    except StepBudgetExceeded as e:
        err = str(e)
    except Exception as e:  # an agent that blew up is a harness/agent problem, not a solve
        err = f"agent error: {type(e).__name__}: {e}"

    state = env.get_state()
    output = env.read_output()
    try:
        solved = bool(task.check(state, output))
    except Exception as e:
        solved = False
        err = err or f"checker error: {type(e).__name__}: {e}"

    return EpisodeResult(
        task_id=task.id,
        tier=task.tier,
        agent=agent.name,
        solved=solved,
        steps=env.steps,
        crashed=env.crashed,
        tool_errors=sum(1 for s in env.trace if not s.ok and not s.crash),
        crash_details=[s.error for s in env.trace if s.crash and s.error],
        error=err,
    )


def run_suite(tasks: list[Task], agent_factory: Callable[[Task], BaseAgent],
              *, guard: Any = None) -> list[EpisodeResult]:
    """Run every task. ``agent_factory`` builds the agent per task (ScriptedAgent needs the task's
    own solution; stateless agents can ignore the argument)."""
    return [run_episode(t, agent_factory(t), guard=guard) for t in tasks]
