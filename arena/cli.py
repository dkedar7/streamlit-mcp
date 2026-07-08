"""StreamlitArena CLI: `python -m arena run` / `python -m arena list`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agents import LLMAgent, RandomAgent, ScriptedAgent
from .registry import load_tasks
from .report import to_json, to_markdown
from .runner import run_suite
from .task import Task

RESULTS_DIR = Path(__file__).parent / "results"


def _agent_factory(name: str, seed: int):
    if name == "scripted":
        return lambda task: ScriptedAgent(task.solution)
    if name == "random":
        return lambda task: RandomAgent(seed=seed, budget=task.max_steps)
    if name == "llm":
        return lambda task: LLMAgent()
    raise SystemExit(f"unknown agent {name!r} (choose scripted | random | llm)")


def cmd_list(_: argparse.Namespace) -> int:
    for t in load_tasks():
        print(f"  {t.id:<20} [{t.tier}] {t.goal}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    tasks = load_tasks()
    if args.task:
        tasks = [t for t in tasks if t.id in set(args.task)]
        if not tasks:
            raise SystemExit(f"no matching tasks for {args.task}")
    results = run_suite(tasks, _agent_factory(args.agent, args.seed))
    print(to_markdown(results))
    if args.json:
        RESULTS_DIR.mkdir(exist_ok=True)
        out = RESULTS_DIR / f"{args.agent}.json"
        out.write_text(json.dumps(to_json(results), indent=2), encoding="utf-8")
        print(f"wrote {out}")
    # non-zero exit if any streamlit-mcp crash surfaced (useful as a dogfood gate in CI)
    return 1 if any(r.crashed for r in results) else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="arena", description="StreamlitArena — agent benchmark on "
                                "Streamlit apps, driven via streamlit-mcp.")
    sub = p.add_subparsers(dest="command", required=True)
    pl = sub.add_parser("list", help="list tasks")
    pl.set_defaults(func=cmd_list)
    pr = sub.add_parser("run", help="run tasks with an agent")
    pr.add_argument("--agent", default="scripted", help="scripted | random | llm")
    pr.add_argument("--task", action="append", help="run only this task id (repeatable)")
    pr.add_argument("--seed", type=int, default=0, help="seed for the random agent")
    pr.add_argument("--json", action="store_true", help="also write arena/results/<agent>.json")
    pr.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    try:  # Windows consoles default to cp1252, which can't encode the report's ✅/💥 glyphs
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
