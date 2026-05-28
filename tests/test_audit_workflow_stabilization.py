from __future__ import annotations

from openpyxl import Workbook

from app.pages.audit import AuditPage
from core.audit.compatibility_preview import build_compatibility_impact_preview
from core.audit.defaults import audit_default, connection_changeover_default
from core.audit.drafts import discard_audit_draft, form_values_changed, load_audit_draft, save_audit_draft
from core.audit.history import read_audit_history
from core.audit_compatibility import create_compatibility_entries
from core.audit_entries import save_audit_entry
from core.config import UserConfig
from core.paths import get_press_capacity_file


def _write_press_capacity(project_root, rows):
    path = get_press_capacity_file(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Capacity"
    ws.append(["Machine No.", "NGW Part Number", "NGW Part Description"])
    for machine_cell, part_number, description in rows:
        ws.append([machine_cell, part_number, description])
    workbook.save(path)
    workbook.close()
    return path


def _save_source_audit(project_root, audit_id="AUD-PHASE2-SOURCE"):
    result = save_audit_entry(
        project_root,
        {
            "Audit ID": audit_id,
            "Audit Date": "2026-05-18",
            "Auditor": "KG",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "1",
            "Tool #": "PN-PHASE2",
            "Part Name/Description": "Synthetic Phase 2 Part",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Vacuum",
            "Status": "In Progress",
        },
    )
    assert result.success, result.errors
    return audit_id


def test_form_values_changed_detects_dirty_and_clean_states():
    baseline = {"Audit ID": "AUD-1", "Known Issues": ""}

    assert form_values_changed({"Audit ID": "AUD-1", "Known Issues": ""}, baseline) is False
    assert form_values_changed({"Audit ID": "AUD-1", "Known Issues": "Needs review"}, baseline) is True


def test_audit_draft_save_load_and_discard(fake_project):
    path = save_audit_draft(
        fake_project,
        audit_id="AUD-DRAFT-001",
        mode="edit",
        form_values={"Audit ID": "AUD-DRAFT-001", "Known Issues": "Draft note"},
        baseline_values={"Audit ID": "AUD-DRAFT-001", "Known Issues": ""},
    )

    draft = load_audit_draft(fake_project)
    assert draft is not None
    assert path.exists()
    assert "00_Project_Admin" in str(path)
    assert "cache" in str(path)
    assert draft.audit_id == "AUD-DRAFT-001"
    assert draft.form_values["Known Issues"] == "Draft note"

    assert discard_audit_draft(fake_project) is True
    assert load_audit_draft(fake_project) is None


def test_defaults_can_be_overridden_from_config():
    config = UserConfig(
        audit_defaults={"Auditor": "Synthetic Auditor", "Plant/Area": "Cleanroom"},
        connection_defaults={"ATI": "Easy"},
    )

    assert audit_default("Auditor", config) == "Synthetic Auditor"
    assert audit_default("Plant/Area", config) == "Cleanroom"
    assert connection_changeover_default("ATI", config) == "Easy"


def test_compatibility_preview_detects_linked_rows(fake_project):
    _write_press_capacity(fake_project, [("1, 2, 3", "PN-PHASE2", "Synthetic Phase 2 Part")])
    source_id = _save_source_audit(fake_project)
    result = create_compatibility_entries(fake_project, source_id, ["2", "3"])
    assert result.success, result.errors

    preview = build_compatibility_impact_preview(fake_project, source_id)

    assert preview.has_impact is True
    assert preview.compatible_row_count == 2
    assert preview.will_sync_linked_rows is True
    assert preview.will_run_autorun is True
    assert "Known Issues" in preview.fields_likely_to_propagate
    assert "Audit ID" not in preview.fields_likely_to_propagate


def test_audit_history_records_created_and_updated_fields(fake_project):
    audit_id = _save_source_audit(fake_project, "AUD-HISTORY-001")

    create_records = read_audit_history(fake_project)
    assert create_records
    assert create_records[-1]["audit_id"] == audit_id
    assert create_records[-1]["event_type"] == "audit_created"

    update = save_audit_entry(
        fake_project,
        {
            "Audit ID": audit_id,
            "Audit Date": "2026-05-18",
            "Auditor": "KG",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "1",
            "Tool #": "PN-PHASE2",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Vacuum",
            "Known Issues": "Updated synthetic issue.",
            "Status": "Needs Follow-Up",
        },
        allow_update=True,
    )
    assert update.success, update.errors

    records = read_audit_history(fake_project)
    latest = records[-1]
    assert latest["event_type"] == "audit_updated"
    assert "Known Issues" in latest["changed_fields"]
    assert latest["new_values"]["Known Issues"] == "Updated synthetic issue."


def test_audit_page_dirty_baseline_and_draft_controls(qapp, fake_config):
    page = AuditPage(fake_config)
    page.show()

    assert page.has_unsaved_changes() is False
    page.audit_fields["Known Issues"].setPlainText("Synthetic unsaved issue.")
    assert page.has_unsaved_changes() is True

    draft_path = page._save_current_audit_draft()
    assert "audit_drafts" in draft_path
    assert load_audit_draft(fake_config.project_root) is not None

    page._mark_audit_form_baseline("test")
    assert page.has_unsaved_changes() is False
    page.discard_saved_audit_draft()
    assert load_audit_draft(fake_config.project_root) is None


def test_new_audit_defaults_and_generated_ids_are_clean(qapp, fake_config):
    page = AuditPage(fake_config)
    page.show()

    assert page.has_unsaved_changes() is False
    assert page.is_clean_new_form_or_lookup_only() is True

    first_audit_id = page.audit_fields["Audit ID"].text()
    page.generate_new_audit_id(show_message=False)

    assert page.audit_fields["Audit ID"].text() != first_audit_id
    assert page.has_unsaved_changes() is False
    assert page.is_clean_new_form_or_lookup_only() is True

    page._reset_audit_form_fields(show_generated_message=False)
    assert page.has_unsaved_changes() is False
    assert page.audit_fields["Press/Machine #"].text() == ""
    assert page.audit_fields["Auditor"].text() == "Kato Gray"
    assert page.audit_fields["Status"].currentText() == "In Progress"


def test_loading_existing_audit_resets_dirty_baseline(qapp, fake_config, fake_project):
    source_id = _save_source_audit(fake_project, "AUD-DIRTY-LOAD-001")
    page = AuditPage(fake_config)
    page.show()

    assert page.load_existing_audit(source_id) is True

    assert page.has_unsaved_changes() is False
    page.audit_fields["Known Issues"].setPlainText("Unsaved edit after load.")
    assert page.has_unsaved_changes() is True


def test_saving_audit_resets_dirty_baseline(qapp, fake_config, fake_project):
    page = AuditPage(fake_config)
    page.show()

    page._set_field_value(page.audit_fields["Press/Machine #"], "101")
    page._set_field_value(page.audit_fields["Robot Type"], "Wittmann R9")
    page._set_field_value(page.audit_fields["EOAT Type"], "Vacuum")
    page.audit_fields["Known Issues"].setPlainText("Issue captured before save.")
    assert page.has_unsaved_changes() is True

    page.save_audit()

    assert page.has_unsaved_changes() is False
    assert page._audit_form_baseline == page._current_audit_form_values()


def test_audit_page_compatibility_preview_can_cancel_risky_save(qapp, fake_config, fake_project):
    _write_press_capacity(fake_project, [("1, 2", "PN-PHASE2", "Synthetic Phase 2 Part")])
    source_id = _save_source_audit(fake_project, "AUD-PREVIEW-CANCEL")
    assert create_compatibility_entries(fake_project, source_id, ["2"]).success

    page = AuditPage(fake_config)
    page.show()
    assert page.load_existing_audit(source_id) is True
    page.audit_fields["Known Issues"].setPlainText("Should not save after cancel.")
    seen = {}

    def cancel_preview(preview):
        seen["count"] = preview.compatible_row_count
        return False

    page._confirm_compatibility_impact_preview = cancel_preview
    page.save_audit()

    assert seen["count"] == 1
    assert "save canceled" in page.result_panel.viewer.toPlainText().lower()
