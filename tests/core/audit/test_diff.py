from __future__ import annotations

from core.audit.diff import (
    CHANGE_CHANGED,
    CHANGE_CLEARED,
    CHANGE_SET_TO_NA,
    CHANGE_SMART_DEFAULTED,
    CHANGE_UNKNOWN_NOT_CHECKED,
    build_audit_save_preview,
)


def _change(preview, field):
    for item in preview.changes:
        if item.field == field:
            return item
    raise AssertionError(f"Missing change for {field}")


def test_save_preview_detects_changed_fields():
    preview = build_audit_save_preview(
        {"Audit ID": "AUD-001", "Tool #": "T-1"},
        {"Audit ID": "AUD-001", "Tool #": "T-2"},
    )

    assert _change(preview, "Tool #").change_type == CHANGE_CHANGED
    assert "Tool #" in preview.changed_fields


def test_save_preview_detects_fields_cleared_to_na():
    preview = build_audit_save_preview(
        {"Audit ID": "AUD-001", "# of Cups": "4", "Gripper Model": "Demo"},
        {"Audit ID": "AUD-001", "# of Cups": "N/A", "Gripper Model": ""},
    )

    assert _change(preview, "# of Cups").change_type == CHANGE_SET_TO_NA
    assert _change(preview, "Gripper Model").change_type == CHANGE_CLEARED
    assert "# of Cups" in preview.set_to_na_fields
    assert "Gripper Model" in preview.cleared_fields


def test_preview_detects_robot_side_pneumatic_changes():
    preview = build_audit_save_preview(
        {"Audit ID": "AUD-001", "Robot Vacuum Circuits": "3"},
        {"Audit ID": "AUD-001", "Robot Vacuum Circuits": "4"},
    )

    assert preview.robot_info_changes
    assert preview.robot_info_changes[0].field == "Robot Vacuum Circuits"
    assert preview.robot_info_changes[0].source == "robot_info"


def test_preview_detects_robot_notes_as_robot_info_change():
    preview = build_audit_save_preview(
        {"Audit ID": "AUD-001", "Robot Notes": ""},
        {"Audit ID": "AUD-001", "Robot Notes": "Keep wrist-side air line labels."},
    )

    assert preview.robot_info_changes
    assert preview.robot_info_changes[0].field == "Robot Notes"
    assert preview.robot_info_changes[0].source == "robot_info"


def test_preview_marks_autofilled_sensor_fields_defaulted():
    preview = build_audit_save_preview(
        {"Audit ID": "AUD-001", "Sensor Type": ""},
        {"Audit ID": "AUD-001", "Sensor Type": "Reed Switch"},
        smart_defaulted_fields={"Sensor Type"},
    )

    assert _change(preview, "Sensor Type").change_type == CHANGE_SMART_DEFAULTED
    assert preview.smart_defaulted_fields == ("Sensor Type",)


def test_preview_marks_unknown_not_checked():
    preview = build_audit_save_preview(
        {"Audit ID": "AUD-001", "Tubing Condition": ""},
        {"Audit ID": "AUD-001", "Tubing Condition": "Unknown / Not Checked"},
    )

    assert _change(preview, "Tubing Condition").change_type == CHANGE_UNKNOWN_NOT_CHECKED
    assert "Tubing Condition" in preview.unknown_not_checked_fields
