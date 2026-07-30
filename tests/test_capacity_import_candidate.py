from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.migration.capacity_import_candidate import (
    build_import_candidate,
    validate_candidate_preconditions,
    write_immutable_import_candidate,
)


def _inputs(tmp_path: Path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"payload": {"manifest_type": "eoat_atlas_canonical_plant4_machine_catalog", "production_release": {"application_version": "0.24.1"}, "production_schema": {"current_schema_revision": "20260721_0008"}, "data_revision": "r1", "records": [{"api_identity": "api:27", "machine_number": "27", "row_version": 1, "press_capacity_tons": None}, {"api_identity": "api:8", "machine_number": "8", "row_version": 1, "press_capacity_tons": None}]}}), encoding="utf-8")
    dry = tmp_path / "dry.json"
    update = {"source_sheet": "P4 Capacity", "source_row": 99, "source_press_heading": "Press 27 - 165T", "parsed_machine_number": "27", "parsed_tonnage": "165", "tonnage_source": "press_capacity_workbook", "canonical_identity": "api:27", "canonical_machine_number": "27", "plant_code": "P4", "area": "Plant 4", "mapping_method": "EXACT_CANONICAL_MACHINE_NUMBER", "verification_class": "CANONICAL_MATCH", "existing_capacity_tons": None, "proposed_capacity_tons": "165", "capacity_unit": "US_TONS", "proposed_action": "UPDATE", "reason": None}
    review = {**update, "source_row": 86, "parsed_machine_number": "24", "canonical_identity": None, "canonical_machine_number": None, "mapping_method": "NONE", "verification_class": "UNMAPPED", "proposed_action": "REVIEW_REQUIRED", "reason": "NO_CANONICAL_MACHINE_MATCH"}
    dry.write_text(json.dumps({"mappings": [update, review]}), encoding="utf-8")
    candidate = build_import_candidate(dry_run_manifest=dry, catalog_manifest=catalog, workbook_sha256="workbook", reconciliation_evidence_sha256="recon", branch="integration", commit="abc", application_version="0.25.2", source_schema_target="20260729_0009")
    current = [{"api_identity": "api:27", "machine_number": "27", "row_version": 1, "press_capacity_tons": None}, {"api_identity": "api:8", "machine_number": "8", "row_version": 1, "press_capacity_tons": None}]
    return candidate, current


def _validate(candidate, current):
    return validate_candidate_preconditions(candidate, workbook_sha256="workbook", catalog_manifest_sha256=candidate["catalog_manifest_sha256"], dry_run_manifest_sha256=candidate["prior_dry_run_manifest_sha256"], reconciliation_evidence_sha256="recon", production={"application_version": "0.24.1", "current_schema_revision": "20260721_0008", "writes_enabled": False}, current_catalog_records=current)


def test_candidate_is_non_executable_and_immutable(tmp_path: Path) -> None:
    candidate, current = _inputs(tmp_path)
    path = write_immutable_import_candidate(candidate, tmp_path / "receipts")
    assert candidate["non_executable"] is True
    assert candidate["proposed_counts"] == {"insert": 0, "update": 1, "unchanged": 0, "reject": 0, "review_required": 1}
    assert _validate(candidate, current).valid
    with pytest.raises(FileExistsError):
        write_immutable_import_candidate(candidate, tmp_path / "receipts")


@pytest.mark.parametrize("kind, expected", [
    ("workbook", "workbook_sha256_DRIFT"), ("catalog_hash", "catalog_manifest_sha256_DRIFT"),
    ("dry_hash", "prior_dry_run_manifest_sha256_DRIFT"), ("recon", "reconciliation_evidence_sha256_DRIFT"),
    ("release", "PRODUCTION_RELEASE_DRIFT"), ("schema", "PRODUCTION_SCHEMA_DRIFT"),
    ("writes", "PRODUCTION_WRITES_UNEXPECTEDLY_ENABLED"), ("count", "CATALOG_MACHINE_COUNT_DRIFT"),
    ("missing", "CANONICAL_IDENTITY_MISSING"), ("number", "CANONICAL_MACHINE_NUMBER_DRIFT"),
    ("version", "CANONICAL_ROW_VERSION_DRIFT"), ("capacity", "EXISTING_CAPACITY_DRIFT"),
    ("excluded", "EXCLUDED_MACHINE_INCLUDED"), ("duplicate", "SOURCE_RECORD_MAPS_TO_MULTIPLE_CANONICAL_MACHINES"),
])
def test_candidate_rejects_each_drift_condition(tmp_path: Path, kind: str, expected: str) -> None:
    candidate, current = _inputs(tmp_path)
    candidate, current = copy.deepcopy(candidate), copy.deepcopy(current)
    kwargs = {"workbook_sha256": "workbook", "catalog_manifest_sha256": candidate["catalog_manifest_sha256"], "dry_run_manifest_sha256": candidate["prior_dry_run_manifest_sha256"], "reconciliation_evidence_sha256": "recon", "production": {"application_version": "0.24.1", "current_schema_revision": "20260721_0008", "writes_enabled": False}, "current_catalog_records": current}
    if kind == "workbook": kwargs["workbook_sha256"] = "changed"
    elif kind == "catalog_hash": kwargs["catalog_manifest_sha256"] = "changed"
    elif kind == "dry_hash": kwargs["dry_run_manifest_sha256"] = "changed"
    elif kind == "recon": kwargs["reconciliation_evidence_sha256"] = "changed"
    elif kind == "release": kwargs["production"]["application_version"] = "0.24.2"
    elif kind == "schema": kwargs["production"]["current_schema_revision"] = "other"
    elif kind == "writes": kwargs["production"]["writes_enabled"] = True
    elif kind == "count": kwargs["current_catalog_records"].pop()
    elif kind == "missing": kwargs["current_catalog_records"].pop(0)
    elif kind == "number": kwargs["current_catalog_records"][0]["machine_number"] = "99"
    elif kind == "version": kwargs["current_catalog_records"][0]["row_version"] = 2
    elif kind == "capacity": kwargs["current_catalog_records"][0]["press_capacity_tons"] = 165
    elif kind == "excluded": candidate["approved_mappings"][0]["parsed_machine_number"] = "24"
    elif kind == "duplicate": candidate["approved_mappings"].append(copy.deepcopy(candidate["approved_mappings"][0]))
    assert expected in validate_candidate_preconditions(candidate, **kwargs).errors
