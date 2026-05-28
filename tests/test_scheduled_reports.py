from __future__ import annotations

import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path

from core import scheduled_reports
from core.paths import resolve_project_paths
from core.result import ToolResult
from core.scheduled_reports import (
    DAILY_TASK_NAME,
    WEEKLY_TASK_NAME,
    detect_missed_daily_summaries,
    detect_missed_weekly_summary,
    expected_daily_summary_day,
    expected_weekly_summary_day,
    find_latest_daily_summary,
    get_scheduled_report_status,
    preview_summary_schedule,
    run_catch_up_summaries,
    run_daily_summary_now,
    run_scheduler_preflight,
    run_weekly_summary_now,
    scheduler_timezone,
)


def test_expected_summary_days():
    assert expected_daily_summary_day(date(2026, 5, 18)) is True
    assert expected_daily_summary_day(date(2026, 5, 21)) is True
    assert expected_daily_summary_day(date(2026, 5, 22)) is False
    assert expected_weekly_summary_day(date(2026, 5, 22)) is True
    assert expected_weekly_summary_day(date(2026, 5, 21)) is False


def test_report_detection_and_missed_runs_do_not_create_duplicates(fake_project):
    paths = resolve_project_paths(fake_project)
    monday_report = paths.daily_reports / "Week1_Day1_Status_2026-05-18.md"
    monday_report.write_text("# Monday\n", encoding="utf-8")

    missed = detect_missed_daily_summaries(fake_project, today=date(2026, 5, 20), lookback_days=3)

    assert [item.isoformat() for item in missed] == ["2026-05-19", "2026-05-20"]
    assert find_latest_daily_summary(fake_project).path == monday_report
    assert monday_report.read_text(encoding="utf-8") == "# Monday\n"


def test_weekly_missed_run_detection(fake_project):
    missed = detect_missed_weekly_summary(fake_project, today=date(2026, 5, 22), lookback_days=7)
    assert [item.isoformat() for item in missed] == ["2026-05-22"]

    paths = resolve_project_paths(fake_project)
    (paths.weekly_reports / "Week1_Summary_2026-05-22.md").write_text("# Week\n", encoding="utf-8")
    assert detect_missed_weekly_summary(fake_project, today=date(2026, 5, 22), lookback_days=7) == []


def test_status_check_can_skip_windows_task_query(fake_project):
    status = get_scheduled_report_status(fake_project, today=date(2026, 5, 22), check_tasks=False)

    assert status["daily"]["task"]["installed"] == "Unknown"
    assert status["daily"]["schedule"] == "Monday-Thursday at 7:00 PM"
    assert status["weekly"]["schedule"] == "Friday at 7:00 PM"
    assert "scheduled_tools.log" in status["scheduled_log"]
    assert "daily_reports" in status["paths"]


def test_calendar_preview_marks_weekday_daily_friday_weekly_and_missed(fake_project):
    paths = resolve_project_paths(fake_project)
    existing = paths.daily_reports / "Week1_Day1_Status_2026-05-18.md"
    existing.write_text("# Existing\n", encoding="utf-8")

    rows = preview_summary_schedule(
        fake_project,
        start_date=date(2026, 5, 18),
        days=7,
        current_datetime=datetime(2026, 5, 20, 20, 0, tzinfo=scheduler_timezone()),
        project_start_date="2026-05-18",
    )
    by_date = {row.date.isoformat(): row for row in rows}

    assert by_date["2026-05-18"].expected_automation_type == "daily_summary"
    assert by_date["2026-05-18"].status == "already exists"
    assert by_date["2026-05-19"].status == "missed"
    assert by_date["2026-05-20"].status == "due"
    assert by_date["2026-05-21"].expected_automation_type == "daily_summary"
    assert by_date["2026-05-22"].expected_automation_type == "weekly_summary"
    assert by_date["2026-05-23"].status == "not scheduled"


