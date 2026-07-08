"""clamp_to_max — the requested value (250) exceeds the max (100); the goal says to clamp.

Discriminates + error-recovery: a naive model sets 250, gets a clean rejection (the #12 range
guard), and must read the error / constraint and fall back to 100. A model that reads constraints
first sets 100 directly. A model that sets 250 and declares success (ignoring the rejection) fails —
which is exactly the failure mode a good agent must avoid."""

from pathlib import Path

from arena.task import Task

APP = str(Path(__file__).parent / "app.py")

GOAL = ("Set requests per second to 250. If that is above the allowed maximum, use the maximum "
        "instead.")


def check(state: dict, output: dict) -> bool:
    return state.get("rps") == 100


TASK = Task(
    id="clamp_to_max",
    app=APP,
    goal=GOAL,
    check=check,
    solution=[("set", "Requests per second", 100)],  # oracle resolves to the clamped value
    tier="medium",
    tags=("error-recovery", "read-constraints", "number"),
)
