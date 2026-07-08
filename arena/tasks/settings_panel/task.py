"""settings_panel — precise targeting in a 12-widget tree; leave distractors at their defaults.

Discriminates: 'only those two' checkboxes + 'leave everything else at its default' punishes any
model that toggles an extra feature or nudges an untouched slider. Note the near-miss: a 'Dark mode'
checkbox AND a 'Dark' theme option — the agent must set both correctly and not confuse them."""

from pathlib import Path

from arena.task import Task

APP = str(Path(__file__).parent / "app.py")

GOAL = ("Enable Dark mode and Notifications (only those two features), set Brightness to 80, choose "
        "the Dark theme, and set the display name to 'Ada'. Leave everything else at its default.")


def check(state: dict, output: dict) -> bool:
    return (
        state.get("dark_mode") is True
        and state.get("notifications") is True
        # every other feature must remain off (default)
        and not state.get("autosave")
        and not state.get("telemetry")
        and not state.get("beta_features")
        and not state.get("compact_view")
        and state.get("brightness") == 80
        and state.get("volume") == 50            # untouched default
        and state.get("theme") == "Dark"
        and state.get("language") == "English"   # untouched default
        and state.get("display_name") == "Ada"
    )


TASK = Task(
    id="settings_panel",
    app=APP,
    goal=GOAL,
    check=check,
    solution=[
        ("set", "Dark mode", True),
        ("set", "Notifications", True),
        ("set", "Brightness", 80),
        ("set", "Theme", "Dark"),
        ("set", "Display name", "Ada"),
    ],
    tier="hard",
    tags=("large-tree", "distractors", "precision", "checkbox", "slider", "select"),
)
