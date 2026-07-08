"""dashboard_filter — set filters and verify the RENDERED OUTPUT reflects them.

Dogfoods read_output + document order (the markdown line is a function of state), so a correct
solve depends on streamlit-mcp reporting the app's rendered text faithfully."""

from pathlib import Path

from arena.task import Task

APP = str(Path(__file__).parent / "app.py")

GOAL = "Filter the dashboard to show the top 5 products for the West region."


def check(state: dict, output: dict) -> bool:
    rendered = " ".join(o["text"] for o in output.get("outputs", []))
    return (
        state.get("region") == "West"
        and state.get("top_n") == 5
        and "top 5 products for West" in rendered
    )


TASK = Task(
    id="dashboard_filter",
    app=APP,
    goal=GOAL,
    check=check,
    solution=[
        ("set", "Region", "West"),
        ("set", "Top N", 5),
    ],
    tier="easy",
    tags=("filter", "select", "slider", "read_output"),
)
