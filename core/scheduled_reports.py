from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .constants import TOOLKIT_ROOT
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory
from .schedule import resolve_project_day_for_project
from .weekly_summary import generate_weekly_summary

DAILY_TASK_NAME = "EOAT Daily Summary"
WEEKLY_TASK_NAME = "EOAT Weekly Summary"
DAILY_EXPECTED_WEEKDAYS = {0, 1, 2, 3}
WEEKLY_EXPECTED_WEEKDAY = 4
SCHEDULE_TIME_LABEL = "7:00 PM"
SCHEDULE_HOUR = 19
SCHEDULE_MINUTE = 0
DEFAULT_SCHEDULE_TIMEZONE = "America/New_York"
TEST_REPORTS_FOLDER = "Test_Reports"


@dataclass(frozen=True)
class ReportFileInfo:
    path: Path
    report_date: date | None
    week: int | None = None
    day: int | None = None


@dataclass(frozen=True)
class SummaryScheduleDecision:
    automation: str
    decision: str
    reason: str
    target_date: date
    local_datetime: datetime
    timezone_name: str
    output_path: Path | None = None
    week: int | None = None
    day: int | None = None

    @property
    def should_run(self) -> bool:
        return self.decision == "run"

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "automation": self.automation,
            "decision": self.decision,
            "reason": self.reason,
            "target_date": self.target_date.isoformat(),
            "local_datetime": self.local_datetime.isoformat(timespec="seconds"),
            "timezone": self.timezone_name,
            "output_path": str(self.output_path or ""),
            "week": self.week,
            "day": self.day,
        }


def scheduled_tools_log_path(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).logs / "scheduled_tools.log"


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def append_scheduled_log(project_root: str | Path, line: str) -> Path | None:
    try:
        path = scheduled_tools_log_path(project_root)
        ensure_directory(path.parent)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{_timestamp()}] {line}\n")
        return path
    except Exception:
        return None


