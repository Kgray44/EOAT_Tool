from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .audit_progress import calculate_audit_progress
from .documentation_gaps import scan_documentation_gaps
from .kpi_analysis import analyze_kpis
from .logging import log_tool_run
from .morning_context import MorningPlanningContext, collect_morning_planning_context, detect_generic_morning_report
from .paths import resolve_project_paths
from .reports import list_recent_files, read_report_preview
from .result import ToolResult
from .safe_files import ensure_directory, safe_write_text
from .schedule import ProjectDay, load_week_schedule, resolve_project_day_for_project
from .task_progress import TaskItem
from .validation import validate_project_foundation
from .workbook_io import row_dicts

TOOL_ID = "morning_planner"
TOOL_NAME = "Daily What Should I Work On? Morning Planner"
DONE_STATUSES = {"complete", "skipped"}
CARRYOVER_STATUSES = {"not started", "in progress"}
DETAIL_LEVELS = {"todo", "summary", "debug"}


@dataclass(frozen=True)
class ReducedMorningPlan:
    mission: str
    do_first: str
    main_todo: list[str]
    ask_today: list[str]
    if_blocked: list[str]
    done_when: list[str]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _status_key(value: str) -> str:
    return _clean(value).lower()


def _task_day_int(task: TaskItem) -> int | None:
    try:
        return int(str(task.day).strip())
    except (TypeError, ValueError):
        return None


def _unfinished(task: TaskItem) -> bool:
    return _status_key(task.status) not in DONE_STATUSES


def _format_task(task: TaskItem) -> str:
    task_id = f" ({task.id})" if task.id else ""
    return f"- [{task.status}] {task.description}{task_id}"


def _task_text(task: TaskItem) -> str:
    return _clean(task.description).rstrip(".")


