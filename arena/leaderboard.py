"""Aggregate the per-agent result files in arena/results/ into one comparison table."""

from __future__ import annotations

import json
from pathlib import Path


def load_all(results_dir: Path) -> list[dict]:
    runs = []
    for f in sorted(results_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        summary = data.get("summary", {})
        episodes = data.get("episodes", [])
        label = episodes[0]["agent"] if episodes else f.stem
        runs.append({"label": label, **summary})
    return runs


def to_markdown(runs: list[dict]) -> str:
    lines = [
        "# StreamlitArena leaderboard",
        "",
        "| agent | solved | solve rate | crashes | avg actions |",
        "|---|---:|---:|---:|---:|",
    ]
    # best solve rate first, then fewest actions
    for r in sorted(runs, key=lambda r: (-r.get("solve_rate", 0.0), r.get("avg_steps", 1e9))):
        lines.append(
            f"| {r['label']} | {r.get('solved', 0)}/{r.get('tasks', 0)} | "
            f"{r.get('solve_rate', 0.0):.0%} | {r.get('crashes', 0)} | {r.get('avg_steps', 0)} |"
        )
    return "\n".join(lines) + "\n"
