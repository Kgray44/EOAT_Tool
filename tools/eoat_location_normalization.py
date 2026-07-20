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
        "owner_decisions", "physical_unit_splits", "supersedes_operational_migration_id",
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


def normalized_source_rows(rows: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Return source rows targeted at physical units without altering raw evidence."""
    rewritten: dict[int, dict[str, Any]] = {}
    for number, row in rows.items():
        updated = copy.deepcopy(row)
        source_identifier = _text(updated.get("EOAT Assembly ID"))
        target_identifier = normalized_eoat_identifier(source_identifier, int(number))
        if source_identifier != target_identifier:
            updated["Original EOAT Assembly ID"] = source_identifier
            updated["EOAT Assembly ID"] = target_identifier
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
    }
