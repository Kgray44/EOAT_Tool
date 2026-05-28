from __future__ import annotations

from core.risk_insights import build_risk_insight_summary


def test_risk_insights_combine_fmea_pilot_and_kpi(usability_fake_project):
    summary = build_risk_insight_summary(usability_fake_project)

    assert summary.metrics["kpi_rows"] >= 1
    assert summary.top_pilot_candidates
    assert summary.recommended_actions
    assert "missing_kpi_fields_total" in summary.metrics


def test_risk_insights_report_missing_workbook(minimal_fake_project):
    summary = build_risk_insight_summary(minimal_fake_project)

    assert summary.warnings
    assert summary.metrics["kpi_rows"] == 0

