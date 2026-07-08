"""A benchmark task: an app, a natural-language goal, and an automatic success checker."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

# A checker is a pure function of the finished episode's observations:
#   (session_state: dict, read_output: dict) -> solved?
# Keeping it pure over observations (not the live env) makes scoring deterministic and replayable.
Checker = Callable[[dict, dict], bool]

# An oracle solution is a list of actions the ScriptedAgent replays:
#   ("set", identifier, value) | ("click", identifier)
Action = tuple


@dataclass
class Task:
    id: str
    app: str                       # absolute path to this task's app.py
    goal: str                      # the instruction handed to the agent
    check: Checker                 # (state, output) -> solved?
    solution: list[Action]         # oracle actions (proves solvability; drives ScriptedAgent)
    max_steps: int = 30
    tier: str = "easy"             # easy | medium | hard
    tags: tuple[str, ...] = field(default_factory=tuple)
    server_args: tuple[str, ...] = field(default_factory=tuple)  # extra `serve` flags (mcp transport)
