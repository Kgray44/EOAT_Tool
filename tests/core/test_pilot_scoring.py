from __future__ import annotations

from openpyxl import load_workbook

from core.paths import resolve_project_paths
from core.pilot_scoring import (
    DEFAULT_PILOT_SCORE_WEIGHTS,
    generate_pilot_ranking_report,
    normalize_pilot_weights,
    rank_pilot_candidates,
)


def _seed_inventory_candidate(fake_project, *, press: str = "Press 12") -> None:
    workbook_path = resolve_project_paths(fake_project).master_workbook
    wb = load_workbook(workbook_path)
    inv = wb["EOAT Inventory"]
    inv_headers = [cell.value for cell in inv[1]]
    inventory_row = {header: "" for header in inv_headers}
    inventory_row.update(
        {
            "Audit ID": f"AUD-{press.replace(' ', '-')}",
            "Audit Date": "2026-05-18",
            "Auditor": "KG",
            "Plant/Area": "Plant 4",
            "Press/Machine #": press,
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Vacuum",
            "Known Issues": "Drops parts",
            "Scrap/Quality Concern?": "Yes",
            "Status": "Candidate for pilot",
            "Priority": "High",
            "Pilot Candidate?": "Yes",
            "Follow-Up Needed": "Yes",
            "BOM Available?": "No",
            "Drawing/CAD Available?": "No",
        }
    )
    inv.append([inventory_row.get(header, "") for header in inv_headers])
    issues = wb["Issue Log"]
    issues.append(
        [
            "ISS-1",
            "2026-05-18",
            "Plant 4",
            press,
            "Wittmann R9",
            "Vacuum",
            "Part drop",
            "",
            "",
            "",
            "",
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
    kpi = wb["KPI Baseline"]
    kpi.append(
        [
            "KPI-1",
            "2026-05-18",
            "Plant 4",
            press,
            "",
            "",
            "Vacuum",
            30,
            "Yes",
            4,
            1,
            20,
            "Drop",
            12.5,
            2,
            "",
            "Manual",
            "",
        ]
    )
    wb.save(workbook_path)
    wb.close()


def test_pilot_scoring_suggests_from_inventory_flags(fake_project):
    _seed_inventory_candidate(fake_project)

    summary, error = rank_pilot_candidates(fake_project)
    assert error is None
    assert summary.metrics["candidates_evaluated"] == 1
    candidate = summary.ranked_candidates[0]
    assert candidate["Total Score"] > 0
    assert candidate["Confidence"] in {"High", "Medium"}
    assert "Downtime/Reliability" in candidate["Score Explanation"]
    assert "photos" in candidate["Missing Evidence"]
    assert summary.sensitivity_rows

    result = generate_pilot_ranking_report(fake_project)
    assert result.success is True


def test_pilot_scoring_weight_adjustment_is_normalized_and_explained(fake_project):
    _seed_inventory_candidate(fake_project)

    summary, error = rank_pilot_candidates(
        fake_project,
        weights={
            "downtime_reliability": 0,
            "quality_scrap": 1,
            "ease": 0,
            "safety_maintenance": 0,
            "standardization": 0,
        },
    )

    assert error is None
    assert summary.weights["quality_scrap"] == 1
    candidate = summary.ranked_candidates[0]
    assert candidate["Total Score"] == candidate["Quality/Scrap Score"]
    assert "Most sensitive" in candidate["Sensitivity Analysis"]


def test_pilot_scoring_empty_candidates(fake_project):
    summary, error = rank_pilot_candidates(fake_project)
    assert error is None
    assert summary.metrics["candidates_evaluated"] == 0


def test_normalize_pilot_weights_accepts_display_label_aliases():
    weights = normalize_pilot_weights({"Quality/Scrap Score": 3, "Downtime/Reliability": 1})

    assert set(weights) == set(DEFAULT_PILOT_SCORE_WEIGHTS)
    assert round(sum(weights.values()), 6) == 1
    assert weights["quality_scrap"] > weights["downtime_reliability"]
