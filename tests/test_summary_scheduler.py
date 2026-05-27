from __future__ import annotations

import json
from datetime import datetime

from core import scheduled_reports
from core.result import ToolResult
from core.scheduled_reports import (
    dry_run_daily_reports_dir,
    dry_run_weekly_reports_dir,
    run_due_scheduled_summaries,
    scheduled_tools_log_path,
    scheduler_timezone,
)
from tests.fixtures.fake_project import create_fake_eoat_project


def _ny_datetime(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=scheduler_timezone())


def _decision(result: ToolResult, automation: str) -> dict:
    for item in result.metrics["decisions"]:
        if item["automation"] == automation:
            return item
    raise AssertionError(f"Missing decision for {automation}")


def _json_log_entries(project_root):
    lines = scheduled_tools_log_path(project_root).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip().startswith("{")]


def test_daily_summary_fake_time_matrix(tmp_path):
    project_root = create_fake_eoat_project(tmp_path, with_photos=False)
    daily_dir = dry_run_daily_reports_dir(project_root)

    before = run_due_scheduled_summaries(
        project_root,
        current_datetime=_ny_datetime(2026, 5, 25, 18, 59),
        dry_run=True,
        run_daily=True,
        run_weekly=False,
    )
    assert _decision(before, "daily_summary")["decision"] == "skip"
    assert "before scheduled time" in _decision(before, "daily_summary")["reason"]
    assert list(daily_dir.glob("*.md")) == []

    monday = run_due_scheduled_summaries(
        project_root,
        current_datetime=_ny_datetime(2026, 5, 25, 19, 0),
        dry_run=True,
        run_daily=True,
        run_weekly=False,
    )
    assert monday.success is True
    assert _decision(monday, "daily_summary")["decision"] == "run"
    reports = sorted(daily_dir.glob("Week*_Day*_Status_*_DRY_RUN.md"))
    assert len(reports) == 1
    assert "DRY RUN / TEST OUTPUT" in reports[0].read_text(encoding="utf-8")

    duplicate = run_due_scheduled_summaries(
        project_root,
        current_datetime=_ny_datetime(2026, 5, 25, 19, 1),
        dry_run=True,
        run_daily=True,
        run_weekly=False,
    )
    assert _decision(duplicate, "daily_summary")["decision"] == "skip"
    assert "already exists" in _decision(duplicate, "daily_summary")["reason"]
    assert len(list(daily_dir.glob("Week*_Day*_Status_*_DRY_RUN.md"))) == 1

    for target_day in [26, 27, 28]:
        result = run_due_scheduled_summaries(
            project_root,
            current_datetime=_ny_datetime(2026, 5, target_day, 19, 0),
            dry_run=True,
            run_daily=True,
            run_weekly=False,
        )
        assert result.success is True
        assert _decision(result, "daily_summary")["decision"] == "run"

    assert len(list(daily_dir.glob("Week*_Day*_Status_*_DRY_RUN.md"))) == 4


def test_weekly_summary_fake_time_matrix(tmp_path):
    project_root = create_fake_eoat_project(tmp_path, with_photos=False)
    weekly_dir = dry_run_weekly_reports_dir(project_root)

    before = run_due_scheduled_summaries(
        project_root,
        current_datetime=_ny_datetime(2026, 5, 29, 18, 59),
        dry_run=True,
        run_daily=False,
        run_weekly=True,
    )
    assert _decision(before, "weekly_summary")["decision"] == "skip"
    assert "before scheduled time" in _decision(before, "weekly_summary")["reason"]
    assert list(weekly_dir.glob("*.md")) == []

    friday = run_due_scheduled_summaries(
        project_root,
        current_datetime=_ny_datetime(2026, 5, 29, 19, 0),
        dry_run=True,
        run_daily=False,
        run_weekly=True,
    )
    assert friday.success is True
    assert _decision(friday, "weekly_summary")["decision"] == "run"
    reports = sorted(weekly_dir.glob("Week*_Summary_*_DRY_RUN.md"))
    assert len(reports) == 1
    assert "DRY RUN / TEST OUTPUT" in reports[0].read_text(encoding="utf-8")

    duplicate = run_due_scheduled_summaries(
        project_root,
        current_datetime=_ny_datetime(2026, 5, 29, 19, 1),
        dry_run=True,
        run_daily=False,
        run_weekly=True,
    )
    assert _decision(duplicate, "weekly_summary")["decision"] == "skip"
    assert "already exists" in _decision(duplicate, "weekly_summary")["reason"]
    assert len(list(weekly_dir.glob("Week*_Summary_*_DRY_RUN.md"))) == 1


