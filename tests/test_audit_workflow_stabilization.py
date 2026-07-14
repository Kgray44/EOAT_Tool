from __future__ import annotations

from openpyxl import Workbook

from app.pages.audit import AuditPage
from core.audit.compatibility_preview import build_compatibility_impact_preview
from core.audit.defaults import audit_default, connection_changeover_default
from core.audit.drafts import discard_audit_draft, form_values_changed, load_audit_draft, save_audit_draft
from core.audit.history import read_audit_history
from core.audit_compatibility import create_compatibility_entries
from core.audit_entries import load_audit_entry, save_audit_entry
from core.config import UserConfig
from core.paths import get_press_capacity_file
from core.result import ToolResult


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


def test_new_audit_form_initialization_is_clean_and_can_close_without_prompt(qapp, fake_config, monkeypatch):
    page = AuditPage(fake_config)
    page.show()

    def fail_if_prompted(*_args, **_kwargs):
        raise AssertionError("Clean initialized audit form should not show unsaved prompt.")

    monkeypatch.setattr("app.pages.audit.QMessageBox.exec", fail_if_prompted)

    assert page.has_unsaved_changes() is False
    assert page.can_close("notes") == (True, "")


def test_hidden_audit_page_does_not_open_draft_recovery_dialog(qapp, fake_config, monkeypatch):
    save_audit_draft(
        fake_config.project_root,
        audit_id="AUD-HIDDEN-DRAFT",
        mode="new",
        form_values={"Audit ID": "AUD-HIDDEN-DRAFT", "Known Issues": "Hidden stale draft."},
        baseline_values={"Audit ID": "AUD-HIDDEN-DRAFT", "Known Issues": ""},
    )
    page = AuditPage(fake_config)

    def fail_if_prompted(*_args, **_kwargs):
        raise AssertionError("Hidden audit pages should not open draft recovery dialogs.")

    monkeypatch.setattr("app.pages.audit.QMessageBox.exec", fail_if_prompted)

    page._offer_draft_recovery(None)

    assert load_audit_draft(fake_config.project_root) is not None


def test_user_edit_marks_dirty_and_restoring_baseline_clears_dirty(qapp, fake_config):
    page = AuditPage(fake_config)
    page.show()

    original = page.audit_fields["Known Issues"].toPlainText()
    page.audit_fields["Known Issues"].setPlainText("User-entered issue.")
    assert page.has_unsaved_changes() is True

    page.audit_fields["Known Issues"].setPlainText(original)
    assert page.has_unsaved_changes() is False


def test_navigation_during_save_does_not_prompt(qapp, fake_config, monkeypatch):
    page = AuditPage(fake_config)
    page.show()
    page.audit_fields["Known Issues"].setPlainText("Save is in progress.")
    page._save_requested = True
    page._save_in_progress = True

    def fail_if_prompted(*_args, **_kwargs):
        raise AssertionError("Save-in-progress navigation should not show unsaved prompt.")

    monkeypatch.setattr("app.pages.audit.QMessageBox.exec", fail_if_prompted)

    assert page.can_close("notes") == (True, "")
    assert page._save_navigation_requested is True


def test_restored_draft_is_clean_and_second_draft_save_is_idempotent(qapp, fake_config):
    page = AuditPage(fake_config)
    page.show()
    page.audit_fields["Known Issues"].setPlainText("Original draft issue.")
    first_path = page._save_current_audit_draft()
    first_draft = load_audit_draft(fake_config.project_root)
    assert first_draft is not None

    restored = AuditPage(fake_config)
    restored.show()
    restored._restore_audit_draft(first_draft)
    assert restored.audit_fields["Known Issues"].toPlainText() == "Original draft issue."
    assert restored.has_unsaved_changes() is False
    restored._save_current_audit_draft()
    second_draft = load_audit_draft(fake_config.project_root)

    assert second_draft is not None
    assert str(first_path).endswith("latest_audit_draft.json")
    assert second_draft.form_values["Known Issues"] == "Original draft issue."


