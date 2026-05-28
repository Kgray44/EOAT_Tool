from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .constants import TOOLKIT_ROOT
from .logging import log_tool_run
from .paths import resolve_project_paths
from .report_context import build_daily_report_context, daily_summary_cli_items
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
EMERGENCY_LOG_FILE_NAME = "eoat_scheduled_task_emergency.log"


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


@dataclass(frozen=True)
class SummarySchedulePreviewRow:
    date: date
    weekday: str
    expected_automation_type: str
    scheduled_time: str
    status: str
    existing_report_path: str = ""
    decision_reason: str = ""
    week: int | None = None
    day: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "weekday": self.weekday,
            "expected_automation_type": self.expected_automation_type,
            "scheduled_time": self.scheduled_time,
            "status": self.status,
            "existing_report_path": self.existing_report_path,
            "decision_reason": self.decision_reason,
            "week": self.week,
            "day": self.day,
        }


@dataclass(frozen=True)
class SchedulerPreflightCheck:
    name: str
    status: str
    message: str
    details: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "message": self.message, "details": self.details}


def scheduled_tools_log_path(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).logs / "scheduled_tools.log"


def scheduled_task_emergency_log_path() -> Path:
    return Path(tempfile.gettempdir()) / EMERGENCY_LOG_FILE_NAME


def describe_task_result(raw_result: Any) -> str:
    raw = str(raw_result or "").strip()
    if not raw:
        return "No run recorded"
    try:
        normalized = str(int(raw, 16) if raw.lower().startswith("0x") else int(raw))
    except ValueError:
        normalized = raw
    descriptions = {
        "0": "Task completed successfully",
        "1": "Task failed / script returned error",
        "267008": "Task is ready",
        "267009": "Task is currently running",
        "267010": "Task is disabled",
        "267011": "Task has not yet run",
    }
    return descriptions.get(normalized, f"Task returned code {raw}")


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


def _daily_report_for_date(project_root: str | Path, target_date: date) -> ReportFileInfo | None:
    return next((info for info in _daily_report_infos(project_root) if info.report_date == target_date), None)


def _weekly_report_for_date(project_root: str | Path, target_date: date) -> ReportFileInfo | None:
    return next((info for info in _weekly_report_infos(project_root) if info.report_date == target_date), None)


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


def _parse_date_list(items: list[str | date]) -> list[date]:
    dates: list[date] = []
    for item in items:
        if isinstance(item, date):
            dates.append(item)
            continue
        try:
            dates.append(date.fromisoformat(str(item)[:10]))
        except ValueError:
            continue
    return sorted(set(dates))


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


