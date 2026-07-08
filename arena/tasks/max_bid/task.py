"""max_bid — the goal doesn't state the number; the agent must read the widget's max constraint.

Discriminates: a model that ignores `constraints.max` (250) from list_widgets can't know the answer."""

from pathlib import Path

from arena.task import Task

APP = str(Path(__file__).parent / "app.py")

GOAL = "Place the maximum bid this form allows."


def check(state: dict, output: dict) -> bool:
    return state.get("bid") == 250


TASK = Task(
    id="max_bid",
    app=APP,
    goal=GOAL,
    check=check,
    solution=[("set", "Your bid", 250)],
    tier="medium",
    tags=("read-constraints", "number"),
)
