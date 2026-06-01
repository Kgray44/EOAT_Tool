from __future__ import annotations

import json
from datetime import date

from core.schedule import available_schedule_weeks, load_week_schedule, resolve_project_day
from core.task_progress import progress_file_for_week, update_task_status


def test_schedule_and_task_progress_load_and_update(tmp_path):
    admin = tmp_path / "00_Project_Admin"
    admin.mkdir()
    (admin / "project_schedule_week1.json").write_text(
        json.dumps({"week": 1, "days": {"1": ["Task A"]}}),
        encoding="utf-8",
    )
    progress_path = admin / "task_progress_week1.json"
    progress_path.write_text(
        json.dumps({"tasks": [{"task_id": "W1D1T1", "day": "1", "task_text": "Task A", "status": "Not started"}]}),
        encoding="utf-8",
    )

    assert available_schedule_weeks(tmp_path) == [1]
    week = load_week_schedule(tmp_path, 1)
    assert week.days["1"] == ["Task A"]
    assert week.tasks[0].id == "W1D1T1"

    assert update_task_status(progress_file_for_week(tmp_path, 1), "W1D1T1", "Complete") is True
    updated = load_week_schedule(tmp_path, 1)
    assert updated.tasks[0].status == "Complete"


def test_project_day_resolver_counts_workdays_from_project_start():
    start = date(2026, 5, 18)

    assert (resolve_project_day(date(2026, 5, 18), start).week, resolve_project_day(date(2026, 5, 18), start).day) == (
        1,
        1,
    )
    assert (resolve_project_day(date(2026, 5, 19), start).week, resolve_project_day(date(2026, 5, 19), start).day) == (
        1,
        2,
    )
    assert (resolve_project_day(date(2026, 5, 22), start).week, resolve_project_day(date(2026, 5, 22), start).day) == (
        1,
        5,
    )
    assert (resolve_project_day(date(2026, 5, 25), start).week, resolve_project_day(date(2026, 5, 25), start).day) == (
        2,
        1,
    )


def test_project_day_resolver_manual_override():
    resolved = resolve_project_day(
        date(2026, 5, 19),
        date(2026, 5, 18),
        manual_week=3,
        manual_day=4,
        manual_override=True,
    )

    assert resolved.week == 3
    assert resolved.day == 4
    assert resolved.source == "manual override"
