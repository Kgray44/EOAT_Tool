from __future__ import annotations

from core.pm_due import analyze_pm_due, build_pm_due_item


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
    summary = analyze_pm_due(usability_fake_project)

    assert summary.metrics["items"] >= 1
    assert summary.items
    assert summary.metrics["highest_risk_score"] == summary.items[0].risk_score

