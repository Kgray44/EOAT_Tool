from __future__ import annotations

from core.audit.coach import (
    STATE_FOLLOW_UP_NEEDED,
    STATE_MISSING,
    STATE_NOT_APPLICABLE,
    STATE_STALE_CONFLICT,
    STATE_UNKNOWN_NOT_CHECKED,
    STATE_VERIFIED_COMPLETE,
    calculate_audit_coach_summary,
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
    ],
    "EOAT Type and Tooling": [
        "EOAT Type",
        "Tool #",
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
    "Documentation / Photos": ["Photos Taken?", "Photo Folder/Link"],
    "Connections / Routing / Mechanical": ["Tubing Condition", "Tubing Routing Notes"],
    "Pilot / Final Notes": ["Notes"],
}


def _base_entry(**overrides):
    entry = {
        "Audit ID": "AUD-COACH-001",
        "Audit Date": "2026-05-27",
        "Auditor": "Demo Auditor",
        "Plant/Area": "Demo Area",
        "Press/Machine #": "Demo Press",
        "Status": "In Progress",
        "Priority": "Medium",
        "Follow-Up Needed": "No",
        "EOAT Type": "Vacuum",
        "Tool #": "Demo Tool",
        "# of Cups": "4",
        "Cup Type/Material": "Demo Cup",
        "Cup Diameter/Size": "20",
        "Vacuum Generator Type": "Venturi",
        "# of Grippers": "N/A",
        "Gripper Type": "N/A",
        "Gripper Model": "N/A",
        "Gripper Size": "N/A",
        "Sensors Present?": "Yes",
        "Sensor Type": "Reed Switch",
        "Sensor Brand/Model": "Demo Sensor",
        "Vacuum Confirmation Present?": "Yes",
        "Part-Present Detection Present?": "No",
        "Electrical/Wiring Present?": "Unknown / Not Checked",
        "Photos Taken?": "No",
        "Photo Folder/Link": "",
        "Tubing Condition": "OK",
        "Tubing Routing Notes": "",
        "Notes": "",
    }
    entry.update(overrides)
    return entry


def _status(summary, field):
    for section in summary.sections:
        for status in section.fields:
            if status.field == field:
                return status
    raise AssertionError(f"Missing status for {field}")


def test_vacuum_summary_treats_gripper_fields_as_valid_not_applicable():
    summary = calculate_audit_coach_summary(_base_entry(), SECTIONS)

    assert _status(summary, "Cup Type/Material").state == STATE_VERIFIED_COMPLETE
    assert _status(summary, "Gripper Model").state == STATE_NOT_APPLICABLE
    assert "Gripper Model" not in summary.missing_fields
    assert "Gripper tooling fields do not apply" in _status(summary, "Gripper Model").reason


