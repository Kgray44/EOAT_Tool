"""Apply the owner-approved EOAT physical-location correction to development data.

The script is deliberately unable to target production.  Production receives
the reviewed result only through a guarded operational-data migration package.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.database.import_eoat_location_observations import (
    WORKSHEET,
    apply_plan,
    build_plan,
    load_database,
)  # noqa: E402
from scripts.database.production_data_migration import (
    REQUIRED_REVISION,
    assert_safe_source,
    connect,
    database_identity,
    write_json,
)  # noqa: E402
from tools.eoat_location_normalization import (
    load_policy,
    normalize_machine_reference,
    normalized_source_rows,
    owner_approval_evidence,
    physical_eoat_uuid,
)  # noqa: E402

NORMALIZATION_SOURCE = "OWNER_APPROVED_LOCATION_NORMALIZATION"
PROVENANCE_MARKER = "Owner-approved physical-unit normalization"


def _issue_resolution(issue_code: str, related_rows: list[int]) -> tuple[str, str]:
    """Return an evidence-backed disposition without inventing source facts."""
    resolutions = {
        "POSSIBLE_PART_NOT_CONFIRMED": (
            "RESOLVED",
            "No part relationship was created because the workbook supplies no confirmed part; raw evidence remains preserved.",
        ),
        "INSTALLATION_DATE_UNKNOWN": (
            "RESOLVED",
            "No installation date was invented; the record is represented only as a dated observed-location assertion.",
        ),
        "CURRENT_LOCATION_UNKNOWN": (
            "RESOLVED",
            "The owner-approved observed-location policy resolves the current state without creating lifecycle history.",
        ),
        "MISSING_MACHINE": (
            "RESOLVED",
            "Machine value N/A is owner-approved evidence of STORED with no machine or cabinet identifier.",
        ),
        "MISSING_TOOL": (
            "NOT_APPLICABLE",
            "Tool value N/A is retained as source evidence; no unsupported tool relationship was created.",
        ),
        "AMBIGUOUS_MACHINE_VALUE": (
            "RESOLVED",
            "Owner-approved normalization maps '26 - Xqual in 25' to Machine 26 while preserving the workbook wording.",
        ),
        "CONFLICTING_EOAT_ATTRIBUTE": (
            "RESOLVED",
            "The workbook's unknown attribute is preserved; no replacement classification was fabricated.",
        ),
        "PLACEHOLDER_PHOTO_ROW": (
            "NOT_APPLICABLE",
            "The placeholder row remains source provenance; no unsupported document or photo record was created.",
        ),
    }
    if issue_code == "CONFLICTING_CURRENT_ASSIGNMENT":
        if related_rows == [94, 95, 96, 97]:
            return (
                "RESOLVED",
                "Owner ruling supersedes the movement interpretation: the four Plant 4 rows are independent physical EOATs with row-specific observed locations.",
            )
        return (
            "RESOLVED",
            "Same-day cleanroom observations are owner-approved evidence of separate physical units and were split to deterministic EOAT IDs.",
        )
    if issue_code not in resolutions:
        raise RuntimeError(f"No owner-approved resolution exists for import issue {issue_code}")
    return resolutions[issue_code]


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return {}


def _source_rows(connection) -> tuple[dict[int, dict[str, Any]], str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT source_row_number,raw_values_json,import_batch_id FROM import_rows "
            "WHERE source_sheet=%s ORDER BY source_row_number",
            (WORKSHEET,),
        )
        imported = cursor.fetchall()
        rows = {int(row["source_row_number"]): _json(row["raw_values_json"]) for row in imported}
        batch_ids = {int(row["import_batch_id"]) for row in imported}
        if len(batch_ids) != 1:
            raise RuntimeError("EOAT Inventory source rows must belong to one import batch")
        cursor.execute(
            "SELECT source_file_name,source_file_checksum FROM import_batches WHERE id=%s",
            (next(iter(batch_ids)),),
        )
        batch = cursor.fetchone()
    if not rows or not batch or not batch["source_file_checksum"]:
        raise RuntimeError("Authoritative EOAT workbook evidence is unavailable from import provenance")
    return rows, str(batch["source_file_checksum"]), Path(str(batch["source_file_name"])).name


def _columns(connection, table: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name,extra FROM information_schema.columns "
            "WHERE table_schema=DATABASE() AND table_name=%s ORDER BY ordinal_position",
            (table,),
        )
        return [row["COLUMN_NAME"] for row in cursor.fetchall() if "generated" not in row["EXTRA"].casefold()]


def _insert(connection, table: str, row: dict[str, Any]) -> int:
    columns = list(row)
    values = [row[column] for column in columns]
    quoted = ",".join(f"`{column}`" for column in columns)
    placeholders = ",".join(["%s"] * len(columns))
    with connection.cursor() as cursor:
        cursor.execute(f"INSERT INTO `{table}` ({quoted}) VALUES ({placeholders})", values)
        return int(cursor.lastrowid)


def _append_provenance(existing: Any, message: str) -> str:
    text = "" if existing is None else str(existing).strip()
    if PROVENANCE_MARKER in text:
        return text
    return f"{text}\n\n{message}".strip()


def _eoat_id(connection, identifier: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM eoats WHERE business_identifier=%s", (identifier,))
        row = cursor.fetchone()
    if not row:
        raise RuntimeError(f"EOAT identifier is missing: {identifier}")
    return int(row["id"])


def _clone_eoat(connection, source_identifier: str, target_identifier: str, source_rows: list[int]) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM eoats WHERE business_identifier=%s", (source_identifier,))
        source = cursor.fetchone()
        cursor.execute("SELECT id FROM eoats WHERE business_identifier=%s", (target_identifier,))
        existing = cursor.fetchone()
    if not source:
        raise RuntimeError(f"Physical-unit split source EOAT is missing: {source_identifier}")
    provenance = (
        f"{PROVENANCE_MARKER}: split from shared workbook identifier {source_identifier}; "
        f"this unit is supported by EOAT Inventory row(s) {', '.join(str(row) for row in source_rows)}. "
        "Compatibility relationships are shared evidence; audit, document, photo, and lifecycle history were not copied."
    )
    if existing:
        return int(existing["id"])
    copied = {column: source[column] for column in _columns(connection, "eoats") if column != "id"}
    copied.update({
        "business_identifier": target_identifier,
        "physical_uuid": physical_eoat_uuid(target_identifier),
        "design_family_identifier": source_identifier,
        "legacy_identifier": source_identifier,
        "display_name": target_identifier,
        "notes": (
            str(source.get("notes") or "").strip()
            if provenance in str(source.get("notes") or "")
            else f"{str(source.get('notes') or '').strip()}\n\n{provenance}".strip()
        ),
        "source_system": NORMALIZATION_SOURCE,
        "row_version": 1,
    })
    return _insert(connection, "eoats", copied)


def _rebuild_row_specific_compatibility(connection, source_eoat_id: int, units: list[dict[str, Any]]) -> dict[str, int]:
    """Rebuild split-unit compatibility only from the rows that support it."""
    templates: dict[str, list[dict[str, Any]]] = {}
    for table in ("eoat_machine_compatibility", "eoat_tool_compatibility"):
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT * FROM `{table}` WHERE eoat_id=%s ORDER BY id", (source_eoat_id,))
            templates[table] = cursor.fetchall()
    target_ids = [_eoat_id(connection, str(unit["eoat_identifier"])) for unit in units]
    with connection.cursor() as cursor:
        for table in templates:
            cursor.execute(f"DELETE FROM `{table}` WHERE eoat_id IN ({','.join(['%s'] * len(target_ids))})", target_ids)
    copied_counts: Counter[str] = Counter()
    for unit, target_eoat_id in zip(units, target_ids, strict=True):
        for source_row in unit["source_rows"]:
            with connection.cursor() as cursor:
                cursor.execute("SELECT machine_id,tool_id FROM audit_records WHERE source_sheet=%s AND source_row_number=%s", (WORKSHEET, int(source_row)))
                audit = cursor.fetchone()
            if not audit:
                raise RuntimeError(f"Missing audit evidence for compatibility source row {source_row}")
            for table, foreign_key in (("eoat_machine_compatibility", "machine_id"), ("eoat_tool_compatibility", "tool_id")):
                value = audit[foreign_key]
                if value is None:
                    continue
                for template in (row for row in templates[table] if row[foreign_key] == value):
                    copied = {column: template[column] for column in _columns(connection, table) if column != "id"}
                    copied["eoat_id"] = target_eoat_id
                    copied["source_system"] = NORMALIZATION_SOURCE
                    copied["row_version"] = 1
                    _insert(connection, table, copied)
                    copied_counts[table] += 1
    return dict(sorted(copied_counts.items()))


def _reassign_audit_rows(
    connection, source_identifier: str, target_identifier: str, source_rows: list[int], *, allowed_eoat_ids: set[int] | None = None
) -> None:
    source_eoat_id = _eoat_id(connection, source_identifier)
    target_eoat_id = _eoat_id(connection, target_identifier)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM eoats WHERE business_identifier=%s OR legacy_identifier=%s",
            (source_identifier, source_identifier),
        )
        previously_resolved_ids = {int(row["id"]) for row in cursor.fetchall()}
    for source_row in source_rows:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id,eoat_id FROM audit_records WHERE source_sheet=%s AND source_row_number=%s",
                (WORKSHEET, int(source_row)),
            )
            audit = cursor.fetchone()
        if not audit:
            raise RuntimeError(f"Missing audit record for EOAT Inventory row {source_row}")
        allowed = allowed_eoat_ids or (previously_resolved_ids | {source_eoat_id, target_eoat_id})
        if int(audit["eoat_id"]) not in allowed:
            raise RuntimeError(f"Audit row {source_row} is linked to an unexpected EOAT")
        if int(audit["eoat_id"]) != target_eoat_id:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE audit_records SET eoat_id=%s,row_version=row_version+1 WHERE id=%s", (target_eoat_id, audit["id"]))
                cursor.execute(
                    "UPDATE entity_history_events SET entity_id=%s WHERE entity_type='eoat' AND source_table='audit_records' AND source_record_id=%s",
                    (target_eoat_id, audit["id"]),
                )
                cursor.execute(
                    "UPDATE import_rows SET normalized_values_json=JSON_SET(COALESCE(normalized_values_json,JSON_OBJECT()), '$.eoat', %s) WHERE source_sheet=%s AND source_row_number=%s",
                    (target_identifier, WORKSHEET, source_row),
                )


def _apply_physical_unit_splits(connection, policy: dict[str, Any]) -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []
    for split in policy["physical_unit_splits"]:
        source_identifier = str(split["source_identifier"])
        source_eoat_id = _eoat_id(connection, source_identifier)
        unit_identifiers = [str(unit["eoat_identifier"]) for unit in split["units"]]
        provenance = (
            f"{PROVENANCE_MARKER}: shared workbook identifier split into physical units "
            f"{', '.join(unit_identifiers)}. {split['reason']}"
        )
        existing_notes = _notes(connection, source_eoat_id)
        if PROVENANCE_MARKER not in existing_notes:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE eoats SET notes=%s,source_system=%s,row_version=row_version+1 WHERE id=%s",
                    (_append_provenance(existing_notes, provenance), NORMALIZATION_SOURCE, source_eoat_id),
                )
        for unit in split["units"]:
            target_identifier = str(unit["eoat_identifier"])
            target_eoat_id = _clone_eoat(connection, source_identifier, target_identifier, list(unit["source_rows"]))
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE eoats SET physical_uuid=%s,design_family_identifier=%s,legacy_identifier=COALESCE(legacy_identifier,%s) WHERE id=%s",
                    (physical_eoat_uuid(target_identifier), source_identifier, source_identifier if target_identifier != source_identifier else None, target_eoat_id),
                )
                cursor.execute(
                    "INSERT IGNORE INTO eoat_identity_aliases (eoat_id,alias_identifier,alias_type,source_row_number,owner_decision_reference,source_import_batch_id) "
                    "SELECT %s,%s,'SOURCE_IDENTIFIER',%s,%s,source_import_batch_id FROM audit_records WHERE source_sheet=%s AND source_row_number=%s",
                    (target_eoat_id, source_identifier, int(unit["source_rows"][0]), policy["identity_correction"]["owner_decision_reference"], WORKSHEET, int(unit["source_rows"][0])),
                )
            _reassign_audit_rows(connection, source_identifier, target_identifier, list(unit["source_rows"]))
        copied = _rebuild_row_specific_compatibility(connection, source_eoat_id, split["units"])
        report.append({
            "source_identifier": source_identifier,
            "normalized_unit_identifiers": unit_identifiers,
            "reason": split["reason"],
            "row_specific_compatibility_relationships": copied,
        })
    return report


def _notes(connection, eoat_id: int) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT notes FROM eoats WHERE id=%s", (eoat_id,))
        row = cursor.fetchone()
    return "" if not row or row["notes"] is None else str(row["notes"])


def _ensure_stable_physical_uuids(connection) -> int:
    """Backfill UUIDs without deriving them from a machine, tool, or audit date."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT id,business_identifier,physical_uuid,design_family_identifier FROM eoats ORDER BY id")
        eoats = cursor.fetchall()
    changed = 0
    for eoat in eoats:
        if eoat["physical_uuid"]:
            continue
        identifier = str(eoat["business_identifier"])
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE eoats SET physical_uuid=%s,design_family_identifier=COALESCE(design_family_identifier,%s),row_version=row_version+1 WHERE id=%s",
                (physical_eoat_uuid(identifier), identifier, int(eoat["id"])),
            )
        changed += 1
    return changed