def test_second_draft_save_preserves_old_fields_and_new_edits(qapp, fake_config):
    page = AuditPage(fake_config)
    page.show()
    page.audit_fields["Known Issues"].setPlainText("First draft value.")
    page.audit_fields["Drop/Mis-Pick History"].setPlainText("Drop history value.")
    page._save_current_audit_draft()
    first_draft = load_audit_draft(fake_config.project_root)
    assert first_draft is not None

    restored = AuditPage(fake_config)
    restored.show()
    restored._restore_audit_draft(first_draft)
    restored.audit_fields["Maintenance Frequency"].setText("Weekly")
    restored._save_current_audit_draft()
    second_draft = load_audit_draft(fake_config.project_root)

    assert second_draft is not None
    assert second_draft.form_values["Known Issues"] == "First draft value."
    assert second_draft.form_values["Drop/Mis-Pick History"] == "Drop history value."
    assert second_draft.form_values["Maintenance Frequency"] == "Weekly"


def test_draft_save_uses_all_tabs_and_preserves_hidden_values(qapp, fake_config):
    page = AuditPage(fake_config)
    page.show()
    page.audit_section_tabs.setCurrentIndex(0)
    page.audit_fields["Press/Machine #"].setText("Press 44")
    page.audit_fields["Known Issues"].setPlainText("Reliability tab issue.")
    page.audit_fields["Notes"].setPlainText("Final notes survive.")
    page.audit_fields["EOAT Type"].setCurrentText("Vacuum")
    page.audit_fields["Gripper Model"].setCurrentText("Hidden gripper value")

    page._save_current_audit_draft()
    draft = load_audit_draft(fake_config.project_root)
    restored = AuditPage(fake_config)
    restored.show()
    restored._restore_audit_draft(draft)

    assert restored.audit_fields["Press/Machine #"].text() == "Press 44"
    assert restored.audit_fields["Known Issues"].toPlainText() == "Reliability tab issue."
    assert restored.audit_fields["Notes"].toPlainText() == "Final notes survive."
    assert restored.audit_fields["Gripper Model"].currentText() == "Hidden gripper value"


def test_draft_save_keeps_blank_values_raw_not_na(qapp, fake_config):
    page = AuditPage(fake_config)
    page.show()
    page.audit_fields["Known Issues"].setPlainText("")
    page._save_current_audit_draft()

    draft = load_audit_draft(fake_config.project_root)
    assert draft is not None
    assert draft.form_values["Known Issues"] == ""


def test_save_audit_failure_preserves_visible_data_and_dirty_state(qapp, fake_config):
    page = AuditPage(fake_config)
    page.show()
    page.audit_fields["Known Issues"].setPlainText("Must remain visible.")
    page._save_requested = True
    page._save_in_progress = True
    page._pending_save_snapshot = page._current_audit_form_values()

    page._after_save_audit(
        ToolResult.fail("audit_save_entry", "Save Audit Entry", "Save failed.", errors=["boom"]),
        page.audit_fields["Audit ID"].text(),
    )

    assert page.audit_fields["Known Issues"].toPlainText() == "Must remain visible."
    assert page.has_unsaved_changes() is True
    assert page._save_requested is False
    assert page._save_in_progress is False


def test_duplicate_save_click_is_ignored_while_save_in_progress(qapp, fake_config):
    page = AuditPage(fake_config)
    page.show()
    page._save_requested = True
    page._save_in_progress = True

    page.save_audit()

    assert "already in progress" in page.result_panel.viewer.toPlainText()


