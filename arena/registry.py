"""Discover tasks under arena/tasks/*/task.py (each exports ``TASK``)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from .task import Task

TASKS_DIR = Path(__file__).parent / "tasks"


def load_tasks() -> list[Task]:
    tasks: list[Task] = []
    for task_dir in sorted(TASKS_DIR.iterdir()):
        task_py = task_dir / "task.py"
        if not task_py.exists():
            continue
        spec = importlib.util.spec_from_file_location(f"arena_task_{task_dir.name}", task_py)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        task = getattr(module, "TASK", None)
        if isinstance(task, Task):
            tasks.append(task)
    return tasks
