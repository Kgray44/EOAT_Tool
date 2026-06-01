from __future__ import annotations

import re
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .audit_progress import calculate_audit_progress
from .logging import log_tool_run
from .paths import resolve_project_paths
from .report_context import build_weekly_report_context
from .reports import read_report_preview
from .result import ToolResult
from .safe_files import ensure_directory, safe_write_text
from .schedule import load_week_schedule
from .task_progress import STATUS_VALUES

TOOL_ID = "weekly_summary"
TOOL_NAME = "Weekly Summary Generator"

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
SOURCE_PREFIX_RE = re.compile(r"^(?:[\w.-]*Week\s*\d+[_\s-]*Day\s*\d+[\w.-]*|Week\d+_Day\d+[\w.-]*):\s*", re.IGNORECASE)
NOISE_RE = re.compile(r"^(?:tool|activity|debug|trace):?$", re.IGNORECASE)
SEVERITY_ORDER = {"Critical": 0, "Error": 1, "Warning": 2, "Info": 3}
WORK_CATEGORY_ORDER = [
    "Workbook / Data Updates",
    "Reporting Automation",
    "Audit Entries",
    "Documentation",
    "Validation / Testing",
    "General Project Work",
]
WORK_CATEGORY_KEYWORDS = {
    "Audit Entries": ("audit", "eoat", "entry", "press", "machine"),
    "Workbook / Data Updates": ("workbook", "tracker", "data", "kpi", "baseline", "metric", "inventory"),
    "Reporting Automation": ("report", "summary", "automation", "scheduled", "generated"),
    "Documentation": ("document", "training", "handoff", "standard", "pm checklist", "fmea", "guideline"),
    "Validation / Testing": ("validation", "validate", "test", "pytest", "ruff", "smoke", "lint"),
}


def _week_daily_reports(folder: Path, week: int) -> list[Path]:
    if not folder.exists():
        return []
    pattern = re.compile(rf"Week\s*{week}[_\s-]*Day", re.IGNORECASE)
    return sorted([path for path in folder.glob("*.md") if pattern.search(path.stem)], key=lambda path: path.name)


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    text = text.removeprefix("- ").strip()
    text = SOURCE_PREFIX_RE.sub("", text).strip()
    text = re.sub(r"\s+", " ", text)
    if not text or NOISE_RE.fullmatch(text):
        return ""
    if re.fullmatch(r"[a-z0-9_]+", text) and "_" in text:
        return ""
    if text.casefold() in {"none", "n/a", "not available"}:
        return ""
    return text


def _activity_text(entry: dict[str, Any]) -> str:
    label = str(entry.get("tool_name") or entry.get("event_name") or entry.get("tool_id") or "Activity").strip()
    summary = str(entry.get("summary") or entry.get("message") or "").strip()
    if summary:
        return f"{label}: {summary}"
    return label


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        text = _clean_text(item)
        if not text:
            continue
        key = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _extract_bullets(paths: list[Path], limit: int = 40) -> list[str]:
    bullets: list[str] = []
    for path in paths:
        text, warning = read_report_preview(path)
        if warning:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") and len(stripped) > 3:
                bullets.append(_clean_text(f"{path.stem}: {stripped[2:]}"))
            if len(bullets) >= limit:
                return _dedupe(bullets)
    return _dedupe(bullets)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _workbook_metrics(project_root: str | Path) -> dict[str, Any]:
    try:
        summary, error = calculate_audit_progress(project_root)
    except Exception:
        return {}
    if error or summary is None:
        return {}
    data = summary.metrics
    inventory_rows = _to_int(data.get("total_eoat_inventory_rows"))
    audited = _to_int(data.get("audited_eoat_count"))
    pilot_candidates = _to_int(data.get("pilot_candidate_yes_count")) + _to_int(data.get("pilot_candidate_maybe_count"))
    completion_percent = round((audited / inventory_rows) * 100, 1) if inventory_rows else None
    return {
        "EOAT inventory rows": inventory_rows,
        "Audited EOATs": audited,
        "audit_completion_percent": completion_percent,
        "Engineering issues logged": _to_int(data.get("issues_logged_count")),
        "Interviews logged": _to_int(data.get("interviews_logged_count")),
        "Photos indexed": _to_int(data.get("photos_indexed_count")),
        "Pilot candidates flagged": pilot_candidates,
        "Assigned open action items": _to_int(data.get("open_action_items_count")),
    }


