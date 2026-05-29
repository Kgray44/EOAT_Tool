from __future__ import annotations

from datetime import date

from core.pm_checklists import generate_pm_checklists
from core.pm_due import (
    STATUS_COMPLETE,
    build_pm_due_item,
    build_pm_due_summary,
    build_pm_records_for_audit,
    export_pm_pack,
    load_pm_records,
    mark_pm_item_complete,
    pm_items_for_audit,
    pm_records_path,
)


def _row(audit_id: str, eoat_type: str, **overrides):
    row = {
        "Audit ID": audit_id,
        "Press/Machine #": "Press 911",
        "EOAT Type": eoat_type,
        "Maintenance Frequency": "Weekly",
        "Sensors Present?": "Yes",
        "Quick Disconnects Present?": "Yes",
        "# of Cylinders": "N/A",
        "Cylinder Type": "Linear",
        "Priority": "Medium",
        "Known Issues": "",
    }
    row.update(overrides)
    return row


def _labels(row):
    return {item.label for item in pm_items_for_audit(row)}


def test_pm_due_item_scores_missing_frequency_and_issues(fake_project):
    item = build_pm_due_item(
        fake_project,
        {
            "Audit ID": "AUD-PM-001",
            "Press/Machine #": "Press 101",
            "EOAT Type": "Vacuum",
            "Priority": "High",
            "Maintenance Frequency": "Unknown / Not Checked",
            "Known Issues": "Vacuum drops",
        },
    )

    assert item.due_state == "Needs Frequency"
    assert item.risk_score >= 47
    assert item.machine == "101"


def test_pm_due_summary_reads_fake_project(usability_fake_project):
    summary = build_pm_due_summary(usability_fake_project)

    assert summary.metrics["items"] >= 1
    assert summary.items
    assert summary.records
    assert summary.metrics["highest_risk_score"] == summary.items[0].risk_score


def test_vacuum_pm_applicability_includes_vacuum_items():
    labels = _labels(_row("AUD-PM-VAC", "Vacuum"))

    assert "Inspect vacuum cups for wear/damage" in labels
    assert "Inspect pneumatic tubing" in labels
    assert "Check gripper jaw/finger wear" not in labels


def test_gripper_pm_applicability_includes_gripper_items():
    labels = _labels(_row("AUD-PM-GRIP", "Mechanical / Gripper"))

    assert "Check gripper jaw/finger wear" in labels
    assert "Inspect vacuum cups for wear/damage" not in labels


def test_hybrid_pm_applicability_includes_vacuum_and_gripper_items():
    labels = _labels(_row("AUD-PM-HYB", "Hybrid"))

    assert "Inspect vacuum cups for wear/damage" in labels
    assert "Check gripper jaw/finger wear" in labels


def test_cylinder_pm_only_when_cylinder_fields_used():
    no_cylinder_labels = _labels(_row("AUD-PM-NO-CYL", "Vacuum", **{"# of Cylinders": ""}))
    cylinder_labels = _labels(_row("AUD-PM-CYL", "Vacuum", **{"# of Cylinders": "2"}))

    assert "Check cylinder movement if cylinder fields exist" not in no_cylinder_labels
    assert "Check cylinder movement if cylinder fields exist" in cylinder_labels


def test_pm_records_saved_outside_repo_in_project_root(usability_fake_project):
    summary = build_pm_due_summary(usability_fake_project, machine="101", today=date(2026, 5, 18))
    record = summary.records[0]

    result = mark_pm_item_complete(usability_fake_project, record.record_id, notes="Completed during test.", completed_on=date(2026, 5, 18))

    path = pm_records_path(usability_fake_project)
    saved = load_pm_records(usability_fake_project)
    assert result.success is True
    assert path == usability_fake_project / "00_Project_Admin" / "pm_due" / "pm_records.json"
    assert path.exists()
    assert any(item.record_id == record.record_id and item.status == STATUS_COMPLETE for item in saved)


def test_checklist_export_still_works_with_pm_due(fake_project):
    records = build_pm_records_for_audit(fake_project, _row("AUD-PM-EXPORT", "Hybrid"), today=date(2026, 5, 18))
    checklist = generate_pm_checklists(fake_project, generic=True)
    pack = export_pm_pack(fake_project, machine="101", today=date(2026, 5, 18))

    assert records
    assert checklist.success is True
    assert checklist.output_reports
    assert pack.success is True
    assert any(path.endswith(".md") for path in pack.output_reports)
