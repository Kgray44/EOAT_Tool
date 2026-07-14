from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .logging import read_recent_activity
from .paths import resolve_project_paths
from .press_lookup import CAPACITY_FILE_NAME, MASTER_FILE_NAME, reference_data_dir
from .reports import list_recent_files, report_folders
from .schedule import load_week_schedule, schedule_file_for_week
from .task_progress import TaskItem, extract_tasks, load_task_progress, progress_file_for_week
from .workbook_io import row_dicts, workbook_sheet_names

WORKBOOK_SHEETS = [
    "EOAT Inventory",
    "Issue Log",
    "KPI Baseline",
    "Interview Notes",
    "Pilot Candidates",
    "FMEA Draft",
    "Action Items",
    "Photo Index",
]
OPEN_ACTION_STATUSES = {"", "open", "not started", "needs follow-up", "in progress", "blocked", "new"}
RECENT_FILE_EXTENSIONS = {
    ".md",
    ".txt",
    ".json",
    ".jsonl",
    ".xlsx",
    ".xls",
    ".csv",
    ".png",
    ".jpg",
    ".jpeg",
    ".heic",
    ".heif",
    ".py",
    ".ps1",
    ".bat",
}
IGNORED_RECENT_PARTS = {"__pycache__", ".pytest_cache"}


@dataclass(frozen=True)
class SourceStatus:
    name: str
    status: str
    detail: str
    path: str = ""


@dataclass(frozen=True)
class RecentFile:
    path: Path
    modified: datetime
    size: int

    @property
    def display_path(self) -> str:
        return self.path.as_posix()


@dataclass
class MorningPlanningContext:
    project_root: Path
    week: int
    day: int
    plan_date: date
    schedule_tasks: list[str] = field(default_factory=list)
    progress_tasks: list[TaskItem] = field(default_factory=list)
    previous_reports: list[Path] = field(default_factory=list)
    previous_completed: list[str] = field(default_factory=list)
    previous_blockers: list[str] = field(default_factory=list)
    previous_modified_files: list[str] = field(default_factory=list)
    previous_created_files: list[str] = field(default_factory=list)
    previous_notes: list[str] = field(default_factory=list)
    activity_entries: list[dict[str, Any]] = field(default_factory=list)
    recent_reports: list[Path] = field(default_factory=list)
    recent_modified_files: list[RecentFile] = field(default_factory=list)
    workbook_counts: dict[str, int] = field(default_factory=dict)
    workbook_mtime: datetime | None = None
    workbook_path: Path | None = None
    audit_rows: list[dict[str, Any]] = field(default_factory=list)
    photo_rows: list[dict[str, Any]] = field(default_factory=list)
    open_actions: list[dict[str, Any]] = field(default_factory=list)
    action_source_checked: bool = False
    validation_reports: list[Path] = field(default_factory=list)
    press_files: dict[str, Path | None] = field(default_factory=dict)
    app_state: list[str] = field(default_factory=list)
    app_pending: list[str] = field(default_factory=list)
    config_state: list[str] = field(default_factory=list)
    source_statuses: list[SourceStatus] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def source(self, name: str) -> SourceStatus | None:
        for status in self.source_statuses:
            if status.name == name:
                return status
        return None

    @property
    def live_state_available(self) -> bool:
        return bool(self.activity_entries or self.workbook_counts or self.recent_modified_files)

    @property
    def confidence(self) -> tuple[str, str]:
        has_progress = (self.source("task_progress_weekN.json") or SourceStatus("", "missing", "")).status in {
            "found",
            "empty",
        }
        has_schedule = (self.source("project_schedule_weekN.json") or SourceStatus("", "missing", "")).status == "found"
        has_activity = (self.source("activity_log.jsonl") or SourceStatus("", "missing", "")).status == "found"
        has_workbook = (self.source("EOAT master workbook") or SourceStatus("", "missing", "")).status == "found"
        has_previous = bool(self.previous_reports)
        if has_progress and has_activity and has_workbook:
            return "High", "activity log, progress file, and workbook state were read successfully"
        if has_schedule and has_previous:
            return "Medium", "schedule and previous summary were found, but live app/workbook state was incomplete"
        return "Low", "only static schedule/default project information was available"


