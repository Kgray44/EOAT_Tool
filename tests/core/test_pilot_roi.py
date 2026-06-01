from __future__ import annotations

import json
from pathlib import Path

from openpyxl import load_workbook

from core.paths import resolve_project_paths
from core.pilot_roi import (
    build_pilot_roi,
    export_pilot_roi_report,
    pilot_roi_assumptions_path,
    save_pilot_roi_assumptions,
)


def _seed_candidate(fake_project) -> None:
    workbook_path = resolve_project_paths(fake_project).master_workbook
    wb = load_workbook(workbook_path)
    candidates = wb["Pilot Candidates"]
    candidates.append(
        [
            "PILOT-ROI-001",
            "2026-05-18",
            "Plant 4",
            "Press 82",
            "Wittmann R9",
            "TOOL-82",
            "Family A",
            "Vacuum",
            "Part drops and scrap",
            "Issue log and KPI baseline",
            "High",
            "Medium",
            "Yes",
            "Vacuum cups and tubing",
            "Reduce drops and downtime",
            "Pilot standard vacuum kit",
            "Proposed",
            "",
        ]
    )
    kpi = wb["KPI Baseline"]
    kpi.append(
        [
            "KPI-ROI-001",
            "2026-05-18",
            "Plant 4",
            "Press 82",
            "TOOL-82",
            "Family A",
            "Vacuum",
            60,
            "Yes",
            6,
            2,
            40,
            "Drop",
            12.5,
            3,
            "",
            "Manual",
            "",
        ]
    )
    issues = wb["Issue Log"]
    issues.append(
        [
            "ISS-ROI-001",
            "2026-05-18",
            "Plant 4",
            "Press 82",
            "Wittmann R9",
            "Vacuum",
            "Part drop",
            "Part drops during transfer",
            "",
            "",
            "Downtime and scrap",
            "8",
            "5",
            "4",
            "",
            "",
            "",
            "Open",
            "",
            "",
        ]
    )
    wb.save(workbook_path)
    wb.close()


def test_pilot_roi_uses_qualitative_mode_without_financial_assumptions(fake_project):
    _seed_candidate(fake_project)

    summary, error = build_pilot_roi(fake_project)

    assert error is None
    assert summary is not None
    result = summary.results[0]
    assert result.mode == "qualitative"
    assert result.annualized_savings_estimate == ""
    assert "No financial value was calculated" in result.justification


def test_pilot_roi_quantitative_estimates_are_labeled_and_assumption_based(fake_project):
    _seed_candidate(fake_project)
    assumptions = {
        "hourly_downtime_cost": 100,
        "expected_downtime_reduction_minutes_per_year": 120,
        "scrap_cost_per_piece": 2,
        "expected_scrap_reduction_pieces_per_year": 50,
    }

    summary, error = build_pilot_roi(fake_project, assumptions=assumptions)

    assert error is None
    assert summary is not None
    result = summary.results[0]
    assert result.mode == "quantitative_estimate"
    assert result.annualized_savings_estimate == 300
    assert "Estimated annual savings" in result.estimate_label
    assert "$300" in result.justification


def test_pilot_roi_stores_assumptions_and_exports_report(fake_project):
    _seed_candidate(fake_project)
    assumptions = {"hourly_downtime_cost": 75, "expected_downtime_reduction_minutes_per_year": 60}

    saved = save_pilot_roi_assumptions(fake_project, assumptions, candidate_id="PILOT-ROI-001")
    result = export_pilot_roi_report(
        fake_project, candidate_id="PILOT-ROI-001", assumptions=assumptions, log_activity=False
    )

    assert saved == pilot_roi_assumptions_path(fake_project)
    payload = json.loads(Path(saved).read_text(encoding="utf-8"))
    assert payload["updated_at"]
    assert payload["candidate_id"] == "PILOT-ROI-001"
    assert payload["assumptions"]["hourly_downtime_cost"] == 75
    assert result.success is True
    assert result.output_reports
    report_text = Path(result.output_reports[0]).read_text(encoding="utf-8")
    assert "Pilot ROI and Justification Report" in report_text
    assert "Justification" in report_text
