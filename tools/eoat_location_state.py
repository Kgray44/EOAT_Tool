"""State-aware EOAT physical-location classification.

Compatibility and historical audit associations are deliberately excluded from
current physical state unless a physically verified audit explicitly says the
EOAT was installed. Explicit audit notes about cabinet storage or removal take
precedence over generic context/machine fields on the same row.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

try:
    from tools.eoat_location_normalization import is_stored_machine_reference, normalize_machine_reference
except ModuleNotFoundError:  # Direct execution from tools/ does not include the repository root.
    from eoat_location_normalization import is_stored_machine_reference, normalize_machine_reference

STATE_INSTALLED = "A. Installed on a machine"
STATE_STORED = "B. Stored at a documented storage location"
STATE_UNKNOWN = "C. Location unknown or not verified"
STATE_INACTIVE = "D. Retired, archived, or otherwise inactive"
STATE_CONFLICT = "E. Conflicting source information requiring review"

_MISSING = {"", "n/a", "na", "none", "null", "unknown", "tbd", "-"}
_CABINET = re.compile(r"\beoat\s+(?:is\s+)?in\s+(?:an?\s+)?cabinet\b", re.IGNORECASE)
_NOT_INSTALLED = re.compile(r"\beoat\s+(?:is\s+)?not\s+installed\b", re.IGNORECASE)
_REMOVED = re.compile(r"\beoat\s+(?:was\s+)?removed\s+from\s+(?:the\s+)?machine\b", re.IGNORECASE)
_SAME_EOAT_TOOL = re.compile(r"\bsame\s+eoat\s+as\s+tool\s*#?\s*([0-9/]+)", re.IGNORECASE)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = _text(value)
    if raw.casefold() in _MISSING:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _is_audited(row: dict[str, Any]) -> bool:
    return _text(row.get("Entry Type")).casefold() == "audited"


def _is_verified(row: dict[str, Any]) -> bool:
    return _text(row.get("Physical Audit Verified")).casefold() == "yes"


def _machine(row: dict[str, Any]) -> str:
    return normalize_machine_reference(row.get("Press/Machine #"))


def _is_plant4(row: dict[str, Any]) -> bool:
    return _text(row.get("Plant/Area")).casefold() in {"plant 4", "p4"}


def _row_number(item: tuple[int, dict[str, Any]]) -> int:
    return int(item[0])


def _latest(items: list[tuple[int, dict[str, Any]]]) -> list[tuple[int, dict[str, Any]]]:
    dated = [(number, row, _date(row.get("Audit Date"))) for number, row in items]
    available = [value for _, _, value in dated if value is not None]
    if not available:
        return items
    latest_date = max(available)
    return [(number, row) for number, row, value in dated if value == latest_date]


def _active_relationships(database: dict[str, Any], key: str, eoat: str) -> list[dict[str, Any]]:
    return [
        row for row in database.get("relationships", {}).get(key, [])
        if _text(row.get("eoat_identifier")).casefold() == eoat.casefold() and bool(row.get("is_current"))
    ]


def _join(values: Iterable[Any]) -> str:
    return " | ".join(_text(value) for value in values if _text(value))


def classify_eoat_locations(
    source_rows: dict[int, dict[str, Any]], database: dict[str, Any]
) -> dict[str, Any]:
    """Classify one current physical state per EOAT and calculate parity metrics."""
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    tool_to_eoats: dict[str, set[str]] = defaultdict(set)
    for number, row in source_rows.items():
        eoat = _text(row.get("EOAT Assembly ID"))
        if not eoat:
            continue
        grouped[eoat].append((int(number), row))
        tool = _text(row.get("Tool #"))
        if tool.casefold() not in _MISSING:
            tool_to_eoats[tool].add(eoat)

    database_eoats = {
        _text(row.get("business_identifier")).casefold(): row for row in database.get("eoats", [])
    }
    identity_conflicts: dict[str, set[str]] = defaultdict(set)
    for eoat, items in grouped.items():
        for _, row in items:
            match = _SAME_EOAT_TOOL.search(_text(row.get("Notes")))
            if not match:
                continue
            for other in tool_to_eoats.get(match.group(1), set()):
                if other != eoat:
                    identity_conflicts[eoat].add(other)
                    identity_conflicts[other].add(eoat)

    records: list[dict[str, Any]] = []
    for eoat in sorted(grouped, key=str.casefold):
        all_items = sorted(grouped[eoat], key=_row_number)
        audited = [item for item in all_items if _is_audited(item[1])]
        current = _latest(audited) if audited else []
        db_eoat = database_eoats.get(eoat.casefold(), {})
        inactive = not bool(db_eoat.get("is_active", True)) or bool(db_eoat.get("archived_at")) or _text(
            db_eoat.get("status")
        ).casefold() in {"retired", "archived", "inactive"}
        stored_rows = [
            item for item in current
            if is_stored_machine_reference(item[1].get("Press/Machine #"))
            or _CABINET.search(_text(item[1].get("Notes")))
        ]
        negative_rows = [
            item for item in current
            if _NOT_INSTALLED.search(_text(item[1].get("Notes"))) or _REMOVED.search(_text(item[1].get("Notes")))
        ]
        installed_rows = [
            item for item in current
            if _is_verified(item[1])
            and _text(item[1].get("Audit Context")).casefold() == "installed on machine"
            and _machine(item[1])
            and item not in negative_rows
            and item not in stored_rows
        ]
        installed_machines = sorted({_machine(row) for _, row in installed_rows}, key=lambda value: int(value))

        machine_number = ""
        storage_location = ""
        ambiguity = ""
        if inactive:
            state = STATE_INACTIVE
            confidence = "High"
            evidence = "Database asset is inactive or archived; no active physical placement should be asserted."
            correction = "Ensure no active installation or storage assignment remains."
        elif stored_rows:
            state = STATE_STORED
            confidence = "High"
            storage_location = "Cabinet unspecified"
            evidence = _join(
                f"row {number}: {_text(row.get('Notes'))}" for number, row in stored_rows
            )
            if any(is_stored_machine_reference(row.get("Press/Machine #")) for _, row in stored_rows):
                evidence = "Owner-approved N/A storage normalization; " + evidence
            if any(_text(row.get("Audit Context")).casefold() == "installed on machine" for _, row in stored_rows):
                ambiguity = "Generic Audit Context/machine field conflicts with storage evidence; storage governs."
            correction = (
                "Represent cabinet-unspecified storage as an observed current state; do not invent stored_at "
                "or a cabinet identifier."
            )
        elif identity_conflicts.get(eoat):
            state = STATE_CONFLICT
            confidence = "Review required"
            related = ", ".join(sorted(identity_conflicts[eoat], key=str.casefold))
            evidence = f"Audit notes say this is the same physical EOAT represented by {related}."
            ambiguity = "Distinct EOAT identifiers may represent one physical asset."
            correction = "Resolve asset identity before creating any normalized current-location row."
        elif len(installed_machines) > 1 and all(_is_plant4(row) for _, row in installed_rows):
            state = STATE_STORED
            confidence = "Owner approved"
            storage_location = "Cabinet unspecified"
            evidence = (
                "Owner-approved Plant 4 movement resolution for latest multiple-machine audit sequence "
                f"({', '.join(installed_machines)}); no duplicate-pair evidence establishes separate physical units."
            )
            correction = "Preserve dated assertions; do not create lifecycle movement history or a cabinet identifier."
        elif len(installed_machines) > 1:
            state = STATE_CONFLICT
            confidence = "Review required"
            evidence = f"Latest physically verified audited rows assert simultaneous installation on machines {', '.join(installed_machines)}."
            ambiguity = "One EOAT identifier cannot be actively installed on multiple machines."
            correction = "Resolve whether the identifier represents multiple assets or which one machine is current."
        elif installed_machines:
            state = STATE_INSTALLED
            confidence = "Medium"
            machine_number = installed_machines[0]
            evidence = _join(
                f"row {number}: verified audit on {_text(row.get('Audit Date'))}, machine {_machine(row)}"
                for number, row in installed_rows
            )
            correction = (
                "Represent as an observed current installation after adding sanctioned observation-time semantics; "
                "do not use the audit date as the original installed_at."
            )
        elif negative_rows:
            state = STATE_STORED
            confidence = "Owner approved"
            storage_location = "Cabinet unspecified"
            evidence = _join(f"row {number}: {_text(row.get('Notes'))}" for number, row in negative_rows)
            ambiguity = "Source does not identify a cabinet/location identifier."
            correction = (
                "Owner-approved storage normalization for an uncertain present location; do not create "
                "an installation, storage lifecycle event, or cabinet identifier."
            )
        else:
            state = STATE_UNKNOWN
            confidence = "Low"
            evidence = "No latest physically verified audited row establishes an installed, stored, or inactive state."
            ambiguity = "Current physical location is not verified."
            correction = "Keep current location unknown and physically verify."

        installations = _active_relationships(database, "installations", eoat)
        storage = _active_relationships(database, "storage_assignments", eoat)
        observations = [
            row for row in database.get("relationships", {}).get("location_observations", [])
            if _text(row.get("eoat_identifier")).casefold() == eoat.casefold()
            and bool(row.get("is_authoritative", True))
        ]
        db_machine = ", ".join(sorted({_text(row.get("machine_number")) for row in installations}))
        db_storage = ", ".join(sorted({_text(row.get("location_code")) for row in storage}))
        observed_states = {_text(row.get("state")).upper() for row in observations}
        observed_machines = {_text(row.get("machine_number")) for row in observations if _text(row.get("machine_number"))}
        if state == STATE_INSTALLED:
            parity_pass = (
                (len(installations) == 1 and db_machine == machine_number and not storage)
                or ("INSTALLED" in observed_states and machine_number in observed_machines and not storage)
            )
        elif state == STATE_STORED:
            parity_pass = (len(storage) == 1 and not installations) or ("STORED" in observed_states and not installations)
        elif state in {STATE_UNKNOWN, STATE_INACTIVE}:
            required = "INACTIVE" if state == STATE_INACTIVE else "UNKNOWN"
            parity_pass = not installations and not storage and (required in observed_states or not observations)
        elif state == STATE_CONFLICT:
            parity_pass = "CONFLICTING" in observed_states and not installations and not storage
        else:
            parity_pass = False

        location_fields = _join(
            f"row {number}: date={_text(row.get('Audit Date')) or 'blank'}; machine={_text(row.get('Press/Machine #')) or 'blank'}; "
            f"context={_text(row.get('Audit Context')) or 'blank'}; verified={_text(row.get('Physical Audit Verified')) or 'blank'}; "
            f"notes={_text(row.get('Notes')) or 'blank'}"
            for number, row in audited
        )
        records.append({
            "eoat_identifier": eoat,
            "workbook_source": "EOAT_Master_Tracker.xlsx",
            "sheet": "EOAT Inventory",
            "rows": ", ".join(str(number) for number, _ in audited),
            "workbook_location_fields": location_fields,
            "current_database_state": (
                f"active installations={len(installations)}{f' ({db_machine})' if db_machine else ''}; "
                f"active storage assignments={len(storage)}{f' ({db_storage})' if db_storage else ''}; "
                f"authoritative observations={len(observations)} ({', '.join(sorted(observed_states)) or 'none'}); "
                f"audit evidence rows={len(audited)}"
            ),
            "determined_physical_state": state,
            "machine_number": machine_number,
            "storage_location": storage_location,
            "confidence": confidence,
            "evidence": evidence,
            "required_database_correction": correction,
            "unresolved_ambiguity": ambiguity,
            "normalized_location_parity": "PASS" if parity_pass else ("UNRESOLVED" if state == STATE_CONFLICT else "FAIL"),
        })

    state_metrics = []
    for state in (STATE_INSTALLED, STATE_STORED, STATE_UNKNOWN, STATE_INACTIVE, STATE_CONFLICT):
        subset = [row for row in records if row["determined_physical_state"] == state]
        passed = sum(row["normalized_location_parity"] == "PASS" for row in subset)
        state_metrics.append({
            "state": state,
            "expected": len(subset),
            "passed": passed,
            "failed_or_unresolved": len(subset) - passed,
            "percent": round(100 * passed / len(subset), 4) if subset else 100.0,
        })

    machine_assertions = []
    tool_assertions = []
    for _, row in source_rows.items():
        eoat = _text(row.get("EOAT Assembly ID"))
        machine = _machine(row)
        tool = _text(row.get("Tool #"))
        if eoat and machine:
            machine_assertions.append((eoat.casefold(), machine.casefold()))
        if eoat and tool.casefold() not in _MISSING:
            tool_assertions.append((eoat.casefold(), tool.casefold()))
    db_machine_pairs = {
        (_text(row.get("eoat_identifier")).casefold(), _text(row.get("machine_number")).casefold())
        for row in database.get("relationships", {}).get("eoat_machine", [])
    }
    db_tool_pairs = {
        (_text(row.get("eoat_identifier")).casefold(), _text(row.get("tool_number")).casefold())
        for row in database.get("relationships", {}).get("eoat_tool", [])
    }
    machine_pass = sum(pair in db_machine_pairs for pair in machine_assertions)
    tool_pass = sum(pair in db_tool_pairs for pair in tool_assertions)
    verified_records = [row for row in records if row["determined_physical_state"] != STATE_CONFLICT]
    overall_pass = sum(row["normalized_location_parity"] == "PASS" for row in verified_records)
    metrics = {
        "state_metrics": state_metrics,
        "installed_eoat_parity": next(item for item in state_metrics if item["state"] == STATE_INSTALLED),
        "stored_eoat_parity": next(item for item in state_metrics if item["state"] == STATE_STORED),
        "unknown_location_eoat_parity": next(item for item in state_metrics if item["state"] == STATE_UNKNOWN),
        "machine_compatibility_parity": {
            "source_assertions": len(machine_assertions), "unique_source_pairs": len(set(machine_assertions)),
            "passed_assertions": machine_pass, "percent": round(100 * machine_pass / len(machine_assertions), 4) if machine_assertions else 100.0,
        },
        "tool_compatibility_parity": {
            "source_assertions": len(tool_assertions), "unique_source_pairs": len(set(tool_assertions)),
            "passed_assertions": tool_pass, "percent": round(100 * tool_pass / len(tool_assertions), 4) if tool_assertions else 100.0,
        },
        "overall_current_location_parity": {
            "verified_nonconflicting_eoats": len(verified_records), "passed": overall_pass,
            "failed": len(verified_records) - overall_pass,
            "conflicting_excluded_pending_review": len(records) - len(verified_records),
            "percent": round(100 * overall_pass / len(verified_records), 4) if verified_records else 100.0,
        },
        "conflict_representation_parity": {
            "expected": sum(row["determined_physical_state"] == STATE_CONFLICT for row in records),
            "passed": sum(
                row["determined_physical_state"] == STATE_CONFLICT and row["normalized_location_parity"] == "PASS"
                for row in records
            ),
        },
    }
    return {"records": records, "metrics": metrics}
