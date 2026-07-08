"""Agents that drive an ArenaEnv toward a task's goal.

- ScriptedAgent replays a task's oracle solution — no LLM, deterministic, runs in CI. It proves each
  task is solvable and dogfoods the full driving path with zero API cost.
- RandomAgent fuzzes: it picks random widgets and plausible/boundary values within a budget, which
  stresses set_widget atomicity, guardrails, and error handling (it should never make the tools
  *crash* — only return clean errors).
- LLMAgent is the real eval subject (Milestone 2): an LLM that reads list_widgets/read_output and
  decides actions. Stubbed here behind a clear interface.
"""

from __future__ import annotations

import random
from typing import Any

from .env import ArenaEnv, StepBudgetExceeded


class BaseAgent:
    name = "base"

    def solve(self, env: ArenaEnv, goal: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ScriptedAgent(BaseAgent):
    """Replays a fixed action list. The oracle each task ships as ``solution``."""

    name = "scripted"

    def __init__(self, solution: list[tuple]):
        self.solution = solution

    def solve(self, env: ArenaEnv, goal: str) -> None:
        for action in self.solution:
            if action[0] == "set":
                env.set_widget(action[1], action[2])
            elif action[0] == "click":
                env.click(action[1])
            else:  # pragma: no cover - guard against a malformed oracle
                raise ValueError(f"unknown scripted action {action!r}")


class RandomAgent(BaseAgent):
    """Picks random valid-ish actions until the budget runs out. A fuzz baseline.

    Deterministic given ``seed``. Chooses a value appropriate to each widget kind — sometimes a
    boundary or out-of-range one — so it exercises both the happy path and streamlit-mcp's
    validation/atomicity (a rejected value must be a clean error, never a crash)."""

    name = "random"

    def __init__(self, seed: int = 0, budget: int = 20):
        self.rng = random.Random(seed)
        self.budget = budget

    def solve(self, env: ArenaEnv, goal: str) -> None:
        for _ in range(self.budget):
            widgets = env.list_widgets().get("widgets", [])
            if not widgets:
                return
            w = self.rng.choice(widgets)
            try:
                if w.get("action"):  # a button
                    env.click(w["identifier"])
                else:
                    env.set_widget(w["identifier"], self._value_for(w))
            except StepBudgetExceeded:
                return

    def _value_for(self, w: dict) -> Any:
        kind = w["kind"]
        c = w.get("constraints", {})
        opts = c.get("options")
        if opts:
            return self.rng.choice(opts)
        if kind in ("number_input", "slider"):
            lo = c.get("min", 0) if c.get("min") is not None else 0
            hi = c.get("max", 100) if c.get("max") is not None else 100
            # occasionally overshoot the range to probe atomicity
            span = (hi - lo) or 1
            return self.rng.randint(int(lo), int(hi)) if self.rng.random() < 0.8 \
                else int(hi + span)
        if kind in ("checkbox", "toggle"):
            return self.rng.random() < 0.5
        if kind == "color_picker":
            return self.rng.choice(["#ff0000", "#00ff00", "notacolor"])  # last probes validation
        if kind in ("date_input", "time_input"):
            return "2026-06-15" if kind == "date_input" else "09:30"
        return self.rng.choice(["hello", "42", "true", ""])  # text-ish


# LLMAgent (an Anthropic tool-use loop over the six tools) lives in arena/llm.py to keep the SDK
# import lazy — scripted/random agents run with no `anthropic` dependency. Re-exported here so the
# agent surface stays in one place.
from .llm import LLMAgent  # noqa: E402,F401
