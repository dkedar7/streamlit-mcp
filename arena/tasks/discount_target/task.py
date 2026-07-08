"""discount_target — read the rendered subtotal, then find the smallest whole-percent discount.

10 Widgets = $120 subtotal; smallest whole discount with total <= $90 is 25% (120*0.75 = 90).
Discriminates: the Widget price isn't in the goal, so the agent must set item+qty, READ the
subtotal from read_output, then inverse-compute — a genuine multi-turn read/reason loop."""

from pathlib import Path

from arena.task import Task

APP = str(Path(__file__).parent / "app.py")

GOAL = ("Order 10 Widgets, then apply the smallest whole-percent discount that brings the total "
        "to $90 or less.")


def check(state: dict, output: dict) -> bool:
    return (
        state.get("item") == "Widget"
        and state.get("qty") == 10
        and state.get("discount") == 25          # 24% -> $91.20 (too high); 25% -> $90.00
    )


TASK = Task(
    id="discount_target",
    app=APP,
    goal=GOAL,
    check=check,
    solution=[("set", "Item", "Widget"), ("set", "Quantity", 10), ("set", "Discount %", 25)],
    tier="hard",
    tags=("read-output", "arithmetic", "select", "number", "slider"),
)