def _apply_machine_aliases(connection, rows: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    applied = []
    for source_row, row in rows.items():
        canonical = normalize_machine_reference(row.get("Press/Machine #"))
        raw = str(row.get("Press/Machine #") or "").strip()
        if not canonical or raw == canonical:
            continue
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT m.id FROM machines m JOIN plants p ON p.id=m.plant_id "
                "WHERE p.plant_code=%s AND m.machine_number=%s",
                ("CL" if str(row.get("Plant/Area") or "").casefold() == "cleanroom" else "P4", canonical),
            )
            machines = cursor.fetchall()
            if len(machines) != 1:
                raise RuntimeError(f"Could not resolve exactly one canonical machine {canonical} for source row {source_row}")
            machine_id = int(machines[0]["id"])
            cursor.execute(
                "UPDATE import_rows SET normalized_values_json=JSON_SET(COALESCE(normalized_values_json,JSON_OBJECT()), '$.machine', %s) "
                "WHERE source_sheet=%s AND source_row_number=%s",
                (canonical, WORKSHEET, source_row),
            )
            cursor.execute(
                "UPDATE audit_records SET machine_id=%s,row_version=row_version+1 "
                "WHERE source_sheet=%s AND source_row_number=%s",
                (machine_id, WORKSHEET, source_row),
            )
        applied.append({"source_row_number": source_row, "original_machine": raw, "normalized_machine": canonical})
    return applied


