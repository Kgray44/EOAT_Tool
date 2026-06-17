from __future__ import annotations

from core.audit.completion import (
    STATE_EXCLUDED,
    STATE_IGNORED_BY_MANUAL_OVERRIDE,
    STATE_IGNORED_BY_OPTIONAL_GROUP,
    STATE_MISSING,
    STATE_NOT_APPLICABLE,
    STATE_NOT_OBSERVABLE,
    STATE_STALE_CONFLICT,
    STATE_UNKNOWN_NOT_CHECKED,
    STATE_VERIFIED_COMPLETE,
    calculate_audit_completion,
)
from core.audit.defaults import UNKNOWN_NOT_CHECKED
from core.audit_constants import (
    AUDIT_CONTEXT_BENCH,
    AUDIT_CONTEXT_FIELD,
    AUDIT_CONTEXT_INSTALLED,
    CYLINDER_COUNT_FIELD,
    CYLINDER_TYPE_DEFAULT,
    CYLINDER_TYPE_FIELD,
    ENTRY_TYPE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_FIELD,
)

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
    "Machine / Robot / Tool Context": [
        "Robot Type",
        "Robot Model/Controller",
        "Tool #",
        "Part Family",
        "Part Name/Description",
        "Cleanroom/Non-Cleanroom",
    ],
    "EOAT Type and Tooling": [
        "EOAT Type",
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
    ],
    "Pneumatic Circuits": [
        "EOAT Vacuum Circuits",
        "EOAT Pressure Circuits",
        "EOAT Interchangeable Circuits",
        "Robot Vacuum Circuits",
        "Robot Pressure Circuits",
        "Robot Interchangeable Circuits",
        "Robot Notes",
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
    "Performance / Reliability / Maintenance": [
        "Known Issues",
        "Drop/Mis-Pick History",
        "Maintenance Frequency",
        "Cycle Time Concern?",
        "Scrap/Quality Concern?",
        "Changeover Difficulty",
    ],
    "Documentation / Photos": ["Photos Taken?", "Photo Folder/Link"],
    "Pilot / Final Notes": ["Robot Notes", "Notes", "Source Audit ID", "Compatibility Source"],
}