def test_catch_up_daily_and_weekly_use_target_dates_and_no_overwrite_paths(fake_project, monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_daily(*args, **kwargs):
        calls.append(("daily", kwargs))
        return ToolResult.ok("daily_status_summary", "Daily", "daily ok", output_reports=["daily.md"])

    def fake_weekly(*args, **kwargs):
        calls.append(("weekly", kwargs))
        return ToolResult.ok("weekly_summary", "Weekly", "weekly ok", output_reports=["weekly.md"])

    monkeypatch.setattr(scheduled_reports, "run_daily_summary_now", fake_daily)
    monkeypatch.setattr(scheduled_reports, "run_weekly_summary_now", fake_weekly)

    daily_result = run_catch_up_summaries(
        fake_project,
        [date(2026, 5, 20)],
        automation="daily_summary",
        project_start_date="2026-05-18",
    )
    weekly_result = run_catch_up_summaries(
        fake_project,
        [date(2026, 5, 22)],
        automation="weekly_summary",
        project_start_date="2026-05-18",
    )

    assert daily_result.success is True
    assert weekly_result.success is True
    assert calls[0][0] == "daily"
    assert calls[0][1]["report_date"] == date(2026, 5, 20)
    assert calls[0][1]["week"] == 1
    assert calls[0][1]["day"] == 3
    assert calls[0][1]["mode"] == "catch-up"
    assert calls[1][0] == "weekly"
    assert calls[1][1]["report_date"] == date(2026, 5, 22)
    assert calls[1][1]["week"] == 1
    assert calls[1][1]["mode"] == "catch-up"


def test_preflight_reports_missing_powershell_as_warning(fake_project, monkeypatch):
    monkeypatch.setattr(scheduled_reports.shutil, "which", lambda _name: None)

    result = run_scheduler_preflight(fake_project, check_tasks=False)
    checks = {row["name"]: row for row in result.structured_data["checks"]}

    assert result.success is True
    assert checks["PowerShell executable"]["status"] == "WARNING"
    assert checks["Task Scheduler commands"]["status"] == "WARNING"


def test_existing_daily_or_weekly_report_is_not_duplicated(fake_project):
    paths = resolve_project_paths(fake_project)
    daily = paths.daily_reports / "Week1_Day1_Status_2026-05-18.md"
    weekly = paths.weekly_reports / "Week1_Summary_2026-05-22.md"
    daily.write_text("# Daily\n", encoding="utf-8")
    weekly.write_text("# Weekly\n", encoding="utf-8")

    daily_result = run_daily_summary_now(fake_project, report_date=date(2026, 5, 18), week=1, day=1)
    weekly_result = run_weekly_summary_now(fake_project, report_date=date(2026, 5, 22), week=1)

    assert daily_result.success is True
    assert weekly_result.success is True
    assert "already exists" in daily_result.summary
    assert "already exists" in weekly_result.summary
    assert list(paths.daily_reports.glob("Week1_Day1_Status_2026-05-18*.md")) == [daily]
    assert list(paths.weekly_reports.glob("Week1_Summary_2026-05-22*.md")) == [weekly]


def test_scheduled_task_script_files_exist_and_installer_dry_run(fake_project):
    scripts = [
        "scripts/run_daily_summary.ps1",
        "scripts/run_weekly_summary.ps1",
        "scripts/install_summary_schedules.ps1",
        "scripts/uninstall_summary_schedules.ps1",
        "scripts/check_summary_schedules.ps1",
    ]

    repo_root = Path(__file__).resolve().parents[1]
    for script in scripts:
        assert (repo_root / script).exists()

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    assert DAILY_TASK_NAME == "EOAT Daily Summary"
    assert WEEKLY_TASK_NAME == "EOAT Weekly Summary"
    if powershell is None:
        return
    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "scripts" / "install_summary_schedules.ps1"),
            "-ProjectRoot",
            str(fake_project),
            "-DryRun",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0
    assert "Dry run completed" in completed.stdout
