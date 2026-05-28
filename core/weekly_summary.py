from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path
from typing import Any

from .audit_progress import calculate_audit_progress
from .logging import log_tool_run, read_recent_activity
from .paths import resolve_project_paths
from .report_context import build_weekly_report_context
from .reports import list_recent_files, read_report_preview
from .result import ToolResult
from .safe_files import ensure_directory, safe_write_text
from .schedule import load_week_schedule
from .task_progress import STATUS_VALUES


TOOL_ID = "weekly_summary"
TOOL_NAME = "Weekly Summary Generator"


def _week_daily_reports(folder: Path, week: int) -> list[Path]:
    if not folder.exists():
        return []
    pattern = re.compile(rf"Week\s*{week}[_\s-]*Day", re.IGNORECASE)
    return sorted(
        [path for path in folder.glob("*.md") if pattern.search(path.stem)],
        key=lambda path: path.stat().st_mtime,
    )


def _extract_bullets(paths: list[Path], limit: int = 12) -> list[str]:
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


def _workbook_metrics(project_root: str | Path) -> dict[str, Any]:
    try:
        summary, error = calculate_audit_progress(project_root)
    except Exception:
        return {}
    if error or summary is None:
        return {}
    data = summary
    return {
        "EOAT inventory rows": data.metrics.get("total_eoat_inventory_rows", 0),
        "Audited EOATs": data.metrics.get("audited_eoat_count", 0),
        "Issues logged": data.metrics.get("issues_logged_count", 0),
        "Interviews logged": data.metrics.get("interviews_logged_count", 0),
        "Photos indexed": data.metrics.get("photos_indexed_count", 0),
        "Pilot candidates flagged": data.metrics.get("pilot_candidate_yes_count", 0) + data.metrics.get("pilot_candidate_maybe_count", 0),
        "Open action items": data.metrics.get("open_action_items_count", 0),
    }


def build_weekly_summary_markdown(
    project_root: str | Path,
    week: int,
    notes: str = "",
) -> tuple[str, list[str], dict[str, Any]]:
    paths = resolve_project_paths(project_root)
    warnings: list[str] = []
    reports = _week_daily_reports(paths.daily_reports, week)
    if not reports:
        warnings.append(f"No daily Markdown reports found for Week {week}.")
    bullets = _extract_bullets(reports)
    schedule = load_week_schedule(project_root, week)
    metrics = _workbook_metrics(project_root)
    context = build_weekly_report_context(project_root, week=week)
    warnings.extend(context.get("warnings", []))
    activity, activity_warning = read_recent_activity(project_root, limit=50)
    if activity_warning:
        warnings.append(activity_warning)
    recent_files = list_recent_files(paths.daily_reports, limit=10)
    status_counts = schedule.status_counts or {status: 0 for status in STATUS_VALUES}
    open_tasks = [task for task in schedule.tasks if task.status in {"Not started", "In progress", "Blocked"}]
    completed_tasks = [task for task in schedule.tasks if task.status == "Complete"]

    lines = [
        f"# Week {week} EOAT Project Summary",
        "",
        "## Date Range",
        "Use the project schedule as the source of truth for exact workdays.",
        "",
        "## Executive Summary",
        f"Week {week} summary generated from daily reports, activity logs, task progress, and workbook metrics where available.",
        "",
        "## Work Completed",
    ]
    if completed_tasks:
        lines.extend(f"- {task.description}" for task in completed_tasks[:12])
    elif bullets:
        lines.extend(f"- {bullet}" for bullet in bullets[:12])
    else:
        lines.append("- No completed-work entries were found yet.")

    lines.extend(["", "## Audit/Data Progress"])
    if metrics:
        lines.extend(f"- {key}: {value}" for key, value in metrics.items())
    else:
        lines.append("- Workbook metrics were unavailable.")

    lines.extend(["", "## Task Progress"])
    lines.extend(f"- {status}: {status_counts.get(status, 0)}" for status in STATUS_VALUES)

    lines.extend(["", "## Key Observations"])
    if bullets:
        lines.extend(f"- {bullet}" for bullet in bullets[:8])
    elif context.get("daily_report_bullets"):
        lines.extend(f"- {bullet}" for bullet in context["daily_report_bullets"][:8])
    else:
        lines.append("- No daily-report observations were found yet.")

    lines.extend(["", "## Issues/Risks"])
    blocked = [task for task in schedule.tasks if task.status == "Blocked"]
    if blocked:
        lines.extend(f"- Blocked: {task.description}" for task in blocked[:8])
    else:
        lines.append("- No blocked schedule tasks were found.")

    lines.extend(["", "## Blockers and Data Gaps"])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- No major missing inputs were detected for this weekly summary.")

    open_summary = context.get("open_items_summary") or {}
    open_items = context.get("open_items") or []
    lines.extend(["", "## Open Items / Follow-Ups"])
    if open_items:
        if open_summary:
            lines.append(
                "- Summary: "
                f"{open_summary.get('total_open_items', 0)} open, "
                f"{open_summary.get('blocked_items', 0)} blocked, "
                f"{open_summary.get('overdue_followups', 0)} overdue follow-up(s)."
            )
        for item in open_items[:10]:
            lines.append(f"- {item.get('severity', 'INFO')}: {item.get('title')} ({item.get('status', 'Open')})")
    else:
        lines.append("- No open item records were available.")

    validation = context.get("validation") or {}
    lines.extend(["", "## Validation Signals"])
    if validation.get("available"):
        counts = validation.get("counts") or {}
        count_text = ", ".join(f"{key}: {value}" for key, value in counts.items() if value) or "no findings counted"
        lines.append(f"- Latest validation JSON: {count_text}.")
        findings = validation.get("findings") or []
        for finding in findings[:5]:
            lines.append(f"- {finding.get('severity', 'WARNING')}: {finding.get('message', '')}")
    else:
        lines.append("- No JSON workbook validation output was available.")

    lines.extend(["", "## Reports/Files Created"])
    if recent_files:
        lines.extend(f"- {path.name}" for path in recent_files[:10])
    else:
        lines.append("- No recent daily report files found.")

    lines.extend(["", "## Decisions Needed"])
    lines.append("- Confirm next week priorities, data collection targets, and any cells needing mentor review.")

    lines.extend(["", "## Next Week Plan"])
    if open_tasks:
        lines.extend(f"- {task.description} ({task.status})" for task in open_tasks[:10])
    else:
        lines.append("- Continue with the next project schedule items.")

    if notes.strip():
        lines.extend(["", "## Notes", notes.strip()])

    lines.extend(["", "## Activity Log Signals"])
    if activity:
        lines.extend(f"- {entry.get('tool_name', 'Tool')}: {entry.get('summary', '')}" for entry in activity[:10])
    elif context.get("activity_lines"):
        lines.extend(f"- {line}" for line in context["activity_lines"][:10])
    else:
        lines.append("- No activity log entries were found.")

    output_metrics = {
        "daily_reports_found": len(reports),
        "activity_entries_considered": len(activity),
        "open_or_carryover_tasks": len(open_tasks),
        "open_items_considered": len(open_items),
        "validation_json_available": bool(validation.get("available")),
        **metrics,
    }
    return "\n".join(lines) + "\n", warnings, output_metrics


