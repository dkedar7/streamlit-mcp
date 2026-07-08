"""budget_split — allocate a fixed budget under two interacting constraints.

Eng = half of 1200 = 600; the rest (600) splits so Marketing = 2 x Design -> Design 200, Marketing 400.
Discriminates: requires arithmetic reasoning over a constraint, not just entering stated numbers."""

from pathlib import Path

from arena.task import Task

APP = str(Path(__file__).parent / "app.py")

GOAL = ("Allocate the entire $1200 budget: Engineering gets exactly half, and Marketing gets "
        "twice as much as Design.")


def check(state: dict, output: dict) -> bool:
    e, m, d = state.get("engineering"), state.get("marketing"), state.get("design")
    return e == 600 and m == 400 and d == 200


TASK = Task(
    id="budget_split",
    app=APP,
    goal=GOAL,
    check=check,
    solution=[("set", "Engineering", 600), ("set", "Marketing", 400), ("set", "Design", 200)],
    tier="hard",
    tags=("arithmetic", "constraint", "number"),
)
