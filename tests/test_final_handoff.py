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


def test_final_handoff_copies_files_and_creates_index(fake_project):
    paths = resolve_project_paths(fake_project)
    paths.weekly_reports.mkdir(parents=True, exist_ok=True)
    source = paths.weekly_reports / "Week1_Summary_Test.md"
    source.write_text("# Week 1", encoding="utf-8")

    result = build_final_handoff_package(fake_project, dry_run=False, include_weekly_reports=True)

    assert result.success is True
    assert result.metrics["files_copied"] >= 1
    packages = list(paths.handoff_package_root.glob("Final_Handoff_*"))
    assert packages
    assert (packages[-1] / "HANDOFF_INDEX.md").exists()
    assert source.exists()