def _replace_location_evidence(connection, rows: dict[int, dict[str, Any]], digest: str, workbook_name: str, policy: dict[str, Any]) -> dict[str, Any]:
    plan = build_plan(
        normalized_source_rows(rows), load_database(connection),
        workbook_sha256=digest, source_workbook=workbook_name,
    )
    if plan["state_counts"] != policy["expected_location_state_counts"]:
        raise RuntimeError(
            f"Owner-approved location totals do not match: {plan['state_counts']} != {policy['expected_location_state_counts']}"
        )
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM eoat_location_assertions")
        cursor.execute("DELETE FROM eoat_location_observations")
    apply_plan(connection, plan, commit=False)
    return plan


def _resolve_import_issues(connection) -> dict[str, int]:
    """Close legacy importer warnings using the approved, non-fabricating dispositions."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT id,issue_code,resolution_notes FROM import_issues ORDER BY id")
        issues = cursor.fetchall()
    counts: Counter[str] = Counter()
    for issue in issues:
        notes = _json(issue["resolution_notes"])
        related_rows = [int(value) for value in notes.get("related_source_rows") or []]
        status, rationale = _issue_resolution(str(issue["issue_code"]), related_rows)
        notes.update({
            "status": status,
            "resolution_authority": "Kato Gray, EOAT Atlas project/data owner",
            "resolution_rationale": rationale,
            "normalization_source": NORMALIZATION_SOURCE,
        })
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE import_issues SET resolution_notes=%s WHERE id=%s",
                (json.dumps(notes, ensure_ascii=False, sort_keys=True), int(issue["id"])),
            )
        counts[status] += 1
    return dict(sorted(counts.items()))


def correct(connection, *, apply: bool) -> dict[str, Any]:
    policy = load_policy()
    identity = database_identity(connection)
    assert_safe_source(identity)
    if identity["alembic_revision"] != REQUIRED_REVISION:
        raise RuntimeError(f"Schema mismatch: required {REQUIRED_REVISION}, found {identity['alembic_revision']}")
    rows, digest, workbook_name = _source_rows(connection)
    if not apply:
        planned_rows = normalized_source_rows(rows)
        return {
            "status": "PLANNED",
            "database": identity["database_name"],
            "source_workbook": workbook_name,
            "source_workbook_sha256": digest,
            "approval": owner_approval_evidence(),
            "physical_unit_splits": policy["physical_unit_splits"],
            "planned_source_row_targets": {
                str(number): target["EOAT Assembly ID"] for number, target in planned_rows.items()
                if target.get("Original EOAT Assembly ID")
            },
        }
    try:
        uuid_backfills = _ensure_stable_physical_uuids(connection)
        aliases = _apply_machine_aliases(connection, rows)
        split_report = _apply_physical_unit_splits(connection, policy)
        plan = _replace_location_evidence(connection, rows, digest, workbook_name, policy)
        issue_resolutions = _resolve_import_issues(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {
        "status": "APPLIED",
        "database": identity["database_name"],
        "source_workbook": workbook_name,
        "source_workbook_sha256": digest,
        "approval": owner_approval_evidence(),
        "physical_uuid_backfills": uuid_backfills,
        "machine_aliases_applied": aliases,
        "physical_unit_splits": split_report,
        "location_observation_count": len(plan["observations"]),
        "location_assertion_count": len(plan["assertions"]),
        "location_state_counts": plan["state_counts"],
        "import_issue_resolutions": issue_resolutions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply owner-approved EOAT observed-location normalization to development")
    parser.add_argument("--environment", default="development")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    from scripts.database.production_data_migration import read_env

    values = read_env(args.environment)
    with connect(values) as connection:
        report = correct(connection, apply=args.apply)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.report, report)
    print(json.dumps({"status": report["status"], "report": str(args.report)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
