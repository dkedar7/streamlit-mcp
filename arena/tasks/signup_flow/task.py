"""signup_flow — fill a multi-field form and submit. Dogfoods text/select/slider/checkbox/button."""

from pathlib import Path

from arena.task import Task

APP = str(Path(__file__).parent / "app.py")

GOAL = ("Create an account for 'Ada' on the Pro plan with 10 years of experience, "
        "subscribed to the newsletter.")


def check(state: dict, output: dict) -> bool:
    return (
        state.get("created") is True
        and state.get("name") == "Ada"
        and state.get("plan") == "Pro"
        and state.get("experience") == 10
        and state.get("subscribe") is True
    )


TASK = Task(
    id="signup_flow",
    app=APP,
    goal=GOAL,
    check=check,
    solution=[
        ("set", "Name", "Ada"),
        ("set", "Plan", "Pro"),
        ("set", "Years of experience", 10),
        ("set", "Subscribe to newsletter", True),
        ("click", "Create account"),
    ],
    tier="easy",
    tags=("form", "text", "select", "slider", "checkbox", "button"),
)
