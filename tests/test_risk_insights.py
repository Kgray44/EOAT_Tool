from __future__ import annotations

from core.risk_insights import build_risk_insight_summary, generate_risk_insights_report


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


def test_generate_risk_insights_report_writes_safe_markdown(usability_fake_project):
    result = generate_risk_insights_report(usability_fake_project, log_activity=False)

    assert result.success is True
    assert result.output_reports
    assert result.output_reports[0].endswith(".md")
    assert "Workbook was not modified." in result.details
