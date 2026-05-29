from __future__ import annotations

import json

import pytest

from app.pages.home import HomePage
from app.pages.schedule import SchedulePage
from tests.ui.helpers import click_button, wait_for_background_tasks, wait_for_path

pytestmark = pytest.mark.usability


def test_morning_plan_user_flow_creates_week1_day2_plan(qapp, fake_config, fake_project, frozen_project_date):
    page = SchedulePage(fake_config)
    page.show()

    assert "Resolved: Week 1 Day 2" in page.resolved_label.text()
    click_button(page, "Generate Morning Plan")
    wait_for_background_tasks()

    output = wait_for_path(fake_project / "00_Project_Admin" / "Daily_Status_Reports" / "Morning_Plans" / "Week1_Day2_Morning_Plan_2026-05-19.md")
    text = output.read_text(encoding="utf-8")

    assert "# Week 1 Day 2 Morning Plan" in text
    assert "Week 1 Day 1 Morning Plan" not in text
    assert "## Optional Stretch" not in text
    assert "No stretch tasks suggested yet." not in text
    assert "- If ahead, start: \n" not in text
    assert "choose the next highest-value task" not in text
    for section in ["Today's Mission", "Do First", "Main TODO", "Ask Today", "If Blocked", "Done When"]:
        assert f"## {section}" in text
    assert "## Source Availability" not in text
    assert "## Recent Activity" not in text
    assert len(text.split()) <= 250
    details = fake_project / "00_Project_Admin" / "Daily_Status_Reports" / "Morning_Plans" / "Week1_Day2_Planning_Context_Details_2026-05-19.md"
    assert details.exists()


def test_daily_start_workflow_from_home_generates_outputs_and_activity(qapp, fake_config, fake_project, frozen_project_date):
    page = HomePage(fake_config)
    page.show()
    wait_for_background_tasks()

    click_button(page, "Run Daily Start Workflow")
    wait_for_background_tasks(timeout_ms=30000)

    activity_log = fake_project / "00_Project_Admin" / "Activity_Logs" / "activity_log.jsonl"
    assert activity_log.exists()
    entries = [json.loads(line) for line in activity_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(entry["tool_id"] == "workflow_runner" and entry["success"] for entry in entries)
    assert list((fake_project / "00_Project_Admin" / "Validation_Reports").glob("Workflow_daily_start_*.md"))
    assert "Workflow daily-start completed" in page.result_panel.viewer.toPlainText()
