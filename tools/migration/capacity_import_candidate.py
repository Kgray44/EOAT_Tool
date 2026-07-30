"""Immutable, non-executable candidate for a future press-capacity import."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class CandidateValidation:
    valid: bool
    errors: tuple[str, ...]


def build_import_candidate(
    *,
    dry_run_manifest: str | Path,
    catalog_manifest: str | Path,
    workbook_sha256: str,
    reconciliation_evidence_sha256: str,
    branch: str,
    commit: str,
    application_version: str,
    source_schema_target: str,
) -> dict[str, Any]:
    """Build a capacity-only candidate from immutable, already-verified inputs."""
    dry_path, catalog_path = Path(dry_run_manifest).resolve(), Path(catalog_manifest).resolve()
    dry = json.loads(dry_path.read_text(encoding="utf-8"))
    catalog_document = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog = catalog_document.get("payload", catalog_document)
    by_identity = {record["api_identity"]: record for record in catalog["records"]}
    approved: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for mapping in dry["mappings"]:
        action = mapping["proposed_action"]
        if action == "UPDATE" and mapping["verification_class"] == "CANONICAL_MATCH" and mapping["mapping_method"] in {
            "EXACT_CANONICAL_MACHINE_NUMBER", "EXACT_GOVERNED_ALIAS", "DETERMINISTIC_NORMALIZED_MACHINE_NUMBER",
        }:
            record = by_identity.get(mapping["canonical_identity"])
            if record is None:
                raise ValueError(f"Approved mapping identity is absent from the catalog: {mapping['canonical_identity']}")
            approved.append({
                **{key: mapping[key] for key in ("source_sheet", "source_row", "source_press_heading", "parsed_machine_number", "parsed_tonnage", "tonnage_source", "canonical_identity", "canonical_machine_number", "plant_code", "area", "mapping_method", "verification_class", "existing_capacity_tons", "proposed_capacity_tons", "capacity_unit", "proposed_action")},
                "catalog_row_version": record.get("row_version"),
            })
        else:
            excluded.append({
                "source_sheet": mapping["source_sheet"], "source_row": mapping["source_row"],
                "machine_number": mapping["parsed_machine_number"], "action": action,
                "verification_class": mapping["verification_class"], "reason": mapping.get("reason"),
            })
    machine_27 = next(item for item in approved if item["parsed_machine_number"] == "27")
    payload = {
        "manifest_type": "eoat_atlas_press_capacity_import_candidate", "format_version": 1,
        "non_executable": True,
        "candidate_branch": branch, "candidate_commit": commit,
        "application_version": application_version, "source_schema_target": source_schema_target,
        "workbook_sha256": workbook_sha256, "catalog_manifest_sha256": _digest(catalog_path),
        "prior_dry_run_manifest_sha256": _digest(dry_path), "reconciliation_evidence_sha256": reconciliation_evidence_sha256,
        "production_identity": catalog.get("production_release", {}), "production_schema": catalog.get("production_schema", {}),
        "catalog_record_count": len(catalog["records"]), "catalog_data_revision": catalog.get("data_revision"),
        "approved_mappings": approved, "excluded_mappings": excluded,
        "catalog_only_exclusions": ["6", "8", "70", "72"],
        "machine_27_proof": machine_27,
        "proposed_counts": {"insert": 0, "update": len(approved), "unchanged": 0, "reject": 0, "review_required": len(excluded)},
        "import_policy": {
            "allowed_action": "update_existing_press_capacity_only", "allow_machine_creation": False,
            "allow_alias_creation": False, "allow_relationship_creation": False, "allow_destructive_updates": False,
            "allowed_existing_capacity": "null_or_exactly_candidate_expected", "requires_backup": True,
            "requires_immediate_dry_run": True, "requires_catalog_drift_check": True,
            "requires_immutable_receipt": True, "rollback": "restore_verified_backup_and_record_receipt",
        },
    }
    return payload


def validate_candidate_preconditions(
    candidate: dict[str, Any], *, workbook_sha256: str, catalog_manifest_sha256: str,
    dry_run_manifest_sha256: str, reconciliation_evidence_sha256: str,
    production: dict[str, Any], current_catalog_records: list[dict[str, Any]],
) -> CandidateValidation:
    """Fail closed on every drift condition; this function never executes an import."""
    errors: list[str] = []
    for field, actual in {
        "workbook_sha256": workbook_sha256, "catalog_manifest_sha256": catalog_manifest_sha256,
        "prior_dry_run_manifest_sha256": dry_run_manifest_sha256,
        "reconciliation_evidence_sha256": reconciliation_evidence_sha256,
    }.items():
        if candidate.get(field) != actual:
            errors.append(f"{field}_DRIFT")
    expected_release = candidate.get("production_identity", {})
    expected_schema = candidate.get("production_schema", {})
    if production.get("application_version") != expected_release.get("application_version"):
        errors.append("PRODUCTION_RELEASE_DRIFT")
    if production.get("current_schema_revision") != expected_schema.get("current_schema_revision"):
        errors.append("PRODUCTION_SCHEMA_DRIFT")
    if production.get("writes_enabled") is not False:
        errors.append("PRODUCTION_WRITES_UNEXPECTEDLY_ENABLED")
    if len(current_catalog_records) != candidate.get("catalog_record_count"):
        errors.append("CATALOG_MACHINE_COUNT_DRIFT")
    current = {record.get("api_identity"): record for record in current_catalog_records}
    excluded = {item["machine_number"] for item in candidate.get("excluded_mappings", [])} | set(candidate.get("catalog_only_exclusions", []))
    seen: set[str] = set()
    for approved in candidate.get("approved_mappings", []):
        identity = approved["canonical_identity"]
        if approved["parsed_machine_number"] in excluded:
            errors.append("EXCLUDED_MACHINE_INCLUDED")
        if identity in seen:
            errors.append("SOURCE_RECORD_MAPS_TO_MULTIPLE_CANONICAL_MACHINES")
        seen.add(identity)
        record = current.get(identity)
        if record is None:
            errors.append("CANONICAL_IDENTITY_MISSING")
            continue
        if str(record.get("machine_number")) != str(approved["canonical_machine_number"]):
            errors.append("CANONICAL_MACHINE_NUMBER_DRIFT")
        if record.get("row_version") != approved.get("catalog_row_version"):
            errors.append("CANONICAL_ROW_VERSION_DRIFT")
        existing = approved.get("existing_capacity_tons")
        current_capacity = record.get("press_capacity_tons")
        if current_capacity != existing:
            errors.append("EXISTING_CAPACITY_DRIFT")
    return CandidateValidation(valid=not errors, errors=tuple(sorted(set(errors))))


def write_immutable_import_candidate(candidate: dict[str, Any], directory: str | Path) -> Path:
    """Write a non-overwriting candidate and embed a digest of its canonical payload."""
    payload = json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    document = {"payload": candidate, "payload_sha256": hashlib.sha256(payload).hexdigest()}
    output = Path(directory); output.mkdir(parents=True, exist_ok=True)
    target = output / f"press-capacity-import-candidate-{candidate['workbook_sha256'][:12]}-{candidate['catalog_manifest_sha256'][:12]}.json"
    with target.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return target