def test_completed_audit_update_checkbox_choice_checked_runs_compatibility(
    qapp, fake_config, fake_project, monkeypatch
):
    source_id = _save_source_audit(fake_project, "AUD-COMPLETE-CHECKED-001")
    completed_entry = load_audit_entry(fake_project, source_id)
    completed_entry["Status"] = "Complete"
    save_audit_entry(fake_project, completed_entry, allow_update=True)
    page = AuditPage(fake_config)
    page.show()
    assert page.load_existing_audit(source_id) is True
    page.audit_fields["Known Issues"].setPlainText("Completed audit update.")
    monkeypatch.setattr(page, "_confirm_completed_audit_update", lambda audit_id: (True, True))
    seen = {}

    def fake_save_workflow(entry, *, allow_update, create_followup_action, sync_linked_compatibility=None):
        seen["sync_linked_compatibility"] = sync_linked_compatibility
        return ToolResult.ok(
            "eoat_audit_form",
            "EOAT Audit Form Tool",
            f"Saved audit entry {entry['Audit ID']}. Updated 1 linked compatibility entrie(s) from this source audit.",
            metrics={"audit_id": entry["Audit ID"], "row": 2, "updated": True, "compatibility_rows_synced": 1},
            duration_seconds=0.01,
        )

    monkeypatch.setattr(page, "_save_audit_workflow", fake_save_workflow)
    page.save_audit()

    assert seen["sync_linked_compatibility"] is True
    assert "Fit Check update for completed audit was requested." in page.result_panel.viewer.toPlainText()


def test_completed_audit_update_checkbox_choice_unchecked_skips_compatibility(
    qapp, fake_config, fake_project, monkeypatch
):
    source_id = _save_source_audit(fake_project, "AUD-COMPLETE-UNCHECKED-001")
    completed_entry = load_audit_entry(fake_project, source_id)
    completed_entry["Status"] = "Complete"
    save_audit_entry(fake_project, completed_entry, allow_update=True)
    page = AuditPage(fake_config)
    page.show()
    assert page.load_existing_audit(source_id) is True
    page.audit_fields["Known Issues"].setPlainText("Completed audit update.")
    monkeypatch.setattr(page, "_confirm_completed_audit_update", lambda audit_id: (True, False))
    seen = {}

    def fake_save_workflow(entry, *, allow_update, create_followup_action, sync_linked_compatibility=None):
        seen["sync_linked_compatibility"] = sync_linked_compatibility
        return ToolResult.ok(
            "eoat_audit_form",
            "EOAT Audit Form Tool",
            f"Saved audit entry {entry['Audit ID']}.",
            metrics={"audit_id": entry["Audit ID"], "row": 2, "updated": True, "compatibility_rows_synced": 0},
            duration_seconds=0.01,
        )

    monkeypatch.setattr(page, "_save_audit_workflow", fake_save_workflow)
    page.save_audit()

    assert seen["sync_linked_compatibility"] is False
    assert "Fit Check update skipped by user choice." in page.result_panel.viewer.toPlainText()


def test_completed_audit_update_cancel_performs_no_save(qapp, fake_config, fake_project, monkeypatch):
    source_id = _save_source_audit(fake_project, "AUD-COMPLETE-CANCEL-001")
    completed_entry = load_audit_entry(fake_project, source_id)
    completed_entry["Status"] = "Complete"
    save_audit_entry(fake_project, completed_entry, allow_update=True)
    page = AuditPage(fake_config)
    page.show()
    assert page.load_existing_audit(source_id) is True
    monkeypatch.setattr(page, "_confirm_completed_audit_update", lambda audit_id: (False, True))

    def fail_save(*_args, **_kwargs):
        raise AssertionError("Canceled completed-audit prompt should not save.")

    monkeypatch.setattr(page, "_save_audit_workflow", fail_save)
    page.save_audit()

    assert "canceled" in page.result_panel.viewer.toPlainText().lower()


def test_completed_audit_update_checkbox_defaults_checked(qapp, fake_config, monkeypatch):
    page = AuditPage(fake_config)
    page.show()
    seen = {}
    clicked = {}

    def fake_exec(box):
        seen["checked"] = box.checkBox().isChecked()
        clicked["button"] = next(button for button in box.buttons() if button.text() == "Cancel")
        return 0

    def fake_clicked_button(box):
        return clicked["button"]

    monkeypatch.setattr("app.pages.audit.QMessageBox.exec", fake_exec)
    monkeypatch.setattr("app.pages.audit.QMessageBox.clickedButton", fake_clicked_button)

    accepted, update_compatibility = page._confirm_completed_audit_update("AUD-COMPLETE-DEFAULT")

    assert accepted is False
    assert update_compatibility is True
    assert seen["checked"] is True


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