def test_no_run_weekend_days(tmp_path):
    project_root = create_fake_eoat_project(tmp_path, with_photos=False)

    for target_day in [30, 31]:
        result = run_due_scheduled_summaries(
            project_root,
            current_datetime=_ny_datetime(2026, 5, target_day, 19, 0),
            dry_run=True,
            run_daily=True,
            run_weekly=True,
        )
        assert _decision(result, "daily_summary")["decision"] == "skip"
        assert _decision(result, "weekly_summary")["decision"] == "skip"

    assert list(dry_run_daily_reports_dir(project_root).glob("*.md")) == []
    assert list(dry_run_weekly_reports_dir(project_root).glob("*.md")) == []


def test_duplicate_prevention_persists_across_scheduler_ticks_and_restarts(tmp_path):
    project_root = create_fake_eoat_project(tmp_path, with_photos=False)
    daily_dir = dry_run_daily_reports_dir(project_root)

    first = run_due_scheduled_summaries(
        project_root,
        current_datetime=_ny_datetime(2026, 5, 25, 19, 0),
        dry_run=True,
        run_daily=True,
        run_weekly=False,
    )
    second_tick = run_due_scheduled_summaries(
        project_root,
        current_datetime=_ny_datetime(2026, 5, 25, 19, 3),
        dry_run=True,
        run_daily=True,
        run_weekly=False,
    )
    restarted = run_due_scheduled_summaries(
        project_root,
        current_datetime=_ny_datetime(2026, 5, 25, 19, 7),
        dry_run=True,
        run_daily=True,
        run_weekly=False,
    )

    assert first.success is True
    assert _decision(second_tick, "daily_summary")["decision"] == "skip"
    assert _decision(restarted, "daily_summary")["decision"] == "skip"
    assert len(list(daily_dir.glob("Week*_Day*_Status_*_DRY_RUN.md"))) == 1


def test_failed_run_is_logged_and_retried_when_no_output_exists(tmp_path, monkeypatch):
    project_root = create_fake_eoat_project(tmp_path, with_photos=False)
    calls = {"count": 0}

    def fake_daily_runner(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return ToolResult.fail(
                "daily_status_summary",
                "Daily Status Summary Generator",
                "Injected failure.",
                errors=["boom"],
            )
        return ToolResult.ok(
            "daily_status_summary",
            "Daily Status Summary Generator",
            "Injected retry success.",
            output_reports=[str(dry_run_daily_reports_dir(project_root) / "retry_success.md")],
        )

    monkeypatch.setattr(scheduled_reports, "run_daily_summary_now", fake_daily_runner)

    first = scheduled_reports.run_due_scheduled_summaries(
        project_root,
        current_datetime=_ny_datetime(2026, 5, 25, 19, 0),
        dry_run=True,
        run_daily=True,
        run_weekly=False,
    )
    retry = scheduled_reports.run_due_scheduled_summaries(
        project_root,
        current_datetime=_ny_datetime(2026, 5, 25, 19, 1),
        dry_run=True,
        run_daily=True,
        run_weekly=False,
    )

    assert first.success is False
    assert retry.success is True
    assert calls["count"] == 2


def test_structured_scheduler_log_contains_decision_fields(tmp_path):
    project_root = create_fake_eoat_project(tmp_path, with_photos=False)

    run_due_scheduled_summaries(
        project_root,
        current_datetime=_ny_datetime(2026, 5, 25, 18, 59),
        dry_run=True,
        run_daily=True,
        run_weekly=False,
    )

    entries = _json_log_entries(project_root)
    assert entries
    latest = entries[-1]
    assert latest["timestamp"] == "2026-05-25T18:59:00-04:00"
    assert latest["local_timezone"] == "America/New_York"
    assert latest["automation"] == "daily_summary"
    assert latest["mode"] == "scheduled"
    assert latest["dry_run"] is True
    assert latest["decision"] == "skip"
    assert latest["status"] == "skipped"
    assert latest["reason"]