def _entry(**overrides):
    data = {
        "Audit ID": "AUD-COMP-001",
        "Audit Date": "2026-05-28",
        "Auditor": "Synthetic Auditor",
        "Plant/Area": "Plant 4",
        "Press/Machine #": "12",
        "Robot Type": "Wittmann R9",
        "Robot Model/Controller": "W833 / R9",
        "Part Family": "Demo family",
        "Part Name/Description": "Demo part",
        "Cleanroom/Non-Cleanroom": "Whiteroom",
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
        "EOAT Vacuum Circuits": "2",
        "EOAT Pressure Circuits": "1",
        "EOAT Interchangeable Circuits": "0",
        "Robot Vacuum Circuits": "4",
        "Robot Pressure Circuits": "2",
        "Robot Interchangeable Circuits": "0",
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
        "Known Issues": "None",
        "Drop/Mis-Pick History": "None",
        "Maintenance Frequency": "Standard",
        "Cycle Time Concern?": "No",
        "Scrap/Quality Concern?": "No",
        "Changeover Difficulty": "Normal",
        "Photos Taken?": "Yes",
        "Photo Folder/Link": "photos/demo",
        "Robot Notes": "",
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
    summary = calculate_audit_completion(
        _entry(**{AUDIT_CONTEXT_FIELD: AUDIT_CONTEXT_INSTALLED, "Press/Machine #": "", "Tool #": ""}), SECTIONS
    )

    assert summary.percent_complete < 100
    assert "Press/Machine #" in summary.missing_required_fields
    assert _status(summary, "Press/Machine #").state == STATE_MISSING


def test_uninstalled_tool_audit_ignores_machine_context_fields():
    summary = calculate_audit_completion(
        _entry(
            **{
                AUDIT_CONTEXT_FIELD: AUDIT_CONTEXT_BENCH,
                "Plant/Area": "",
                "Press/Machine #": "",
                "Robot Type": "",
                "Robot Model/Controller": "",
                "Robot Vacuum Circuits": "",
                "Robot Pressure Circuits": "",
                "Robot Interchangeable Circuits": "",
                "Robot Notes": "",
                "Cycle Time Concern?": "",
                "Scrap/Quality Concern?": "",
                "Tool #": "T-001",
            }
        ),
        SECTIONS,
    )

    assert summary.percent_complete == 100
    assert summary.audit_context == AUDIT_CONTEXT_BENCH
    assert summary.installed_cell_validation_score == "Not Installed / Pending"
    ignored_fields = {
        "Plant/Area",
        "Press/Machine #",
        "Robot Type",
        "Robot Model/Controller",
        "Robot Vacuum Circuits",
        "Robot Pressure Circuits",
        "Robot Interchangeable Circuits",
        "Robot Notes",
        "Cycle Time Concern?",
        "Scrap/Quality Concern?",
    }
    assert ignored_fields.isdisjoint(summary.missing_required_fields)
    assert ignored_fields.isdisjoint(summary.missing_fields)
    for field in ignored_fields - {"Robot Notes"}:
        assert _status(summary, field).state == STATE_NOT_OBSERVABLE
    assert _status(summary, "Robot Notes").state == STATE_EXCLUDED


def test_bench_audit_still_scores_eoat_documentation_fields():
    summary = calculate_audit_completion(
        _entry(
            **{
                AUDIT_CONTEXT_FIELD: AUDIT_CONTEXT_BENCH,
                "Press/Machine #": "",
                "Robot Type": "",
                "EOAT Type": "",
                "Tool #": "T-001",
            }
        ),
        SECTIONS,
    )

    assert summary.percent_complete < 100
    assert "EOAT Type" in summary.missing_fields
    assert "Robot Type" not in summary.missing_fields
    assert _status(summary, "Robot Type").state == STATE_NOT_OBSERVABLE


def test_installed_tool_audit_counts_missing_robot_circuit_fields():
    summary = calculate_audit_completion(
        _entry(
            **{
                "Press/Machine #": "12",
                AUDIT_CONTEXT_FIELD: AUDIT_CONTEXT_INSTALLED,
                "Tool #": "T-001",
                "Robot Vacuum Circuits": "",
                "Robot Pressure Circuits": "",
                "Robot Interchangeable Circuits": "",
                "Cycle Time Concern?": "",
                "Scrap/Quality Concern?": "",
            }
        ),
        SECTIONS,
    )

    assert summary.percent_complete < 100
    assert "Robot Vacuum Circuits" in summary.missing_fields
    assert "Robot Pressure Circuits" in summary.missing_fields
    assert "Robot Interchangeable Circuits" in summary.missing_fields
    assert "Cycle Time Concern?" in summary.missing_fields
    assert "Scrap/Quality Concern?" in summary.missing_fields
    assert _status(summary, "Robot Vacuum Circuits").state == STATE_MISSING


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
    assert _status(summary, "Robot Notes").state == STATE_EXCLUDED
    assert _status(summary, "Tubing Routing Notes").state == STATE_EXCLUDED
    assert "Notes" in summary.excluded_fields
    assert "Robot Notes" in summary.excluded_fields
    assert "Robot Notes" not in summary.missing_fields
    assert "Tubing Routing Notes" not in summary.missing_fields


def test_empty_optional_cylinder_group_is_ignored():
    summary = calculate_audit_completion(_entry(), SECTIONS)

    assert _status(summary, CYLINDER_COUNT_FIELD).state == STATE_IGNORED_BY_OPTIONAL_GROUP
    assert _status(summary, CYLINDER_TYPE_FIELD).state == STATE_IGNORED_BY_OPTIONAL_GROUP
    assert CYLINDER_COUNT_FIELD not in summary.missing_fields


def test_cylinder_type_alone_does_not_trigger_optional_group():
    summary = calculate_audit_completion(_entry(**{CYLINDER_TYPE_FIELD: "Rotary", CYLINDER_COUNT_FIELD: ""}), SECTIONS)

    assert _status(summary, CYLINDER_COUNT_FIELD).state == STATE_IGNORED_BY_OPTIONAL_GROUP
    assert _status(summary, CYLINDER_TYPE_FIELD).state == STATE_IGNORED_BY_OPTIONAL_GROUP
    assert CYLINDER_TYPE_FIELD not in summary.missing_fields


def test_default_cylinder_type_alone_does_not_count_against_completion():
    summary = calculate_audit_completion(
        _entry(**{CYLINDER_TYPE_FIELD: CYLINDER_TYPE_DEFAULT, CYLINDER_COUNT_FIELD: ""}), SECTIONS
    )

    assert _status(summary, CYLINDER_COUNT_FIELD).state == STATE_IGNORED_BY_OPTIONAL_GROUP
    assert _status(summary, CYLINDER_TYPE_FIELD).state == STATE_IGNORED_BY_OPTIONAL_GROUP
    assert CYLINDER_TYPE_FIELD not in summary.missing_fields


def test_triggered_optional_cylinder_group_is_counted_and_defaults_type():
    summary = calculate_audit_completion(_entry(**{CYLINDER_TYPE_FIELD: "", CYLINDER_COUNT_FIELD: "2"}), SECTIONS)

    assert _status(summary, CYLINDER_COUNT_FIELD).state == STATE_VERIFIED_COMPLETE
    assert _status(summary, CYLINDER_TYPE_FIELD).state == STATE_VERIFIED_COMPLETE
    assert _status(summary, CYLINDER_TYPE_FIELD).value == CYLINDER_TYPE_DEFAULT
    assert CYLINDER_COUNT_FIELD not in summary.missing_fields


def test_triggered_optional_cylinder_group_preserves_manual_type():
    summary = calculate_audit_completion(_entry(**{CYLINDER_TYPE_FIELD: "Rotary", CYLINDER_COUNT_FIELD: "2"}), SECTIONS)

    assert _status(summary, CYLINDER_COUNT_FIELD).state == STATE_VERIFIED_COMPLETE
    assert _status(summary, CYLINDER_TYPE_FIELD).state == STATE_VERIFIED_COMPLETE
    assert _status(summary, CYLINDER_TYPE_FIELD).value == "Rotary"


def test_manual_override_sets_audit_percent_without_verifying_fields():
    summary = calculate_audit_completion(
        _entry(
            **{
                "Press/Machine #": "",
                AUDIT_CONTEXT_FIELD: AUDIT_CONTEXT_INSTALLED,
                "Tool #": "",
                MANUAL_COMPLETION_OVERRIDE_FIELD: "Yes",
                "Ignored Empty Fields At Override": "Press/Machine #",
            }
        ),
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
