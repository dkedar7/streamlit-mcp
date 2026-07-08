"""Aggregate episode results into scores + human/machine-readable reports."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .runner import EpisodeResult


def summarize(results: list[EpisodeResult]) -> dict:
    total = len(results)
    solved = sum(r.solved for r in results)
    crashed = sum(r.crashed for r in results)
    by_tier: dict[str, dict] = defaultdict(lambda: {"solved": 0, "total": 0})
    for r in results:
        by_tier[r.tier]["total"] += 1
        by_tier[r.tier]["solved"] += int(r.solved)
    return {
        "tasks": total,
        "solved": solved,
        "solve_rate": round(solved / total, 3) if total else 0.0,
        "crashes": crashed,                     # streamlit-mcp defects surfaced (should be 0)
        "avg_steps": round(sum(r.steps for r in results) / total, 2) if total else 0.0,
        "by_tier": {k: dict(v) for k, v in sorted(by_tier.items())},
    }


def to_json(results: list[EpisodeResult]) -> dict:
    return {
        "summary": summarize(results),
        "episodes": [
            {
                "task": r.task_id, "tier": r.tier, "agent": r.agent, "solved": r.solved,
                "steps": r.steps, "crashed": r.crashed, "tool_errors": r.tool_errors,
                "crash_details": r.crash_details, "error": r.error,
            }
            for r in results
        ],
    }


def to_markdown(results: list[EpisodeResult]) -> str:
    s = summarize(results)
    agent = results[0].agent if results else "?"
    lines = [
        f"# StreamlitArena — {agent} agent",
        "",
        f"**{s['solved']}/{s['tasks']} solved** "
        f"({s['solve_rate']:.0%}) · avg {s['avg_steps']} actions · "
        f"**{s['crashes']} streamlit-mcp crash(es)**",
        "",
        "| tier | solved |",
        "|---|---|",
    ]
    lines += [f"| {t} | {v['solved']}/{v['total']} |" for t, v in s["by_tier"].items()]
    lines += ["", "| task | tier | solved | actions | tool errors | crash | note |",
              "|---|---|:---:|---:|---:|:---:|---|"]
    for r in results:
        note = r.error or ("; ".join(r.crash_details) if r.crashed else "")
        lines.append(
            f"| {r.task_id} | {r.tier} | {'✅' if r.solved else '❌'} | {r.steps} | "
            f"{r.tool_errors} | {'💥' if r.crashed else ''} | {note} |"
        )
    if s["crashes"]:
        lines += ["", "> ⚠️ A crash means a streamlit-mcp tool raised an *unexpected* exception "
                  "while being driven — a bug in the library, surfaced by dogfooding."]
    return "\n".join(lines) + "\n"