def preview_summary_schedule(
    project_root: str | Path,
    start_date: date | str | None = None,
    days: int = 14,
    timezone_name: str = DEFAULT_SCHEDULE_TIMEZONE,
    *,
    current_datetime: datetime | None = None,
    project_start_date: str = "",
    skip_weekends: bool = True,
    holidays: list[str] | None = None,
) -> list[SummarySchedulePreviewRow]:
    local_now = local_scheduler_datetime(current_datetime, timezone_name)
    today = local_now.date()
    if isinstance(start_date, date):
        cursor = start_date
    elif start_date:
        cursor = date.fromisoformat(str(start_date)[:10])
    else:
        cursor = today
    day_count = max(1, min(int(days or 14), 30))
    holiday_dates = set(_parse_date_list(list(holidays or [])))
    rows: list[SummarySchedulePreviewRow] = []
    for offset in range(day_count):
        target = cursor + timedelta(days=offset)
        weekday = target.strftime("%A")
        scheduled_time = f"{SCHEDULE_TIME_LABEL} {timezone_name}"

        if target in holiday_dates:
            rows.append(
                SummarySchedulePreviewRow(
                    date=target,
                    weekday=weekday,
                    expected_automation_type="",
                    scheduled_time="",
                    status="skipped",
                    decision_reason="Configured holiday/non-workday.",
                )
            )
            continue

        if expected_daily_summary_day(target):
            resolved = resolve_project_day_for_project(
                project_root,
                current_date=target,
                project_start_date=project_start_date,
                skip_weekends=skip_weekends,
                holidays=holidays or [],
            )
            existing = _daily_report_for_date(project_root, target)
            status, reason = _preview_status(target, today, local_now, bool(existing), "daily summary")
            rows.append(
                SummarySchedulePreviewRow(
                    date=target,
                    weekday=weekday,
                    expected_automation_type="daily_summary",
                    scheduled_time=scheduled_time,
                    status=status,
                    existing_report_path=str(existing.path) if existing else "",
                    decision_reason=reason,
                    week=resolved.week,
                    day=resolved.day,
                )
            )
            continue

        if expected_weekly_summary_day(target):
            resolved = resolve_project_day_for_project(
                project_root,
                current_date=target,
                project_start_date=project_start_date,
                skip_weekends=skip_weekends,
                holidays=holidays or [],
                manual_day=5,
            )
            existing = _weekly_report_for_date(project_root, target)
            status, reason = _preview_status(target, today, local_now, bool(existing), "weekly summary")
            rows.append(
                SummarySchedulePreviewRow(
                    date=target,
                    weekday=weekday,
                    expected_automation_type="weekly_summary",
                    scheduled_time=scheduled_time,
                    status=status,
                    existing_report_path=str(existing.path) if existing else "",
                    decision_reason=reason,
                    week=resolved.week,
                    day=5,
                )
            )
            continue

        rows.append(
            SummarySchedulePreviewRow(
                date=target,
                weekday=weekday,
                expected_automation_type="",
                scheduled_time="",
                status="not scheduled",
                decision_reason="No daily or weekly summary is scheduled for this weekday.",
            )
        )
    return rows


