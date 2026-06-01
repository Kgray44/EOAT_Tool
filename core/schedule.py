from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .task_progress import TaskItem, extract_tasks, load_task_progress, progress_file_for_week, summarize_task_status


@dataclass(frozen=True)
class WeekSchedule:
    week: int
    schedule_path: Path | None
    progress_path: Path | None
    days: dict[str, list[str]]
    tasks: list[TaskItem]
    status_counts: dict[str, int]


@dataclass(frozen=True)
class ProjectDay:
    week: int
    day: int
    date: date
    source: str
    project_start_date: date | None = None
    warning: str = ""


def parse_project_date(value: str | date | None) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def infer_project_start_date(project_root: str | Path) -> date | None:
    paths_to_scan = [
        Path(project_root) / "00_Project_Admin" / "Daily_Status_Reports",
        Path(project_root) / "00_Project_Admin" / "Daily_Status_Reports" / "Morning_Plans",
    ]
    pattern = re.compile(r"Week\s*1[_\s-]*Day\s*1.*?(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
    candidates: list[date] = []
    for folder in paths_to_scan:
        if not folder.exists():
            continue
        for path in folder.glob("*"):
            match = pattern.search(path.stem)
            if match:
                parsed = parse_project_date(match.group(1))
                if parsed:
                    candidates.append(parsed)
    return min(candidates) if candidates else None


def resolve_project_day(
    current_date: date,
    project_start_date: date,
    skip_weekends: bool = True,
    holidays: list[date] | None = None,
    manual_week: int | None = None,
    manual_day: int | None = None,
    manual_override: bool = False,
) -> ProjectDay:
    if manual_override:
        week = int(manual_week or 1)
        day = int(manual_day or 1)
        return ProjectDay(
            week=week, day=day, date=current_date, source="manual override", project_start_date=project_start_date
        )

    holiday_set = set(holidays or [])
    if current_date < project_start_date:
        return ProjectDay(
            week=1,
            day=1,
            date=current_date,
            source="project calendar",
            project_start_date=project_start_date,
            warning="Current date is before the configured project start date; using Week 1 Day 1.",
        )

    elapsed_workdays = 0
    cursor = project_start_date
    while cursor <= current_date:
        is_weekend = skip_weekends and cursor.weekday() >= 5
        if not is_weekend and cursor not in holiday_set:
            elapsed_workdays += 1
        cursor += timedelta(days=1)

    warning = ""
    if skip_weekends and current_date.weekday() >= 5 or current_date in holiday_set:
        warning = "Today is not a configured workday; using the most recent configured project workday."

    elapsed_workdays = max(elapsed_workdays, 1)
    week = ((elapsed_workdays - 1) // 5) + 1
    day = ((elapsed_workdays - 1) % 5) + 1
    return ProjectDay(
        week=week,
        day=day,
        date=current_date,
        source="project calendar",
        project_start_date=project_start_date,
        warning=warning,
    )


def resolve_project_day_for_project(
    project_root: str | Path,
    current_date: date | None = None,
    project_start_date: str | date | None = None,
    skip_weekends: bool = True,
    holidays: list[str | date] | None = None,
    manual_week: int | None = None,
    manual_day: int | None = None,
    manual_override: bool = False,
) -> ProjectDay:
    today = current_date or date.today()
    parsed_start = parse_project_date(project_start_date)
    warning = ""
    if parsed_start is None:
        parsed_start = infer_project_start_date(project_root)
        if parsed_start:
            warning = f"Project start date inferred from existing Week 1 Day 1 report: {parsed_start.isoformat()}."
    if parsed_start is None:
        return ProjectDay(
            week=int(manual_week or 1),
            day=int(manual_day or 1),
            date=today,
            source="fallback",
            project_start_date=None,
            warning="Project start date is missing; using selected/default Week 1 Day 1 until configured.",
        )

    parsed_holidays = [item for item in (parse_project_date(value) for value in (holidays or [])) if item]
    resolved = resolve_project_day(
        today,
        parsed_start,
        skip_weekends=skip_weekends,
        holidays=parsed_holidays,
        manual_week=manual_week,
        manual_day=manual_day,
        manual_override=manual_override,
    )
    if warning and not resolved.warning:
        return ProjectDay(
            week=resolved.week,
            day=resolved.day,
            date=resolved.date,
            source=resolved.source,
            project_start_date=resolved.project_start_date,
            warning=warning,
        )
    return resolved


def available_schedule_weeks(project_root: str | Path) -> list[int]:
    admin = Path(project_root) / "00_Project_Admin"
    if not admin.exists():
        return []
    weeks: set[int] = set()
    for pattern in ["project_schedule_week*.json", "task_progress_week*.json"]:
        for path in admin.glob(pattern):
            match = re.search(r"week(\d+)", path.stem, re.IGNORECASE)
            if match:
                weeks.add(int(match.group(1)))
    return sorted(weeks)


def schedule_file_for_week(project_root: str | Path, week: int) -> Path:
    return Path(project_root) / "00_Project_Admin" / f"project_schedule_week{week}.json"


def load_schedule_file(path: str | Path) -> dict[str, Any]:
    schedule_path = Path(path)
    if not schedule_path.exists():
        return {"days": {}}
    try:
        data = json.loads(schedule_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"days": {}}
    if not isinstance(data, dict):
        return {"days": {}}
    data.setdefault("days", {})
    return data


def load_week_schedule(project_root: str | Path, week: int) -> WeekSchedule:
    schedule_path = schedule_file_for_week(project_root, week)
    progress_path = progress_file_for_week(project_root, week)
    schedule_data = load_schedule_file(schedule_path)
    progress_data = load_task_progress(progress_path)
    raw_days = schedule_data.get("days", {})
    days: dict[str, list[str]] = {}
    if isinstance(raw_days, dict):
        for day, tasks in raw_days.items():
            if isinstance(tasks, list):
                days[str(day)] = [str(task) for task in tasks]
    tasks = extract_tasks(progress_data)
    return WeekSchedule(
        week=week,
        schedule_path=schedule_path if schedule_path.exists() else None,
        progress_path=progress_path if progress_path.exists() else None,
        days=days,
        tasks=tasks,
        status_counts=summarize_task_status(tasks),
    )