def collect_morning_planning_context(
    project_root: str | Path,
    week: int,
    day: int,
    plan_date: date,
    *,
    activity_limit: int = 20,
    recent_days: int = 3,
) -> MorningPlanningContext:
    root = Path(project_root)
    paths = resolve_project_paths(root)
    ctx = MorningPlanningContext(project_root=root, week=week, day=day, plan_date=plan_date)

    _collect_schedule_and_progress(ctx)
    _collect_previous_reports(ctx, recent_days)
    _collect_activity(ctx, activity_limit)
    _collect_workbook_state(ctx)
    _collect_validation_and_reports(ctx)
    _collect_recent_modified_files(ctx, recent_days)
    _collect_press_sources(ctx)
    _collect_config_state(ctx)
    _collect_app_state(ctx)
    return ctx


def detect_generic_morning_report(markdown: str, schedule_tasks: list[str] | None = None) -> list[str]:
    issues: list[str] = []
    lowered = markdown.lower()
    if (
        "## main todo" not in lowered
        and "## top priorities" not in lowered
        and "## recommended next actions" not in lowered
    ):
        issues.append("missing prioritized action section")
    if "## if blocked" not in lowered and "## if you do not get floor access" not in lowered:
        issues.append("missing blocked/no-floor-access fallback")
    if (
        "## do first" in lowered or "## top priorities" in lowered or "## recommended next actions" in lowered
    ) and not any(line.startswith(("1. ", "2. ", "3. ")) for line in markdown.splitlines()):
        issues.append("recommended actions are not ranked")

    schedule_tasks = schedule_tasks or []
    if schedule_tasks:
        repeated = 0
        for task in schedule_tasks:
            task = str(task).strip()
            if task and markdown.count(task) > 1:
                repeated += 1
        if repeated >= max(3, len(schedule_tasks) // 2):
            issues.append("too many sections repeat schedule task text")

    if "all scheduled tasks are not started" in lowered:
        issues.append("all tasks listed without interpretation")
    if "no open action items found" in lowered and "confirmed none from action items" not in lowered:
        issues.append("claims no action items without naming checked source")
    forbidden = [
        "## confidence / data quality",
        "## source availability",
        "## recent activity",
        "## workbook state",
        "## recent modified files",
        "## app state signals",
        "## planner reasoning summary",
        "## plan sources",
        "## what changed since yesterday",
        "## yesterday -> today continuity",
    ]
    if any(heading in lowered for heading in forbidden):
        issues.append("main morning plan includes diagnostic dump sections")
    return issues


def _add_source(
    ctx: MorningPlanningContext, name: str, status: str, detail: str, path: Path | str | None = None
) -> None:
    ctx.source_statuses.append(SourceStatus(name=name, status=status, detail=detail, path=str(path or "")))


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _collect_schedule_and_progress(ctx: MorningPlanningContext) -> None:
    schedule_path = schedule_file_for_week(ctx.project_root, ctx.week)
    progress_path = progress_file_for_week(ctx.project_root, ctx.week)
    schedule = load_week_schedule(ctx.project_root, ctx.week)
    ctx.schedule_tasks = [task for task in schedule.days.get(str(ctx.day), []) if _clean(task)]
    if schedule_path.exists():
        detail = f"found {len(ctx.schedule_tasks)} static task(s) for Week {ctx.week} Day {ctx.day}"
        _add_source(ctx, "project_schedule_weekN.json", "found", detail, schedule_path)
    else:
        _add_source(
            ctx,
            "project_schedule_weekN.json",
            "missing",
            f"missing project_schedule_week{ctx.week}.json",
            schedule_path,
        )

    raw_progress = load_task_progress(progress_path)
    ctx.progress_tasks = extract_tasks(raw_progress)
    if progress_path.exists():
        if ctx.progress_tasks:
            detail = f"found {len(ctx.progress_tasks)} progress task record(s)"
            _add_source(ctx, "task_progress_weekN.json", "found", detail, progress_path)
        else:
            _add_source(
                ctx,
                "task_progress_weekN.json",
                "empty",
                "progress file exists but contains no task records",
                progress_path,
            )
    else:
        _add_source(
            ctx, "task_progress_weekN.json", "missing", f"missing task_progress_week{ctx.week}.json", progress_path
        )


def _collect_previous_reports(ctx: MorningPlanningContext, recent_days: int) -> None:
    paths = resolve_project_paths(ctx.project_root)
    target_day = ctx.day - 1
    target_week = ctx.week
    if target_day < 1 and ctx.week > 1:
        target_week = ctx.week - 1
        target_day = 5

    reports = list_recent_files(paths.daily_reports, limit=40)
    if target_day >= 1:
        reports = [path for path in reports if f"Week{target_week}_Day{target_day}" in path.stem] or reports
    cutoff = _start_of_day(ctx.plan_date - timedelta(days=recent_days))
    ctx.previous_reports = [path for path in reports if _mtime(path) >= cutoff][:6]
    if ctx.previous_reports:
        _add_source(
            ctx,
            "previous daily activity summaries",
            "found",
            f"found {len(ctx.previous_reports)} recent previous daily report(s)",
            paths.daily_reports,
        )
    elif paths.daily_reports.exists():
        _add_source(
            ctx,
            "previous daily activity summaries",
            "empty",
            "daily report folder exists but no recent previous daily summaries matched",
            paths.daily_reports,
        )
    else:
        _add_source(
            ctx, "previous daily activity summaries", "missing", "daily report folder is missing", paths.daily_reports
        )

    for report in ctx.previous_reports:
        _parse_previous_report(ctx, report)
    ctx.previous_completed = _dedupe_text(ctx.previous_completed)
    ctx.previous_blockers = _dedupe_text(ctx.previous_blockers)
    ctx.previous_modified_files = _dedupe_text(ctx.previous_modified_files)
    ctx.previous_created_files = _dedupe_text(ctx.previous_created_files)
    ctx.previous_notes = _dedupe_text(ctx.previous_notes)


def _parse_previous_report(ctx: MorningPlanningContext, report: Path) -> None:
    if report.suffix.lower() == ".json":
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            ctx.warnings.append(f"Could not parse previous summary {report.name}: {exc}")
            return
        ctx.previous_completed.extend(_as_text_list(data.get("completed")))
        ctx.previous_completed.extend(_as_text_list(data.get("suggested_completed_items")))
        ctx.previous_blockers.extend(_as_text_list(data.get("blocked")))
        ctx.previous_blockers.extend(_as_text_list(data.get("blockers")))
        ctx.previous_notes.extend(_as_text_list(data.get("notes")))
        for key, target in [
            ("modified_files", ctx.previous_modified_files),
            ("created_files", ctx.previous_created_files),
        ]:
            for item in data.get(key, []) if isinstance(data.get(key), list) else []:
                if isinstance(item, dict):
                    value = _clean(item.get("path") or item.get("file") or item.get("name"))
                else:
                    value = _clean(item)
                if value:
                    target.append(value)
        for check in data.get("workbook_checks", []) if isinstance(data.get("workbook_checks"), list) else []:
            if isinstance(check, dict) and check.get("available") is True:
                ctx.previous_notes.append(f"Workbook check available: {_clean(check.get('workbook'))}")
        return

    if report.suffix.lower() not in {".md", ".txt"}:
        return
    try:
        lines = report.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        ctx.warnings.append(f"Could not read previous summary {report.name}: {exc}")
        return
    current = ""
    for raw in lines:
        line = raw.strip()
        if line.endswith(":") and not line.startswith("-"):
            current = line.rstrip(":").lower()
            continue
        if not line.startswith("- "):
            continue
        item = line[2:].strip()
        if not item:
            continue
        if "completed" in current:
            ctx.previous_completed.append(item)
        elif "need" in current or "block" in current:
            ctx.previous_blockers.append(item)
        elif "changed files" in current or "key changed files" in current:
            ctx.previous_modified_files.append(item)
        else:
            ctx.previous_notes.append(item)


def _collect_activity(ctx: MorningPlanningContext, limit: int) -> None:
    activity, warning = read_recent_activity(ctx.project_root, limit=limit)
    ctx.activity_entries = activity
    activity_path = resolve_project_paths(ctx.project_root).activity_logs / "activity_log.jsonl"
    if activity_path.exists() and activity:
        _add_source(ctx, "activity_log.jsonl", "found", f"read {len(activity)} recent tool/app run(s)", activity_path)
    elif activity_path.exists():
        _add_source(
            ctx, "activity_log.jsonl", "empty", "activity log exists but has no readable entries", activity_path
        )
    else:
        _add_source(ctx, "activity_log.jsonl", "missing", "activity log file is missing", activity_path)
    if warning:
        ctx.warnings.append(warning)


def _collect_workbook_state(ctx: MorningPlanningContext) -> None:
    paths = resolve_project_paths(ctx.project_root)
    workbook = paths.master_workbook
    ctx.workbook_path = workbook
    if not workbook.exists():
        _add_source(ctx, "EOAT master workbook", "missing", "master workbook is missing", workbook)
        _add_source(
            ctx,
            "open action items",
            "missing",
            "could not check action items because master workbook is missing",
            workbook,
        )
        return

    try:
        ctx.workbook_mtime = _mtime(workbook)
        sheets = workbook_sheet_names(workbook)
        for sheet in WORKBOOK_SHEETS:
            rows = row_dicts(workbook, sheet)
            ctx.workbook_counts[sheet] = len(rows)
            if sheet == "EOAT Inventory":
                ctx.audit_rows = rows
            elif sheet == "Photo Index":
                ctx.photo_rows = rows
            elif sheet == "Action Items":
                ctx.action_source_checked = True
                ctx.open_actions = [row for row in rows if _clean(row.get("Status")).lower() in OPEN_ACTION_STATUSES]
        missing = [sheet for sheet in WORKBOOK_SHEETS if sheet not in sheets]
        detail = "read workbook; rows by sheet: " + ", ".join(
            f"{sheet}={ctx.workbook_counts.get(sheet, 0)}" for sheet in WORKBOOK_SHEETS
        )
        if missing:
            detail += f"; missing sheets: {', '.join(missing)}"
        _add_source(ctx, "EOAT master workbook", "found", detail, workbook)
        if "Action Items" in sheets:
            status = "found" if ctx.open_actions else "empty"
            detail = f"checked Action Items sheet; {len(ctx.open_actions)} open item(s)"
            _add_source(ctx, "open action items", status, detail, workbook)
        else:
            _add_source(
                ctx, "open action items", "missing", "Action Items sheet is missing from master workbook", workbook
            )
    except Exception as exc:
        _add_source(ctx, "EOAT master workbook", "error", f"could not read workbook: {exc}", workbook)
        _add_source(ctx, "open action items", "error", f"could not check action items: {exc}", workbook)
        ctx.warnings.append(f"Workbook state collection failed: {exc}")


def _collect_validation_and_reports(ctx: MorningPlanningContext) -> None:
    paths = resolve_project_paths(ctx.project_root)
    ctx.validation_reports = list_recent_files(paths.validation_reports, limit=6)
    if ctx.validation_reports:
        _add_source(
            ctx,
            "workbook validation reports",
            "found",
            f"found {len(ctx.validation_reports)} recent validation/system audit report(s)",
            paths.validation_reports,
        )
    elif paths.validation_reports.exists():
        _add_source(
            ctx,
            "workbook validation reports",
            "empty",
            "validation report folder exists but no reports were found",
            paths.validation_reports,
        )
    else:
        _add_source(
            ctx,
            "workbook validation reports",
            "missing",
            "validation report folder is missing",
            paths.validation_reports,
        )

    recent: list[Path] = []
    for folder in report_folders(ctx.project_root, limit=3):
        if folder.label == "Morning Plans":
            continue
        recent.extend(folder.recent_files)
    ctx.recent_reports = sorted(
        set(recent), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True
    )[:12]
    if ctx.recent_reports:
        _add_source(
            ctx,
            "generated reports from last 1-3 days",
            "found",
            f"found {len(ctx.recent_reports)} recent generated report/data file(s)",
            ctx.project_root,
        )
    else:
        _add_source(
            ctx, "generated reports from last 1-3 days", "empty", "no recent generated reports found", ctx.project_root
        )


def _collect_recent_modified_files(ctx: MorningPlanningContext, recent_days: int) -> None:
    if not ctx.project_root.exists():
        _add_source(ctx, "recent files modified", "missing", "project root is missing", ctx.project_root)
        return
    cutoff = _start_of_day(ctx.plan_date - timedelta(days=recent_days))
    files: list[RecentFile] = []
    try:
        for path in ctx.project_root.rglob("*"):
            if not path.is_file():
                continue
            parts = set(path.parts)
            if parts & IGNORED_RECENT_PARTS:
                continue
            if path.suffix.lower() not in RECENT_FILE_EXTENSIONS:
                continue
            modified = _mtime(path)
            if modified < cutoff:
                continue
            files.append(
                RecentFile(path=path.relative_to(ctx.project_root), modified=modified, size=path.stat().st_size)
            )
    except OSError as exc:
        _add_source(ctx, "recent files modified", "error", f"could not scan project files: {exc}", ctx.project_root)
        ctx.warnings.append(f"Recent file scan failed: {exc}")
        return
    ctx.recent_modified_files = sorted(files, key=lambda item: item.modified, reverse=True)[:14]
    if ctx.recent_modified_files:
        _add_source(
            ctx,
            "recent files modified",
            "found",
            f"found {len(ctx.recent_modified_files)} recently modified project file(s)",
            ctx.project_root,
        )
    else:
        _add_source(
            ctx,
            "recent files modified",
            "empty",
            f"no files modified in the last {recent_days} day(s)",
            ctx.project_root,
        )


def _collect_press_sources(ctx: MorningPlanningContext) -> None:
    data_dir = reference_data_dir(ctx.project_root)
    master = data_dir / MASTER_FILE_NAME
    capacity = data_dir / CAPACITY_FILE_NAME
    ctx.press_files = {
        "master_press_list": master if master.exists() else None,
        "press_capacity": capacity if capacity.exists() else None,
    }
    found = [path.name for path in [master, capacity] if path.exists()]
    missing = [path.name for path in [master, capacity] if not path.exists()]
    if found:
        _add_source(
            ctx,
            "imported press list / press capacity files",
            "found",
            f"found {', '.join(found)}; missing {', '.join(missing) if missing else 'none'}",
            data_dir,
        )
    else:
        _add_source(
            ctx, "imported press list / press capacity files", "missing", f"missing {', '.join(missing)}", data_dir
        )


def _collect_config_state(ctx: MorningPlanningContext) -> None:
    candidates = [
        ctx.project_root.parent / "config" / "user_config.json",
        ctx.project_root / "00_Project_Admin" / "fake_user_config.json",
        Path("config") / "user_config.json",
    ]
    config_path = next((path for path in candidates if path.exists()), None)
    if not config_path:
        _add_source(ctx, "known user/app configuration changes", "missing", "no user configuration file found", "")
        return
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _add_source(ctx, "known user/app configuration changes", "error", f"could not read config: {exc}", config_path)
        return
    for key in ["project_start_date", "theme", "skip_weekends", "holidays"]:
        if key in data:
            ctx.config_state.append(f"{key}: {data[key]}")
    _add_source(
        ctx,
        "known user/app configuration changes",
        "found",
        f"read config values: {', '.join(ctx.config_state) if ctx.config_state else 'no tracked values'}",
        config_path,
    )


def _collect_app_state(ctx: MorningPlanningContext) -> None:
    root = Path(__file__).resolve().parent.parent
    audit_page = root / "app" / "pages" / "audit.py"
    theme_file = root / "app" / "theme.py"
    press_lookup = root / "core" / "press_lookup.py"
    docs_dark = root / "docs" / "EOAT_Atlas_Responsiveness_and_Dark_Mode_Report.md"

    audit_text = _read_text(audit_page)
    theme_text = _read_text(theme_file)
    press_text = _read_text(press_lookup)
    if "Kato Gray" in audit_text:
        ctx.app_state.append("EOAT Audit page default auditor is configured as Kato Gray.")
    else:
        ctx.app_pending.append("EOAT Audit page default auditor is pending.")
    if "Plant 4" in audit_text and "Cleanroom" in audit_text:
        ctx.app_state.append("Plant/Area menu includes Plant 4 and Cleanroom.")
    else:
        ctx.app_pending.append("Plant/Area menu options are pending.")
    if "lookup_press" in audit_text and MASTER_FILE_NAME in press_text and CAPACITY_FILE_NAME in press_text:
        ctx.app_state.append(
            "Machine number lookup/autofill can use master press list and Plant 4 capacity data when those files are present."
        )
    else:
        ctx.app_pending.append("Machine number autofill from press/capacity data is pending.")
    if "dark" in theme_text and "light" in theme_text:
        ctx.app_state.append("Light/dark theme support is implemented.")
    else:
        ctx.app_pending.append("EOAT Atlas dark mode/theme support is pending.")
    if docs_dark.exists():
        ctx.app_state.append("Recent responsiveness/dark-mode work is documented.")

    if ctx.app_state or ctx.app_pending:
        _add_source(
            ctx,
            "real app/app-state awareness",
            "found",
            f"detected {len(ctx.app_state)} implemented app feature(s) and {len(ctx.app_pending)} pending item(s)",
            root,
        )
    else:
        _add_source(ctx, "real app/app-state awareness", "empty", "no tracked app-state signals found", root)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    except OSError:
        return ""


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        output: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = _clean(item.get("summary") or item.get("task") or item.get("path") or item.get("name"))
            else:
                text = _clean(item)
            if text:
                output.append(text)
        return output
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = _clean(value)
        normalized = text.lower()
        for suffix in [" - modified", " - created", " - added"]:
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
        if not text or normalized in seen:
            continue
        seen.add(normalized)
        output.append(text)
    return output


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _start_of_day(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
