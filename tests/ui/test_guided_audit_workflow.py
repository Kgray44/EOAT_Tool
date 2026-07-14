from __future__ import annotations

import pytest

from app.pages.audit import AuditPage
from tests.ui.helpers import click_button, wait_for_background_tasks

pytestmark = pytest.mark.usability


def test_guided_audit_mode_toggle_open_full_and_draft_resume(qapp, fake_config):
    page = AuditPage(fake_config)
    page.show()

    assert page.audit_entry_mode_combo.currentText() == "Section Form"
    page.audit_entry_mode_combo.setCurrentText("Guided Audit")
    assert page.audit_mode_stack.currentIndex() == 0
    assert page.guided_audit_tabs.count() == 8

    page.audit_fields["Press/Machine #"].setText("Press 88")
    click_button(page, "Save Draft")
    page.audit_fields["Press/Machine #"].setText("")
    click_button(page, "Resume Draft")

    assert page.audit_fields["Press/Machine #"].text() == "Press 88"

    click_button(page, "Open Full Audit")

    assert page.audit_entry_mode_combo.currentText() == "Section Form"
    assert page.audit_mode_stack.currentIndex() == 1
    assert page.audit_view_mode_combo.currentText() == "Full Audit"


def test_guided_final_review_shows_save_impact_categories(qapp, fake_config):
    page = AuditPage(fake_config)
    page.show()
    page.audit_entry_mode_combo.setCurrentText("Guided Audit")
    page.guided_audit_tabs.setCurrentIndex(page.guided_audit_tabs.count() - 1)
    page.audit_fields["Photos Taken?"].setCurrentText("Yes")
    page.audit_fields["Photo Folder/Link"].setText("")
    page._refresh_guided_audit(force_io_preview=True)

    table = page._guided_step_tables["final_review_save_impact"]
    rows = [table.item(row, 0).text() for row in range(table.rowCount())]

    assert "Missing fields" in rows
    assert "Unknown / Not Checked" in rows
    assert "Defaults" in rows
    assert "Robot info updates" in rows
    assert "Fit Check impact" in rows
    assert "Photo warnings" in rows


def test_guided_mode_save_audit_uses_existing_save_workflow(qapp, fake_config, fake_project):
    page = AuditPage(fake_config)
    page.show()
    page.audit_entry_mode_combo.setCurrentText("Guided Audit")
    page.audit_fields["Press/Machine #"].setText("Press 91")
    page.audit_fields["Robot Type"].setCurrentText("Wittmann R9")
    page.audit_fields["EOAT Type"].setCurrentText("Vacuum")
    page.audit_fields["Tool #"].setText("GUIDED-TOOL")

    click_button(page, "Save Audit Entry")
    wait_for_background_tasks()

    audit_id = page.audit_fields["Audit ID"].text()
    assert audit_id
    assert "Audit Save Summary" in page.result_panel.viewer.toPlainText()
