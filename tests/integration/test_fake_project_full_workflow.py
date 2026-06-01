from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QComboBox, QTextEdit

from app.dashboard_ui import DashboardWindow
from app.navigation import NAV_ITEMS
from app.pages.audit import AuditPage
from core.workbook_io import row_dicts
from tests.ui.helpers import assert_only_fake_project_paths, click_button, wait_for_background_tasks, wait_until

pytestmark = [pytest.mark.usability, pytest.mark.integration, pytest.mark.slow]


def _set_audit_field(page: AuditPage, field: str, value: str) -> None:
    widget = page.audit_fields[field]
    if isinstance(widget, QComboBox):
        if widget.findText(value) >= 0:
            widget.setCurrentText(value)
        else:
            widget.setEditText(value)
    elif isinstance(widget, QTextEdit):
        widget.setPlainText(value)
    else:
        widget.setText(value)


def test_fake_user_day2_workflow_end_to_end(
    qapp, fake_config, fake_project, frozen_project_date, captured_open_requests, monkeypatch
):
    import app.dashboard_ui as dashboard_ui

    monkeypatch.setattr(dashboard_ui, "load_config", lambda: fake_config)
    window = DashboardWindow()
    window.show()
    wait_for_background_tasks()

    home = window.pages["home"]
    wait_until(
        lambda: bool(home.cards["Resolved Project Day"].value_label.text()),
        timeout_ms=2000,
        message="home dashboard resolved day",
    )
    assert home.cards["Resolved Project Day"].value_label.text().startswith("Week 1 Day 2")

    click_button(home, "Generate Morning Plan")
    wait_for_background_tasks(timeout_ms=30000)

    window._show_page("schedule")
    schedule = window.pages["schedule"]
    schedule.task_table.selectRow(3)
    click_button(schedule, "In progress")

    window._show_page("audit")
    audit = window.pages["audit"]
    for field, value in {
        "Auditor": "End to End Tester",
        "Plant/Area": "Plant 4",
        "Press/Machine #": "Press 106",
        "Robot Type": "Wittmann R9",
        "Part Family": "Part family E2E",
        "EOAT Type": "Vacuum",
        "Known Issues": "Misalignment found in fake end-to-end test.",
        "Vacuum Confirmation Present?": "Unknown / Not Checked",
        "Quick Disconnects Present?": "Yes",
        "Status": "Needs Follow-Up",
        "Priority": "High",
        "Pilot Candidate?": "Maybe",
        "Notes": "Synthetic controller. Pilot candidate: maybe.",
    }.items():
        _set_audit_field(audit, field, value)
    audit_id = audit.audit_fields["Audit ID"].text()
    click_button(audit, "Save Audit Entry")
    wait_for_background_tasks(timeout_ms=30000)
    assert any(
        row["Audit ID"] == audit_id
        for row in row_dicts(
            fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx", "EOAT Inventory"
        )
    )

    window._show_page("photos")
    photos = window.pages["photos"]
    photos.incoming_list.item(0).setSelected(True)
    photos.plant_edit.setText("Molding")
    photos.press_edit.setText("Press 106")
    photos.date_edit.setText("2026-05-19")
    photos.view_combo.setCurrentText("Overall")
    photos.audit_id_edit.setText(audit_id)
    click_button(photos, "Confirm Intake")
    wait_for_background_tasks(timeout_ms=30000)

    for page_key, button_label in [
        ("workbook_health", "Run Foundation Validation"),
        ("issue_analysis", "Run Issue Analysis"),
        ("fmea", "Run FMEA Analysis"),
        ("pilot_candidates", "Run Pilot Ranking"),
        ("kpi_dashboard", "Run KPI Analysis"),
        ("pm_checklists", "Generate Generic Templates"),
        ("bom_spares", "Run BOM/Spare Parts Analysis"),
    ]:
        window._show_page(page_key)
        click_button(window.pages[page_key], button_label)
        wait_for_background_tasks(timeout_ms=30000)

    window._show_page("reports")
    reports = window.pages["reports"]
    reports.refresh()
    assert reports.folder_table.rowCount() > 0

    window._show_page("handoff")
    handoff = window.pages["handoff"]
    click_button(handoff, "Run Final Deliverable Check")
    wait_for_background_tasks(timeout_ms=30000)

    window.apply_theme("dark")
    assert window.config.theme == "dark"
    for item in NAV_ITEMS:
        window._show_page(item.page_key)
        qapp.processEvents()

    activity_log = fake_project / "00_Project_Admin" / "Activity_Logs" / "activity_log.jsonl"
    entries = [json.loads(line) for line in activity_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(entries) >= 8
    assert all(str(fake_project) in entry["project_root"] for entry in entries if entry.get("project_root"))

    generated_paths: list[str] = []
    for entry in entries:
        generated_paths.extend(entry.get("files_created") or [])
        generated_paths.extend(entry.get("files_modified") or [])
    assert_only_fake_project_paths(fake_project, generated_paths)
    assert not captured_open_requests
