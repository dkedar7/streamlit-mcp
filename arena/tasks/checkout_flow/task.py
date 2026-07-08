"""checkout_flow — a longer form with an ordering trap and a distractor button.

The order only places if 'agree' is set BEFORE clicking 'Place order' (else it just warns), and there
are two buttons — the agent must click 'Place order', not 'Cancel'. Discriminates: precondition +
correct-button selection + a multi-field horizon."""

from pathlib import Path

from arena.task import Task

APP = str(Path(__file__).parent / "app.py")

GOAL = ("Place an Overnight order for 'Ada Lovelace' shipping to '10 Downing St', agreeing to the "
        "terms. Do not cancel.")


def check(state: dict, output: dict) -> bool:
    return (
        state.get("order_placed") is True
        and not state.get("order_cancelled")
        and state.get("name") == "Ada Lovelace"
        and state.get("address") == "10 Downing St"
        and state.get("speed") == "Overnight"
        and state.get("agree") is True
    )


TASK = Task(
    id="checkout_flow",
    app=APP,
    goal=GOAL,
    check=check,
    solution=[
        ("set", "Full name", "Ada Lovelace"),
        ("set", "Shipping address", "10 Downing St"),
        ("set", "Shipping speed", "Overnight"),
        ("set", "I agree to the terms", True),
        ("click", "Place order"),
    ],
    tier="hard",
    tags=("long-horizon", "ordering", "distractor-button", "form"),
)
