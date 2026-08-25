"""Idempotent repair for historical physical-audit data omitted from MySQL.

The command is dry-run by default.  It resolves only explicit EOAT business or
physical UUID identities, preserves every source row as an ``audit_records``
record, and creates a historical observation rather than an active
installation.  Existing non-null EOAT values are never overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from openpyxl import load_workbook
from sqlalchemy import select

from server.eoat_api.audit_profiles import configuration_from_details, is_physical_audit, latest_physical_audit
from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory
from tools.migration.excel_to_mysql import _checksum, _rows, _text


@dataclass
class BackfillReport:
    source_workbook: str
    source_checksum: str
    dry_run: bool
    rows_considered: int = 0
    physical_audits: int = 0
    exact_matches: int = 0
    ambiguous_matches: int = 0
    skipped_records: int = 0
    audit_records_to_insert: int = 0
    observations_to_insert: int = 0
    eoats_to_update: int = 0
    fields_to_update: int = 0
    conflicts: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    executed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _SourceAudit:
    row_number: int
    values: dict[str, Any]

    @property
    def audit_identifier(self) -> str:
        return _text(self.values.get("Audit ID"))

    @property
    def source_identity(self) -> tuple[str, str]:
        physical_uuid = _text(self.values.get("Physical EOAT UUID"))
        if physical_uuid:
            return ("physical_uuid", physical_uuid)
        return ("business_identifier", _text(self.values.get("Canonical Physical EOAT ID")) or _text(self.values.get("EOAT Assembly ID")))


def _audit_date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    try:
        return datetime.fromisoformat(_text(value)) if _text(value) else None
    except ValueError:
        return None


def _load_source_audits(source_workbook: str | Path) -> list[_SourceAudit]:
    workbook = load_workbook(Path(source_workbook), read_only=True, data_only=True)
    try:
        rows = _rows(workbook["EOAT Inventory"])
    finally:
        workbook.close()
    return [_SourceAudit(number, row) for number, row in rows if is_physical_audit(row)]


def _resolve_eoat(source: _SourceAudit, by_business: dict[str, db.EOAT], by_physical_uuid: dict[str, db.EOAT]) -> tuple[db.EOAT | None, bool]:
    physical_uuid = _text(source.values.get("Physical EOAT UUID"))
    business_identifier = _text(source.values.get("Canonical Physical EOAT ID")) or _text(source.values.get("EOAT Assembly ID"))
    physical_match = by_physical_uuid.get(physical_uuid) if physical_uuid else None
    business_match = by_business.get(business_identifier) if business_identifier else None
    if physical_match is not None and business_match is not None and physical_match.id != business_match.id:
        return None, True
    return physical_match or business_match, False


def _nullable_profile_updates(eoat: db.EOAT, source: _SourceAudit) -> dict[str, Any]:
    values = configuration_from_details(source.values)
    field_map = {
        "number_of_parts_picked": values["parts_picked"],
        "number_of_vacuum_cups": values["vacuum_cup_count"],
        "number_of_grippers": values["gripper_count"],
        "cup_material": values["cup_material"],
        "sensors_present": values["sensors_present"],
        "part_present_sensor_present": values["part_present_sensor_present"],
        "vacuum_confirmation_sensor_present": values["vacuum_confirmation_sensor_present"],
        "quick_disconnect_present": values["quick_disconnect_present"],
    }
    description = _text(source.values.get("Part Name/Description")) or None
    if description:
        field_map["description"] = description
    return {name: value for name, value in field_map.items() if value is not None and getattr(eoat, name) is None}


def plan_backfill(source_workbook: str | Path, session) -> tuple[BackfillReport, list[tuple[_SourceAudit, db.EOAT]], dict[int, dict[str, Any]]]:
    source = Path(source_workbook).resolve()
    report = BackfillReport(str(source), _checksum(source), dry_run=True)
    audits = _load_source_audits(source)
    report.rows_considered = len(audits)
    report.physical_audits = len(audits)
    eoats = list(session.scalars(select(db.EOAT)))
    by_business = {item.business_identifier: item for item in eoats}
    by_physical_uuid = {item.physical_uuid: item for item in eoats if item.physical_uuid}
    existing_audit_ids = set(session.scalars(select(db.AuditRecord.audit_identifier)))
    existing_observation_ids = set(session.scalars(select(db.EOATLocationObservation.observation_uuid)))
    matches: list[tuple[_SourceAudit, db.EOAT]] = []
    grouped: dict[int, list[_SourceAudit]] = defaultdict(list)
    for source_audit in audits:
        if not source_audit.audit_identifier:
            report.skipped_records += 1
            report.unresolved.append(f"row {source_audit.row_number}: missing Audit ID")
            continue
        target, ambiguous = _resolve_eoat(source_audit, by_business, by_physical_uuid)
        if ambiguous:
            report.ambiguous_matches += 1
            report.conflicts.append(f"{source_audit.audit_identifier}: physical UUID and canonical ID resolve to different EOATs")
            continue
        if target is None:
            report.skipped_records += 1
            report.unresolved.append(f"{source_audit.audit_identifier}: no exact EOAT identity match")
            continue
        report.exact_matches += 1
        matches.append((source_audit, target))
        grouped[target.id].append(source_audit)
        if source_audit.audit_identifier not in existing_audit_ids:
            report.audit_records_to_insert += 1
        observation_uuid = str(uuid5(NAMESPACE_URL, f"{report.source_checksum}|physical-observation|{source_audit.audit_identifier}"))
        if _text(source_audit.values.get("Press/Machine #")).isdigit() and observation_uuid not in existing_observation_ids:
            report.observations_to_insert += 1
    updates: dict[int, dict[str, Any]] = {}
    for eoat_id, source_rows in grouped.items():
        # Use the most recent physical audit only to fill fields that are
        # presently null.  Existing user-entered or newer values win.
        latest = latest_physical_audit(
            [
                {
                    "audit_identifier": row.audit_identifier,
                    "audit_date": _audit_date(row.values.get("Audit Date")),
                    "source_row_number": row.row_number,
                    "details_json": row.values,
                }
                for row in source_rows
            ]
        )
        if latest is None:
            continue
        source_row = next(row for row in source_rows if row.audit_identifier == latest.audit_identifier)
        target = next(item for row, item in matches if row is source_row)
        change = _nullable_profile_updates(target, source_row)
        if change:
            updates[eoat_id] = change
            report.eoats_to_update += 1
            report.fields_to_update += len(change)
    return report, matches, updates


def execute_backfill(
    source_workbook: str | Path,
    *,
    dry_run: bool = True,
    session_factory: Callable[[], Any] | None = None,
) -> BackfillReport:
    if not dry_run and os.getenv("EOAT_ATLAS_ENVIRONMENT", "development") not in {"development", "staging_local"}:
        raise RuntimeError("Historical audit backfill is restricted to development or staging_local.")
    factory = session_factory or create_session_factory(migration=True)
    with factory() as session:
        report, matches, updates = plan_backfill(source_workbook, session)
        report.dry_run = dry_run
        if dry_run:
            return report
        # Planning performs read queries, which may have opened an implicit
        # transaction.  Close it before the single mutation transaction.
        session.rollback()
        with session.begin():
            batch = db.ImportBatch(
                batch_uuid=str(uuid4()),
                batch_name="historical-physical-audit-backfill",
                source_type="excel_workbook_backfill",
                source_file_name=report.source_workbook,
                source_file_checksum=report.source_checksum,
                started_at=datetime.now(timezone.utc),
                status="RUNNING",
                dry_run=False,
                records_discovered=report.rows_considered,
                notes="Idempotent physical-audit provenance repair",
            )
            session.add(batch)
            session.flush()
            audits_by_identifier = {
                item.audit_identifier: item for item in session.scalars(select(db.AuditRecord))
            }
            observations = set(session.scalars(select(db.EOATLocationObservation.observation_uuid)))
            machines = {item.machine_number: item for item in session.scalars(select(db.Machine))}
            for source_audit, eoat in matches:
                audit = audits_by_identifier.get(source_audit.audit_identifier)
                if audit is None:
                    audit = db.AuditRecord(
                        audit_identifier=source_audit.audit_identifier,
                        eoat_id=eoat.id,
                        machine_id=machines.get(_text(source_audit.values.get("Press/Machine #"))).id if _text(source_audit.values.get("Press/Machine #")) in machines else None,
                        audit_date=_audit_date(source_audit.values.get("Audit Date")),
                        source_sheet="EOAT Inventory",
                        source_row_number=source_audit.row_number,
                        details_json=source_audit.values,
                        notes=_text(source_audit.values.get("Notes")) or None,
                        source_system="historical_audit_backfill",
                        source_import_batch_id=batch.id,
                    )
                    session.add(audit)
                    session.flush()
                    audits_by_identifier[audit.audit_identifier] = audit
                observation_uuid = str(uuid5(NAMESPACE_URL, f"{report.source_checksum}|physical-observation|{source_audit.audit_identifier}"))
                machine = machines.get(_text(source_audit.values.get("Press/Machine #")))
                observed_at = _audit_date(source_audit.values.get("Audit Date"))
                if machine is not None and observed_at is not None and observation_uuid not in observations:
                    session.add(
                        db.EOATLocationObservation(
                            observation_uuid=observation_uuid,
                            eoat_id=eoat.id,
                            state="INSTALLED",
                            machine_id=machine.id,
                            observed_on=observed_at.date(),
                            observation_precision="DATE",
                            source_type="PHYSICAL_AUDIT",
                            source_audit_record_id=audit.id,
                            source_import_batch_id=batch.id,
                            source_workbook=report.source_workbook,
                            source_worksheet="EOAT Inventory",
                            source_row_number=source_audit.row_number,
                            original_source_wording=f"Physical audit {source_audit.audit_identifier} observed on Machine {machine.machine_number}",
                            confidence="PHYSICAL_AUDIT_VERIFIED" if source_audit.values.get("Physical Audit Verified") == "Yes" else "PHYSICAL_AUDIT_OBSERVED",
                            resolution_status="CURRENT",
                            is_authoritative=True,
                        )
                    )
                    observations.add(observation_uuid)
            for eoat_id, values in updates.items():
                target = session.get(db.EOAT, eoat_id)
                if target is None:
                    continue
                for field_name, value in values.items():
                    if getattr(target, field_name) is None:
                        setattr(target, field_name, value)
            batch.status = "COMPLETED"
            batch.completed_at = datetime.now(timezone.utc)
            batch.records_imported = report.audit_records_to_insert + report.observations_to_insert + report.fields_to_update
        report.executed = True
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill physical-audit provenance into EOAT Atlas MySQL.")
    parser.add_argument("--source-workbook", required=True)
    parser.add_argument("--execute", action="store_true", help="Write only to development/staging_local; otherwise dry-run.")
    args = parser.parse_args()
    report = execute_backfill(args.source_workbook, dry_run=not args.execute)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
