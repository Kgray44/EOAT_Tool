from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .logging import read_recent_activity
from .open_items import list_open_items, summarize_open_items
from .paths import resolve_project_paths
from .reports import list_recent_files, read_report_preview
from .schedule import load_week_schedule
from .task_progress import STATUS_VALUES


def _date_text(value: date | str | None) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "")


def _parse_date(value: Any) -> date | None:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _activity_line(entry: dict[str, Any]) -> str:
    label = str(entry.get("tool_name") or entry.get("event_name") or entry.get("tool_id") or "Activity").strip()
    summary = str(entry.get("summary") or entry.get("message") or "").strip()
    if summary:
        return f"{label}: {summary}"
    return label


def _recent_activity(project_root: str | Path, limit: int = 40) -> tuple[list[dict[str, Any]], list[str]]:
    entries, warning = read_recent_activity(project_root, limit=limit)
    warnings = [warning] if warning else []
    return entries, warnings


def _recent_validation_payload(project_root: str | Path) -> dict[str, Any]:
    folder = resolve_project_paths(project_root).validation_reports
    if not folder.exists():
        return {}
    candidates = sorted(
        folder.glob("Foundation_Validation_*.json"), key=lambda path: path.stat().st_mtime, reverse=True
    )
    for path in candidates[:3]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload["_path"] = str(path)
        return payload
    return {}


def _validation_summary(project_root: str | Path) -> dict[str, Any]:
    payload = _recent_validation_payload(project_root)
    if not payload:
        return {"available": False, "summary": "No JSON validation findings were found.", "counts": {}, "findings": []}
    counts = dict((payload.get("summary_counts") or {}).get("by_severity") or {})
    findings = list(payload.get("findings") or [])
    return {
        "available": True,
        "path": payload.get("_path", ""),
        "summary": str(payload.get("summary") or "Latest workbook validation findings loaded."),
        "counts": counts,
        "findings": findings,
    }


