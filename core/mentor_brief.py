from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .logging import log_tool_run, read_recent_activity
from .paths import resolve_project_paths
from .reports import list_recent_files, read_report_preview
from .result import ToolResult
from .safe_files import ensure_directory
from .analysis_common import write_timestamped_report
from .workbook_io import row_dicts


TOOL_ID = "mentor_meeting_prep"
TOOL_NAME = "Mentor Meeting Prep Tool"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _open_status(value: Any) -> bool:
    return _clean(value).lower() in {"", "open", "not started", "needs follow-up", "in progress", "blocked", "new"}


def _recent_report_bullets(folder: Path, limit: int = 8) -> list[str]:
    bullets: list[str] = []
    for path in list_recent_files(folder, limit=5):
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


def _workbook_context(project_root: str | Path) -> tuple[dict[str, Any], list[str]]:
    paths = resolve_project_paths(project_root)
    warnings: list[str] = []
    if not paths.master_workbook.exists():
        return {"actions": [], "issues": [], "pilots": []}, [f"Master workbook not found: {paths.master_workbook}"]
    try:
        actions = row_dicts(paths.master_workbook, "Action Items")
        issues = row_dicts(paths.master_workbook, "Issue Log")
        pilots = row_dicts(paths.master_workbook, "Pilot Candidates")
    except Exception as exc:
        return {"actions": [], "issues": [], "pilots": []}, [f"Could not read workbook context: {exc}"]
    return {"actions": actions, "issues": issues, "pilots": pilots}, warnings


def build_mentor_brief_markdown(
    project_root: str | Path,
    days: int = 7,
    since: str | None = None,
    notes: str = "",
) -> tuple[str, list[str], dict[str, Any]]:
    paths = resolve_project_paths(project_root)
    warnings: list[str] = []
    since_label = since or f"last {days} days"
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            since_dt = datetime.now() - timedelta(days=days)
            warnings.append(f"Could not parse since date {since}; using last {days} days.")
    else:
        since_dt = datetime.now() - timedelta(days=days)

    activity, activity_warning = read_recent_activity(project_root, limit=100)
    if activity_warning:
        warnings.append(activity_warning)
    recent_activity = []
    for entry in activity:
        stamp = _clean(entry.get("timestamp"))
        try:
            if stamp and datetime.fromisoformat(stamp.replace("Z", "+00:00")).replace(tzinfo=None) < since_dt:
                continue
        except ValueError:
            pass
        recent_activity.append(entry)

    context, context_warnings = _workbook_context(project_root)
    warnings.extend(context_warnings)
    open_actions = [row for row in context["actions"] if _open_status(row.get("Status"))]
    blockers = [row for row in open_actions if _clean(row.get("Status")).lower() == "blocked"]
    open_issues = [row for row in context["issues"] if _open_status(row.get("Status"))]
    pilot_rows = context["pilots"]
    report_bullets = _recent_report_bullets(paths.daily_reports) + _recent_report_bullets(paths.weekly_reports)

    lines = [
        "# Mentor Check-In Brief",
        "",
        f"Date: {datetime.now().date().isoformat()}",
        "",
        "## Since Last Check-In",
        f"- Window: {since_label}",
        f"- Activity log entries considered: {len(recent_activity)}",
        "",
        "## Completed Since Last Check-In",
    ]
    if recent_activity:
        lines.extend(f"- {entry.get('tool_name', 'Tool')}: {entry.get('summary', '')}" for entry in recent_activity[:10])
    elif report_bullets:
        lines.extend(f"- {bullet}" for bullet in report_bullets[:8])
    else:
        lines.append("- No recent activity entries or report bullets were found.")

    lines.extend(["", "## Current Blockers"])
    if blockers:
        lines.extend(f"- {row.get('Action Item', 'Action item')} ({row.get('Related Cell/Press', '')})" for row in blockers[:8])
    else:
        lines.append("- No blocked action items were found.")

    lines.extend(["", "## Decisions Needed"])
    lines.append("- Confirm which EOAT/cell should receive the most attention before the next check-in.")
    if open_issues:
        lines.append("- Decide which open EOAT issues should become FMEA or pilot candidate inputs.")
    if pilot_rows:
        lines.append("- Review pilot candidate shortlist and data needed before final selection.")

    lines.extend(["", "## Questions to Ask"])
    lines.extend(
        [
            "- Which cells are highest priority from production/maintenance perspective?",
            "- Are any BOM/CAD/process binder sources available that are not yet in the tracker?",
            "- Which findings should become standard PM checklist requirements?",
        ]
    )

    lines.extend(["", "## Top Issues / Risks"])
    if open_issues:
        for row in open_issues[:8]:
            lines.append(f"- {row.get('Press/Machine #', '')}: {row.get('Issue Category', 'Issue')} - {row.get('Issue Description', '')}")
    else:
        lines.append("- No open issue rows were found.")

    lines.extend(["", "## Pilot Candidates to Review"])
    if pilot_rows:
        for row in pilot_rows[:6]:
            lines.append(f"- {row.get('Press/Machine #', '')}: {row.get('Main Problem', '')} ({row.get('Approval Status', 'No status')})")
    else:
        lines.append("- No Pilot Candidates sheet rows were found yet.")

    lines.extend(["", "## Data Needed"])
    lines.extend(
        [
            "- Missing or uncertain EOAT documentation fields from audit records.",
            "- Before/after KPI baseline data for likely pilot candidates.",
            "- Verified spare part details before any standardization claim.",
        ]
    )
    if notes.strip():
        lines.extend(["", "## Manual Notes", notes.strip()])
    lines.extend(["", "## Recommended Meeting Outcomes"])
    lines.extend(
        [
            "- Agree on the next audit/data collection focus.",
            "- Confirm one or two decisions needed before the next report.",
            "- Identify the next person/source for missing EOAT documentation.",
        ]
    )
    metrics = {
        "activity_entries": len(recent_activity),
        "open_actions": len(open_actions),
        "blocked_actions": len(blockers),
        "open_issues": len(open_issues),
        "pilot_candidates": len(pilot_rows),
    }
    return "\n".join(lines) + "\n", warnings, metrics


def generate_mentor_brief(project_root: str | Path, days: int = 7, since: str | None = None, notes: str = "") -> ToolResult:
    start = time.perf_counter()
    paths = resolve_project_paths(project_root)
    ensure_directory(paths.mentor_briefs)
    markdown, warnings, metrics = build_mentor_brief_markdown(project_root, days=days, since=since, notes=notes)
    report = write_timestamped_report(paths.mentor_briefs, "Mentor_Brief", markdown)
    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Generated mentor meeting brief.",
        details=[f"Mentor brief saved to {report}."],
        warnings=warnings,
        files_created=[str(report)],
        output_reports=[str(report)],
        metrics=metrics,
        duration_seconds=time.perf_counter() - start,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result