def _parse_dates_from_texts(values: list[str]) -> list[date]:
    dates: list[date] = []
    for value in values:
        for match in DATE_RE.findall(value):
            try:
                dates.append(date.fromisoformat(match))
            except ValueError:
                continue
    return dates


def _parse_target_date(value: date | str | None) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    match = DATE_RE.search(str(value))
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _format_date(value: date) -> str:
    return value.strftime("%b %d, %Y").replace(" 0", " ")


def _format_date_range(start: date, end: date) -> str:
    if start == end:
        return _format_date(start)
    if start.year == end.year and start.month == end.month:
        return f"{start.strftime('%b').replace(' 0', ' ')} {start.day}-{end.day}, {end.year}"
    return f"{_format_date(start)} - {_format_date(end)}"


def _resolve_date_range(
    week: int,
    reports: list[Path],
    context: dict[str, Any],
    target_date: date | str | None,
) -> str:
    source_dates = _parse_dates_from_texts([path.name for path in reports])
    if not source_dates:
        source_dates = _parse_dates_from_texts(
            [str(entry.get("timestamp") or "") for entry in context.get("activity", [])]
        )
    if source_dates:
        return _format_date_range(min(source_dates), max(source_dates))
    report_date = _parse_target_date(target_date)
    if report_date:
        return _format_date_range(report_date - timedelta(days=4), report_date)
    return f"Week {week}, dates not fully resolved from available source data"


def _format_generated_at(value: datetime | date | str | None) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).strftime("%Y-%m-%d %H:%M")
    if value:
        parsed_date = _parse_target_date(value)
        if parsed_date:
            return datetime.combine(parsed_date, datetime.min.time()).strftime("%Y-%m-%d %H:%M")
        return str(value)
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _project_phase(week: int) -> str:
    if week <= 2:
        return "Discovery & Audit"
    if week <= 4:
        return "Audit, Baseline Metrics, and Standards Drafting"
    if week <= 6:
        return "FMEA, PM Checklist, and Pilot Screening"
    return "Final Handoff Readiness"


def _metric(metrics: dict[str, Any], key: str) -> int | None:
    if not metrics or key not in metrics:
        return None
    return _to_int(metrics.get(key))


def _audit_progress_text(metrics: dict[str, Any]) -> str:
    inventory_rows = _metric(metrics, "EOAT inventory rows")
    audited = _metric(metrics, "Audited EOATs")
    percent = metrics.get("audit_completion_percent") if metrics else None
    if inventory_rows is None or audited is None:
        return "Audited EOATs: not available"
    if inventory_rows <= 0 or percent is None:
        return f"Audited EOATs: {audited} / {inventory_rows} (not available)"
    return f"Audited EOATs: {audited} / {inventory_rows} ({percent:.1f}%)"


def _progress_snapshot(metrics: dict[str, Any], open_summary: dict[str, Any]) -> list[str]:
    return [
        f"EOAT inventory rows: {metrics.get('EOAT inventory rows', 'not available') if metrics else 'not available'}",
        _audit_progress_text(metrics),
        f"Engineering issues logged: {metrics.get('Engineering issues logged', 'not available') if metrics else 'not available'}",
        f"Assigned open action items: {metrics.get('Assigned open action items', 'not available') if metrics else 'not available'}",
        f"Data quality follow-ups: {_to_int(open_summary.get('total_open_items'))} open",
        f"Critical data conflicts: {_to_int(open_summary.get('data_conflict_count'))}",
        f"Photos indexed: {metrics.get('Photos indexed', 'not available') if metrics else 'not available'}",
        f"Pilot candidates flagged: {metrics.get('Pilot candidates flagged', 'not available') if metrics else 'not available'}",
    ]


