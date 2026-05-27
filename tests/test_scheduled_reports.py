from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

from core.paths import resolve_project_paths
from core.scheduled_reports import (
    DAILY_TASK_NAME,
    WEEKLY_TASK_NAME,
    detect_missed_daily_summaries,
    detect_missed_weekly_summary,
    expected_daily_summary_day,
    expected_weekly_summary_day,
    find_latest_daily_summary,
    get_scheduled_report_status,
    run_daily_summary_now,
    run_weekly_summary_now,
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
