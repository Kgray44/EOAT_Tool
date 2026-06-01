from __future__ import annotations

import json

from core.workflows import run_workflow


def test_daily_start_workflow_generates_report(fake_project):
    admin = fake_project / "00_Project_Admin"
    (admin / "project_schedule_week1.json").write_text(json.dumps({"days": {"1": ["Start audit"]}}), encoding="utf-8")
    (admin / "task_progress_week1.json").write_text(
        json.dumps({"tasks": [{"id": "T1", "day": "1", "task": "Start audit", "status": "Not started"}]}),
        encoding="utf-8",
    )

    result = run_workflow(fake_project, "daily-start", week=1, day=1)

    assert result.success is True
    assert result.output_reports
    assert result.metrics["steps"] == 2


def test_unknown_workflow_fails_cleanly(fake_project):
    result = run_workflow(fake_project, "mystery")

    assert result.success is False
    assert "Unknown workflow" in result.summary
