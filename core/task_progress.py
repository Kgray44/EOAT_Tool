from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .safe_files import backup_file, ensure_directory

STATUS_VALUES = ["Not started", "In progress", "Blocked", "Complete", "Skipped"]


@dataclass
class TaskItem:
    id: str
    description: str
    day: str = ""
    status: str = "Not started"
    evidence: list[str] = field(default_factory=list)


def normalize_status(value: str | None) -> str:
    if not value:
        return "Not started"
    lowered = value.strip().lower()
    for status in STATUS_VALUES:
        if lowered == status.lower():
            return status
    aliases = {"todo": "Not started", "done": "Complete", "completed": "Complete", "in_progress": "In progress"}
    return aliases.get(lowered, value)


def progress_file_for_week(project_root: str | Path, week: int) -> Path:
    return Path(project_root) / "00_Project_Admin" / f"task_progress_week{week}.json"


def load_task_progress(path: str | Path) -> dict[str, Any]:
    progress_path = Path(path)
    if not progress_path.exists():
        return {"week": None, "tasks": []}
    try:
        data = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"week": None, "tasks": []}
    if not isinstance(data, dict):
        return {"week": None, "tasks": []}
    data.setdefault("tasks", [])
    return data


def extract_tasks(progress_data: dict[str, Any]) -> list[TaskItem]:
    tasks: list[TaskItem] = []
    for index, item in enumerate(progress_data.get("tasks", []), start=1):
        if not isinstance(item, dict):
            continue
        description = str(
            item.get("task") or item.get("task_text") or item.get("description") or item.get("name") or ""
        )
        task_id = str(item.get("id") or item.get("task_id") or f"task_{index}")
        tasks.append(
            TaskItem(
                id=task_id,
                description=description,
                day=str(item.get("day") or ""),
                status=normalize_status(str(item.get("status") or "Not started")),
                evidence=list(item.get("evidence") or []),
            )
        )
    return tasks


def summarize_task_status(tasks: list[TaskItem]) -> dict[str, int]:
    summary = {status: 0 for status in STATUS_VALUES}
    for task in tasks:
        status = normalize_status(task.status)
        summary[status] = summary.get(status, 0) + 1
    return summary


def update_task_status(progress_path: str | Path, task_id: str, status: str) -> bool:
    path = Path(progress_path)
    data = load_task_progress(path)
    changed = False
    for item in data.get("tasks", []):
        if str(item.get("id") or item.get("task_id")) == str(task_id):
            item["status"] = normalize_status(status)
            changed = True
            break
    if not changed:
        return False
    ensure_directory(path.parent)
    if path.exists():
        backup_file(path, path.parent / "_backups")
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True
