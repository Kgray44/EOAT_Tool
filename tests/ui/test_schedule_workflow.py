from __future__ import annotations

import json

import pytest

from app.pages.schedule import SchedulePage
from tests.ui.helpers import click_button, wait_for_background_tasks

pytestmark = pytest.mark.usability


def test_schedule_task_status_persists_and_completed_task_leaves_main_plan(
    qapp, fake_config, fake_project, frozen_project_date
):
    page = SchedulePage(fake_config)
    page.show()
    page.task_table.selectRow(0)

    click_button(page, "In progress")
    progress_path = fake_project / "00_Project_Admin" / "task_progress_week1.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert any(task["id"] == "W1D1T1" and task["status"] == "In progress" for task in progress["tasks"])

    click_button(page, "Complete")
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert any(task["id"] == "W1D1T1" and task["status"] == "Complete" for task in progress["tasks"])

    page.refresh()
    statuses = [page.task_table.item(row, 1).text() for row in range(page.task_table.rowCount())]
    assert "Complete" in statuses

    page.override_checkbox.setChecked(True)
    page.day_spin.setValue(1)
    click_button(page, "Generate Morning Plan")
    wait_for_background_tasks()
    generated = sorted(
        (fake_project / "00_Project_Admin" / "Daily_Status_Reports" / "Morning_Plans").glob(
            "Week1_Day1_Morning_Plan_*.md"
        )
    )[-1]
    text = generated.read_text(encoding="utf-8")
    assert "[Complete] Confirm project folder structure" not in text