def _task_progress_lines(schedule_context: dict[str, Any]) -> list[str]:
    status_counts = schedule_context.get("status_counts") or {status: 0 for status in STATUS_VALUES}
    total_tasks = sum(_to_int(status_counts.get(status)) for status in STATUS_VALUES)
    if total_tasks == 0:
        return ["Task progress data was not available for this summary."]
    lines = [f"Total tasks: {total_tasks}"]
    lines.extend(f"{status}: {_to_int(status_counts.get(status))}" for status in STATUS_VALUES)
    return lines


def _completed_work_items(
    schedule_context: dict[str, Any],
    report_bullets: list[str],
    activity: list[dict[str, Any]],
) -> tuple[list[str], int]:
    raw_items: list[str] = []
    raw_items.extend(
        str(task.get("description") or task.get("task") or "") for task in schedule_context.get("completed_tasks", [])
    )
    raw_items.extend(item for item in report_bullets if _looks_like_completed_work(item))
    for entry in activity:
        if entry.get("success") is False:
            continue
        raw_items.append(_activity_text(entry))
    cleaned = _dedupe(raw_items)
    filtered_count = len(raw_items) - len(cleaned)
    return cleaned, max(filtered_count, 0)


def _looks_like_completed_work(value: str) -> bool:
    text = _clean_text(value).casefold()
    if not text:
        return False
    return not text.startswith(("blocker:", "blocked:", "risk:", "warning:", "missing ", "needs "))


def _categorize_work(items: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {category: [] for category in WORK_CATEGORY_ORDER}
    for item in items:
        text = item.casefold()
        category = "General Project Work"
        for candidate, keywords in WORK_CATEGORY_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                category = candidate
                break
        grouped[category].append(item)
    return {category: grouped[category] for category in WORK_CATEGORY_ORDER if grouped[category]}


def _work_completed_lines(grouped_work: dict[str, list[str]]) -> list[str]:
    if not grouped_work:
        return ["- No completed-work entries were found in the available sources."]
    lines: list[str] = []
    for category, items in grouped_work.items():
        lines.extend([f"### {category}", ""])
        lines.extend(f"- {item}" for item in items[:8])
        if len(items) > 8:
            lines.append(f"- Additional {category.lower()} items: {len(items) - 8}")
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _severity_label(value: Any) -> str:
    text = str(value or "Info").strip().title()
    if text in {"Critical", "Error", "Warning", "Info"}:
        return text
    return "Info"


def _category_label(value: Any) -> str:
    text = str(value or "follow_up").strip().replace("_", " ")
    return text.title() if text else "Follow Up"


def _followup_label(item: dict[str, Any]) -> str:
    category = str(item.get("category") or "").strip()
    title = _clean_text(item.get("title") or item.get("message") or "Open follow-up")
    if category == "missing_evidence":
        match = re.search(r"missing evidence:\s*(.+)", title, re.IGNORECASE)
        evidence_area = match.group(1).strip() if match else title
        return f"Missing evidence: {evidence_area}"
    if category == "data_conflict":
        return f"Data conflict: {title}"
    if category:
        return f"{_category_label(category)}: {title}"
    return title


def _group_followups(open_items: list[dict[str, Any]]) -> dict[str, Counter[str]]:
    grouped: dict[str, Counter[str]] = {}
    for item in open_items:
        status = str(item.get("status") or "Open")
        if status not in {"Open", "In Progress", "Waiting on Info", "Blocked"}:
            continue
        severity = _severity_label(item.get("severity"))
        label = _followup_label(item)
        grouped.setdefault(severity, Counter())[label] += 1
    return grouped


def _open_followup_lines(open_items: list[dict[str, Any]], open_summary: dict[str, Any]) -> tuple[list[str], int]:
    total_open = _to_int(open_summary.get("total_open_items"), len(open_items))
    grouped = _group_followups(open_items)
    if not grouped:
        if total_open:
            return [f"- Total open follow-ups: {total_open}", "- Detailed follow-up rows were not available."], 0
        return ["- No open follow-up records were available."], 0
    lines = [f"- Total open follow-ups: {total_open}"]
    group_count = 0
    for severity in sorted(grouped, key=lambda value: SEVERITY_ORDER.get(value, 99)):
        counter = grouped[severity]
        lines.extend(["", f"### {severity}", ""])
        ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0].casefold()))
        for label, count in ranked[:8]:
            noun = "entry" if count == 1 else "entries"
            lines.append(f"- {label}: {count} open {noun}")
            group_count += 1
        if len(ranked) > 8:
            lines.append(f"- Additional {severity.lower()} categories: {len(ranked) - 8}")
    return lines, group_count


