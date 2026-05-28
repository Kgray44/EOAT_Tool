from __future__ import annotations

from core.final_handoff_readiness import (
    MISSING,
    READY,
    build_final_handoff_readiness,
    build_leadership_summary_markdown,
    build_open_items_carryover_markdown,
    build_technical_appendix_markdown,
    export_leadership_summary,
    export_open_items_carryover,
    export_technical_appendix,
    open_items_carryover_dir,
    technical_appendix_dir,
)
from core.paths import resolve_project_paths


def _by_key(project_root):
    return {item.key: item for item in build_final_handoff_readiness(project_root).deliverables}


def test_final_handoff_readiness_detects_missing_outputs(minimal_fake_project):
    missing = _by_key(minimal_fake_project)
    assert missing["eoat_database"].status == MISSING
    assert missing["executive_summary"].status == MISSING


def test_final_handoff_readiness_detects_ready_outputs(usability_fake_project):
    paths = resolve_project_paths(usability_fake_project)
    (paths.standards / "EOAT_Design_Guideline_Draft").mkdir(parents=True, exist_ok=True)
    (paths.standards / "EOAT_Design_Guideline_Draft" / "Guideline.md").write_text("# Guideline\n", encoding="utf-8")
    (paths.pm_generated_checklists / "PM_Checklist_Test.md").write_text("# PM\n", encoding="utf-8")
    (paths.fmea_reports / "FMEA_Report.md").write_text("# FMEA\n", encoding="utf-8")
    (paths.kpi_dashboard_exports / "KPI_Report.md").write_text("# KPI\n", encoding="utf-8")
    (paths.pilot_project / "Before_After_Data").mkdir(parents=True, exist_ok=True)
    (paths.pilot_project / "Before_After_Data" / "Pilot_Before_After.csv").write_text("metric,before,after\n", encoding="utf-8")
    (paths.pilot_project / "Pilot_Reports").mkdir(parents=True, exist_ok=True)
    (paths.pilot_project / "Pilot_Reports" / "Pilot_Report.md").write_text("# Pilot\n", encoding="utf-8")
    (paths.documentation_gap_reports / "Documentation_Gaps.md").write_text("# Gaps\n", encoding="utf-8")
    (paths.training_materials / "Training.md").write_text("# Training\n", encoding="utf-8")
    (paths.executive_summary / "Executive_Summary.md").write_text("# Executive Summary\n", encoding="utf-8")
    technical_appendix_dir(usability_fake_project).mkdir(parents=True, exist_ok=True)
    (technical_appendix_dir(usability_fake_project) / "Technical_Appendix.md").write_text("# Technical Appendix\n", encoding="utf-8")
    open_items_carryover_dir(usability_fake_project).mkdir(parents=True, exist_ok=True)
    (open_items_carryover_dir(usability_fake_project) / "Open_Items_Carryover.md").write_text("# Carryover\n", encoding="utf-8")

    ready = _by_key(usability_fake_project)
    for key in [
        "eoat_database",
        "standards_guidelines",
        "pm_checklist_package",
        "fmea_output",
        "kpi_dashboard_export",
        "pilot_results_or_packets",
        "training_materials",
        "documentation_gap_summary",
        "open_items_carryover",
        "executive_summary",
        "technical_appendix",
    ]:
        assert ready[key].status == READY


def test_executive_summary_headings_and_honest_unavailable_language(fake_project):
    text = build_leadership_summary_markdown(fake_project)

    for heading in [
        "## Project Objective",
        "## Work Completed",
        "## Major Findings",
        "## Pilot Recommendation / Results",
        "## Integrated Risk Insight",
        "## KPI Impact",
        "## Remaining Risks",
        "## Next Steps",
    ]:
        assert heading in text
    assert "KPI impact unavailable" in text
    assert "Pilot recommendation/results unavailable" in text


def test_technical_appendix_required_headings(fake_project):
    text = build_technical_appendix_markdown(fake_project)

    for heading in [
        "## Audit Coverage",
        "## Validation Findings Summary",
        "## Standards Gaps",
        "## FMEA Details",
        "## Integrated Risk Insight",
        "## PM/BOM Findings",
        "## Photo / Evidence References",
        "## Open Items",
        "## Compatibility Health Summary",
    ]:
        assert heading in text


def test_open_items_carryover_export(fake_project):
    text = build_open_items_carryover_markdown(fake_project)
    assert "# Open Items Carryover" in text
    assert "## Carryover Items" in text

    result = export_open_items_carryover(fake_project)
    assert result.success is True
    assert result.output_reports
    assert result.output_reports[0].endswith(".md")


def test_standalone_executive_and_appendix_exports(fake_project):
    executive = export_leadership_summary(fake_project)
    appendix = export_technical_appendix(fake_project)

    assert executive.success is True
    assert appendix.success is True
    assert "Executive_Summary_" in executive.output_reports[0]
    assert "Technical_Appendix_" in appendix.output_reports[0]