def _parse_report_date(text: str) -> date | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _daily_report_infos(project_root: str | Path) -> list[ReportFileInfo]:
    folder = resolve_project_paths(project_root).daily_reports
    if not folder.exists():
        return []
    pattern = re.compile(r"Week(\d+)_Day(\d+)_Status_(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
    reports: list[ReportFileInfo] = []
    for path in folder.glob("Week*_Day*_Status_*.md"):
        match = pattern.search(path.stem)
        if not match:
            continue
        week, day, report_date = match.groups()
        try:
            reports.append(ReportFileInfo(path=path, report_date=date.fromisoformat(report_date), week=int(week), day=int(day)))
        except ValueError:
            continue
    return sorted(reports, key=lambda item: (item.report_date or date.min, item.path.stat().st_mtime), reverse=True)


def _weekly_report_infos(project_root: str | Path) -> list[ReportFileInfo]:
    folder = resolve_project_paths(project_root).weekly_reports
    if not folder.exists():
        return []
    pattern = re.compile(r"Week(\d+)_Summary_(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
    reports: list[ReportFileInfo] = []
    for path in folder.glob("Week*_Summary_*.md"):
        match = pattern.search(path.stem)
        if not match:
            continue
        week, report_date = match.groups()
        try:
            reports.append(ReportFileInfo(path=path, report_date=date.fromisoformat(report_date), week=int(week)))
        except ValueError:
            continue
    return sorted(reports, key=lambda item: (item.report_date or date.min, item.path.stat().st_mtime), reverse=True)


def find_latest_daily_summary(project_root: str | Path) -> ReportFileInfo | None:
    reports = _daily_report_infos(project_root)
    return reports[0] if reports else None


def find_latest_weekly_summary(project_root: str | Path) -> ReportFileInfo | None:
    reports = _weekly_report_infos(project_root)
    return reports[0] if reports else None


def daily_summary_exists_for_date(project_root: str | Path, target_date: date) -> bool:
    return any(info.report_date == target_date for info in _daily_report_infos(project_root))


def weekly_summary_exists_for_date(project_root: str | Path, target_date: date) -> bool:
    return any(info.report_date == target_date for info in _weekly_report_infos(project_root))


def expected_daily_summary_day(target_date: date) -> bool:
    return target_date.weekday() in DAILY_EXPECTED_WEEKDAYS


def expected_weekly_summary_day(target_date: date) -> bool:
    return target_date.weekday() == WEEKLY_EXPECTED_WEEKDAY


def scheduler_timezone(timezone_name: str = DEFAULT_SCHEDULE_TIMEZONE):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == DEFAULT_SCHEDULE_TIMEZONE:
            return timezone(timedelta(hours=-4), DEFAULT_SCHEDULE_TIMEZONE)
        raise


def local_scheduler_datetime(current: datetime | None = None, timezone_name: str = DEFAULT_SCHEDULE_TIMEZONE) -> datetime:
    tz = scheduler_timezone(timezone_name)
    if current is None:
        return datetime.now(tz)
    if current.tzinfo is None:
        return current.replace(tzinfo=tz)
    return current.astimezone(tz)


def dry_run_reports_root(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).project_admin / TEST_REPORTS_FOLDER


def dry_run_daily_reports_dir(project_root: str | Path) -> Path:
    return dry_run_reports_root(project_root) / "Daily_Status_Reports"


def dry_run_weekly_reports_dir(project_root: str | Path) -> Path:
    return dry_run_reports_root(project_root) / "Weekly_Status_Reports"


def _scheduled_time_reached(local_now: datetime) -> bool:
    return local_now.time() >= datetime_time(SCHEDULE_HOUR, SCHEDULE_MINUTE)


def _daily_expected_report_path(project_root: str | Path, target_date: date, *, dry_run: bool, resolved_week: int, resolved_day: int, output_dir: str | Path | None = None) -> Path:
    folder = Path(output_dir).expanduser() if output_dir else (dry_run_daily_reports_dir(project_root) if dry_run else resolve_project_paths(project_root).daily_reports)
    suffix = "_DRY_RUN" if dry_run else ""
    return folder / f"Week{resolved_week}_Day{resolved_day}_Status_{target_date.isoformat()}{suffix}.md"


def _weekly_expected_report_path(project_root: str | Path, target_date: date, *, dry_run: bool, week: int, output_dir: str | Path | None = None) -> Path:
    folder = Path(output_dir).expanduser() if output_dir else (dry_run_weekly_reports_dir(project_root) if dry_run else resolve_project_paths(project_root).weekly_reports)
    suffix = "_DRY_RUN" if dry_run else ""
    return folder / f"Week{week}_Summary_{target_date.isoformat()}{suffix}.md"


def evaluate_summary_schedule(
    project_root: str | Path,
    automation: str,
    *,
    current_datetime: datetime | None = None,
    timezone_name: str = DEFAULT_SCHEDULE_TIMEZONE,
    dry_run: bool = False,
    force: bool = False,
    project_start_date: str = "",
    skip_weekends: bool = True,
    holidays: list[str] | None = None,
) -> SummaryScheduleDecision:
    local_now = local_scheduler_datetime(current_datetime, timezone_name)
    target_date = local_now.date()
    automation = automation.strip().lower()

    if automation == "daily_summary":
        resolved = resolve_project_day_for_project(
            project_root,
            current_date=target_date,
            project_start_date=project_start_date,
            skip_weekends=skip_weekends,
            holidays=holidays or [],
        )
        output_path = _daily_expected_report_path(project_root, target_date, dry_run=dry_run, resolved_week=resolved.week, resolved_day=resolved.day)
        if not expected_daily_summary_day(target_date):
            return SummaryScheduleDecision(automation, "skip", "not a Monday-Thursday daily summary day", target_date, local_now, timezone_name, output_path, resolved.week, resolved.day)
        if not _scheduled_time_reached(local_now):
            return SummaryScheduleDecision(automation, "skip", f"before scheduled time {SCHEDULE_TIME_LABEL}", target_date, local_now, timezone_name, output_path, resolved.week, resolved.day)
        if output_path.exists() and not force:
            return SummaryScheduleDecision(automation, "skip", "daily summary already exists for this date", target_date, local_now, timezone_name, output_path, resolved.week, resolved.day)
        return SummaryScheduleDecision(automation, "run", "weekday Monday-Thursday at or after 19:00", target_date, local_now, timezone_name, output_path, resolved.week, resolved.day)

    if automation == "weekly_summary":
        resolved = resolve_project_day_for_project(
            project_root,
            current_date=target_date,
            project_start_date=project_start_date,
            skip_weekends=skip_weekends,
            holidays=holidays or [],
            manual_day=5,
        )
        target_week = resolved.week
        output_path = _weekly_expected_report_path(project_root, target_date, dry_run=dry_run, week=target_week)
        if not expected_weekly_summary_day(target_date):
            return SummaryScheduleDecision(automation, "skip", "not a Friday weekly summary day", target_date, local_now, timezone_name, output_path, target_week, 5)
        if not _scheduled_time_reached(local_now):
            return SummaryScheduleDecision(automation, "skip", f"before scheduled time {SCHEDULE_TIME_LABEL}", target_date, local_now, timezone_name, output_path, target_week, 5)
        if output_path.exists() and not force:
            return SummaryScheduleDecision(automation, "skip", "weekly summary already exists for this date", target_date, local_now, timezone_name, output_path, target_week, 5)
        return SummaryScheduleDecision(automation, "run", "Friday at or after 19:00", target_date, local_now, timezone_name, output_path, target_week, 5)

    return SummaryScheduleDecision(automation, "skip", f"unknown automation: {automation}", target_date, local_now, timezone_name)


def log_scheduled_attempt(
    project_root: str | Path,
    *,
    automation: str,
    mode: str,
    dry_run: bool,
    decision: str,
    reason: str,
    status: str,
    timestamp: datetime | None = None,
    timezone_name: str = DEFAULT_SCHEDULE_TIMEZONE,
    output_path: str | Path = "",
    error: str = "",
    duration_seconds: float | None = None,
) -> Path | None:
    local_now = local_scheduler_datetime(timestamp, timezone_name)
    entry: dict[str, Any] = {
        "timestamp": local_now.isoformat(timespec="seconds"),
        "local_timezone": timezone_name,
        "automation": automation,
        "mode": mode,
        "dry_run": dry_run,
        "decision": decision,
        "reason": reason,
        "output_path": str(output_path or ""),
        "status": status,
        "error": error,
        "duration_seconds": round(duration_seconds, 2) if duration_seconds is not None else None,
    }
    try:
        path = scheduled_tools_log_path(project_root)
        ensure_directory(path.parent)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
        return path
    except Exception:
        return None


def detect_missed_daily_summaries(project_root: str | Path, today: date | None = None, lookback_days: int = 7) -> list[date]:
    current = today or date.today()
    missed: list[date] = []
    for offset in range(lookback_days):
        candidate = current - timedelta(days=offset)
        if expected_daily_summary_day(candidate) and not daily_summary_exists_for_date(project_root, candidate):
            missed.append(candidate)
    return sorted(missed)


def detect_missed_weekly_summary(project_root: str | Path, today: date | None = None, lookback_days: int = 7) -> list[date]:
    current = today or date.today()
    missed: list[date] = []
    for offset in range(lookback_days):
        candidate = current - timedelta(days=offset)
        if expected_weekly_summary_day(candidate) and not weekly_summary_exists_for_date(project_root, candidate):
            missed.append(candidate)
    return sorted(missed)


def _last_scheduled_log_status(project_root: str | Path, tool_name: str) -> dict[str, str]:
    path = scheduled_tools_log_path(project_root)
    if not path.exists():
        return {}
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if tool_name in line]
    except OSError:
        return {}
    if not lines:
        return {}
    latest = lines[-1]
    try:
        parsed = json.loads(latest)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        status_map = {
            "success": "Success",
            "failed": "Failed",
            "failure": "Failed",
            "skipped": "Skipped",
            "started": "Started",
        }
        raw_status = str(parsed.get("status") or "").lower()
        return {
            "last_log_line": latest,
            "last_status": status_map.get(raw_status, raw_status.title() if raw_status else "Unknown"),
            "last_error": str(parsed.get("error") or ""),
            "last_generated_report": str(parsed.get("output_path") or ""),
        }
    status = "Unknown"
    if " SUCCESS " in f" {latest} ":
        status = "Success"
    elif " FAILURE " in f" {latest} ":
        status = "Failed"
    return {"last_log_line": latest, "last_status": status}


def _task_status(task_name: str) -> dict[str, Any]:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        (
            f"$task = Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue; "
            "if ($null -eq $task) { @{installed=$false} | ConvertTo-Json -Compress } "
            "else { $info = Get-ScheduledTaskInfo -TaskName $task.TaskName -ErrorAction SilentlyContinue; "
            "@{installed=$true; state=[string]$task.State; last_run_time=[string]$info.LastRunTime; "
            "last_result=[string]$info.LastTaskResult; next_run_time=[string]$info.NextRunTime} | ConvertTo-Json -Compress }"
        ),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    except Exception as exc:
        return {"installed": "Unknown", "warning": str(exc)}
    if completed.returncode != 0:
        return {"installed": "Unknown", "warning": completed.stderr.strip() or completed.stdout.strip()}
    try:
        return json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"installed": "Unknown", "warning": "Could not parse scheduled task status."}