def _dedupe_lines(lines: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        cleaned = _clean(line).rstrip(".")
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned = cleaned[0].upper() + cleaned[1:] if cleaned else cleaned
        output.append(cleaned + ".")
        if len(output) >= limit:
            break
    return output


def _dedupe_questions(lines: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        cleaned = _clean(line).rstrip(".")
        if not cleaned:
            continue
        if not cleaned.endswith("?"):
            cleaned += "?"
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
        if len(output) >= limit:
            break
    return output


def _task_action(task: TaskItem) -> str:
    text = _task_text(task)
    lowered = text.lower()
    if "target" in lowered and "cell" in lowered:
        return "start the target-cell list and flag the cells that need mentor or supervisor confirmation"
    if "photo" in lowered and ("naming" in lowered or "format" in lowered or "system" in lowered):
        return "decide the photo naming format before more evidence gets collected"
    if "photo" in lowered:
        return "organize photo intake so new evidence is named, tagged, and easy to trace later"
    if "question" in lowered or "mentor" in lowered or "maintenance" in lowered or "supervisor" in lowered:
        if "confirm" in lowered and ("priorit" in lowered or "mentor" in lowered or "supervisor" in lowered):
            return "confirm initial audit priorities with mentor or supervisor"
        return "capture the priority questions while the right people are available"
    if "walkthrough" in lowered or "audit" in lowered:
        if "approved" in lowered or "approval" in lowered:
            return "confirm the first safe walkthrough or audit target, then start the audit entry if access is approved"
        return f"make progress on {text[0].lower() + text[1:] if text else 'the audit work'}"
    if "validation" in lowered or "validate" in lowered:
        return "run workbook validation after any audit or template changes"
    if "documentation" in lowered or "bom" in lowered or "cad" in lowered or "binder" in lowered:
        return "check which documentation sources are available and which gaps need follow-up"
    return f"advance {text[0].lower() + text[1:]}" if text else ""


def _task_done_outcome(task: TaskItem) -> str:
    text = _task_text(task)
    lowered = text.lower()
    if "target" in lowered and "cell" in lowered:
        return "Initial target-cell list started, with unclear priorities marked for follow-up"
    if "photo" in lowered and ("naming" in lowered or "format" in lowered or "system" in lowered):
        return "Photo naming format decided or the open naming question recorded"
    if "photo" in lowered:
        return "Available photos imported/indexed, or photo access clearly blocked"
    if "walkthrough" in lowered or "audit" in lowered:
        return "First walkthrough/audit task completed or clearly blocked with the reason recorded"
    if "validation" in lowered or "validate" in lowered:
        return "Workbook validation run after changes, or validation blocker documented"
    if "question" in lowered:
        return "Priority questions written down with owners or next chances to ask"
    return f"{text} completed or clearly blocked"


def _phrase_list(items: list[str]) -> str:
    cleaned = [item for item in (_clean(value).rstrip(".") for value in items) if item]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def _open_actions(project_root: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return [], [f"Master workbook not found: {paths.master_workbook}"]
    try:
        rows = row_dicts(paths.master_workbook, "Action Items")
    except Exception as exc:
        return [], [f"Could not read Action Items: {exc}"]
    open_statuses = {"", "open", "not started", "needs follow-up", "in progress", "blocked", "new"}
    return [row for row in rows if _clean(row.get("Status")).lower() in open_statuses], []


def _previous_daily_report(paths, week: int, day: int) -> Path | None:
    target_week = week
    target_day = day - 1
    if target_day < 1 and week > 1:
        target_week = week - 1
        target_day = 5
    reports = list_recent_files(paths.daily_reports, limit=30)
    if target_day >= 1:
        for report in reports:
            if f"Week{target_week}_Day{target_day}" in report.stem:
                return report
    return reports[0] if reports else None


def _phase_for_week(week: int) -> tuple[str, str]:
    if 1 <= week <= 3:
        return "Discovery", "audit setup, EOAT data capture, photos, interviews, target-cell selection, and workbook validation"
    if 4 <= week <= 6:
        return "Analysis", "issue analysis, FMEA-lite, documentation gaps, and pilot-candidate selection"
    if 7 <= week <= 10:
        return "Implementation", "pilot work, before/after KPI tracking, PM/BOM updates, and validation"
    return "Wrap-up", "final deliverables, handoff package, presentation assets, and final report"


def _unique_tasks(tasks: list[TaskItem]) -> list[TaskItem]:
    seen: set[str] = set()
    unique: list[TaskItem] = []
    for task in tasks:
        key = f"{task.id}|{task.description}".lower()
        if key not in seen and task.description:
            seen.add(key)
            unique.append(task)
    return unique


def _scheduled_tasks_for_day(schedule, day: int) -> list[TaskItem]:
    progress_tasks = [task for task in schedule.tasks if _task_day_int(task) == day]
    known_descriptions = {_clean(task.description).lower() for task in progress_tasks}
    schedule_only: list[TaskItem] = []
    for index, description in enumerate(schedule.days.get(str(day), []), start=1):
        if _clean(description).lower() not in known_descriptions:
            schedule_only.append(TaskItem(id=f"W{schedule.week}D{day}S{index}", description=_clean(description), day=str(day), status="Not started"))
    return _unique_tasks(progress_tasks + schedule_only)


def _collect_project_state(project_root: str | Path) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    state: dict[str, Any] = {
        "audited_eoat_count": "not available",
        "photos_indexed_count": "not available",
        "interviews_logged_count": "not available",
        "issues_logged_count": "not available",
        "documentation_gaps": "not available",
        "kpi_rows": "not available",
        "pilot_candidates": "not available",
        "workbook_health_ok": "not available",
    }
    audit_summary, audit_error = calculate_audit_progress(project_root)
    if audit_summary:
        metrics = audit_summary.metrics
        state.update(
            {
                "audited_eoat_count": metrics.get("audited_eoat_count", 0),
                "photos_indexed_count": metrics.get("photos_indexed_count", 0),
                "interviews_logged_count": metrics.get("interviews_logged_count", 0),
                "issues_logged_count": metrics.get("issues_logged_count", 0),
                "pilot_candidates": metrics.get("pilot_candidate_yes_count", 0) + metrics.get("pilot_candidate_maybe_count", 0),
                "open_action_items_count": metrics.get("open_action_items_count", 0),
            }
        )
    elif audit_error:
        warnings.extend(audit_error.errors or [audit_error.summary])

    doc_summary, doc_error = scan_documentation_gaps(project_root)
    if doc_summary:
        state["documentation_gaps"] = doc_summary.metrics.get("total_gaps", 0)
    elif doc_error:
        warnings.extend(doc_error.errors or [doc_error.summary])

    kpi_summary, kpi_error = analyze_kpis(project_root)
    if kpi_summary:
        state["kpi_rows"] = kpi_summary.metrics.get("kpi_rows", 0)
    elif kpi_error:
        warnings.extend(kpi_error.errors or [kpi_error.summary])

    validation = validate_project_foundation(project_root)
    state["workbook_health_ok"] = bool(validation.success and not validation.warnings)
    if validation.warnings:
        warnings.extend(validation.warnings[:3])
    return state, warnings


def _recommended_next_actions(
    phase: str,
    state: dict[str, Any],
    today_open: list[TaskItem],
    carryover: list[TaskItem],
    blockers: list[TaskItem],
    open_actions: list[dict[str, Any]],
    latest_validation_today: bool,
    context: MorningPlanningContext | None = None,
) -> list[str]:
    actions: list[str] = []
    press_available = bool(context and (context.press_files.get("master_press_list") or context.press_files.get("press_capacity")))
    for task in today_open[:4]:
        text = _task_text(task)
        lowered = text.lower()
        if "target" in lowered and "cell" in lowered:
            if press_available:
                action = "Open the EOAT Audit page and start the Plant 4 target-cell list; use the imported press/capacity data to pre-fill known machine details before walking the floor"
            else:
                action = "Open the EOAT Audit page and start the Plant 4 target-cell list; note that master press/capacity source files are missing, so machine details will need manual confirmation"
        elif "walkthrough" in lowered or "audit" in lowered:
            action = "Ask mentor/supervisor which 3-5 Plant 4 robot cells should be audited first, especially cells with part drops, vacuum loss, mis-picks, or frequent maintenance"
        elif "photo" in lowered and ("naming" in lowered or "format" in lowered or "system" in lowered):
            action = "Set the photo naming convention before collecting more images so audit evidence can be tied back to plant, press, EOAT area, and audit ID"
        elif "validation" in lowered or "validate" in lowered:
            action = "Run workbook validation after any audit-entry, photo-index, or workbook-template change and save the validation report as today's evidence"
        elif "mentor" in lowered or "supervisor" in lowered or "priorit" in lowered:
            action = "Use the mentor/supervisor check-in to confirm audit priority, floor access, and which known EOAT failures should be captured first"
        else:
            action = _task_action(task)
        if action:
            actions.append(action)
    for task in blockers[:2]:
        text = _task_text(task)
        if text:
            actions.insert(0, f"Unblock {text[0].lower() + text[1:]} by recording the exact access, decision, or owner needed before starting dependent floor work")
    for task in carryover[:2]:
        text = _task_text(task)
        if text:
            actions.append(f"Close or update the carryover item '{text}' before treating today's schedule as clean")
    if open_actions:
        first = open_actions[0]
        item = _clean(first.get("Action Item")) or _clean(first.get("Task")) or "the highest-priority open action item"
        actions.append(f"Update the open action item '{item}' with owner/status before starting stretch work")
    audited = state.get("audited_eoat_count")
    photos = state.get("photos_indexed_count")
    issues = state.get("issues_logged_count")
    if audited == 0:
        actions.append("Add the first EOAT audit entry once the walkthrough target is approved")
    if isinstance(audited, int) and audited > 0 and photos == 0:
        actions.append("Take or intake photos for the first audited EOAT so the audit has visual evidence")
    if isinstance(audited, int) and audited > 0 and issues == 0:
        actions.append("Review audit notes and log known EOAT issues instead of leaving them only in free-text notes")
    if not latest_validation_today:
        actions.append("Run workbook validation after data entry or template changes")
    if not today_open:
        actions.append("Pull the next unfinished scheduled task forward only after carryover and blockers are current")
    if phase == "Discovery":
        actions.extend(
            [
                "If floor access is unavailable, work safely from the workbook: clean the target list, validate templates, review documentation gaps, and prepare audit questions",
                "Do not start scoring pilots or drafting final recommendations until at least a few real audit rows, photos, or issue records exist",
            ]
        )
    return _dedupe_lines(actions, 5) or ["Pick the next unresolved scheduled task and define what would make it complete today."]


def _questions_for_phase(week: int, today_open: list[TaskItem] | None = None, blockers: list[TaskItem] | None = None) -> list[str]:
    today_open = today_open or []
    blockers = blockers or []
    task_text = " ".join(_task_text(task).lower() for task in today_open + blockers)
    questions: list[str] = []
    if blockers:
        questions.append("What decision, access, or information is needed to unblock today's blocked task?")
    if "target" in task_text and "cell" in task_text:
        questions.extend(
            [
                "Which robot cells should be prioritized first?",
                "Which cells are easiest and safest for a first walkthrough?",
            ]
        )
    if "audit" in task_text or "walkthrough" in task_text:
        questions.append("Who can approve or guide the first walkthrough/audit target today?")
    if "photo" in task_text:
        questions.append("What photo naming format would be easiest for future handoff and maintenance use?")
    if "documentation" in task_text or "bom" in task_text or "cad" in task_text or "binder" in task_text:
        questions.append("Are CAD, BOMs, and process binder information stored consistently?")
    if 1 <= week <= 3:
        questions.extend(
            [
            "Which robot cells should be prioritized first?",
            "Where is EOAT downtime or part-drop history tracked?",
            "Are there known high-problem EOATs maintenance wants reviewed first?",
            "Are process binders, CAD, or BOMs stored in a consistent location?",
            "What fields are mandatory for the final EOAT database?",
            ]
        )
    if 4 <= week <= 6:
        questions.extend(
            [
            "Which issue categories matter most to maintenance and production?",
            "What failure modes should be treated as safety or uptime risks?",
            "Which documentation gaps block repeatable PM or repair work?",
            "Which candidate cell has enough evidence for a practical pilot?",
            ]
        )
    if 7 <= week <= 10:
        questions.extend(
            [
            "What baseline KPI should be frozen before pilot changes?",
            "Who needs to approve PM, BOM, or setup-document updates?",
            "What result would prove the pilot is worth keeping?",
            "What before/after photos or signoffs are required?",
            ]
        )
    if week > 10:
        questions.extend(
            [
                "Who owns each final deliverable after handoff?",
                "What format does leadership want for the final presentation?",
                "Which open risks should be included in the final report?",
                "What training or reference material needs to be easiest to find?",
            ]
        )
    return _dedupe_questions(questions, 7)


def _latest_validation_ran_today(paths, plan_date: date) -> bool:
    reports = list_recent_files(paths.validation_reports, limit=5)
    today = plan_date.isoformat()
    return any(today in report.name and ("Foundation_Validation" in report.name or "System_Audit" in report.name) for report in reports)


def _primary_focus(phase: str, phase_detail: str, week: int, day: int, today_open: list[TaskItem], carryover: list[TaskItem], state: dict[str, Any]) -> str:
    priority_tasks = carryover[:2] + today_open[:3]
    if priority_tasks:
        actions = [_task_action(task) for task in priority_tasks[:3]]
        mission = _phrase_list(actions)
        if phase == "Discovery":
            return f"Today's goal is to turn setup into real discovery progress: {mission}."
        if phase == "Analysis":
            return f"Today's goal is to turn collected EOAT evidence into decisions: {mission}."
        if phase == "Implementation":
            return f"Today's goal is to keep pilot and standardization work moving with proof: {mission}."
        return f"Today's goal is to tighten the final handoff path: {mission}."
    audited = state.get("audited_eoat_count")
    if phase == "Discovery" and audited == 0:
        return "Turn the project structure into usable data: verify workbook health, confirm the first target cell, and add the first EOAT audit entry if access is approved."
    return f"Use the {phase.lower()} phase priorities to move the project forward through {phase_detail}."


def _if_blocked_lines(phase: str, today_open: list[TaskItem], blockers: list[TaskItem], carryover: list[TaskItem]) -> list[str]:
    lines: list[str] = []
    for task in blockers[:2]:
        text = _task_text(task)
        if text:
            lines.append(f"If {text} stays blocked, write down the blocker, who can clear it, and the next useful follow-up")
    task_text = " ".join(_task_text(task).lower() for task in today_open + carryover)
    if phase == "Discovery":
        if "audit" in task_text or "walkthrough" in task_text or not task_text:
            lines.append("If floor access is not available, prepare the audit template and refine the target-cell list from known robot/press information")
        if "photo" in task_text or not task_text:
            lines.append("If no photos can be taken yet, finalize the naming convention and confirm the folder path before importing more images")
        lines.append("If mentor or supervisor is unavailable, write the priority questions clearly and continue workbook/photo setup")
        lines.append("If audit work pauses, run workbook validation and review documentation gaps")
    elif phase == "Analysis":
        lines.extend(
            [
                "If new data is blocked, work from existing workbook rows and mark assumptions clearly",
                "If issue risk data is missing, list the exact severity/frequency/detectability questions to ask next",
                "If pilot ranking cannot be finalized, document the missing evidence instead of forcing a score",
            ]
        )
    elif phase == "Implementation":
        lines.extend(
            [
                "If pilot access is blocked, update before/after measurement plans and parts/documentation needs",
                "If approvals are unavailable, prepare a concise decision list for the next mentor or supervisor check-in",
                "If physical changes pause, validate PM/BOM updates against existing audit evidence",
            ]
        )
    else:
        lines.extend(
            [
                "If a final deliverable is blocked, record the missing owner, evidence, or source file",
                "If package building pauses, run the deliverable check and update the handoff gap list",
                "If review time is unavailable, prepare the shortest list of decisions needed for signoff",
            ]
        )
    return _dedupe_lines(lines, 5)


def _definition_of_done_lines(today_open: list[TaskItem], carryover: list[TaskItem], blockers: list[TaskItem]) -> list[str]:
    lines = [_task_done_outcome(task) for task in (today_open[:4] + carryover[:1])]
    if blockers:
        lines.append("Blocked items have the blocker reason, owner/source, and next follow-up recorded")
    lines.append("Task statuses updated before the daily end summary")
    return _dedupe_lines(lines, 6)


def _latest_tool_run_line(latest_activity: dict[str, Any] | None) -> str:
    if not latest_activity:
        return "- Latest tool run: not available."
    name = _clean(latest_activity.get("tool_name")) or "not available"
    parts = [f"- Latest tool run: {name}"]
    if "success" in latest_activity:
        parts.append("success" if latest_activity.get("success") else "failed")
    timestamp = _clean(latest_activity.get("timestamp"))
    if timestamp:
        display = timestamp.replace("T", " ").replace("Z", "")
        if "+" in display:
            display = display.split("+", 1)[0]
        if "." in display:
            display = display.split(".", 1)[0]
        display = display[:16]
        parts.append(display)
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} - {' - '.join(parts[1:])}"


def _limit_lines(items: list[str], limit: int = 6) -> list[str]:
    return _dedupe_lines(items, limit)


def _ranked_lines(items: list[str]) -> list[str]:
    return [f"{index}. {item}" for index, item in enumerate(items, start=1)]


def _status_lookup(context: MorningPlanningContext, name: str) -> str:
    source = context.source(name)
    return source.status if source else "missing"


def _source_availability_lines(context: MorningPlanningContext) -> list[str]:
    lines: list[str] = []
    for source in context.source_statuses:
        suffix = f" ({Path(source.path).name})" if source.path else ""
        lines.append(f"- {source.name}: {source.status} - {source.detail}{suffix}")
    return lines


def _display_activity(entry: dict[str, Any]) -> str:
    timestamp = _clean(entry.get("timestamp"))
    display = timestamp.replace("T", " ")[:16] if timestamp else "time unavailable"
    tool = _clean(entry.get("tool_name")) or _clean(entry.get("tool_id")) or "Unknown tool"
    summary = _clean(entry.get("summary")) or ("success" if entry.get("success") else "failed" if entry.get("success") is False else "no summary")
    created = len(entry.get("files_created") or [])
    modified = len(entry.get("files_modified") or [])
    file_note = f"; files created {created}, modified {modified}" if created or modified else ""
    return f"{display} - {tool}: {summary}{file_note}"


def _recent_file_line(item) -> str:
    stamp = item.modified.astimezone().strftime("%Y-%m-%d %H:%M")
    return f"{item.display_path} - modified {stamp}"


def _workbook_state_lines(context: MorningPlanningContext) -> list[str]:
    lines: list[str] = []
    if context.workbook_counts:
        counts = context.workbook_counts
        lines.append(
            "EOAT workbook rows read: "
            f"audits={counts.get('EOAT Inventory', 0)}, "
            f"issues={counts.get('Issue Log', 0)}, "
            f"photos={counts.get('Photo Index', 0)}, "
            f"actions={counts.get('Action Items', 0)}."
        )
        if context.workbook_mtime:
            lines.append(f"Master workbook last modified: {context.workbook_mtime.astimezone().strftime('%Y-%m-%d %H:%M')}.")
        if context.audit_rows:
            latest = context.audit_rows[-1]
            press = _clean(latest.get("Press/Machine #")) or "unknown press"
            status = _clean(latest.get("Status")) or "unknown status"
            issues = _clean(latest.get("Known Issues"))
            tail = f"; known issues: {issues}" if issues else ""
            lines.append(f"Latest workbook audit row: {press}, status {status}{tail}.")
        if context.photo_rows:
            latest_photo = context.photo_rows[-1]
            filename = _clean(latest_photo.get("Photo Filename")) or _clean(latest_photo.get("Photo ID")) or "latest photo row"
            lines.append(f"Photo index has {len(context.photo_rows)} row(s); latest: {filename}.")
    else:
        source = context.source("EOAT master workbook")
        lines.append(source.detail if source else "EOAT workbook state could not be checked.")
    return _limit_lines(lines, 6)


def _continuity_reason(today_open: list[TaskItem], carryover: list[TaskItem], blockers: list[TaskItem], context: MorningPlanningContext) -> str:
    if blockers:
        return f"Today's plan starts with blocked work because {blockers[0].description} needs an owner, access window, or decision before dependent floor work."
    if carryover:
        return f"Today's plan starts with carryover because {carryover[0].description} was not completed before Day {context.day}."
    if today_open:
        first = today_open[0].description
        if context.previous_completed:
            return f"Yesterday's setup work created enough structure to move into '{first}' today."
        return f"Day {context.day} schedule points first at '{first}', with live state checked for blockers and evidence before ranking the actions."
    return "No unfinished scheduled Day task was found, so the plan shifts to validation, evidence cleanup, and source checks."


def _empty_carryover_line(schedule_progress_status: str, week: int) -> str:
    if schedule_progress_status == "found":
        return f"- Confirmed none from task_progress_week{week}.json: no earlier in-progress or blocked task records were found."
    if schedule_progress_status == "empty":
        return f"- Progress file task_progress_week{week}.json exists but contains no completed/blocked task records to evaluate."
    if schedule_progress_status == "missing":
        return f"- Could not check carryover/blockers because task_progress_week{week}.json is missing."
    return f"- Could not confirm carryover/blockers because task_progress_week{week}.json could not be read."


def _empty_action_line(context: MorningPlanningContext) -> str:
    status = context.source("open action items")
    if context.action_source_checked:
        return "- Confirmed none from Action Items sheet: the workbook was checked and no open action item rows matched open statuses."
    if status:
        return f"- Could not confirm open action items: {status.detail}."
    return "- No action item source was available, so open action items could not be checked."


def _press_data_available(context: MorningPlanningContext) -> bool:
    return bool(context.press_files.get("master_press_list") or context.press_files.get("press_capacity"))


def _has_task(tasks: list[TaskItem], *needles: str) -> bool:
    text = " ".join(_task_text(task).lower() for task in tasks)
    return all(needle.lower() in text for needle in needles)


def reduce_morning_tasks(
    *,
    week: int,
    day: int,
    phase: str,
    today_open: list[TaskItem],
    carryover: list[TaskItem],
    blockers: list[TaskItem],
    open_actions: list[dict[str, Any]],
    context: MorningPlanningContext,
    latest_validation_today: bool,
) -> ReducedMorningPlan:
    if blockers:
        mission = f"Clear the blocker on {blockers[0].description} and keep Week {week} Day {day} moving with desk-ready audit prep."
        do_first = f"Find out who can unblock {blockers[0].description} and what decision or access is needed."
    elif phase == "Discovery":
        mission = "Start real EOAT discovery by building the Plant 4 target-cell list and getting approval for the first walkthrough/audit."
        do_first = "Open the EOAT Audit page and start the Plant 4 target-cell list using the available press/capacity reference data."
        if not _press_data_available(context):
            do_first = "Open the EOAT Audit page and start the Plant 4 target-cell list, marking press details that need manual confirmation."
    else:
        mission = f"Move Week {week} Day {day} {phase.lower()} work forward by closing the highest-value unfinished task."
        do_first = _task_action(today_open[0]) if today_open else "Pick the highest-value unfinished task and define today's completion point."

    main_todo = [
        "Ask mentor/supervisor which 3-5 Plant 4 robot cells should be audited first.",
        "Confirm the first safe walkthrough/audit target.",
        "Decide the photo naming format before collecting more photos.",
        "Start the first EOAT audit if floor access is approved.",
        "Update task statuses before leaving for the day.",
    ]
    if blockers:
        main_todo[0] = f"Resolve or document the blocker on {blockers[0].description}."
    elif open_actions:
        action = _clean(open_actions[0].get("Action Item")) or _clean(open_actions[0].get("Task")) or "open action item"
        main_todo.insert(0, f"Update open action: {action}.")
    if not _has_task(today_open, "photo"):
        main_todo = [item for item in main_todo if "photo naming" not in item.lower()]
    if not (_has_task(today_open, "audit") or _has_task(today_open, "walkthrough") or phase == "Discovery"):
        main_todo = [item for item in main_todo if "first EOAT audit" not in item]
    main_todo = _dedupe_lines(main_todo, 5)
    if len(main_todo) > 5:
        main_todo = main_todo[:5]

    ask_today = [
        "Which cells have known part drops, mis-picks, vacuum loss, or frequent maintenance?",
        "Who can approve or guide the first walkthrough?",
    ]
    if not _has_task(today_open, "photo") and phase == "Discovery":
        ask_today.append("Where should downtime, scrap, or cycle-time history be pulled from?")
    ask_today = _dedupe_questions(ask_today, 2)

    if_blocked = []
    if blockers:
        if_blocked.append(f"Document why {blockers[0].description} is blocked and who can clear it")
    if _press_data_available(context):
        if_blocked.append("Clean up the target-cell list from desk using press/capacity data")
    else:
        if_blocked.append("Create the target-cell list shell and mark missing press details")
    if_blocked.append("Prepare audit questions and photo naming rules")
    if not latest_validation_today:
        if_blocked.append("Run workbook validation after any template/data changes")
    if_blocked = _dedupe_lines(if_blocked, 3)[:2]

    done_when = [
        "Target-cell list is started",
        "First audit is completed or clearly blocked",
    ]
    if _has_task(today_open, "photo"):
        done_when.append("Photo naming format is decided or logged as an open decision")
    done_when = _dedupe_lines(done_when, 3)[:2]

    return ReducedMorningPlan(
        mission=mission,
        do_first=do_first,
        main_todo=main_todo[:5],
        ask_today=ask_today[:3],
        if_blocked=if_blocked[:2],
        done_when=done_when[:2],
    )


def render_morning_todo_card(week: int, day: int, reduced: ReducedMorningPlan) -> str:
    lines = [
        f"# Week {week} Day {day} Morning Plan",
        "",
        "## Today's Mission",
        reduced.mission.rstrip(".") + ".",
        "",
        "## Do First",
        f"1. {reduced.do_first.rstrip('.')}.",
        "",
        "## Main TODO",
    ]
    lines.extend(f"- [ ] {item.rstrip('.')}." for item in reduced.main_todo[:5])
    lines.extend(["", "## Ask Today"])
    lines.extend(f"- {question}" for question in reduced.ask_today[:4])
    lines.extend(["", "## If Blocked"])
    lines.extend(f"- {item.rstrip('.')}." for item in reduced.if_blocked[:3])
    lines.extend(["", "## Done When"])
    lines.extend(f"- {item.rstrip('.')}." for item in reduced.done_when[:3])
    return "\n".join(lines) + "\n"


def build_morning_plan_details_markdown(
    project_root: str | Path,
    week: int,
    day: int,
    plan_date: date,
) -> str:
    context = collect_morning_planning_context(project_root, week, day, plan_date)
    confidence, confidence_reason = context.confidence
    lines = [
        f"# Week {week} Day {day} Planning Context Details",
        "",
        f"Date: {plan_date.isoformat()}",
        "",
        "## Confidence / Data Quality",
        f"- Confidence: {confidence} - {confidence_reason}.",
        "",
        "## Source Availability",
        *_source_availability_lines(context),
        "",
        "## Recent Activity",
    ]
    if context.activity_entries:
        lines.extend(f"- {_display_activity(entry)}" for entry in context.activity_entries[:10])
    else:
        lines.append("- No recent activity entries found.")
    lines.extend(["", "## Workbook State"])
    lines.extend(f"- {item}" for item in _workbook_state_lines(context))
    lines.extend(["", "## Recent Modified Files"])
    if context.recent_modified_files:
        lines.extend(f"- {_recent_file_line(item)}" for item in context.recent_modified_files[:20])
    else:
        lines.append("- No recent modified files found.")
    lines.extend(["", "## App State Signals"])
    if context.app_state:
        lines.extend(f"- Implemented: {item}" for item in context.app_state)
    if context.app_pending:
        lines.extend(f"- Pending: {item}" for item in context.app_pending)
    return "\n".join(lines) + "\n"


def build_morning_plan_markdown(
    project_root: str | Path,
    week: int | None = None,
    day: int | None = None,
    notes: str = "",
    detail_level: str = "todo",
    resolved_day: ProjectDay | None = None,
    project_start_date: str | date | None = None,
    skip_weekends: bool = True,
    holidays: list[str | date] | None = None,
    current_date: date | None = None,
    manual_override: bool | None = None,
) -> tuple[str, list[str], dict[str, Any]]:
    if detail_level not in DETAIL_LEVELS:
        raise ValueError(f"detail_level must be one of: {', '.join(sorted(DETAIL_LEVELS))}")
    paths = resolve_project_paths(project_root)
    if resolved_day is None:
        explicit_override = manual_override if manual_override is not None else (week is not None and day is not None)
        resolved_day = resolve_project_day_for_project(
            project_root,
            current_date=current_date,
            project_start_date=project_start_date,
            skip_weekends=skip_weekends,
            holidays=holidays,
            manual_week=week,
            manual_day=day,
            manual_override=bool(explicit_override),
        )
    else:
        explicit_override = manual_override if manual_override is not None else False
    week = resolved_day.week
    day = resolved_day.day
    warnings: list[str] = []
    if resolved_day.warning:
        warnings.append(resolved_day.warning)

    schedule = load_week_schedule(project_root, week)
    if not schedule.schedule_path:
        warnings.append(f"No project schedule file found for Week {week}.")
    if not schedule.progress_path:
        warnings.append(f"No task progress file found for Week {week}.")
    context = collect_morning_planning_context(project_root, week, day, resolved_day.date)
    warnings.extend(context.warnings)

    scheduled_all = _scheduled_tasks_for_day(schedule, day)
    today_open = [task for task in scheduled_all if _unfinished(task)]
    carryover = [
        task
        for task in schedule.tasks
        if (_task_day_int(task) or 999) < day and _status_key(task.status) in CARRYOVER_STATUSES
    ]
    blockers = [task for task in schedule.tasks if _status_key(task.status) == "blocked" and _unfinished(task)]
    future_open = [
        task
        for task in schedule.tasks
        if (_task_day_int(task) or 0) > day and _status_key(task.status) == "not started"
    ]
    carryover = _unique_tasks(carryover)
    open_actions = context.open_actions
    activity = context.activity_entries
    previous_report = context.previous_reports[0] if context.previous_reports else _previous_daily_report(paths, week, day)
    previous_text = ""
    if previous_report:
        previous_text, _ = read_report_preview(previous_report, max_chars=5000)

    state, state_warnings = _collect_project_state(project_root)
    if context.workbook_counts:
        state.update(
            {
                "audited_eoat_count": context.workbook_counts.get("EOAT Inventory", state.get("audited_eoat_count")),
                "photos_indexed_count": context.workbook_counts.get("Photo Index", state.get("photos_indexed_count")),
                "issues_logged_count": context.workbook_counts.get("Issue Log", state.get("issues_logged_count")),
                "open_action_items_count": len(open_actions),
            }
        )
    warnings.extend(state_warnings)
    phase, phase_detail = _phase_for_week(week)
    latest_validation_today = _latest_validation_ran_today(paths, resolved_day.date)
    recommendations = _recommended_next_actions(phase, state, today_open, carryover, blockers, open_actions, latest_validation_today, context)
    primary = _primary_focus(phase, phase_detail, week, day, today_open, carryover, state)
    latest_activity = activity[0] if activity else None
    carryover_and_blockers = _unique_tasks(blockers + carryover)
    if_blocked = _if_blocked_lines(phase, today_open, blockers, carryover)
    done_lines = _definition_of_done_lines(today_open, carryover, blockers)
    confidence, _confidence_reason = context.confidence
    reduced = reduce_morning_tasks(
        week=week,
        day=day,
        phase=phase,
        today_open=today_open,
        carryover=carryover,
        blockers=blockers,
        open_actions=open_actions,
        context=context,
        latest_validation_today=latest_validation_today,
    )
    if detail_level == "debug":
        markdown = build_morning_plan_details_markdown(project_root, week, day, resolved_day.date)
    else:
        markdown = render_morning_todo_card(week, day, reduced)
    generic_issues = detect_generic_morning_report(markdown, context.schedule_tasks)
    metrics = {
        "resolved_week": week,
        "resolved_day": day,
        "resolved_source": resolved_day.source,
        "primary_focus_items": 1,
        "carryover_tasks": len(carryover),
        "blocked_tasks": len(blockers),
        "scheduled_open_tasks": len(today_open),
        "open_actions": len(open_actions),
        "recommended_next_actions": 1 + len(reduced.main_todo),
        "if_blocked_items": len(reduced.if_blocked),
        "definition_of_done_items": len(reduced.done_when),
        "audited_eoat_count": state.get("audited_eoat_count"),
        "photos_indexed_count": state.get("photos_indexed_count"),
        "issues_logged_count": state.get("issues_logged_count"),
        "source_status_found": sum(1 for source in context.source_statuses if source.status == "found"),
        "source_status_missing": sum(1 for source in context.source_statuses if source.status == "missing"),
        "confidence": confidence,
        "generic_report_issues": len(generic_issues),
        "generic_report_issue_details": generic_issues,
    }
    return markdown, warnings, metrics

    lines = [
        f"# Week {week} Day {day} Morning Plan",
        "",
        f"Date: {resolved_day.date.isoformat()}",
        f"Resolved from: {resolved_day.source}",
        f"Project phase: Week {week} {phase} - {phase_detail}",
    ]
    if resolved_day.warning:
        lines.append(f"Warning: {resolved_day.warning}")

    lines.extend(["", "## Primary Focus", primary])

    lines.extend(["", "## Yesterday -> Today Continuity"])
    if context.previous_completed:
        lines.append("Yesterday's completed tasks:")
        lines.extend(f"- {item}" for item in _limit_lines(context.previous_completed, 6))
    else:
        lines.append("- Yesterday's completed tasks: no completed-task details were found in the previous daily summaries.")
    if context.previous_blockers:
        lines.append("Yesterday's unresolved blockers:")
        lines.extend(f"- {item}" for item in _limit_lines(context.previous_blockers, 5))
    else:
        previous_status = _status_lookup(context, "previous daily activity summaries")
        if previous_status == "found":
            lines.append("- Yesterday's unresolved blockers: confirmed none listed in the previous summaries that were readable.")
        else:
            lines.append("- Yesterday's unresolved blockers: could not confirm because previous daily summaries were missing or empty.")
    if context.previous_reports:
        lines.append("Reports generated or reviewed yesterday:")
        lines.extend(f"- {report.name}" for report in context.previous_reports[:5])
    else:
        lines.append("- Reports generated or reviewed yesterday: no previous daily reports were available.")
    if context.previous_modified_files or context.previous_created_files:
        lines.append("Workbook or app/project files changed yesterday:")
        lines.extend(f"- Created: {item}" for item in _limit_lines(context.previous_created_files, 4))
        lines.extend(f"- Modified: {item}" for item in _limit_lines(context.previous_modified_files, 6))
    else:
        lines.append("- Workbook or app/project files changed yesterday: no changed-file list was found in the previous summaries.")
    if notes.strip() or context.previous_notes:
        lines.append("User notes or manual overrides:")
        if notes.strip():
            lines.append(f"- Today's manual note: {notes.strip()}")
        lines.extend(f"- {item}" for item in _limit_lines(context.previous_notes, 4))
    else:
        lines.append("- User notes or manual overrides: none found in checked sources.")
    lines.append(f"- Reason for today's plan: {_continuity_reason(today_open, carryover, blockers, context)}")

    lines.extend(["", "## What Changed Since Yesterday"])
    changed_lines = []
    if context.previous_completed:
        changed_lines.append(f"Day {day - 1 if day > 1 else '?'} completion signal: {_phrase_list(context.previous_completed[:3])}")
    if context.activity_entries:
        changed_lines.extend(_display_activity(entry) for entry in context.activity_entries[:4])
    if context.validation_reports:
        changed_lines.append(f"Latest validation/system audit report available: {context.validation_reports[0].name}")
    if context.workbook_mtime:
        changed_lines.append(f"EOAT master workbook timestamp: {context.workbook_mtime.astimezone().strftime('%Y-%m-%d %H:%M')}")
    if context.recent_reports:
        changed_lines.append(f"Recent generated report/data file: {context.recent_reports[0].name}")
    if changed_lines:
        lines.extend(f"- {item}" for item in _limit_lines(changed_lines, 8))
    else:
        lines.append("- No recent activity, report, workbook, or file-change signals were available beyond the static schedule.")

    lines.extend(["", "## Current App and Project State"])
    lines.extend(f"- {item}" for item in _workbook_state_lines(context))
    if context.recent_modified_files:
        lines.append("- Recently modified files are listed below and should be treated as active context for today's work.")
    if context.validation_reports:
        lines.append(f"- Workbook validation/audit evidence exists: {context.validation_reports[0].name}.")
    if context.press_files:
        master_status = "available" if context.press_files.get("master_press_list") else "missing"
        capacity_status = "available" if context.press_files.get("press_capacity") else "missing"
        lines.append(f"- Press lookup sources: master press list {master_status}; Plant 4 capacity file {capacity_status}.")

    lines.extend(
        [
            "",
            "## First 15 Minutes",
            "- Open the project folder and EOAT master workbook.",
            "- Check yesterday's summary and any carryover below.",
            "- Confirm today's scheduled tasks and update anything already completed.",
            "- Run or review workbook validation if the workbook changed since the last validation.",
        ]
    )

    lines.extend(["", "## Main Work Blocks"])
    lines.extend(
        [
            "### Block 1 - Schedule / Clean Start",
            f"- Check the Week {week} Day {day} task list and resolve any carryover before stretch work.",
            "- If a task is blocked, record the person/source needed and ask that question early.",
            "- Run workbook validation after template or audit-data changes.",
            "",
            "### Block 2 - EOAT Audit Data Capture",
            "- Add or continue the next EOAT audit entry when floor access is approved.",
            "- Record robot type, EOAT type, vacuum/gripper details, sensors, tubing condition, cable management, known issues, and pilot-candidate flag.",
            "- Link notes, evidence, or photos to the audited cell when available.",
            "",
            "### Block 3 - Photos / Evidence",
            "- Move new photos into Incoming_Photos before running Photo Intake.",
            "- Tag photos by press or machine, EOAT area shown, and relevant audit entry.",
            "- Keep photo names consistent with the project naming system once confirmed.",
            "",
            "### Block 4 - End-of-Day Prep",
            "- Mark tasks complete, in progress, blocked, or skipped while the details are fresh.",
            "- Record blockers, mentor questions, and any data gaps found today.",
            "- Generate the daily end summary after task and workbook updates.",
        ]
    )

    lines.extend(["", "## Scheduled Tasks"])
    if today_open:
        lines.extend(_format_task(task) for task in today_open)
    elif scheduled_all:
        lines.append(f"- No unfinished scheduled tasks were found for Week {week} Day {day}; scheduled tasks for this day are already complete or skipped.")
    else:
        lines.append(
            f"- No unfinished scheduled tasks were found for Week {week} Day {day}. Suggested fallback: run workbook validation, review audit coverage, and add the next EOAT audit entry."
        )

    lines.extend(["", "## State-Aware Work Triage"])
    unfinished = _unique_tasks(today_open + carryover)
    if unfinished:
        lines.append("Still unfinished:")
        lines.extend(_format_task(task) for task in unfinished[:8])
    else:
        progress_status = _status_lookup(context, "task_progress_weekN.json")
        if progress_status == "found":
            lines.append(f"- Confirmed from task_progress_week{week}.json: no unfinished Day {day} or carryover task records were found.")
        elif progress_status == "empty":
            lines.append(f"- task_progress_week{week}.json exists but contains no task records, so unfinished work could not be inferred from progress data.")
        else:
            lines.append(f"- Could not confirm unfinished work because task_progress_week{week}.json was not available.")
    if blockers:
        lines.append("Blocked:")
        lines.extend(_format_task(task) for task in blockers[:6])
    else:
        lines.append(_empty_carryover_line(_status_lookup(context, "task_progress_weekN.json"), week))
    evidence_lines = []
    for entry in context.activity_entries[:8]:
        evidence_lines.extend(_clean(path) for path in (entry.get("files_created") or [])[:3])
        evidence_lines.extend(_clean(path) for path in (entry.get("files_modified") or [])[:3])
    if context.recent_reports:
        evidence_lines.extend(report.name for report in context.recent_reports[:6])
    if evidence_lines:
        lines.append("Evidence/data created or updated recently:")
        lines.extend(f"- {item}" for item in _limit_lines(evidence_lines, 8))
    else:
        lines.append("- Evidence/data created or updated recently: none found in activity logs or report folders.")
    lines.append(f"- Highest-priority work: {recommendations[0] if recommendations else primary}")

    lines.extend(["", "## Carryover / Blockers"])
    if carryover_and_blockers:
        lines.extend(_format_task(task) for task in carryover_and_blockers[:10])
    else:
        lines.append(_empty_carryover_line(_status_lookup(context, "task_progress_weekN.json"), week))

    lines.extend(["", "## Open Action Items"])
    if open_actions:
        for row in open_actions[:6]:
            item = _clean(row.get("Action Item")) or _clean(row.get("Task")) or "Open action item"
            priority = _clean(row.get("Priority")) or "No priority"
            status = _clean(row.get("Status")) or "Open"
            lines.append(f"- [{status}] {item} ({priority})")
    else:
        lines.append(_empty_action_line(context))

    lines.extend(["", "## Recommended Next Actions"])
    lines.extend(_ranked_lines(recommendations))

    lines.extend(["", "## If Blocked / Floor Access Unavailable"])
    lines.extend(f"- {item}" for item in if_blocked[:4])
    lines.append("- Safe desk work: reconcile workbook rows, review validation reports, prepare audit questions, clean photo naming rules, and inspect press/capacity source availability.")

    lines.extend(["", "## Optional Stretch"])
    stretch_lines = []
    if not carryover_and_blockers:
        stretch_lines = [f"- Optional: {task.description} ({task.id})" for task in future_open[:5] if task.description]
    if stretch_lines:
        lines.extend(stretch_lines)
    else:
        lines.append("- No stretch tasks suggested yet.")

    lines.extend(["", "## Mentor / Supervisor Dependencies"])
    mentor_lines = [
        "Which 3-5 Plant 4 robot cells should be audited first?",
        "Are any target cells known for part drops, vacuum loss, mis-picks, cable/tubing wear, or frequent maintenance?",
        "Who can approve the first walkthrough window and confirm any safety restrictions?",
    ]
    if blockers:
        mentor_lines.insert(0, f"What decision or access is needed to unblock {blockers[0].description}?")
    lines.extend(f"- {question}" for question in _dedupe_questions(mentor_lines, 5))

    lines.extend(["", "## Should Not Start Yet"])
    not_yet = [
        "Do not treat the Day 2 schedule as complete until task_progress_weekN.json has been updated with real status changes.",
        "Do not start pilot ranking or final recommendations until workbook audit/issue/photo evidence exists for candidate cells.",
    ]
    if not context.press_files.get("master_press_list") or not context.press_files.get("press_capacity"):
        not_yet.append("Do not rely on press autofill for final machine details until the missing press list/capacity source file is imported.")
    if not latest_validation_today:
        not_yet.append("Do not consider workbook changes validated until today's validation/system audit report has been generated or reviewed.")
    lines.extend(f"- {item}" for item in _dedupe_lines(not_yet, 5))

    lines.extend(["", "## Questions to Ask Today"])
    lines.extend(f"- {question}" for question in _questions_for_phase(week, today_open, blockers))

    lines.extend(["", "## Definition of Done for Today"])
    lines.extend(f"- {item}" for item in done_lines)

    lines.extend(["", "## End-of-Day Checklist"])
    lines.extend(
        [
            "- Update task statuses in the schedule tracker.",
            "- Save audit entries and close the workbook cleanly.",
            "- Intake or index photos taken today.",
            "- Record blockers, data gaps, and mentor/technician questions.",
            "- Generate the daily end summary.",
        ]
    )

    lines.extend(["", "## Recently Modified Files"])
    if context.recent_modified_files:
        lines.extend(f"- {_recent_file_line(item)}" for item in context.recent_modified_files[:10])
    else:
        source = context.source("recent files modified")
        lines.append(f"- {source.detail if source else 'Recent file scan did not return any files.'}")

    lines.extend(["", "## Real App / App-State Awareness"])
    if context.app_state:
        lines.extend(f"- Implemented: {item}" for item in context.app_state)
    if context.app_pending:
        lines.extend(f"- Pending: {item}" for item in context.app_pending)
    if not context.app_state and not context.app_pending:
        lines.append("- No app-state signals were available to inspect.")

    confidence, confidence_reason = context.confidence
    lines.extend(["", "## Confidence / Data Quality"])
    lines.append(f"- Confidence: {confidence} - {confidence_reason}.")
    lines.append(f"- Source coverage: {sum(1 for source in context.source_statuses if source.status == 'found')} found, {sum(1 for source in context.source_statuses if source.status == 'empty')} empty, {sum(1 for source in context.source_statuses if source.status == 'missing')} missing, {sum(1 for source in context.source_statuses if source.status == 'error')} error.")
    if confidence != "High":
        lines.append("- Treat recommendations as planning guidance until the missing live-state sources are filled in.")

    lines.extend(["", "## Planner Reasoning Summary"])
    reasoning_lines = [
        f"Project day resolved as Week {week} Day {day} from {resolved_day.source}.",
        f"Static tasks for today: {len(context.schedule_tasks)} found in project_schedule_week{week}.json.",
        f"Progress file status: {_status_lookup(context, 'task_progress_weekN.json')}.",
        f"Previous report status: {_status_lookup(context, 'previous daily activity summaries')}.",
        f"Activity log status: {_status_lookup(context, 'activity_log.jsonl')}.",
        f"Workbook/audit/photo source status: {_status_lookup(context, 'EOAT master workbook')}; audit rows {context.workbook_counts.get('EOAT Inventory', 'not available')}; photo rows {context.workbook_counts.get('Photo Index', 'not available')}.",
        f"Priority chosen because: {_continuity_reason(today_open, carryover, blockers, context)}",
    ]
    lines.extend(f"- {item}" for item in reasoning_lines)

    lines.extend(["", "## Source Availability"])
    lines.extend(_source_availability_lines(context))

    if previous_report:
        lines.extend(["", "## Yesterday / Recent Context", f"- Previous daily report reviewed: {previous_report.name}"])
    if previous_text:
        reminders = [line.strip("- ").strip() for line in previous_text.splitlines() if line.strip().startswith("- ")][:4]
        lines.extend(f"- {reminder}" for reminder in reminders if reminder)
    if notes.strip():
        lines.extend(["", "## Manual Notes", notes.strip()])
    if warnings:
        lines.extend(["", "## Data Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)

    lines.extend(["", "## Plan Sources"])
    lines.extend(
        [
            f"- Project day resolved from: {resolved_day.source}",
            f"- Project start date: {resolved_day.project_start_date.isoformat() if resolved_day.project_start_date else 'not available'}",
            f"- Schedule file: {schedule.schedule_path.name if schedule.schedule_path else 'not available'}",
            f"- Progress file: {schedule.progress_path.name if schedule.progress_path else 'not available'}",
            f"- Previous daily report: {previous_report.name if previous_report else 'not available'}",
            _latest_tool_run_line(latest_activity),
            f"- Activity entries inspected: {len(context.activity_entries)}",
            f"- Workbook rows inspected: {sum(context.workbook_counts.values()) if context.workbook_counts else 'not available'}",
            f"- Recent modified files inspected: {len(context.recent_modified_files)}",
            f"- Confidence: {confidence}",
            f"- Manual override: {'yes' if explicit_override else 'no'}",
        ]
    )

    markdown = "\n".join(lines) + "\n"
    generic_issues = detect_generic_morning_report(markdown, context.schedule_tasks)
    metrics = {
        "resolved_week": week,
        "resolved_day": day,
        "resolved_source": resolved_day.source,
        "primary_focus_items": 1 if primary else 0,
        "carryover_tasks": len(carryover),
        "blocked_tasks": len(blockers),
        "scheduled_open_tasks": len(today_open),
        "open_actions": len(open_actions),
        "recommended_next_actions": len(recommendations),
        "if_blocked_items": len(if_blocked),
        "definition_of_done_items": len(done_lines),
        "audited_eoat_count": state.get("audited_eoat_count"),
        "photos_indexed_count": state.get("photos_indexed_count"),
        "issues_logged_count": state.get("issues_logged_count"),
        "source_status_found": sum(1 for source in context.source_statuses if source.status == "found"),
        "source_status_missing": sum(1 for source in context.source_statuses if source.status == "missing"),
        "confidence": confidence,
        "generic_report_issues": len(generic_issues),
        "generic_report_issue_details": generic_issues,
    }
    return markdown, warnings, metrics


def generate_morning_plan(
    project_root: str | Path,
    week: int | None = None,
    day: int | None = None,
    notes: str = "",
    detail_level: str = "todo",
    project_start_date: str | date | None = None,
    skip_weekends: bool = True,
    holidays: list[str | date] | None = None,
    current_date: date | None = None,
    manual_override: bool | None = None,
) -> ToolResult:
    start = time.perf_counter()
    paths = resolve_project_paths(project_root)
    ensure_directory(paths.morning_plans)
    markdown, warnings, metrics = build_morning_plan_markdown(
        project_root,
        week=week,
        day=day,
        notes=notes,
        detail_level=detail_level,
        project_start_date=project_start_date,
        skip_weekends=skip_weekends,
        holidays=holidays,
        current_date=current_date,
        manual_override=manual_override,
    )
    resolved_week = int(metrics["resolved_week"])
    resolved_day = int(metrics["resolved_day"])
    plan_date = current_date or date.today()
    path = paths.morning_plans / f"Week{resolved_week}_Day{resolved_day}_Morning_Plan_{plan_date.isoformat()}.md"
    if path.exists():
        path = paths.morning_plans / f"Week{resolved_week}_Day{resolved_day}_Morning_Plan_{time.strftime('%Y-%m-%d_%H%M%S')}.md"
    output = safe_write_text(path, markdown, overwrite=False)
    details_path = paths.morning_plans / f"Week{resolved_week}_Day{resolved_day}_Planning_Context_Details_{plan_date.isoformat()}.md"
    if details_path.exists():
        details_path = paths.morning_plans / f"Week{resolved_week}_Day{resolved_day}_Planning_Context_Details_{time.strftime('%Y-%m-%d_%H%M%S')}.md"
    details_markdown = build_morning_plan_details_markdown(project_root, resolved_week, resolved_day, plan_date)
    details_output = safe_write_text(details_path, details_markdown, overwrite=False)
    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        f"Generated Week {resolved_week} Day {resolved_day} morning plan.",
        details=[f"Morning plan saved to {output}.", f"Planning context details saved to {details_output}."],
        warnings=warnings,
        files_created=[str(output), str(details_output)],
        output_reports=[str(output)],
        metrics=metrics,
        duration_seconds=time.perf_counter() - start,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result