def test_gripper_summary_treats_vacuum_na_as_not_applicable_not_missing():
    summary = calculate_audit_coach_summary(
        _base_entry(
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

    assert _status(summary, "Cup Type/Material").state == STATE_NOT_APPLICABLE
    assert "Cup Type/Material" not in summary.missing_fields
    assert "Cup Type/Material" not in summary.guided_fields


def test_hybrid_summary_reports_missing_both_sides_without_false_completion():
    summary = calculate_audit_coach_summary(
        _base_entry(
            **{
                "EOAT Type": "Hybrid",
                "# of Cups": "",
                "Cup Type/Material": "",
                "Cup Diameter/Size": "",
                "Vacuum Generator Type": "",
                "# of Grippers": "",
                "Gripper Type": "",
                "Gripper Model": "",
                "Gripper Size": "",
            }
        ),
        SECTIONS,
    )

    assert "Cup Type/Material" in summary.missing_fields
    assert "# of Cups" in summary.missing_fields
    assert "Gripper Model" in summary.missing_fields
    assert any(finding.category == "hybrid_warning" for finding in summary.findings)
    assert not summary.can_finish


def test_unknown_not_checked_is_not_verified_complete():
    summary = calculate_audit_coach_summary(_base_entry(**{"Sensor Type": "Unknown / Not Checked"}), SECTIONS)

    status = _status(summary, "Sensor Type")
    assert status.state == STATE_UNKNOWN_NOT_CHECKED
    assert "Sensor Type" in summary.unknown_not_checked_fields
    assert "Sensor Type" in summary.guided_fields
    assert status.state != STATE_VERIFIED_COMPLETE


def test_follow_up_and_stale_hidden_values_are_actionable_findings():
    summary = calculate_audit_coach_summary(
        _base_entry(
            **{
                "EOAT Type": "Mechanical / Gripper",
                "# of Cups": "3",
                "Cup Type/Material": "Demo Cup",
                "# of Grippers": "2",
                "Gripper Type": "Single Pressure",
                "Gripper Model": "Demo Gripper",
                "Gripper Size": "Small",
                "Status": "Needs Follow-Up",
            }
        ),
        SECTIONS,
    )

    assert _status(summary, "Status").state == STATE_FOLLOW_UP_NEEDED
    assert _status(summary, "# of Cups").state == STATE_STALE_CONFLICT
    assert _status(summary, "Cup Type/Material").state == STATE_STALE_CONFLICT
    assert "# of Cups" in summary.stale_conflict_fields
    assert "Cup Type/Material" in summary.stale_conflict_fields
    assert any(finding.category == "stale_hidden_value" for finding in summary.findings)


def test_next_best_field_prioritizes_required_identity_before_optional_gaps():
    summary = calculate_audit_coach_summary(
        _base_entry(**{"Press/Machine #": "", "Cup Diameter/Size": "", "Sensor Brand/Model": ""}),
        SECTIONS,
    )

    assert summary.next_best_field == "Press/Machine #"
    assert summary.missing_required_fields == ("Press/Machine #",)
    assert _status(summary, "Cup Diameter/Size").state == STATE_MISSING


def test_hidden_field_reason_viewer_data_uses_shared_non_applicable_reason():
    summary = calculate_audit_coach_summary(
        _base_entry(
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
            }
        ),
        SECTIONS,
    )

    reasons = {status.field: status.reason for status in summary.not_applicable_fields}
    assert "Vacuum tooling fields do not apply" in reasons["# of Cups"]
    assert "Vacuum tooling fields do not apply" in reasons["Cup Type/Material"]


def test_vacuum_summary_marks_missing_cup_count_as_applicable_guided_field():
    summary = calculate_audit_coach_summary(_base_entry(**{"# of Cups": ""}), SECTIONS)

    assert _status(summary, "# of Cups").state == STATE_MISSING
    assert "# of Cups" in summary.missing_fields
    assert "# of Cups" in summary.missing_important_fields
    assert "# of Cups" in summary.guided_fields


def test_optional_notes_do_not_reduce_completion_or_missing_fields():
    complete = _base_entry(
        **{
            "Electrical/Wiring Present?": "Yes",
            "Photos Taken?": "Yes",
            "Photo Folder/Link": "photos/demo",
            "Tubing Routing Notes": "",
            "Notes": "",
        }
    )

    summary = calculate_audit_coach_summary(complete, SECTIONS)

    assert summary.percent_complete == 100
    assert "Tubing Routing Notes" not in summary.missing_fields
    assert "Notes" not in summary.missing_fields
    assert _status(summary, "Tubing Routing Notes").state == STATE_VERIFIED_COMPLETE
    assert _status(summary, "Notes").state == STATE_VERIFIED_COMPLETE


def test_filled_optional_notes_are_saved_in_completion_display_without_changing_required_math():
    blank_summary = calculate_audit_coach_summary(
        _base_entry(
            **{
                "Electrical/Wiring Present?": "Yes",
                "Photos Taken?": "Yes",
                "Photo Folder/Link": "photos/demo",
                "Tubing Routing Notes": "",
                "Notes": "",
            }
        ),
        SECTIONS,
    )
    filled_summary = calculate_audit_coach_summary(
        _base_entry(
            **{
                "Electrical/Wiring Present?": "Yes",
                "Photos Taken?": "Yes",
                "Photo Folder/Link": "photos/demo",
                "Tubing Routing Notes": "Route behind wrist.",
                "Notes": "Final context.",
            }
        ),
        SECTIONS,
    )

    assert filled_summary.percent_complete == blank_summary.percent_complete == 100
    assert _status(filled_summary, "Tubing Routing Notes").value == "Route behind wrist."
    assert _status(filled_summary, "Notes").value == "Final context."


def test_miscellaneous_eoat_counts_gripper_fields_as_applicable():
    summary = calculate_audit_coach_summary(
        _base_entry(
            **{
                "EOAT Type": "Miscellaneous",
                "# of Grippers": "",
                "Gripper Type": "",
                "Gripper Model": "",
                "Gripper Size": "",
            }
        ),
        SECTIONS,
    )

    assert _status(summary, "Gripper Model").state == STATE_MISSING
    assert "Gripper Model" in summary.missing_fields