def get_scheduled_report_status(project_root: str | Path, today: date | None = None, check_tasks: bool = True) -> dict[str, Any]:
    daily = find_latest_daily_summary(project_root)
    weekly = find_latest_weekly_summary(project_root)
    daily_task = _task_status(DAILY_TASK_NAME) if check_tasks else {"installed": "Unknown"}
    weekly_task = _task_status(WEEKLY_TASK_NAME) if check_tasks else {"installed": "Unknown"}
    daily_log = _last_scheduled_log_status(project_root, "daily_summary")
    weekly_log = _last_scheduled_log_status(project_root, "weekly_summary")
    missed_daily = detect_missed_daily_summaries(project_root, today=today)
    missed_weekly = detect_missed_weekly_summary(project_root, today=today)
    current_date = today or date.today()
    next_daily = next_expected_run(current_date, "daily_summary")
    next_weekly = next_expected_run(current_date, "weekly_summary")
    return {
        "daily": {
            "schedule": f"Monday-Thursday at {SCHEDULE_TIME_LABEL}",
            "task": daily_task,
            "last_report": str(daily.path) if daily else "",
            "last_report_date": daily.report_date.isoformat() if daily and daily.report_date else "",
            "missed_dates": [item.isoformat() for item in missed_daily],
            "next_expected_run": next_daily.isoformat(timespec="seconds"),
            **daily_log,
        },
        "weekly": {
            "schedule": f"Friday at {SCHEDULE_TIME_LABEL}",
            "task": weekly_task,
            "last_report": str(weekly.path) if weekly else "",
            "last_report_date": weekly.report_date.isoformat() if weekly and weekly.report_date else "",
            "missed_dates": [item.isoformat() for item in missed_weekly],
            "next_expected_run": next_weekly.isoformat(timespec="seconds"),
            **weekly_log,
        },
        "scheduled_log": str(scheduled_tools_log_path(project_root)),
    }


