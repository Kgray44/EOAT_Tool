from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from core.atlas_data_loader import invalidate_atlas_data_cache, load_atlas_data
from core.atlas_recommendations import recommend_for_query
from core.atlas_search import search_atlas
from core.atlas_utils import row_value
from core.compatibility_engine import compatibility_matrix_rows, machine_to_eoats, tool_to_eoats
from core.documentation_score import calculate_documentation_status
from core.paths import resolve_project_paths
from tests.fixtures.fake_project import create_fake_eoat_project
from tests.fixtures.reference_workbooks import create_press_reference_workbooks


def test_atlas_header_alias_lookup() -> None:
    row = {"Tool Number": "12345", "Machine Number": "Press 12", "EOAT ID": "P4-EOAT-0001"}

    assert row_value(row, ("Tool #", "Tool Number")) == "12345"
    assert row_value(row, ("Machine #", "Machine Number")) == "Press 12"
    assert row_value(row, ("EOAT Assembly ID", "EOAT ID")) == "P4-EOAT-0001"


def test_atlas_load_builds_fast_lookup_indexes(tmp_path: Path) -> None:
    root = create_fake_eoat_project(tmp_path)
    create_press_reference_workbooks(resolve_project_paths(root).reference_data, multiple_capacity_rows=True)
    invalidate_atlas_data_cache(root)

    bundle = load_atlas_data(root, force_refresh=True)

    assert len(bundle.eoats) == 3
    assert "toola" in bundle.indexes.eoats_by_tool
    assert bundle.indexes.eoats_by_machine["101"] == ("AUD-20260518-001",)
    assert bundle.metrics["workbook_load_ms"] >= 0
    assert bundle.metrics["cache_build_ms"] >= 0


def test_atlas_search_and_recommendation_use_exact_tool_match(tmp_path: Path) -> None:
    root = create_fake_eoat_project(tmp_path)
    create_press_reference_workbooks(resolve_project_paths(root).reference_data)
    bundle = load_atlas_data(root, force_refresh=True)

    matches = search_atlas(bundle, "Tool TOOL-A")
    recommendation = recommend_for_query(bundle, "Tool TOOL-A")

    assert matches[0].result_type in {"eoat", "tool"}
    assert recommendation.best is not None
    assert recommendation.best.eoat_id == "AUD-20260518-001"
    assert [candidate.eoat_id for candidate in recommendation.candidates] == ["AUD-20260518-001"]
    assert recommendation.install_checklist


def test_atlas_compatibility_engine_answers_tool_and_machine(tmp_path: Path) -> None:
    root = create_fake_eoat_project(tmp_path)
    create_press_reference_workbooks(resolve_project_paths(root).reference_data)
    bundle = load_atlas_data(root, force_refresh=True)

    assert tool_to_eoats(bundle, "TOOL-A")[0].eoat_id == "AUD-20260518-001"
    assert machine_to_eoats(bundle, "101")[0].eoat_id == "AUD-20260518-001"
    rows = compatibility_matrix_rows(bundle)
    assert any(row["EOAT"] == "AUD-20260518-001" and row["Machine"] == "101" for row in rows)


def test_atlas_indexes_photo_folder_by_eoat_id(tmp_path: Path) -> None:
    root = create_fake_eoat_project(tmp_path, with_photos=False)
    paths = resolve_project_paths(root)
    _set_first_inventory_eoat_id(paths.master_workbook, "P4-EOAT-0001")
    photo_folder = paths.cell_photos / "P4-EOAT-0001" / "00_Overall"
    photo_folder.mkdir(parents=True)
    (photo_folder / "P4-EOAT-0001_overall_001.jpg").write_bytes(b"not a real image but enough for indexing")

    bundle = load_atlas_data(root, force_refresh=True)
    eoat = next(record for record in bundle.eoats if record.eoat_id == "P4-EOAT-0001")

    assert eoat.photo_count == 1
    assert bundle.indexes.photos_by_eoat["p4eoat0001"]


def test_atlas_handles_missing_optional_sources(tmp_path: Path) -> None:
    root = create_fake_eoat_project(tmp_path, with_photos=False)
    bundle = load_atlas_data(root, force_refresh=True)

    assert len(bundle.eoats) == 3
    assert any(not source.available for source in bundle.source_statuses if source.label in {"Press Capacity", "Robot Info"})
    assert bundle.warnings


def test_documentation_score_flags_missing_critical_fields() -> None:
    status = calculate_documentation_status({"Tool #": "123", "EOAT Type": "Vacuum"}, photo_count=0)

    assert status.score < 75
    assert "EOAT Assembly ID" in status.critical_missing_fields
    assert status.status_label in {"Critical gaps", "Missing important info"}


def _set_first_inventory_eoat_id(workbook_path: Path, eoat_id: str) -> None:
    workbook = load_workbook(workbook_path)
    try:
        ws = workbook["EOAT Inventory"]
        headers = [cell.value for cell in ws[1]]
        column = headers.index("EOAT Assembly ID") + 1
        ws.cell(row=2, column=column).value = eoat_id
        workbook.save(workbook_path)
    finally:
        workbook.close()