def _preview_status(target: date, today: date, local_now: datetime, exists: bool, report_label: str) -> tuple[str, str]:
    if exists:
        return "already exists", f"{report_label.title()} already exists for this date."
    if target < today:
        return "missed", f"Scheduled {report_label} date passed and no report was found."
    if target == today and _scheduled_time_reached(local_now):
        return "due", f"Scheduled time has passed and no {report_label} was found."
    return "future", f"{report_label.title()} is scheduled for this future time."


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

    def existing_path(path_text: str) -> str:
        if not path_text:
            return ""
        try:
            candidate = Path(path_text.strip().strip('"'))
            return str(candidate) if candidate.exists() else ""
        except OSError:
            return ""

    def output_from_plain_text(line: str) -> str:
        match = re.search(r'output="([^"]+)"', line)
        return match.group(1).strip() if match else ""

    try:
        parsed = json.loads(latest)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        if parsed.get("event") == "launch_diagnostic":
            return {
                "last_log_line": latest,
                "last_status": "Launch confirmed - report result pending",
                "report_generation_result": "Launch confirmed - report result pending",
                "last_error": "",
                "last_generated_report": "",
            }
        status_map = {
            "failed": "Failed",
            "failure": "Failed",
            "skipped": "Skipped",
            "started": "Started",
        }
        raw_status = str(parsed.get("status") or "").lower()
        output_path = str(parsed.get("output_path") or "")
        if raw_status == "success":
            status = "Success - report file created" if existing_path(output_path) else "No report file confirmed"
        elif raw_status == "skipped":
            status = "Skipped - report already existed"
        else:
            status = status_map.get(raw_status, raw_status.title() if raw_status else "Unknown")
        return {
            "last_log_line": latest,
            "last_status": status,
            "report_generation_result": status,
            "last_error": str(parsed.get("error") or ""),
            "last_generated_report": existing_path(output_path),
        }
    status = "Unknown"
    output_path = output_from_plain_text(latest)
    output_exists = bool(existing_path(output_path))
    padded = f" {latest} "
    if " SUCCESS " in padded:
        if "report_created=true" in latest and output_exists:
            status = "Success - report file created"
        elif "already exists" in latest.lower() or "report_created=false" in latest:
            status = "Skipped - report already existed"
        elif output_exists:
            status = "Success - report file confirmed"
        else:
            status = "No report file confirmed"
    elif " SKIPPED " in padded:
        status = "Skipped - report already existed"
    elif " FAILURE " in padded:
        status = "Failed"
    elif " START " in padded:
        status = "Started - report result pending"
    return {
        "last_log_line": latest,
        "last_status": status,
        "report_generation_result": status,
        "last_generated_report": existing_path(output_path),
    }


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
        data = json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"installed": "Unknown", "warning": "Could not parse scheduled task status."}
    if data.get("installed") is True:
        raw_result = str(data.get("last_result") or "")
        data["last_result_raw"] = raw_result
        data["last_result_description"] = describe_task_result(raw_result)
    return data


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
    paths = resolve_project_paths(project_root)
    return {
        "daily": {
            "schedule": f"Monday-Thursday at {SCHEDULE_TIME_LABEL}",
            "task": daily_task,
            "last_report": str(daily.path) if daily else "",
            "last_report_date": daily.report_date.isoformat() if daily and daily.report_date else "",
            "missed_dates": [item.isoformat() for item in missed_daily],
            "next_expected_run": next_daily.isoformat(timespec="seconds"),
            "report_generation_result": daily_log.get("report_generation_result", ""),
            **daily_log,
        },
        "weekly": {
            "schedule": f"Friday at {SCHEDULE_TIME_LABEL}",
            "task": weekly_task,
            "last_report": str(weekly.path) if weekly else "",
            "last_report_date": weekly.report_date.isoformat() if weekly and weekly.report_date else "",
            "missed_dates": [item.isoformat() for item in missed_weekly],
            "next_expected_run": next_weekly.isoformat(timespec="seconds"),
            "report_generation_result": weekly_log.get("report_generation_result", ""),
            **weekly_log,
        },
        "scheduled_log": str(scheduled_tools_log_path(project_root)),
        "emergency_log": str(scheduled_task_emergency_log_path()),
        "paths": {
            "daily_reports": str(paths.daily_reports),
            "weekly_reports": str(paths.weekly_reports),
            "logs": str(paths.logs),
            "scheduled_log": str(scheduled_tools_log_path(project_root)),
            "emergency_log": str(scheduled_task_emergency_log_path()),
        },
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


def _context_cli_values(project_root: str | Path, target_date: date, week: int, day: int, run_mode: str) -> dict[str, list[str]]:
    try:
        context = build_daily_report_context(project_root, target_date=target_date, week=week, day=day)
        values = daily_summary_cli_items(context)
    except Exception as exc:
        values = {"completed": [], "need": [], "plan": [], "notes": [f"Report context builder warning: {exc}"]}
    if not values.get("completed"):
        values["completed"] = ["Reviewed EOAT Command Center dashboard status"]
    if not values.get("need"):
        values["need"] = ["Confirm next EOAT project priority with mentor or supervisor"]
    if not values.get("plan"):
        values["plan"] = ["Continue EOAT project execution from the current schedule"]
    notes = values.setdefault("notes", [])
    notes.append("Generated by EOAT scheduled summary automation.")
    if run_mode == "catch-up":
        notes.append(f"Catch-up summary generated for target date {target_date.isoformat()}.")
    return {key: _dedupe_text(items)[:10] for key, items in values.items()}


def _dedupe_text(items: list[str]) -> list[str]:
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
    context_values = _context_cli_values(project_root, target_date, resolved.week, resolved.day, run_mode)
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
        *context_values["completed"],
        "--need",
        *context_values["need"],
        "--plan",
        *context_values["plan"],
        "--note",
        *context_values["notes"],
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


def run_catch_up_summaries(
    project_root: str | Path,
    dates: list[str | date],
    *,
    automation: str = "daily_summary",
    dry_run: bool = False,
    timezone_name: str = DEFAULT_SCHEDULE_TIMEZONE,
    project_start_date: str = "",
    skip_weekends: bool = True,
    holidays: list[str] | None = None,
) -> ToolResult:
    started = time.perf_counter()
    targets = _parse_date_list(dates)
    results: list[ToolResult] = []
    skipped: list[str] = []
    details: list[str] = []
    for target in targets:
        requested = automation.strip().lower()
        if requested in {"all", "auto"}:
            requested = "weekly_summary" if expected_weekly_summary_day(target) else "daily_summary"
        if requested == "daily_summary" and not expected_daily_summary_day(target):
            skipped.append(target.isoformat())
            details.append(f"{target.isoformat()}: skipped because daily summaries run Monday-Thursday.")
            continue
        if requested == "weekly_summary" and not expected_weekly_summary_day(target):
            skipped.append(target.isoformat())
            details.append(f"{target.isoformat()}: skipped because weekly summaries run Friday.")
            continue
        if requested == "daily_summary":
            resolved = resolve_project_day_for_project(
                project_root,
                current_date=target,
                project_start_date=project_start_date,
                skip_weekends=skip_weekends,
                holidays=holidays or [],
            )
            result = run_daily_summary_now(
                project_root,
                scheduled=False,
                dry_run=dry_run,
                report_date=target,
                week=resolved.week,
                day=resolved.day,
                mode="catch-up",
                decision_reason="catch-up daily summary generation",
                timezone_name=timezone_name,
                project_start_date=project_start_date,
                skip_weekends=skip_weekends,
                holidays=holidays,
            )
        elif requested == "weekly_summary":
            resolved = resolve_project_day_for_project(
                project_root,
                current_date=target,
                project_start_date=project_start_date,
                skip_weekends=skip_weekends,
                holidays=holidays or [],
                manual_day=5,
            )
            result = run_weekly_summary_now(
                project_root,
                scheduled=False,
                dry_run=dry_run,
                report_date=target,
                week=resolved.week,
                notes=f"Catch-up summary generated for target date {target.isoformat()}.",
                mode="catch-up",
                decision_reason="catch-up weekly summary generation",
                timezone_name=timezone_name,
                project_start_date=project_start_date,
                skip_weekends=skip_weekends,
                holidays=holidays,
            )
        else:
            skipped.append(target.isoformat())
            details.append(f"{target.isoformat()}: skipped unknown automation {automation!r}.")
            continue
        results.append(result)
        details.append(f"{target.isoformat()}: {result.summary}")

    success = all(result.success for result in results)
    errors = [error for result in results for error in result.errors]
    warnings = [warning for result in results for warning in result.warnings]
    output_reports = [path for result in results for path in result.output_reports]
    files_created = [path for result in results for path in result.files_created]
    result = ToolResult(
        tool_id="scheduled_report_catch_up",
        tool_name="Scheduled Report Catch-Up",
        success=success,
        summary=f"Catch-up processed {len(results)} run(s) and skipped {len(skipped)} date(s).",
        details=details,
        warnings=warnings,
        errors=errors,
        files_created=files_created,
        output_reports=output_reports,
        metrics={"automation": automation, "dry_run": dry_run, "skipped_dates": skipped},
        structured_data={"runs": [item.to_dict() for item in results], "skipped_dates": skipped},
        duration_seconds=time.perf_counter() - started,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result


def run_scheduler_preflight(project_root: str | Path, *, check_tasks: bool = True) -> ToolResult:
    started = time.perf_counter()
    root = Path(project_root)
    paths = resolve_project_paths(root)
    checks: list[SchedulerPreflightCheck] = []

    def add(name: str, status: str, message: str, details: str = "") -> None:
        checks.append(SchedulerPreflightCheck(name, status, message, details))

    add(
        "Windows platform",
        "PASS" if platform.system().casefold() == "windows" else "WARNING",
        f"Detected platform: {platform.system() or 'unknown'}.",
        "Windows Task Scheduler automation only installs on Windows.",
    )
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    add(
        "PowerShell executable",
        "PASS" if powershell else "WARNING",
        f"PowerShell executable {'found' if powershell else 'not found'}.",
        powershell or "Install/repair and uninstall buttons require PowerShell.",
    )
    if powershell:
        completed = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "Get-Command Get-ScheduledTask -ErrorAction Stop | Out-Null; 'OK'"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        add(
            "Task Scheduler commands",
            "PASS" if completed.returncode == 0 else "WARNING",
            "Task Scheduler commands are accessible." if completed.returncode == 0 else "Task Scheduler commands were not accessible.",
            (completed.stderr or completed.stdout).strip(),
        )
    else:
        add("Task Scheduler commands", "WARNING", "Task Scheduler commands could not be checked without PowerShell.")

    scripts = [
        TOOLKIT_ROOT / "scripts" / "install_summary_schedules.ps1",
        TOOLKIT_ROOT / "scripts" / "uninstall_summary_schedules.ps1",
        TOOLKIT_ROOT / "scripts" / "check_summary_schedules.ps1",
        TOOLKIT_ROOT / "scripts" / "run_daily_summary.ps1",
        TOOLKIT_ROOT / "scripts" / "run_weekly_summary.ps1",
    ]
    missing_scripts = [str(path) for path in scripts if not path.exists()]
    add(
        "Scheduled report scripts",
        "ERROR" if missing_scripts else "PASS",
        "All scheduled report scripts exist." if not missing_scripts else "One or more scheduled report scripts are missing.",
        "; ".join(missing_scripts),
    )
    add("Python executable", "PASS" if Path(sys.executable).exists() else "ERROR", f"Python executable: {sys.executable}.")
    add("Project root", "PASS" if root.exists() else "ERROR", f"Project root {'exists' if root.exists() else 'does not exist'}: {root}.")

    for label, folder in [("Daily output folder", paths.daily_reports), ("Weekly output folder", paths.weekly_reports), ("Log folder", paths.logs)]:
        try:
            ensure_directory(folder)
            probe = folder / ".scheduled_preflight_write_test.tmp"
            probe.write_text("preflight\n", encoding="utf-8")
            probe.unlink(missing_ok=True)
            add(label, "PASS", f"{folder} is writable.")
        except Exception as exc:
            add(label, "ERROR", f"{folder} is not writable.", str(exc))

    log_path = scheduled_tools_log_path(root)
    if log_path.exists():
        try:
            log_path.read_text(encoding="utf-8").splitlines()[-5:]
            add("Scheduled log readable", "PASS", f"{log_path} is readable.")
        except Exception as exc:
            add("Scheduled log readable", "ERROR", f"{log_path} could not be read.", str(exc))
    else:
        add("Scheduled log readable", "WARNING", f"{log_path} does not exist yet; it will be created on first run.")

    if check_tasks:
        for label, task_name in [("Daily scheduled task", DAILY_TASK_NAME), ("Weekly scheduled task", WEEKLY_TASK_NAME)]:
            task = _task_status(task_name) if powershell else {"installed": "Unknown", "warning": "PowerShell unavailable."}
            installed = task.get("installed")
            if installed is True:
                add(label, "PASS", f"{task_name} is installed.", json.dumps(task, ensure_ascii=True))
            elif installed is False:
                add(label, "WARNING", f"{task_name} is not installed.", json.dumps(task, ensure_ascii=True))
            else:
                add(label, "WARNING", f"{task_name} status is unknown.", str(task.get("warning") or ""))

    rows = [check.to_dict() for check in checks]
    errors = [f"{check.name}: {check.message}" for check in checks if check.status == "ERROR"]
    warnings = [f"{check.name}: {check.message}" for check in checks if check.status == "WARNING"]
    return ToolResult(
        tool_id="scheduled_report_preflight",
        tool_name="Scheduled Report Preflight",
        success=not errors,
        summary="Scheduled report preflight completed." if not errors else "Scheduled report preflight found blocking issues.",
        details=[f"{check.status}: {check.name} - {check.message}" for check in checks],
        warnings=warnings,
        errors=errors,
        metrics={"pass": sum(1 for check in checks if check.status == "PASS"), "warning": len(warnings), "error": len(errors)},
        structured_data={"checks": rows},
        duration_seconds=time.perf_counter() - started,
    )


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


def _task_name_for_automation(automation: str) -> tuple[str, str]:
    requested = automation.strip().casefold()
    if requested in {"daily", "daily_summary", DAILY_TASK_NAME.casefold()}:
        return DAILY_TASK_NAME, "daily_summary"
    if requested in {"weekly", "weekly_summary", WEEKLY_TASK_NAME.casefold()}:
        return WEEKLY_TASK_NAME, "weekly_summary"
    raise ValueError(f"Unknown scheduled report automation: {automation}")


def _file_offset(path: Path) -> int:
    try:
        return path.stat().st_size if path.exists() else 0
    except OSError:
        return 0


def _read_new_log_lines(path: Path, offset: int) -> list[str]:
    try:
        if not path.exists():
            return []
        if path.stat().st_size < offset:
            offset = 0
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            return [line.strip() for line in handle.readlines() if line.strip()]
    except OSError:
        return []


def _line_mentions_automation(line: str, automation: str) -> bool:
    return automation in line or ("daily_summary" in line if automation == "daily_summary" else "weekly_summary" in line)


def _log_line_output_path(line: str) -> str:
    match = re.search(r'output="([^"]+)"', line)
    if match:
        return match.group(1).strip()
    match = re.search(r'"output_path"\s*:\s*"([^"]+)"', line)
    return match.group(1).strip() if match else ""


def _confirmed_created_report_from_lines(lines: list[str], automation: str) -> str:
    for line in reversed(lines):
        if not _line_mentions_automation(line, automation):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            if parsed.get("automation") == automation and str(parsed.get("status") or "").casefold() == "success":
                output_path = str(parsed.get("output_path") or "")
                if output_path and Path(output_path).exists():
                    return str(Path(output_path))
            continue
        if " SUCCESS " in f" {line} " and "report_created=true" in line:
            output_path = _log_line_output_path(line)
            if output_path and Path(output_path).exists():
                return str(Path(output_path))
    return ""


def _report_result_from_lines(lines: list[str], automation: str) -> str:
    launch_seen = False
    for line in reversed(lines):
        if not _line_mentions_automation(line, automation):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            if parsed.get("event") == "launch_diagnostic":
                launch_seen = True
                continue
            status = str(parsed.get("status") or "").casefold()
            if status == "success" and _confirmed_created_report_from_lines([line], automation):
                return "Success - report file created"
            if status == "skipped":
                return "Skipped - report already existed"
            if status in {"failed", "failure"}:
                return "Failed"
            if status == "started":
                return "Started - report result pending"
            continue
        padded = f" {line} "
        if " SUCCESS " in padded and "report_created=true" in line:
            return "Success - report file created"
        if " SKIPPED " in padded:
            return "Skipped - report already existed"
        if " FAILURE " in padded:
            return "Failed"
        if " START " in padded:
            return "Started - report result pending"
    return "Launch confirmed - report result pending" if launch_seen else ""


def run_actual_scheduled_task_now(
    project_root: str | Path,
    automation: str = "daily_summary",
    *,
    timeout_seconds: float = 60.0,
    poll_interval_seconds: float = 0.5,
) -> ToolResult:
    started = time.perf_counter()
    try:
        task_name, automation_name = _task_name_for_automation(automation)
    except ValueError as exc:
        return ToolResult.fail("actual_scheduled_task", "Run Actual Scheduled Task", str(exc), errors=[str(exc)])

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        return ToolResult.fail("actual_scheduled_task", "Run Actual Scheduled Task", "PowerShell is not available.", errors=["PowerShell executable was not found."])

    scheduled_log = scheduled_tools_log_path(project_root)
    emergency_log = scheduled_task_emergency_log_path()
    scheduled_offset = _file_offset(scheduled_log)
    emergency_offset = _file_offset(emergency_log)
    command = [
        powershell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        f"Start-ScheduledTask -TaskName '{task_name}' -ErrorAction Stop",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    except Exception as exc:
        return ToolResult.fail("actual_scheduled_task", "Run Actual Scheduled Task", "Could not start the scheduled task.", errors=[str(exc)], duration_seconds=time.perf_counter() - started)
    if completed.returncode != 0:
        output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
        return ToolResult.fail("actual_scheduled_task", "Run Actual Scheduled Task", "Task Scheduler rejected the start request.", errors=[output or f"Exit code {completed.returncode}"], duration_seconds=time.perf_counter() - started)

    scheduled_lines: list[str] = []
    emergency_lines: list[str] = []
    launch_confirmed = False
    report_created = ""
    report_result = ""
    deadline = time.time() + max(1.0, timeout_seconds)
    while time.time() < deadline:
        scheduled_lines = _read_new_log_lines(scheduled_log, scheduled_offset)
        emergency_lines = _read_new_log_lines(emergency_log, emergency_offset)
        combined = scheduled_lines + emergency_lines
        launch_confirmed = any("launch_diagnostic" in line and _line_mentions_automation(line, automation_name) for line in combined)
        report_created = _confirmed_created_report_from_lines(combined, automation_name)
        report_result = _report_result_from_lines(combined, automation_name)
        if report_created or report_result in {"Failed", "Skipped - report already existed"}:
            break
        if launch_confirmed and time.time() + poll_interval_seconds >= deadline:
            break
        time.sleep(max(0.1, poll_interval_seconds))

    task_after = _task_status(task_name)
    raw_result = str(task_after.get("last_result_raw") or task_after.get("last_result") or "")
    result_description = task_after.get("last_result_description") or describe_task_result(raw_result)
    combined_lines = scheduled_lines + emergency_lines
    if not report_result:
        report_result = _report_result_from_lines(combined_lines, automation_name) or "No report result confirmed"

    details = [
        f"Task: {task_name}",
        f"Raw Task Scheduler result: {raw_result or 'No run recorded'} ({result_description})",
        f"Launch diagnostic confirmed: {'yes' if launch_confirmed else 'no'}",
        f"Report generation result: {report_result}",
        f"Scheduled log: {scheduled_log}",
        f"Emergency log: {emergency_log}",
    ]
    if scheduled_lines:
        details.append("New scheduled log lines:")
        details.extend(scheduled_lines[-6:])
    if emergency_lines:
        details.append("New emergency log lines:")
        details.extend(emergency_lines[-6:])

    structured_data = {
        "task_name": task_name,
        "automation": automation_name,
        "raw_task_result": raw_result,
        "task_result_description": result_description,
        "launch_confirmed": launch_confirmed,
        "report_generation_result": report_result,
        "scheduled_log": str(scheduled_log),
        "emergency_log": str(emergency_log),
        "scheduled_log_lines": scheduled_lines,
        "emergency_log_lines": emergency_lines,
    }
    duration = time.perf_counter() - started
    if report_created:
        return ToolResult.ok(
            "actual_scheduled_task",
            "Run Actual Scheduled Task",
            f"{task_name} launched and created a report file.",
            details=details,
            files_created=[report_created],
            output_reports=[report_created],
            structured_data=structured_data,
            duration_seconds=duration,
        )

    errors: list[str] = []
    warnings: list[str] = []
    if not launch_confirmed:
        errors.append("No launch diagnostic line appeared in the emergency or scheduled log during the polling window.")
    elif report_result == "Failed" or raw_result == "1":
        errors.append("The task launched, but the script reported a failure.")
    else:
        warnings.append("The task launched, but no newly created report file was confirmed during the polling window.")
    return ToolResult(
        tool_id="actual_scheduled_task",
        tool_name="Run Actual Scheduled Task",
        success=False,
        summary=f"{task_name} was started, but no new report file was confirmed.",
        details=details,
        warnings=warnings,
        errors=errors,
        structured_data=structured_data,
        duration_seconds=duration,
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
