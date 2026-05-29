from __future__ import annotations

from app.dashboard_ui import DashboardWindow
from app.pages.annotation_suggestions_dialog import AnnotationSuggestionsDialog
from app.pages.audit import AuditPage
from app.pages.open_items import OpenItemsPage
from core.annotations.service import AnnotationService
from core.open_items import list_open_items
from tests.ui.helpers import wait_for_background_tasks


def test_annotation_suggestions_dialog_applies_and_ignores_rows(qapp, fake_config):
    page = AuditPage(fake_config)
    entry = {
        "Audit ID": "AUD-DIALOG-SUGGEST-001",
        "Press/Machine #": "12",
        "EOAT Type": "Mechanical / Gripper",
        "Cup Type/Material": "Silicone",
    }
    dialog = AnnotationSuggestionsDialog(page, entry)

    assert dialog.table.rowCount() == 1
    dialog.table.selectRow(0)
    dialog.apply_selected()

    service = AnnotationService(fake_config.project_root)
    assignments = service.list_tag_assignments(audit_id="AUD-DIALOG-SUGGEST-001", target_type="audit_field")
    assert assignments[0]["tag_name"] == "Data Conflict"

    dialog.refresh()
    dialog.table.selectRow(0)
    dialog.ignore_selected()
    assert dialog.table.rowCount() == 0
    dialog.show_ignored_check.setChecked(True)
    assert dialog.table.rowCount() == 1


def test_open_items_page_filters_and_status_actions(qapp, fake_config, monkeypatch):
    service = AnnotationService(fake_config.project_root)
    target = service.create_or_get_target("audit_field", audit_id="AUD-OPEN-UI-001", machine_id="12", field_key="Sensor Type", field_label="Sensor Type")
    service.create_note("UI open note", "Body", "Critical", status="Open", target_ids=[target.id])
    service.assign_tag_to_target(service.get_tag_by_name("Needs Review").id, target.id, sync_workbook=False)
    page = OpenItemsPage(fake_config)
    page.show()
    wait_for_background_tasks()
    page.deep_rebuild(force=True)
    wait_for_background_tasks()

    assert page.table.rowCount() >= 2
    page.search_edit.setText("UI open note")
    assert page.table.rowCount() == 1
    page.table.selectRow(0)
    selected = page.selected_item()
    assert selected is not None
    page.mark_resolved()
    assert "cannot be manually marked resolved" in page.status_label.text()
    assert selected.id in {item.id for item in list_open_items(fake_config.project_root, include_validation=False)}

    monkeypatch.setattr("app.pages.open_items.QInputDialog.getText", lambda *args, **kwargs: ("UI dismissal reason", True))
    page.dismiss_selected()
    visible_ids = {item.id for item in list_open_items(fake_config.project_root, include_validation=False)}
    assert selected.id not in visible_ids
    page.status_filter.setCurrentText("Dismissed / Overridden")
    assert page.table.rowCount() == 1


def test_open_items_page_opens_audit_field_target(qapp, fake_config, fake_project):
    from core.audit_entries import save_audit_entry

    save_audit_entry(
        fake_project,
        {
            "Audit ID": "AUD-OPEN-TARGET-001",
            "Audit Date": "2026-05-18",
            "Auditor": "Demo",
            "Plant/Area": "Demo",
            "Press/Machine #": "12",
            "Robot Type": "Demo Robot",
            "EOAT Type": "Vacuum",
            "Sensor Type": "Demo Sensor",
            "Status": "In Progress",
        },
    )
    service = AnnotationService(fake_config.project_root)
    target = service.create_or_get_target("audit_field", audit_id="AUD-OPEN-TARGET-001", machine_id="12", field_key="Sensor Type", field_label="Sensor Type")
    service.assign_tag_to_target(service.get_tag_by_name("Needs Review").id, target.id, sync_workbook=False)

    window = DashboardWindow(fake_config)
    window._show_page("open_items")
    page = window.pages["open_items"]
    page.deep_rebuild(force=True)
    wait_for_background_tasks()
    page.search_edit.setText("AUD-OPEN-TARGET-001")
    page.source_filter.setCurrentText("tag")
    page.table.selectRow(0)
    page.open_target()

    audit_page = window.pages["audit"]
    assert audit_page.audit_fields["Audit ID"].text() == "AUD-OPEN-TARGET-001"
    assert "Target field: Sensor Type" in audit_page.result_panel.viewer.toPlainText()