def generate_weekly_summary(
    project_root: str | Path,
    week: int,
    notes: str = "",
    *,
    scheduled: bool = False,
    output_dir: str | Path | None = None,
    report_date: date | str | None = None,
    dry_run: bool = False,
) -> ToolResult:
    start = time.perf_counter()
    paths = resolve_project_paths(project_root)
    output_folder = Path(output_dir).expanduser() if output_dir else (paths.project_admin / "Test_Reports" / "Weekly_Status_Reports" if dry_run else paths.weekly_reports)
    ensure_directory(output_folder)
    markdown, warnings, metrics = build_weekly_summary_markdown(project_root, week, notes)
    if dry_run:
        markdown = (
            "> DRY RUN / TEST OUTPUT: This weekly summary was generated by the automation test harness. "
            "It did not write to the normal weekly report folder.\n\n"
            + markdown
        )
    if isinstance(report_date, date):
        date_text = report_date.isoformat()
    elif report_date:
        date_text = str(report_date)
    else:
        date_text = time.strftime("%Y-%m-%d")
    suffix = "_DRY_RUN" if dry_run else ""
    path = output_folder / f"Week{week}_Summary_{date_text}{suffix}.md"
    if path.exists():
        if scheduled or dry_run:
            result = ToolResult.ok(
                TOOL_ID,
                TOOL_NAME,
                "Weekly summary already exists; no duplicate report was created.",
                details=[f"Existing weekly summary: {path}."],
                warnings=warnings,
                output_reports=[str(path)],
                metrics={**metrics, "scheduled": scheduled, "dry_run": dry_run, "skipped_duplicate": True},
                duration_seconds=time.perf_counter() - start,
            )
            warning = log_tool_run(result, project_root)
            if warning:
                result.warnings.append(warning)
            return result
        path = output_folder / f"Week{week}_Summary_{time.strftime('%Y-%m-%d_%H%M%S')}.md"
    path = safe_write_text(path, markdown, overwrite=False)
    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        f"Generated Week {week} summary.",
        details=[f"Weekly summary saved to {path}."],
        warnings=warnings,
        files_created=[str(path)],
        output_reports=[str(path)],
        metrics={**metrics, "scheduled": scheduled, "dry_run": dry_run},
        duration_seconds=time.perf_counter() - start,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result
