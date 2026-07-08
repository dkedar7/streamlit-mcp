"""wizard_branching — a state-dependent layout where each step reveals the next widget.

The hard tier. It dogfoods the dynamic-layout capability end to end: after each set_widget rerun a
new widget appears, so it exercises re-introspection, document order (#39), and resolving a widget
that did not exist a step earlier. An agent that doesn't re-observe between steps will fail."""

from pathlib import Path

from arena.task import Task

APP = str(Path(__file__).parent / "app.py")

GOAL = ("Complete the advanced setup: choose Advanced mode, set the threshold to 75, "
        "then confirm the high threshold.")


def check(state: dict, output: dict) -> bool:
    return (
        state.get("mode") == "Advanced"
        and state.get("threshold") == 75
        and state.get("confirmed") is True
    )


TASK = Task(
    id="wizard_branching",
    app=APP,
    goal=GOAL,
    check=check,
    solution=[
        ("set", "Mode", "Advanced"),            # reveals Threshold
        ("set", "Threshold", 75),               # >=50 reveals Confirm high threshold
        ("set", "Confirm high threshold", True),
    ],
    tier="hard",
    tags=("dynamic-layout", "branching", "radio", "number", "checkbox"),
)
