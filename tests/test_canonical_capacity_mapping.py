from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from tools.migration.canonical_capacity_mapping import (
    plan_catalog_capacity_dry_run,
    write_immutable_catalog_dry_run,
)
from tools.migration import press_capacity_import


def _workbook(path: Path, headings: list[str]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "P4 Capacity"
    sheet.append(["Machine No.", "NGW Part Number"])
    for heading in headings:
        sheet.append([heading, None])
        sheet.append([heading.split()[1], "provenance-only"])
    workbook.save(path)
    workbook.close()
    return path


def _record(
    number: str,
    *,
    plant: str = "P4",
    active: bool = True,
    capacity: int | None = None,
    aliases: list[str] | None = None,
    identity: str | None = None,
) -> dict[str, object]:
    return {
        "api_identity": identity or f"GET /api/v1/machines/{number}?plant_code={plant}",
        "machine_number": number,
        "plant_code": plant,
        "area": "Production",
        "machine_name": f"Press {number}",
        "manufacturer": "Acme",
        "model": "Model",
        "is_active": active,
        "status": "ACTIVE" if active else "INACTIVE",
        "row_version": 1,
        "press_capacity_tons": capacity,
        "capacity_unit": "US_TONS",
        "governed_aliases": aliases or [],
    }


def _catalog(path: Path, records: list[dict[str, object]]) -> Path:
    payload = {
        "manifest_type": "eoat_atlas_canonical_plant4_machine_catalog",
        "source_type": "production_api_read_only",
        "retrieval_timestamp_utc": "2026-07-30T00:00:00Z",
        "production_release": {"application_version": "0.24.1"},
        "production_schema": {"current_schema_revision": "20260721_0008"},
        "data_revision": "test-revision",
        "plant4_filter_rule": "plant_code equals P4",
        "records": records,
    }
    path.write_text(json.dumps({"payload": payload, "payload_sha256": "test"}), encoding="utf-8")
    return path


def _decision(report, machine_number: str):
    return next(item for item in report.mappings if item.parsed_machine_number == machine_number)


def test_exact_plant4_machine_27_maps_to_existing_empty_capacity(tmp_path: Path) -> None:
    source = _workbook(tmp_path / "capacity.xlsx", ["Press 27 - 165T - 45mm Screw"])
    catalog = _catalog(tmp_path / "catalog.json", [_record("27")])

    report = plan_catalog_capacity_dry_run(source, catalog, plant_code="P4")

    decision = _decision(report, "27")
    assert decision.source_sheet == "P4 Capacity"
    assert decision.source_row == 2
    assert decision.parsed_tonnage == 165
    assert decision.mapping_method == "EXACT_CANONICAL_MACHINE_NUMBER"
    assert decision.canonical_identity.endswith("27?plant_code=P4")
    assert decision.proposed_action == "UPDATE"
    assert report.proposed_counts == {"INSERT": 0, "UPDATE": 1, "UNCHANGED": 0, "REJECT": 0, "REVIEW_REQUIRED": 0}


def test_alias_and_deterministic_normalization_are_distinguished(tmp_path: Path) -> None:
    source = _workbook(tmp_path / "capacity.xlsx", ["Press 27 - 165T", "Press 28 - 200T"])
    catalog = _catalog(tmp_path / "catalog.json", [_record("027"), _record("99", aliases=["28"])])

    report = plan_catalog_capacity_dry_run(source, catalog, plant_code="P4")

    assert _decision(report, "27").mapping_method == "DETERMINISTIC_NORMALIZED_MACHINE_NUMBER"
    assert _decision(report, "28").mapping_method == "EXACT_GOVERNED_ALIAS"


def test_duplicate_and_cross_plant_machine_numbers_are_rejected(tmp_path: Path) -> None:
    source = _workbook(tmp_path / "capacity.xlsx", ["Press 27 - 165T", "Press 28 - 200T"])
    catalog = _catalog(
        tmp_path / "catalog.json",
        [_record("27", identity="api:one"), _record("27", identity="api:two"), _record("28", plant="P5")],
    )

    report = plan_catalog_capacity_dry_run(source, catalog, plant_code="P4")

    assert _decision(report, "27").proposed_action == "REJECT"
    assert _decision(report, "27").reason == "DUPLICATE_ACTIVE_CANONICAL_MACHINE_NUMBER"
    assert _decision(report, "28").reason == "CROSS_PLANT_CANONICAL_COLLISION"
    assert report.duplicate_machine_numbers == {"27": ["api:one", "api:two"]}


def test_missing_inactive_equal_and_conflicting_capacities_stay_fail_closed(tmp_path: Path) -> None:
    source = _workbook(
        tmp_path / "capacity.xlsx",
        ["Press 27 - 165T", "Press 28 - 200T", "Press 29 - 110T", "Press 30 - 50T", "Press 31 - 80T"],
    )
    catalog = _catalog(
        tmp_path / "catalog.json",
        [_record("27"), _record("28", capacity=200), _record("29", capacity=120), _record("30", active=False)],
    )

    report = plan_catalog_capacity_dry_run(source, catalog, plant_code="P4")

    assert _decision(report, "27").proposed_action == "UPDATE"
    assert _decision(report, "28").proposed_action == "UNCHANGED"
    assert _decision(report, "29").verification_class == "EXISTING_CAPACITY_CONFLICT"
    assert _decision(report, "29").proposed_action == "REVIEW_REQUIRED"
    assert _decision(report, "30").verification_class == "INACTIVE_MACHINE"
    assert _decision(report, "31").verification_class == "UNMAPPED"
    assert report.existing_capacity_conflicts == ["29"]


def test_complete_54_section_manifest_is_immutable_and_has_no_insert_path(tmp_path: Path) -> None:
    headings = [f"Press {number} - 100T" for number in range(1, 55)]
    source = _workbook(tmp_path / "capacity.xlsx", headings)
    catalog = _catalog(tmp_path / "catalog.json", [_record(str(number)) for number in range(1, 55)])

    report = plan_catalog_capacity_dry_run(source, catalog, plant_code="P4")
    manifest = write_immutable_catalog_dry_run(report, tmp_path / "receipts")

    assert len(report.mappings) == 54
    assert report.proposed_counts["INSERT"] == 0
    assert report.proposed_counts["UPDATE"] == 54
    assert manifest.exists()
    with pytest.raises(FileExistsError):
        write_immutable_catalog_dry_run(report, tmp_path / "receipts")


def test_duplicate_catalog_identity_is_rejected_before_any_mapping(tmp_path: Path) -> None:
    source = _workbook(tmp_path / "capacity.xlsx", ["Press 27 - 165T"])
    catalog = _catalog(
        tmp_path / "catalog.json",
        [_record("27", identity="api:duplicate"), _record("28", identity="api:duplicate")],
    )

    with pytest.raises(ValueError, match="duplicate stable identity"):
        plan_catalog_capacity_dry_run(source, catalog, plant_code="P4")


def test_catalog_planner_never_opens_a_database_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _workbook(tmp_path / "capacity.xlsx", ["Press 27 - 165T"])
    catalog = _catalog(tmp_path / "catalog.json", [_record("27")])

    def unexpected_database_access(*_args, **_kwargs):
        raise AssertionError("catalog planning must not open a database session")

    monkeypatch.setattr(press_capacity_import, "create_session_factory", unexpected_database_access)

    report = plan_catalog_capacity_dry_run(source, catalog, plant_code="P4")

    assert report.proposed_counts["UPDATE"] == 1
