"""StreamlitArena — a reproducible benchmark that measures whether an AI agent can operate a
Streamlit app to accomplish a goal, driving purely through streamlit-mcp's semantic interface
(no browser, no vision).

It doubles as streamlit-mcp's heaviest dogfooding vehicle: every episode drives real apps through
the same tools an agent uses over MCP, so multi-step flows, dynamic layouts, every widget kind, and
the atomicity/ordering/identifier guarantees all get stress-tested — and any unexpected exception is
flagged as a crash (a library bug).
"""

from .agents import LLMAgent, RandomAgent, ScriptedAgent
from .env import ArenaEnv
from .registry import load_tasks
from .runner import EpisodeResult, run_episode, run_suite
from .task import Task

__all__ = [
    "ArenaEnv", "Task", "EpisodeResult", "run_episode", "run_suite", "load_tasks",
    "ScriptedAgent", "RandomAgent", "LLMAgent",
]
