from __future__ import annotations

from core.audit.completion import (
    STATE_EXCLUDED,
    STATE_IGNORED_BY_MANUAL_OVERRIDE,
    STATE_IGNORED_BY_OPTIONAL_GROUP,
    STATE_MISSING,
    STATE_NOT_APPLICABLE,
    STATE_STALE_CONFLICT,
    STATE_UNKNOWN_NOT_CHECKED,
    STATE_VERIFIED_COMPLETE,
    calculate_audit_completion,
)
from core.audit_constants import CYLINDER_COUNT_FIELD, CYLINDER_TYPE_DEFAULT, CYLINDER_TYPE_FIELD, ENTRY_TYPE_FIELD, MANUAL_COMPLETION_OVERRIDE_FIELD
from core.audit.defaults import UNKNOWN_NOT_CHECKED


SECTIONS = {
    "Audit Header": [
        "Audit ID",
        "Audit Date",
        "Auditor",
        "Plant/Area",
        "Press/Machine #",
        "Status",
        "Priority",
        "Follow-Up Needed",
        ENTRY_TYPE_FIELD,
    ],
    "EOAT Type and Tooling": [
        "EOAT Type",
        "Tool #",
        "EOAT Moves",
        "Connection Type",
        "Number of Parts Picked",
        CYLINDER_COUNT_FIELD,
        CYLINDER_TYPE_FIELD,
        "# of Cups",
        "Cup Type/Material",
        "Cup Diameter/Size",
        "Vacuum Generator Type",
        "# of Grippers",
        "Gripper Type",
        "Gripper Model",
        "Gripper Size",
    ],
    "Sensors and Detection": [
        "Sensors Present?",
        "Sensor Type",
        "Sensor Brand/Model",
        "Vacuum Confirmation Present?",
        "Part-Present Detection Present?",
        "Electrical/Wiring Present?",
    ],
    "Connections / Routing / Mechanical": [
        "Quick Disconnects Present?",
        "Pneumatic Quick Disconnect Type",
        "Electrical Quick Disconnect Type",
        "Tubing Condition",
        "Tubing Routing Notes",
    ],
    "Documentation / Photos": ["Photos Taken?", "Photo Folder/Link"],
    "Pilot / Final Notes": ["Notes", "Source Audit ID", "Compatibility Source"],
}


def _entry(**overrides):
    data = {
        "Audit ID": "AUD-COMP-001",
        "Audit Date": "2026-05-28",
        "Auditor": "Synthetic Auditor",
        "Plant/Area": "Plant 4",
        "Press/Machine #": "12",
        "Status": "Complete",
        "Priority": "Medium",
        "Follow-Up Needed": "No",
        ENTRY_TYPE_FIELD: "Audited",
        "EOAT Type": "Vacuum",
        "Tool #": "T-001",
        "EOAT Moves": "Part",
        "Connection Type": "ATI",
        "Number of Parts Picked": "1",
        CYLINDER_COUNT_FIELD: "",
        CYLINDER_TYPE_FIELD: CYLINDER_TYPE_DEFAULT,
        "# of Cups": "4",
        "Cup Type/Material": "Silicone",
        "Cup Diameter/Size": "20 mm",
        "Vacuum Generator Type": "Venturi",
        "# of Grippers": "N/A",
        "Gripper Type": "N/A",
        "Gripper Model": "N/A",
        "Gripper Size": "N/A",
        "Sensors Present?": "Yes",
        "Sensor Type": "Reed Switch",
        "Sensor Brand/Model": "SMC",
        "Vacuum Confirmation Present?": "Yes",
        "Part-Present Detection Present?": "No",
        "Electrical/Wiring Present?": "No",
        "Quick Disconnects Present?": "No",
        "Pneumatic Quick Disconnect Type": "N/A",
        "Electrical Quick Disconnect Type": "N/A",
        "Tubing Condition": "OK",
        "Tubing Routing Notes": "",
        "Photos Taken?": "Yes",
        "Photo Folder/Link": "photos/demo",
        "Notes": "",
        "Source Audit ID": "",
        "Compatibility Source": "",
    }
    data.update(overrides)
    return data


def _status(summary, field):
    for section in summary.sections:
        for status in section.fields:
            if status.field == field:
                return status
    raise AssertionError(f"Missing status for {field}")


def test_full_audit_calculates_100_percent():
    summary = calculate_audit_completion(_entry(), SECTIONS)

    assert summary.percent_complete == 100
    assert summary.can_finish is True
    assert summary.missing_fields == ()


def test_missing_required_field_reduces_completion():
    summary = calculate_audit_completion(_entry(**{"Press/Machine #": ""}), SECTIONS)

    assert summary.percent_complete < 100
    assert "Press/Machine #" in summary.missing_required_fields
    assert _status(summary, "Press/Machine #").state == STATE_MISSING