def next_expected_run(start_date: date, automation: str, timezone_name: str = DEFAULT_SCHEDULE_TIMEZONE) -> datetime:
    tz = scheduler_timezone(timezone_name)
    cursor = start_date
    for _ in range(14):
        if automation == "daily_summary" and expected_daily_summary_day(cursor):
            return datetime.combine(cursor, datetime_time(SCHEDULE_HOUR, SCHEDULE_MINUTE), tzinfo=tz)
        if automation == "weekly_summary" and expected_weekly_summary_day(cursor):
            return datetime.combine(cursor, datetime_time(SCHEDULE_HOUR, SCHEDULE_MINUTE), tzinfo=tz)
        cursor += timedelta(days=1)
    return datetime.combine(start_date, datetime_time(SCHEDULE_HOUR, SCHEDULE_MINUTE), tzinfo=tz)


def _tool_result_from_subprocess(tool_id: str, tool_name: str, completed: subprocess.CompletedProcess[str], started: float, output_path: str = "") -> ToolResult:
    elapsed = time.perf_counter() - started
    output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
    if not output_path:
        for line in output.splitlines():
            if "Created daily status report:" in line:
                output_path = line.split("Created daily status report:", 1)[1].strip()
                break
    if completed.returncode == 0:
        details = [line for line in output.splitlines() if line.strip()][:20]
        files = [output_path] if output_path else []
        return ToolResult.ok(tool_id, tool_name, f"{tool_name} completed.", details=details, files_created=files, output_reports=files, duration_seconds=elapsed)
    return ToolResult.fail(tool_id, tool_name, f"{tool_name} failed.", errors=[output or f"Exit code {completed.returncode}"], duration_seconds=elapsed)