def _safe_open_items(
    project_root: str | Path, *, limit: int | None = 12
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    paths = resolve_project_paths(project_root)
    if not paths.annotations_database.exists():
        return [], {}, []
    try:
        items = list_open_items(
            project_root,
            include_resolved=False,
            include_validation=False,
            record_source_fixes=False,
        )
        summary = summarize_open_items(items)
    except Exception as exc:
        return [], {}, [f"Open items could not be read: {exc}"]
    rows = [
        {
            "id": item.id,
            "source": item.source,
            "severity": item.severity,
            "category": item.category,
            "title": item.title,
            "status": item.status,
            "due_date": item.due_date,
            "recommended_action": item.recommended_action,
        }
        for item in (items if limit is None else items[:limit])
    ]
    return rows, summary, []


def _schedule_context(project_root: str | Path, week: int, *, day: int | None = None) -> dict[str, Any]:
    schedule = load_week_schedule(project_root, week)
    tasks = list(schedule.tasks)
    if day is not None:
        current_day = str(day)
        next_day = str(day + 1)
        current_tasks = [task for task in tasks if task.day == current_day]
        next_tasks = [task for task in tasks if task.day == next_day]
    else:
        current_tasks = tasks
        next_tasks = []
    status_counts = schedule.status_counts or {status: 0 for status in STATUS_VALUES}
    return {
        "status_counts": status_counts,
        "current_tasks": [
            {"id": task.id, "day": task.day, "description": task.description, "status": task.status}
            for task in current_tasks
        ],
        "next_tasks": [
            {"id": task.id, "day": task.day, "description": task.description, "status": task.status}
            for task in next_tasks
        ],
        "blocked_tasks": [
            {"id": task.id, "day": task.day, "description": task.description, "status": task.status}
            for task in tasks
            if task.status == "Blocked"
        ],
        "open_tasks": [
            {"id": task.id, "day": task.day, "description": task.description, "status": task.status}
            for task in tasks
            if task.status in {"Not started", "In progress", "Blocked"}
        ],
        "completed_tasks": [
            {"id": task.id, "day": task.day, "description": task.description, "status": task.status}
            for task in tasks
            if task.status == "Complete"
        ],
    }


def _daily_report_paths(project_root: str | Path, week: int) -> list[Path]:
    folder = resolve_project_paths(project_root).daily_reports
    if not folder.exists():
        return []
    return sorted(folder.glob(f"Week{week}_Day*_Status_*.md"), key=lambda path: path.stat().st_mtime)


def _daily_report_bullets(paths: list[Path], limit: int = 12) -> list[str]:
    bullets: list[str] = []
    for path in paths:
        text, warning = read_report_preview(path)
        if warning:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") and len(stripped) > 3:
                bullets.append(f"{path.stem}: {stripped[2:]}")
            if len(bullets) >= limit:
                return bullets
    return bullets


def build_daily_report_context(
    project_root: str | Path,
    *,
    target_date: date | str | None = None,
    week: int | None = None,
    day: int | None = None,
) -> dict[str, Any]:
    activity, warnings = _recent_activity(project_root, limit=30)
    open_items, open_summary, item_warnings = _safe_open_items(project_root, limit=8)
    validation = _validation_summary(project_root)
    schedule = _schedule_context(project_root, int(week or 1), day=day) if week else {}
    paths = resolve_project_paths(project_root)
    recent_reports = [str(path) for path in list_recent_files(paths.daily_reports, limit=6)]
    changed_files = Counter()
    for entry in activity:
        for key in ("files_created", "files_modified"):
            for path_text in entry.get(key, []) or []:
                name = Path(str(path_text)).name
                if name:
                    changed_files[name] += 1
    return {
        "type": "daily",
        "target_date": _date_text(target_date),
        "week": week,
        "day": day,
        "activity": activity,
        "activity_lines": [_activity_line(entry) for entry in activity[:10]],
        "open_items": open_items,
        "open_items_summary": open_summary,
        "validation": validation,
        "schedule": schedule,
        "reports_generated": recent_reports,
        "changed_files": [name for name, _count in changed_files.most_common(8)],
        "warnings": warnings + item_warnings,
    }


def daily_summary_cli_items(context: dict[str, Any]) -> dict[str, list[str]]:
    completed: list[str] = []
    need: list[str] = []
    plan: list[str] = []
    notes: list[str] = []

    for entry in context.get("activity", [])[:8]:
        if entry.get("success") is True and entry.get("summary"):
            completed.append(_activity_line(entry))
    for task in (context.get("schedule") or {}).get("completed_tasks", [])[:4]:
        completed.append(f"Schedule task complete: {task.get('description')}")
    for item in context.get("open_items", [])[:5]:
        title = str(item.get("title") or "Open item")
        status = str(item.get("status") or "Open")
        if status == "Blocked":
            need.append(f"Unblock open item: {title}")
        else:
            need.append(f"Review open item: {title}")
    validation = context.get("validation") or {}
    if validation.get("available"):
        counts = validation.get("counts") or {}
        blockers = int(counts.get("BLOCKER") or 0)
        errors = int(counts.get("ERROR") or 0)
        if blockers or errors:
            need.append(f"Review workbook validation findings: {blockers} blocker(s), {errors} error(s)")
        else:
            notes.append("Latest workbook validation JSON did not show blocker/error findings.")
    for task in (context.get("schedule") or {}).get("open_tasks", [])[:5]:
        plan.append(f"{task.get('description')} ({task.get('status')})")
    for path_text in context.get("reports_generated", [])[:3]:
        notes.append(f"Recent report available: {Path(path_text).name}")
    for warning in context.get("warnings", [])[:3]:
        notes.append(warning)

    return {
        "completed": _dedupe(completed)[:8],
        "need": _dedupe(need)[:8],
        "plan": _dedupe(plan)[:8],
        "notes": _dedupe(notes)[:8],
    }


def build_weekly_report_context(
    project_root: str | Path,
    *,
    week: int,
    target_date: date | str | None = None,
) -> dict[str, Any]:
    activity, warnings = _recent_activity(project_root, limit=80)
    open_items, open_summary, item_warnings = _safe_open_items(project_root, limit=None)
    validation = _validation_summary(project_root)
    schedule = _schedule_context(project_root, week)
    daily_reports = _daily_report_paths(project_root, week)
    report_bullets = _daily_report_bullets(daily_reports)
    cutoff = (_parse_date(target_date) or date.today()) - timedelta(days=7)
    weekly_activity = []
    for entry in activity:
        entry_date = _parse_date(entry.get("timestamp"))
        if entry_date is None or entry_date >= cutoff:
            weekly_activity.append(entry)
    return {
        "type": "weekly",
        "target_date": _date_text(target_date),
        "week": week,
        "activity": weekly_activity,
        "activity_lines": [_activity_line(entry) for entry in weekly_activity[:15]],
        "open_items": open_items,
        "open_items_summary": open_summary,
        "validation": validation,
        "schedule": schedule,
        "daily_reports": [str(path) for path in daily_reports],
        "daily_report_bullets": report_bullets,
        "warnings": warnings + item_warnings,
    }


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        text = " ".join(str(item).split())
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def utc_week_window(today: date | None = None) -> tuple[datetime, datetime]:
    end = datetime.combine(today or date.today(), datetime.max.time(), tzinfo=timezone.utc)
    start = end - timedelta(days=7)
    return start, end