def _top_missing_evidence(open_items: list[dict[str, Any]], limit: int = 2) -> list[str]:
    missing = Counter()
    for item in open_items:
        if item.get("category") == "missing_evidence":
            missing[_followup_label(item).removeprefix("Missing evidence: ").strip()] += 1
    return [
        f"{label} ({count})" for label, count in sorted(missing.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _validation_lines(validation: dict[str, Any]) -> list[str]:
    if not validation.get("available"):
        return [
            "- Workbook validation output was not available. Run workbook validation before using this report for readiness/release claims."
        ]
    counts = {str(key).title(): _to_int(value) for key, value in (validation.get("counts") or {}).items()}
    passed = counts.get("Pass", counts.get("Passed", 0))
    warnings = counts.get("Warning", 0)
    errors = counts.get("Error", 0)
    critical = counts.get("Critical", 0) + counts.get("Blocker", 0)
    lines = [
        f"- Passed checks: {passed}",
        f"- Warnings: {warnings}",
        f"- Errors: {errors}",
        f"- Critical issues: {critical}",
    ]
    if validation.get("path"):
        lines.append(f"- Validation report file: {validation['path']}")
    findings = validation.get("findings") or []
    for finding in findings[:3]:
        severity = _severity_label(finding.get("severity"))
        message = _clean_text(finding.get("message") or finding.get("summary"))
        if message:
            lines.append(f"- {severity}: {message}")
    return lines


def _issue_risk_lines(
    schedule_context: dict[str, Any],
    metrics: dict[str, Any],
    open_summary: dict[str, Any],
    validation: dict[str, Any],
    open_items: list[dict[str, Any]],
    warnings: list[str],
) -> list[str]:
    lines: list[str] = []
    blocked_tasks = schedule_context.get("blocked_tasks") or []
    lines.extend(f"- Blocked schedule task: {task.get('description')}" for task in blocked_tasks[:5])
    data_conflicts = _to_int(open_summary.get("data_conflict_count"))
    missing_evidence = _to_int(open_summary.get("missing_evidence_count"))
    if data_conflicts:
        lines.append(f"- Critical data conflicts remain open: {data_conflicts}")
    if not validation.get("available"):
        lines.append("- Workbook validation output is missing, so readiness/release claims need validation before use.")
    if missing_evidence:
        top_missing = ", ".join(_top_missing_evidence(open_items)) or f"{missing_evidence} open entries"
        lines.append(f"- Evidence collection gaps remain, especially {top_missing}.")
    if _metric(metrics, "Photos indexed") == 0:
        lines.append(
            "- No photos are indexed yet; photo evidence should be collected or linked before readiness claims."
        )
    if _metric(metrics, "Pilot candidates flagged") == 0:
        lines.append("- No pilot candidates are flagged yet; candidate screening still needs confirmation.")
    for warning in _dedupe(warnings)[:3]:
        lines.append(f"- {warning}")
    if not lines:
        return ["- No major schedule blockers were found. Data quality follow-ups remain open."]
    return _dedupe(lines)


def _key_observation_lines(
    metrics: dict[str, Any],
    open_summary: dict[str, Any],
    validation: dict[str, Any],
    open_items: list[dict[str, Any]],
    daily_report_count: int,
) -> list[str]:
    lines: list[str] = []
    if metrics:
        lines.append(f"- {_audit_progress_text(metrics)}.")
    if daily_report_count:
        lines.append(f"- {daily_report_count} daily report source(s) were referenced for this weekly summary.")
    missing_evidence = _to_int(open_summary.get("missing_evidence_count"))
    if missing_evidence:
        top_missing = ", ".join(_top_missing_evidence(open_items)) or f"{missing_evidence} open entries"
        lines.append(f"- Evidence collection gaps are concentrated in {top_missing}.")
    data_conflicts = _to_int(open_summary.get("data_conflict_count"))
    if data_conflicts:
        lines.append(f"- Data conflict follow-ups need correction or an explicit override decision: {data_conflicts}.")
    if validation.get("available"):
        counts = validation.get("counts") or {}
        lines.append(
            "- Workbook validation data was available "
            f"({', '.join(f'{key}: {value}' for key, value in sorted(counts.items())) or 'no findings counted'})."
        )
    else:
        lines.append("- Workbook validation output was not available for this weekly report.")
    if not lines:
        return ["- No additional observations beyond completed work and open follow-ups."]
    return _dedupe(lines)


def _executive_summary(
    week: int,
    grouped_work: dict[str, list[str]],
    metrics: dict[str, Any],
    open_summary: dict[str, Any],
    validation: dict[str, Any],
    open_items: list[dict[str, Any]],
) -> str:
    categories = list(grouped_work)[:3]
    if categories:
        work_text = "work centered on " + ", ".join(category.lower() for category in categories)
    else:
        work_text = "available sources did not show completed-work entries"
    audit_text = _audit_progress_text(metrics).removeprefix("Audited EOATs: ")
    gaps: list[str] = []
    missing = _to_int(open_summary.get("missing_evidence_count"))
    conflicts = _to_int(open_summary.get("data_conflict_count"))
    if missing:
        top_missing = ", ".join(_top_missing_evidence(open_items)) or f"{missing} missing-evidence follow-ups"
        gaps.append(f"missing evidence in {top_missing}")
    if conflicts:
        gaps.append(f"{conflicts} data conflict(s)")
    if not validation.get("available"):
        gaps.append("missing workbook validation output")
    gap_text = "; ".join(gaps) if gaps else "no major schedule blockers in the available data"
    return (
        f"During Week {week}, {work_text}. Audit progress reached {audit_text}. "
        f"Current risks or data gaps include {gap_text}. Next focus should be continued audit progress, "
        "evidence cleanup, validation output, and confirmation of supervisor priorities."
    )


def _data_files_updated(activity: list[dict[str, Any]]) -> list[str]:
    files: list[str] = []
    for entry in activity:
        for key in ("files_modified", "files_created"):
            for value in entry.get(key, []) or []:
                name = Path(str(value)).name
                if name and name.lower().endswith((".xlsx", ".json", ".csv")):
                    files.append(name)
    return sorted(_dedupe(files), key=str.casefold)[:12]


def _as_bullets(items: list[str]) -> list[str]:
    lines: list[str] = []
    for item in items:
        text = _clean_text(item)
        if text:
            lines.append(f"- {text}")
    return lines


def _decisions_needed(metrics: dict[str, Any], open_summary: dict[str, Any]) -> list[str]:
    decisions = ["Confirm next audit targets, machines, and EOATs for the next work period."]
    if _to_int(open_summary.get("missing_evidence_count")):
        decisions.append(
            "Confirm how missing evidence should be handled: collect, link existing photos, or document why unavailable."
        )
    if _to_int(open_summary.get("data_conflict_count")):
        decisions.append(
            "Confirm whether critical data conflicts should be corrected manually or through the tool workflow."
        )
    if _metric(metrics, "Photos indexed") == 0:
        decisions.append("Confirm whether photos need to be indexed before the next weekly report.")
    decisions.append("Confirm the next priority for FMEA preparation and pilot candidate screening.")
    return decisions


def _next_week_plan(
    metrics: dict[str, Any], open_summary: dict[str, Any], schedule_context: dict[str, Any]
) -> list[str]:
    lines: list[str] = []
    for task in (schedule_context.get("open_tasks") or [])[:3]:
        lines.append(f"Continue scheduled task: {task.get('description')} ({task.get('status')}).")
    audited = _metric(metrics, "Audited EOATs")
    inventory = _metric(metrics, "EOAT inventory rows")
    if audited is not None and inventory is not None and inventory > audited:
        lines.append(f"Continue EOAT audits and increase audited count beyond {audited} / {inventory}.")
    else:
        lines.append("Continue EOAT audits and confirm the next measurable audit target.")
    if _to_int(open_summary.get("missing_evidence_count")):
        lines.append("Resolve or triage the largest missing-evidence follow-up groups.")
    lines.append("Run workbook validation and include the output in the next weekly report.")
    lines.append("Begin identifying recurring issue categories for future FMEA work.")
    if _metric(metrics, "Photos indexed") == 0:
        lines.append("Start collecting or indexing photos where evidence gaps exist.")
    lines.append("Confirm mentor or supervisor priorities before expanding the next work batch.")
    return _dedupe(lines)[:8]


def build_weekly_summary_markdown(
    project_root: str | Path,
    week: int,
    notes: str = "",
    *,
    target_date: date | str | None = None,
    generated_at: datetime | date | str | None = None,
) -> tuple[str, list[str], dict[str, Any]]:
    paths = resolve_project_paths(project_root)
    warnings: list[str] = []
    reports = _week_daily_reports(paths.daily_reports, week)
    if not reports:
        warnings.append(f"No daily Markdown reports found for Week {week}.")
    report_bullets = _extract_bullets(reports)
    schedule = load_week_schedule(project_root, week)
    metrics = _workbook_metrics(project_root)
    context = build_weekly_report_context(project_root, week=week, target_date=target_date)
    warnings.extend(context.get("warnings", []))
    schedule_context = context.get("schedule") or {}
    schedule_context.setdefault("status_counts", schedule.status_counts or {status: 0 for status in STATUS_VALUES})
    schedule_context.setdefault(
        "open_tasks",
        [
            {"description": task.description, "status": task.status}
            for task in schedule.tasks
            if task.status in {"Not started", "In progress", "Blocked"}
        ],
    )
    schedule_context.setdefault(
        "blocked_tasks",
        [
            {"description": task.description, "status": task.status}
            for task in schedule.tasks
            if task.status == "Blocked"
        ],
    )
    schedule_context.setdefault(
        "completed_tasks",
        [
            {"description": task.description, "status": task.status}
            for task in schedule.tasks
            if task.status == "Complete"
        ],
    )
    context_bullets = [_clean_text(value) for value in context.get("daily_report_bullets", [])]
    all_report_bullets = _dedupe([*report_bullets, *context_bullets])
    open_summary = context.get("open_items_summary") or {}
    open_items = context.get("open_items") or []
    validation = context.get("validation") or {}
    activity = context.get("activity") or []
    completed_items, filtered_activity_count = _completed_work_items(schedule_context, all_report_bullets, activity)
    grouped_work = _categorize_work(completed_items)
    followup_lines, followup_group_count = _open_followup_lines(open_items, open_summary)
    source_report_names = sorted(
        {Path(path).name for path in context.get("daily_reports", [])} | {path.name for path in reports}
    )
    data_files = _data_files_updated(activity)

    lines = [
        f"# Week {week} EOAT Project Summary",
        "",
        f"**Date Range:** {_resolve_date_range(week, reports, context, target_date)}",
        f"**Project Phase:** {_project_phase(week)}",
        f"**Generated:** {_format_generated_at(generated_at)}",
        "**Evidence Sources:** Daily reports, activity logs, workbook metrics, task progress, follow-ups, and validation output where available",
        "",
        "## Executive Summary",
        "",
        _executive_summary(week, grouped_work, metrics, open_summary, validation, open_items),
        "",
        "## Progress Snapshot",
        "",
    ]
    lines.extend(f"- {line}" for line in _progress_snapshot(metrics, open_summary))
    lines.extend(["", "## Task Progress", ""])
    lines.extend(f"- {line}" for line in _task_progress_lines(schedule_context))
    lines.extend(["", "## Work Completed", ""])
    lines.extend(_work_completed_lines(grouped_work))
    lines.extend(["", "## Key Observations", ""])
    lines.extend(
        _as_bullets(_key_observation_lines(metrics, open_summary, validation, open_items, len(source_report_names)))
    )
    lines.extend(["", "## Issues, Risks, and Data Gaps", ""])
    lines.extend(
        _as_bullets(_issue_risk_lines(schedule_context, metrics, open_summary, validation, open_items, warnings))
    )
    lines.extend(["", "## Open Follow-Ups", ""])
    lines.extend(followup_lines)
    lines.extend(["", "## Validation Signals", ""])
    lines.extend(_as_bullets(_validation_lines(validation)))
    lines.extend(["", "## Reports and Files", "", "### Created This Week", ""])
    lines.append(f"- Week {week} summary generated by this run.")
    lines.extend(["", "### Source Reports Referenced", ""])
    if source_report_names:
        lines.extend(f"- {name}" for name in source_report_names)
    else:
        lines.append("- No daily source reports were available for this week.")
    lines.extend(["", "### Data Files Updated", ""])
    if data_files:
        lines.extend(f"- {name}" for name in data_files)
    else:
        lines.append("- No updated data files were identified from activity logs.")
    lines.extend(["", "## Decisions Needed", ""])
    lines.extend(f"- {line}" for line in _decisions_needed(metrics, open_summary))
    lines.extend(["", "## Next Week Plan", ""])
    lines.extend(f"- {line}" for line in _next_week_plan(metrics, open_summary, schedule_context))
    lines.extend(["", "## Notes", ""])
    lines.append(
        "- Evidence basis: daily reports, activity logs, task progress, workbook metrics, open follow-ups, and validation output where available."
    )
    lines.append("- Do not claim production impact from audit metrics alone.")
    if not validation.get("available"):
        lines.append("- Do not claim release readiness without workbook validation output.")
    lines.append("- Estimated or subjective values must remain labeled in their source reports.")
    if notes.strip():
        lines.append(f"- Manual note: {notes.strip()}")

    output_metrics = {
        "daily_reports_found": len(reports),
        "activity_entries_considered": len(activity),
        "activity_lines_filtered_or_deduped": filtered_activity_count,
        "open_or_carryover_tasks": len(schedule_context.get("open_tasks") or []),
        "open_items_considered": len(open_items),
        "open_followup_groups": followup_group_count,
        "validation_json_available": bool(validation.get("available")),
        **metrics,
    }
    return "\n".join(lines).rstrip() + "\n", warnings, output_metrics


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
    output_folder = (
        Path(output_dir).expanduser()
        if output_dir
        else (paths.project_admin / "Test_Reports" / "Weekly_Status_Reports" if dry_run else paths.weekly_reports)
    )
    ensure_directory(output_folder)
    if isinstance(report_date, date):
        date_text = report_date.isoformat()
    elif report_date:
        date_text = str(report_date)
    else:
        date_text = time.strftime("%Y-%m-%d")
    markdown, warnings, metrics = build_weekly_summary_markdown(
        project_root,
        week,
        notes,
        target_date=report_date,
        generated_at=datetime.now(),
    )
    if dry_run:
        markdown = (
            "> DRY RUN / TEST OUTPUT: This weekly summary was generated by the automation test harness. "
            "It did not write to the normal weekly report folder.\n\n" + markdown
        )
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