def run_daily_summary_now(
    project_root: str | Path,
    *,
    scheduled: bool = False,
    dry_run: bool = False,
    report_date: date | None = None,
    week: int | None = None,
    day: int | None = None,
    output_dir: str | Path | None = None,
    mode: str | None = None,
    decision_reason: str = "manual daily summary request",
    scheduler_now: datetime | None = None,
    timezone_name: str = DEFAULT_SCHEDULE_TIMEZONE,
    project_start_date: str = "",
    skip_weekends: bool = True,
    holidays: list[str] | None = None,
) -> ToolResult:
    started = time.perf_counter()
    target_date = report_date or date.today()
    resolved = resolve_project_day_for_project(
        project_root,
        current_date=target_date,
        project_start_date=project_start_date,
        skip_weekends=skip_weekends,
        holidays=holidays or [],
        manual_week=week,
        manual_day=day,
        manual_override=week is not None and day is not None,
    )
    paths = resolve_project_paths(project_root)
    output_folder = Path(output_dir).expanduser() if output_dir else (dry_run_daily_reports_dir(project_root) if dry_run else paths.daily_reports)
    expected_report = _daily_expected_report_path(project_root, target_date, dry_run=dry_run, resolved_week=resolved.week, resolved_day=resolved.day, output_dir=output_folder)
    run_mode = mode or ("scheduled" if scheduled else "manual")
    if expected_report.exists():
        elapsed = time.perf_counter() - started
        log_scheduled_attempt(
            project_root,
            automation="daily_summary",
            mode=run_mode,
            dry_run=dry_run,
            decision="skip",
            reason="daily summary already exists for this date",
            status="skipped",
            timestamp=scheduler_now,
            timezone_name=timezone_name,
            output_path=expected_report,
            duration_seconds=elapsed,
        )
        result = ToolResult.ok(
            "daily_status_summary",
            "Daily Status Summary Generator",
            "Daily summary already exists; no duplicate report was created.",
            details=[f"Existing report: {expected_report}"],
            output_reports=[str(expected_report)],
            metrics={"scheduled": scheduled, "dry_run": dry_run, "skipped_duplicate": True},
            duration_seconds=elapsed,
        )
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
        return result
    log_scheduled_attempt(
        project_root,
        automation="daily_summary",
        mode=run_mode,
        dry_run=dry_run,
        decision="run",
        reason=decision_reason,
        status="started",
        timestamp=scheduler_now,
        timezone_name=timezone_name,
        output_path=expected_report,
    )
    script = TOOLKIT_ROOT / "daily_status_summary.py"
    args = [
        sys.executable,
        str(script),
        "--project-root",
        str(project_root),
        "--week",
        str(resolved.week),
        "--day",
        str(resolved.day),
        "--date",
        target_date.isoformat(),
        "--scheduled",
        "--output-dir",
        str(output_folder),
        "--completed",
        "Reviewed EOAT Command Center dashboard status",
        "--need",
        "Confirm next EOAT project priority with mentor or supervisor",
        "--plan",
        "Continue EOAT project execution from the current schedule",
        "--note",
        "Generated by EOAT scheduled summary automation.",
    ]
    if dry_run:
        args.append("--dry-run")
    completed = subprocess.run(args, cwd=TOOLKIT_ROOT, capture_output=True, text=True, timeout=180, check=False)
    result = _tool_result_from_subprocess("daily_status_summary", "Daily Status Summary Generator", completed, started, str(expected_report) if expected_report.exists() else "")
    result.metrics["scheduled"] = scheduled
    result.metrics["dry_run"] = dry_run
    if result.success:
        log_scheduled_attempt(
            project_root,
            automation="daily_summary",
            mode=run_mode,
            dry_run=dry_run,
            decision="run",
            reason=decision_reason,
            status="success",
            timestamp=scheduler_now,
            timezone_name=timezone_name,
            output_path=result.output_reports[0] if result.output_reports else expected_report,
            duration_seconds=result.duration_seconds,
        )
    else:
        log_scheduled_attempt(
            project_root,
            automation="daily_summary",
            mode=run_mode,
            dry_run=dry_run,
            decision="run",
            reason=decision_reason,
            status="failed",
            timestamp=scheduler_now,
            timezone_name=timezone_name,
            output_path=expected_report,
            error="; ".join(result.errors)[:400],
            duration_seconds=result.duration_seconds,
        )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result


