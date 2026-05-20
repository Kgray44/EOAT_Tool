from __future__ import annotations

from core.paths import resolve_project_paths
from core.presentation_export import export_presentation_assets


def test_presentation_export_creates_asset_package_and_index(fake_project):
    result = export_presentation_assets(fake_project)

    assert result.success is True
    package = result.metrics["package"]
    assert "Presentation_Assets_" in package
    assert any(path.endswith("PRESENTATION_ASSET_INDEX.md") for path in result.output_reports)
    assert any(path.endswith("slide_outline.md") for path in result.output_reports)


def test_presentation_export_handles_missing_kpi_pilot_honestly(fake_project):
    result = export_presentation_assets(fake_project)
    paths = resolve_project_paths(fake_project)
    packages = sorted(paths.presentation_assets_root.glob("Presentation_Assets_*"))
    kpi_summary = packages[-1] / "02_KPI_Charts" / "kpi_summary.md"

    assert kpi_summary.exists()
    assert "KPI baseline data not available yet" in kpi_summary.read_text(encoding="utf-8")
