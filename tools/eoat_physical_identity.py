"""Deterministic physical-identity crosswalks for EOAT source audits.

The workbook retains source wording.  This module resolves only audited rows to
physical units from the owner-approved policy; compatibility rows remain
evidence and cannot create EOAT identities.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from tools.eoat_location_normalization import (
    identity_resolution,
    load_policy,
    physical_eoat_identifier,
    physical_eoat_uuid,
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


@dataclass(frozen=True)
class CrosswalkValidation:
    audited_rows: int
    physical_units: int
    canonical_identifiers: int
    duplicate_physical_identifier: str
    duplicate_audit_rows: int


def build_crosswalk(
    rows: Iterable[tuple[int, dict[str, Any]]],
    *,
    source_workbook_sha256: str,
    worksheet: str = "EOAT Inventory",
) -> list[dict[str, Any]]:
    """Build a complete, source-preserving physical-identity crosswalk."""
    policy = load_policy()
    decision = policy["identity_correction"]
    crosswalk: list[dict[str, Any]] = []
    for row_number, raw_row in rows:
        row = {str(key): _value(value) for key, value in raw_row.items()}
        entry_type = _text(row.get("Entry Type"))
        source_identifier = _text(row.get("EOAT Assembly ID"))
        canonical = physical_eoat_identifier(source_identifier, row_number, entry_type)
        classification = identity_resolution(source_identifier, row_number, entry_type)
        crosswalk.append(
            {
                "source_workbook_sha256": source_workbook_sha256,
                "worksheet": worksheet,
                "workbook_row_number": int(row_number),
                "audit_id": _text(row.get("Audit ID")),
                "audit_date": _value(row.get("Audit Date")),
                "entry_type": entry_type,
                "physical_audit_verified": _text(row.get("Physical Audit Verified")),
                "plant_area": _text(row.get("Plant/Area")),
                "machine": _text(row.get("Press/Machine #")),
                "tool": _text(row.get("Tool #")),
                "original_source_eoat_identifier": source_identifier,
                "original_raw_values": row,
                "canonical_physical_eoat_identifier": canonical,
                "physical_eoat_uuid": physical_eoat_uuid(canonical) if canonical else None,
                "shared_design_family_identifier": source_identifier if canonical and canonical != source_identifier else None,
                "source_legacy_identifier": source_identifier or None,
                "identity_resolution_classification": classification,
                "owner_decision_reference": decision["owner_decision_reference"],
                "mapping_rationale": _rationale(source_identifier, row_number, classification),
                "current_location_treatment": "Preserve row-specific location observation; do not infer an installation event.",
                "history_treatment": "Preserve the audit record on its resolved physical EOAT; do not fabricate lifecycle events.",
                "compatibility_treatment": "Preserve row-specific compatibility evidence; compatibility-only rows do not create physical EOATs.",
                "document_photo_treatment": "Retain existing audit-linked evidence; never clone assets to a split unit without source proof.",
                "notes_provenance_treatment": "Preserve original source wording and owner-resolution provenance.",
            }
        )
    validate_crosswalk(crosswalk)
    return crosswalk


def _rationale(source_identifier: str, row_number: int, classification: str) -> str:
    if classification == "compatibility-only evidence":
        return "Compatibility evidence is retained but excluded from the physical EOAT count."
    if classification == "repeated audit of same unit":
        return "Owner ruling: both P4-EOAT-0018 audit rows represent one physical unit."
    if classification == "separate duplicate physical unit":
        return f"Owner ruling assigns source row {row_number} for {source_identifier} to an independent simultaneous physical unit."
    return "One audited source row maps to one physical EOAT identity."


def validate_crosswalk(crosswalk: Iterable[dict[str, Any]]) -> CrosswalkValidation:
    """Fail closed unless the governed 67-audit/66-physical invariant holds."""
    policy = load_policy()["identity_correction"]
    rows = list(crosswalk)
    audited = [row for row in rows if _text(row.get("entry_type")).casefold() == "audited"]
    missing = [row["workbook_row_number"] for row in audited if not row.get("canonical_physical_eoat_identifier")]
    if missing:
        raise RuntimeError(f"Audited rows are missing physical identity mappings: {missing}")
    canonical = [str(row["canonical_physical_eoat_identifier"]) for row in audited]
    uuids = [str(row["physical_eoat_uuid"]) for row in audited]
    if len(audited) != int(policy["expected_audited_rows"]):
        raise RuntimeError(f"Expected {policy['expected_audited_rows']} audited rows, found {len(audited)}")
    if len(set(canonical)) != int(policy["expected_physical_units"]) or len(set(uuids)) != int(policy["expected_physical_units"]):
        raise RuntimeError("Physical EOAT identity count does not match the governed 66-unit invariant")
    duplicate_counts = {identifier: count for identifier, count in Counter(canonical).items() if count > 1}
    expected_identifier = str(policy["expected_duplicate_physical_identifier"])
    expected_count = int(policy["expected_duplicate_audit_rows"])
    if duplicate_counts != {expected_identifier: expected_count}:
        raise RuntimeError(f"Unexpected many-to-one audit mapping: {duplicate_counts}")
    if any(row.get("canonical_physical_eoat_identifier") for row in rows if _text(row.get("entry_type")).casefold() != "audited"):
        raise RuntimeError("Compatibility-only source rows may not create physical EOATs")
    return CrosswalkValidation(
        audited_rows=len(audited),
        physical_units=len(set(uuids)),
        canonical_identifiers=len(set(canonical)),
        duplicate_physical_identifier=expected_identifier,
        duplicate_audit_rows=expected_count,
    )