def run_weekly_summary_now(
    project_root: str | Path,
    *,
    scheduled: bool = False,
    dry_run: bool = False,
    report_date: date | None = None,
    week: int | None = None,
    notes: str = "",
    output_dir: str | Path | None = None,
    mode: str | None = None,
    decision_reason: str = "manual weekly summary request",
    scheduler_now: datetime | None = None,
    timezone_name: str = DEFAULT_SCHEDULE_TIMEZONE,
    project_start_date: str = "",
    skip_weekends: bool = True,
    holidays: list[str] | None = None,
) -> ToolResult:
    started = time.perf_counter()
    target_date = report_date or date.today()
    resolved = resolve_project_day_for_project(
        project_root,
        current_date=target_date,
        project_start_date=project_start_date,
        skip_weekends=skip_weekends,
        holidays=holidays or [],
        manual_week=week,
        manual_day=5,
        manual_override=week is not None,
    )
    target_week = int(week or resolved.week)
    output_folder = Path(output_dir).expanduser() if output_dir else (dry_run_weekly_reports_dir(project_root) if dry_run else resolve_project_paths(project_root).weekly_reports)
    expected_report = _weekly_expected_report_path(project_root, target_date, dry_run=dry_run, week=target_week, output_dir=output_folder)
    run_mode = mode or ("scheduled" if scheduled else "manual")
    if expected_report.exists():
        elapsed = time.perf_counter() - started
        log_scheduled_attempt(
            project_root,
            automation="weekly_summary",
            mode=run_mode,
            dry_run=dry_run,
            decision="skip",
            reason="weekly summary already exists for this date",
            status="skipped",
            timestamp=scheduler_now,
            timezone_name=timezone_name,
            output_path=expected_report,
            duration_seconds=elapsed,
        )
        result = ToolResult.ok(
            "weekly_summary",
            "Weekly Summary Generator",
            "Weekly summary already exists; no duplicate report was created.",
            details=[f"Existing report: {expected_report}"],
            output_reports=[str(expected_report)],
            metrics={"scheduled": scheduled, "dry_run": dry_run, "skipped_duplicate": True},
            duration_seconds=elapsed,
        )
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
        return result
    log_scheduled_attempt(
        project_root,
        automation="weekly_summary",
        mode=run_mode,
        dry_run=dry_run,
        decision="run",
        reason=decision_reason,
        status="started",
        timestamp=scheduler_now,
        timezone_name=timezone_name,
        output_path=expected_report,
    )
    result = generate_weekly_summary(project_root, week=target_week, notes=notes, scheduled=scheduled, output_dir=output_folder, report_date=target_date, dry_run=dry_run)
    result.metrics["scheduled"] = scheduled
    result.metrics["dry_run"] = dry_run
    if result.success:
        output = result.output_reports[0] if result.output_reports else ""
        log_scheduled_attempt(
            project_root,
            automation="weekly_summary",
            mode=run_mode,
            dry_run=dry_run,
            decision="run",
            reason=decision_reason,
            status="success",
            timestamp=scheduler_now,
            timezone_name=timezone_name,
            output_path=output,
            duration_seconds=result.duration_seconds,
        )
    else:
        log_scheduled_attempt(
            project_root,
            automation="weekly_summary",
            mode=run_mode,
            dry_run=dry_run,
            decision="run",
            reason=decision_reason,
            status="failed",
            timestamp=scheduler_now,
            timezone_name=timezone_name,
            output_path=expected_report,
            error="; ".join(result.errors)[:400],
            duration_seconds=result.duration_seconds,
        )
    return result