def test_unknown_not_checked_is_explicit_but_not_verified_complete():
    summary = calculate_audit_completion(_entry(**{"Tubing Condition": UNKNOWN_NOT_CHECKED}), SECTIONS)
    status = _status(summary, "Tubing Condition")

    assert status.state == STATE_UNKNOWN_NOT_CHECKED
    assert status.counted is True
    assert status.verified is False
    assert summary.percent_complete < 100


def test_non_applicable_fields_are_ignored():
    summary = calculate_audit_completion(
        _entry(
            **{
                "EOAT Type": "Mechanical / Gripper",
                "# of Cups": "N/A",
                "Cup Type/Material": "N/A",
                "Cup Diameter/Size": "N/A",
                "Vacuum Generator Type": "N/A",
                "# of Grippers": "2",
                "Gripper Type": "Single Pressure",
                "Gripper Model": "Demo Gripper",
                "Gripper Size": "Small",
                "Vacuum Confirmation Present?": "N/A",
            }
        ),
        SECTIONS,
    )

    assert _status(summary, "# of Cups").state == STATE_NOT_APPLICABLE
    assert _status(summary, "# of Cups").counted is False
    assert "# of Cups" not in summary.missing_fields


def test_stale_hidden_values_are_flagged():
    summary = calculate_audit_completion(
        _entry(
            **{
                "EOAT Type": "Mechanical / Gripper",
                "# of Cups": "3",
                "# of Grippers": "2",
                "Gripper Type": "Single Pressure",
                "Gripper Model": "Demo Gripper",
                "Gripper Size": "Small",
            }
        ),
        SECTIONS,
    )

    assert _status(summary, "# of Cups").state == STATE_STALE_CONFLICT
    assert "# of Cups" in summary.stale_conflict_fields
    assert any("stale_hidden_value" in finding for finding in summary.findings)


def test_excluded_fields_are_ignored():
    summary = calculate_audit_completion(_entry(), SECTIONS)

    assert _status(summary, "Notes").state == STATE_EXCLUDED
    assert _status(summary, "Tubing Routing Notes").state == STATE_EXCLUDED
    assert "Notes" in summary.excluded_fields
    assert "Tubing Routing Notes" not in summary.missing_fields


def test_empty_optional_cylinder_group_is_ignored():
    summary = calculate_audit_completion(_entry(), SECTIONS)

    assert _status(summary, CYLINDER_COUNT_FIELD).state == STATE_IGNORED_BY_OPTIONAL_GROUP
    assert _status(summary, CYLINDER_TYPE_FIELD).state == STATE_IGNORED_BY_OPTIONAL_GROUP
    assert CYLINDER_COUNT_FIELD not in summary.missing_fields


def test_triggered_optional_cylinder_group_is_counted():
    summary = calculate_audit_completion(_entry(**{CYLINDER_TYPE_FIELD: "Rotary", CYLINDER_COUNT_FIELD: ""}), SECTIONS)

    assert _status(summary, CYLINDER_COUNT_FIELD).state == STATE_MISSING
    assert _status(summary, CYLINDER_TYPE_FIELD).state == STATE_VERIFIED_COMPLETE
    assert CYLINDER_COUNT_FIELD in summary.missing_fields


def test_manual_override_sets_audit_percent_without_verifying_fields():
    summary = calculate_audit_completion(
        _entry(**{"Press/Machine #": "", MANUAL_COMPLETION_OVERRIDE_FIELD: "Yes", "Ignored Empty Fields At Override": "Press/Machine #"}),
        SECTIONS,
    )
    status = _status(summary, "Press/Machine #")

    assert summary.percent_complete == 100
    assert summary.raw_percent_complete < 100
    assert summary.can_finish is True
    assert status.state == STATE_IGNORED_BY_MANUAL_OVERRIDE
    assert status.truth_state == STATE_MISSING
    assert status.verified is False


def test_compatibility_rows_and_physical_rows_calculate_differently():
    compatible = calculate_audit_completion(
        _entry(
            **{
                ENTRY_TYPE_FIELD: "Compatible",
                "Audit Date": "",
                "Auditor": "",
                "Robot Type": "",
                "EOAT Type": "",
                "Tubing Condition": "",
            }
        ),
        SECTIONS,
    )
    physical = calculate_audit_completion(_entry(**{"Robot Type": "", "Tubing Condition": ""}), SECTIONS)

    assert compatible.percent_complete == 100
    assert _status(compatible, "Tubing Condition").state == STATE_EXCLUDED
    assert physical.percent_complete < 100
    assert _status(physical, "Tubing Condition").state == STATE_MISSING
