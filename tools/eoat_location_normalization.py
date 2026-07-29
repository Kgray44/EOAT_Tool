"""Owner-approved EOAT location normalization policy.

The workbook remains immutable source evidence.  This module only exposes the
approved normalized relationship and physical-unit mappings used by import,
parity, and controlled correction tooling.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPOSITORY_ROOT / "config" / "eoat_location_normalization.json"
_STORED_MACHINE_VALUES = {"n/a"}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    """Load and validate the single reviewed normalization policy."""
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    required = {
        "approved_by", "expected_location_state_counts", "machine_aliases",
        "owner_decisions", "physical_unit_splits", "repeated_audit_units", "identity_correction",
        "supersedes_operational_migration_id",
    }
    missing = sorted(required - set(policy))
    if missing:
        raise RuntimeError(f"Location-normalization policy is incomplete: {', '.join(missing)}")
    seen_ids: set[str] = set()
    seen_rows: set[int] = set()
    for split in policy["physical_unit_splits"]:
        units = split.get("units") or []
        if len(units) < 2 or units[0].get("eoat_identifier") != split.get("source_identifier"):
            raise RuntimeError(f"Invalid physical-unit split for {split.get('source_identifier')!r}")
        for unit in units:
            identifier = _text(unit.get("eoat_identifier"))
            if not identifier or identifier in seen_ids:
                raise RuntimeError(f"Duplicate or blank normalized EOAT identifier: {identifier!r}")
            seen_ids.add(identifier)
            for number in unit.get("source_rows") or []:
                if int(number) in seen_rows:
                    raise RuntimeError(f"Source row {number} is assigned to more than one physical unit")
                seen_rows.add(int(number))
    repeated_identifiers: set[str] = set()
    for repeated in policy["repeated_audit_units"]:
        identifier = _text(repeated.get("eoat_identifier"))
        source = _text(repeated.get("source_identifier"))
        rows = {int(value) for value in repeated.get("source_rows") or []}
        if not identifier or identifier != source or len(rows) < 2:
            raise RuntimeError(f"Invalid repeated-audit identity resolution for {source!r}")
        if identifier in repeated_identifiers:
            raise RuntimeError(f"Duplicate repeated-audit identity resolution for {identifier!r}")
        if seen_rows & rows:
            raise RuntimeError(f"Repeated-audit rows overlap a physical-unit split for {identifier!r}")
        repeated_identifiers.add(identifier)
    return policy


def normalize_machine_reference(value: Any) -> str:
    """Return an approved canonical machine number, or an empty value if unsafe."""
    text = _text(value)
    aliases = {key.casefold(): str(target) for key, target in load_policy()["machine_aliases"].items()}
    if text.casefold() in aliases:
        return aliases[text.casefold()]
    return text if text.isdigit() else ""


def is_stored_machine_reference(value: Any) -> bool:
    """``N/A`` is owner-approved evidence of cabinet storage, not unknown."""
    return _text(value).casefold() in _STORED_MACHINE_VALUES


def normalized_eoat_identifier(source_identifier: Any, source_row_number: int) -> str:
    """Map a workbook row to its approved physical EOAT unit."""
    source = _text(source_identifier)
    row = int(source_row_number)
    for split in load_policy()["physical_unit_splits"]:
        if source != split["source_identifier"]:
            continue
        for unit in split["units"]:
            if row in {int(value) for value in unit["source_rows"]}:
                return str(unit["eoat_identifier"])
    return source


def physical_eoat_identifier(source_identifier: Any, source_row_number: int, entry_type: Any) -> str | None:
    """Resolve one audited source row to its physical EOAT identifier.

    Compatibility-only rows intentionally return ``None``: they can contribute
    compatibility evidence, but may never manufacture a physical EOAT.
    """
    if _text(entry_type).casefold() != "audited":
        return None
    return normalized_eoat_identifier(source_identifier, source_row_number)


def physical_eoat_uuid(canonical_identifier: Any) -> str:
    """Return the stable UUID for a governed physical EOAT identifier."""
    identifier = _text(canonical_identifier)
    if not identifier:
        raise ValueError("A canonical physical EOAT identifier is required")
    return str(uuid5(NAMESPACE_URL, f"eoat-atlas:physical-identity:v1:{identifier}"))


def identity_resolution(source_identifier: Any, source_row_number: int, entry_type: Any) -> str:
    """Classify an inventory row without inferring identity from location/tool."""
    if _text(entry_type).casefold() != "audited":
        return "compatibility-only evidence"
    source = _text(source_identifier)
    number = int(source_row_number)
    for repeated in load_policy()["repeated_audit_units"]:
        if source == _text(repeated.get("source_identifier")) and number in {
            int(value) for value in repeated.get("source_rows") or []
        }:
            return "repeated audit of same unit"
    canonical = normalized_eoat_identifier(source, number)
    if canonical != source:
        return "separate duplicate physical unit"
    return "unique physical unit"


def normalized_source_rows(rows: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Return source rows targeted at physical units without altering raw evidence."""
    rewritten: dict[int, dict[str, Any]] = {}
    for number, row in rows.items():
        updated = copy.deepcopy(row)
        source_identifier = _text(updated.get("EOAT Assembly ID"))
        target_identifier = physical_eoat_identifier(source_identifier, int(number), updated.get("Entry Type"))
        if target_identifier and source_identifier != target_identifier:
            updated["Original EOAT Assembly ID"] = source_identifier
            updated["EOAT Assembly ID"] = target_identifier
        if target_identifier:
            updated["Physical EOAT UUID"] = physical_eoat_uuid(target_identifier)
            updated["Identity Resolution"] = identity_resolution(source_identifier, int(number), updated.get("Entry Type"))
        rewritten[int(number)] = updated
    return rewritten


def split_units() -> list[dict[str, Any]]:
    return copy.deepcopy(load_policy()["physical_unit_splits"])


def owner_approval_evidence() -> dict[str, Any]:
    policy = load_policy()
    return {
        "approved_by": policy["approved_by"],
        "owner_decisions": policy["owner_decisions"],
        "policy_version": policy["policy_version"],
        "supersedes_operational_migration_id": policy["supersedes_operational_migration_id"],
        "identity_correction": policy["identity_correction"],
    }