def run_due_scheduled_summaries(
    project_root: str | Path,
    *,
    current_datetime: datetime | None = None,
    timezone_name: str = DEFAULT_SCHEDULE_TIMEZONE,
    dry_run: bool = False,
    run_daily: bool = True,
    run_weekly: bool = True,
    force: bool = False,
    project_start_date: str = "",
    skip_weekends: bool = True,
    holidays: list[str] | None = None,
) -> ToolResult:
    started = time.perf_counter()
    local_now = local_scheduler_datetime(current_datetime, timezone_name)
    requested = []
    if run_daily:
        requested.append("daily_summary")
    if run_weekly:
        requested.append("weekly_summary")

    results: list[ToolResult] = []
    decisions: list[dict[str, Any]] = []
    for automation in requested:
        decision = evaluate_summary_schedule(
            project_root,
            automation,
            current_datetime=local_now,
            timezone_name=timezone_name,
            dry_run=dry_run,
            force=force,
            project_start_date=project_start_date,
            skip_weekends=skip_weekends,
            holidays=holidays,
        )
        decisions.append(decision.to_log_dict())
        if not decision.should_run:
            log_scheduled_attempt(
                project_root,
                automation=automation,
                mode="scheduled",
                dry_run=dry_run,
                decision=decision.decision,
                reason=decision.reason,
                status="skipped",
                timestamp=local_now,
                timezone_name=timezone_name,
                output_path=decision.output_path or "",
            )
            results.append(
                ToolResult.ok(
                    automation,
                    "Scheduled Summary Decision",
                    f"{automation} skipped: {decision.reason}.",
                    details=[decision.reason],
                    output_reports=[str(decision.output_path)] if decision.output_path else [],
                    metrics={**decision.to_log_dict(), "dry_run": dry_run},
                )
            )
            continue

        if automation == "daily_summary":
            result = run_daily_summary_now(
                project_root,
                scheduled=True,
                dry_run=dry_run,
                report_date=decision.target_date,
                week=decision.week,
                day=decision.day,
                mode="scheduled",
                decision_reason=decision.reason,
                scheduler_now=local_now,
                timezone_name=timezone_name,
                project_start_date=project_start_date,
                skip_weekends=skip_weekends,
                holidays=holidays,
            )
        else:
            result = run_weekly_summary_now(
                project_root,
                scheduled=True,
                dry_run=dry_run,
                report_date=decision.target_date,
                week=decision.week,
                notes="Generated by EOAT scheduled summary automation.",
                mode="scheduled",
                decision_reason=decision.reason,
                scheduler_now=local_now,
                timezone_name=timezone_name,
                project_start_date=project_start_date,
                skip_weekends=skip_weekends,
                holidays=holidays,
            )
        result.metrics["scheduler_decision"] = decision.to_log_dict()
        results.append(result)

    success = all(result.success for result in results)
    errors = [error for result in results for error in result.errors]
    warnings = [warning for result in results for warning in result.warnings]
    output_reports = [path for result in results for path in result.output_reports]
    files_created = [path for result in results for path in result.files_created]
    status_word = "completed" if success else "failed"
    return ToolResult(
        tool_id="scheduled_summaries",
        tool_name="Scheduled Summary Automation",
        success=success,
        summary=f"Scheduled summary automation {status_word} for {local_now.isoformat(timespec='seconds')}.",
        details=[result.summary for result in results],
        warnings=warnings,
        errors=errors,
        files_created=files_created,
        output_reports=output_reports,
        metrics={
            "dry_run": dry_run,
            "timezone": timezone_name,
            "local_datetime": local_now.isoformat(timespec="seconds"),
            "decisions": decisions,
        },
        duration_seconds=time.perf_counter() - started,
    )


def _run_schedule_script(script_name: str, project_root: str | Path, *, dry_run: bool = False) -> ToolResult:
    started = time.perf_counter()
    script = TOOLKIT_ROOT / "scripts" / script_name
    if not script.exists():
        return ToolResult.fail("summary_schedule_tasks", "Summary Schedule Tasks", "Schedule script is missing.", errors=[str(script)])
    args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-ProjectRoot", str(project_root)]
    if dry_run:
        args.append("-DryRun")
    try:
        completed = subprocess.run(args, cwd=TOOLKIT_ROOT, capture_output=True, text=True, timeout=60, check=False)
    except Exception as exc:
        return ToolResult.fail("summary_schedule_tasks", "Summary Schedule Tasks", "Could not run schedule script.", errors=[str(exc)])
    return _tool_result_from_subprocess("summary_schedule_tasks", "Summary Schedule Tasks", completed, started)


def install_or_repair_schedules(project_root: str | Path, dry_run: bool = False) -> ToolResult:
    return _run_schedule_script("install_summary_schedules.ps1", project_root, dry_run=dry_run)


def uninstall_schedules(project_root: str | Path, dry_run: bool = False) -> ToolResult:
    return _run_schedule_script("uninstall_summary_schedules.ps1", project_root, dry_run=dry_run)
