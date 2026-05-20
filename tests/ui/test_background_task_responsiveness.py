from __future__ import annotations

import pytest

from app.pages.workbook_health import WorkbookHealthPage
from app.task_runner import ActiveTaskGuard, TaskRequest
from tests.ui.helpers import click_button, wait_for_background_tasks


pytestmark = pytest.mark.usability


def test_duplicate_project_writing_policy_rejects_conflicting_workbook_tasks():
    guard = ActiveTaskGuard()
    first = TaskRequest(id="first", name="First Workbook Write", category="test", callable=lambda: None, modifies_files=True, requires_workbook_lock=True)
    duplicate = TaskRequest(id="duplicate", name="Duplicate Workbook Write", category="test", callable=lambda: None, modifies_files=True, requires_workbook_lock=True)

    allowed, reason = guard.try_start(first)
    assert allowed
    allowed, reason = guard.try_start(duplicate)
    assert not allowed
    assert "project-writing task is already running" in reason
    guard.finish(first)
    allowed, reason = guard.try_start(duplicate)
    assert allowed
    guard.finish(duplicate)


def test_tool_button_reports_running_and_controls_recover(qapp, fake_config):
    page = WorkbookHealthPage(fake_config)
    page.show()

    button = click_button(page, "Run Foundation Validation")
    wait_for_background_tasks()
    assert button.isEnabled()
    text = page.result_panel.viewer.toPlainText()
    assert "Foundation Validation" in text
    assert "SUCCESS" in text or "FAILED" in text
