from __future__ import annotations

from core.final_handoff import build_final_handoff_package
from core.paths import resolve_project_paths


def test_final_handoff_dry_run_creates_report_without_package(fake_project):
    paths = resolve_project_paths(fake_project)
    result = build_final_handoff_package(fake_project, dry_run=True)

    assert result.success is True
    assert result.metrics["dry_run"] is True
    assert result.metrics["files_copied"] == 0
    assert result.output_reports[0].endswith(".md")
    assert not [path for path in paths.handoff_package_root.glob("Final_Handoff_*") if path.is_dir()]
    assert not [path for path in paths.final_handoff.glob("Final_Handoff_Package_*") if path.is_dir()]


def test_final_handoff_copies_files_and_creates_index(fake_project):
    paths = resolve_project_paths(fake_project)
    paths.weekly_reports.mkdir(parents=True, exist_ok=True)
    source = paths.weekly_reports / "Week1_Summary_Test.md"
    source.write_text("# Week 1", encoding="utf-8")

    result = build_final_handoff_package(fake_project, dry_run=False, include_weekly_reports=True)

    assert result.success is True
    assert result.metrics["files_copied"] >= 1
    packages = list(paths.final_handoff.glob("Final_Handoff_Package_*"))
    assert packages
    assert (packages[-1] / "HANDOFF_INDEX.md").exists()
    assert (packages[-1] / "Executive_Summary.md").exists()
    assert (packages[-1] / "Technical_Appendix.md").exists()
    assert (packages[-1] / "Open_Items_Carryover.md").exists()
    assert (packages[-1] / "Deliverable_Readiness.md").exists()
    assert (packages[-1] / "Machine_Summaries" / "Machine_Summary_Report.md").exists()
    for folder in ["FMEA", "KPI", "PM_Checklists", "Pilot_Candidates", "Standards", "Validation"]:
        assert (packages[-1] / folder).is_dir()
    index = (packages[-1] / "HANDOFF_INDEX.md").read_text(encoding="utf-8")
    for label in [
        "Final master tracker",
        "Robot Info workbook",
        "FMEA",
        "KPI dashboard",
        "PM checklist package",
        "BOM/spares report",
        "Standard design guidelines",
        "Work instructions",
        "Pilot report",
        "Training materials",
        "Photos/evidence",
        "Open issues",
        "Recommendations",
        "Machine summary report",
    ]:
        assert label in index
    assert "Missing evidence remains listed as missing" in index
    assert "No financial or performance impact is invented" in index
    assert source.exists()


def test_final_handoff_package_does_not_overwrite_existing_package(fake_project):
    paths = resolve_project_paths(fake_project)

    first = build_final_handoff_package(fake_project, dry_run=False)
    second = build_final_handoff_package(fake_project, dry_run=False)

    assert first.success is True
    assert second.success is True
    packages = sorted(paths.final_handoff.glob("Final_Handoff_Package_*"))
    assert len(packages) == 2
    assert packages[0] != packages[1]
