"""Read-only canonical-catalog mapping for the governed press-capacity importer.

This module consumes a sanitized catalog manifest, not a database connection.
It is deliberately a planning layer: no function here creates a session,
executes SQL, or mutates a workbook.  A separate, explicitly authorized
execution step may consume only clean exact-match updates later.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tools.migration.press_capacity_import import (
    CapacitySourceRow,
    _normalise_machine,
    read_press_capacity_workbook,
)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or not str(value).strip():
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"Invalid catalog capacity: {value!r}") from error
    if parsed <= 0:
        raise ValueError(f"Catalog capacity must be positive: {value!r}")
    return parsed


@dataclass(frozen=True)
class CanonicalMachine:
    """Sanitized canonical machine record from a governed catalog manifest."""

    identity: str
    machine_number: str
    plant_code: str
    area: str | None
    machine_name: str | None
    manufacturer: str | None
    model: str | None
    is_active: bool
    status: str | None
    row_version: int | None
    press_capacity_tons: Decimal | None
    governed_aliases: tuple[str, ...] = ()

    @property
    def normalized_machine_number(self) -> str | None:
        return _normalise_machine(self.machine_number)


@dataclass(frozen=True)
class CatalogMappingDecision:
    source_sheet: str
    source_row: int
    source_press_heading: str
    parsed_machine_number: str
    parsed_tonnage: Decimal | None
    tonnage_source: str
    canonical_identity: str | None
    canonical_machine_number: str | None
    plant_code: str | None
    area: str | None
    mapping_method: str
    verification_class: str
    existing_capacity_tons: Decimal | None
    proposed_capacity_tons: Decimal | None
    capacity_unit: str
    proposed_action: str
    reason: str | None = None


@dataclass
class CatalogCapacityDryRun:
    source_file_name: str
    source_sha256: str
    catalog_file_name: str
    catalog_sha256: str
    catalog_source_type: str
    retrieval_timestamp_utc: str | None
    production_release: dict[str, Any]
    production_schema: dict[str, Any]
    data_revision: str | None
    plant_filter_rule: str | None
    catalog_record_count: int
    plant_record_count: int
    active_plant_record_count: int
    inactive_plant_record_count: int
    mappings: list[CatalogMappingDecision] = field(default_factory=list)
    invalid_source_rows: list[dict[str, Any]] = field(default_factory=list)
    canonical_machines_absent_from_workbook: list[dict[str, str]] = field(default_factory=list)
    duplicate_machine_numbers: dict[str, list[str]] = field(default_factory=dict)
    alias_collisions: dict[str, list[str]] = field(default_factory=dict)
    source_tonnage_conflicts: dict[str, list[str]] = field(default_factory=dict)
    existing_capacity_conflicts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for mapping in payload["mappings"]:
            for name in ("parsed_tonnage", "existing_capacity_tons", "proposed_capacity_tons"):
                if mapping[name] is not None:
                    mapping[name] = str(mapping[name])
        return payload

    @property
    def proposed_counts(self) -> dict[str, int]:
        counts: defaultdict[str, int] = defaultdict(int)
        for mapping in self.mappings:
            counts[mapping.proposed_action] += 1
        return {action: counts[action] for action in ("INSERT", "UPDATE", "UNCHANGED", "REJECT", "REVIEW_REQUIRED")}


def load_canonical_catalog_manifest(path: str | Path) -> tuple[dict[str, Any], list[CanonicalMachine]]:
    """Load only the allow-listed fields from a sanitized catalog manifest."""
    source = Path(path).resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    payload = data.get("payload", data)
    if payload.get("manifest_type") != "eoat_atlas_canonical_plant4_machine_catalog":
        raise ValueError("Unsupported canonical catalog manifest type.")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("Canonical catalog manifest has no records.")
    machines: list[CanonicalMachine] = []
    identities: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Canonical catalog manifest contains a non-object record.")
        identity = str(record.get("api_identity") or record.get("canonical_identity") or "").strip()
        number = str(record.get("machine_number") or "").strip()
        plant = str(record.get("plant_code") or "").strip()
        if not identity or not number or not plant:
            raise ValueError("Canonical catalog record is missing identity, machine_number, or plant_code.")
        if identity in identities:
            raise ValueError(f"Canonical catalog contains a duplicate stable identity: {identity}.")
        identities.add(identity)
        aliases = record.get("governed_aliases") or []
        if not isinstance(aliases, list) or any(not isinstance(item, str) or not item.strip() for item in aliases):
            raise ValueError(f"Canonical catalog aliases are invalid for {identity}.")
        machines.append(
            CanonicalMachine(
                identity=identity,
                machine_number=number,
                plant_code=plant,
                area=str(record["area"]).strip() if record.get("area") is not None else None,
                machine_name=str(record["machine_name"]).strip() if record.get("machine_name") is not None else None,
                manufacturer=str(record["manufacturer"]).strip() if record.get("manufacturer") is not None else None,
                model=str(record["model"]).strip() if record.get("model") is not None else None,
                is_active=bool(record.get("is_active")),
                status=str(record["status"]).strip() if record.get("status") is not None else None,
                row_version=int(record["row_version"]) if record.get("row_version") is not None else None,
                press_capacity_tons=_decimal_or_none(record.get("press_capacity_tons")),
                governed_aliases=tuple(item.strip() for item in aliases),
            )
        )
    return payload, machines


def _source_groups(rows: list[CapacitySourceRow]) -> tuple[dict[str, list[CapacitySourceRow]], list[dict[str, Any]]]:
    grouped: defaultdict[str, list[CapacitySourceRow]] = defaultdict(list)
    invalid: list[dict[str, Any]] = []
    for row in rows:
        if row.issue:
            invalid.append({"sheet": row.sheet, "row_number": row.row_number, "issue": row.issue})
            continue
        for number in row.machine_numbers:
            grouped[number].append(row)
    return dict(grouped), invalid


def _decision(
    row: CapacitySourceRow,
    number: str,
    *,
    candidate: CanonicalMachine | None,
    method: str,
    verification: str,
    action: str,
    reason: str | None = None,
) -> CatalogMappingDecision:
    heading = str(row.raw_values.get("Machine No.") or "")
    existing = candidate.press_capacity_tons if candidate else None
    proposed = row.tonnage if candidate and action in {"UPDATE", "UNCHANGED", "REVIEW_REQUIRED"} else None
    return CatalogMappingDecision(
        source_sheet=row.sheet,
        source_row=row.row_number,
        source_press_heading=heading,
        parsed_machine_number=number,
        parsed_tonnage=row.tonnage,
        tonnage_source=row.capacity_source,
        canonical_identity=candidate.identity if candidate else None,
        canonical_machine_number=candidate.machine_number if candidate else None,
        plant_code=candidate.plant_code if candidate else None,
        area=candidate.area if candidate else None,
        mapping_method=method,
        verification_class=verification,
        existing_capacity_tons=existing,
        proposed_capacity_tons=proposed,
        capacity_unit="US_TONS",
        proposed_action=action,
        reason=reason,
    )


def plan_catalog_capacity_dry_run(
    source_workbook: str | Path,
    catalog_manifest: str | Path,
    *,
    plant_code: str,
    master_press_list: str | Path | None = None,
) -> CatalogCapacityDryRun:
    """Map capacity headings to a catalog without database or workbook mutation."""
    source = Path(source_workbook).resolve()
    catalog = Path(catalog_manifest).resolve()
    metadata, machines = load_canonical_catalog_manifest(catalog)
    rows = read_press_capacity_workbook(source, master_press_list=master_press_list)
    grouped, invalid_rows = _source_groups(rows)
    plant_machines = [machine for machine in machines if machine.plant_code == plant_code]
    active_plant = [machine for machine in plant_machines if machine.is_active]
    inactive_plant = [machine for machine in plant_machines if not machine.is_active]

    number_index: defaultdict[str, list[CanonicalMachine]] = defaultdict(list)
    alias_index: defaultdict[str, list[CanonicalMachine]] = defaultdict(list)
    for machine in active_plant:
        normalized = machine.normalized_machine_number
        if normalized:
            number_index[normalized].append(machine)
        for alias in machine.governed_aliases:
            normalized_alias = _normalise_machine(alias)
            if normalized_alias:
                alias_index[normalized_alias].append(machine)

    duplicates = {
        number: [machine.identity for machine in candidates]
        for number, candidates in number_index.items()
        if len(candidates) > 1
    }
    alias_collisions = {
        alias: [machine.identity for machine in candidates]
        for alias, candidates in alias_index.items()
        if len(candidates) > 1
    }
    report = CatalogCapacityDryRun(
        source_file_name=source.name,
        source_sha256=_digest(source),
        catalog_file_name=catalog.name,
        catalog_sha256=_digest(catalog),
        catalog_source_type=str(metadata.get("source_type") or "UNKNOWN"),
        retrieval_timestamp_utc=metadata.get("retrieval_timestamp_utc"),
        production_release=dict(metadata.get("production_release") or {}),
        production_schema=dict(metadata.get("production_schema") or {}),
        data_revision=metadata.get("data_revision"),
        plant_filter_rule=metadata.get("plant4_filter_rule"),
        catalog_record_count=len(machines),
        plant_record_count=len(plant_machines),
        active_plant_record_count=len(active_plant),
        inactive_plant_record_count=len(inactive_plant),
        invalid_source_rows=invalid_rows,
        duplicate_machine_numbers=duplicates,
        alias_collisions=alias_collisions,
    )
    selected_identities: set[str] = set()
    cross_plant_numbers = {machine.normalized_machine_number for machine in machines if machine.plant_code != plant_code and machine.is_active}
    for number, source_rows in sorted(grouped.items(), key=lambda item: int(item[0])):
        values = {row.tonnage for row in source_rows if row.tonnage is not None}
        representative = min(source_rows, key=lambda item: (item.sheet, item.row_number))
        if len(values) != 1:
            report.source_tonnage_conflicts[number] = sorted(str(value) for value in values)
            report.mappings.append(_decision(representative, number, candidate=None, method="NONE", verification="SOURCE_CONFLICT", action="REJECT", reason="CONFLICTING_SOURCE_CAPACITY_VALUES"))
            continue
        candidates = number_index.get(number, [])
        if len(candidates) > 1:
            report.mappings.append(_decision(representative, number, candidate=None, method="EXACT_CANONICAL_MACHINE_NUMBER", verification="AMBIGUOUS", action="REJECT", reason="DUPLICATE_ACTIVE_CANONICAL_MACHINE_NUMBER"))
            continue
        if len(candidates) == 1:
            candidate = candidates[0]
            selected_identities.add(candidate.identity)
            method = "EXACT_CANONICAL_MACHINE_NUMBER" if candidate.machine_number.strip() == number else "DETERMINISTIC_NORMALIZED_MACHINE_NUMBER"
            if candidate.press_capacity_tons is None:
                report.mappings.append(_decision(representative, number, candidate=candidate, method=method, verification="CANONICAL_MATCH", action="UPDATE"))
            elif candidate.press_capacity_tons == next(iter(values)):
                report.mappings.append(_decision(representative, number, candidate=candidate, method=method, verification="CANONICAL_MATCH", action="UNCHANGED"))
            else:
                report.existing_capacity_conflicts.append(number)
                report.mappings.append(_decision(representative, number, candidate=candidate, method=method, verification="EXISTING_CAPACITY_CONFLICT", action="REVIEW_REQUIRED", reason="CATALOG_CAPACITY_DIFFERS_FROM_SOURCE"))
            continue
        alias_candidates = alias_index.get(number, [])
        if len(alias_candidates) > 1:
            report.mappings.append(_decision(representative, number, candidate=None, method="EXACT_GOVERNED_ALIAS", verification="AMBIGUOUS", action="REJECT", reason="GOVERNED_ALIAS_COLLISION"))
            continue
        if len(alias_candidates) == 1:
            candidate = alias_candidates[0]
            selected_identities.add(candidate.identity)
            if candidate.press_capacity_tons is None:
                report.mappings.append(_decision(representative, number, candidate=candidate, method="EXACT_GOVERNED_ALIAS", verification="CANONICAL_MATCH", action="UPDATE"))
            elif candidate.press_capacity_tons == next(iter(values)):
                report.mappings.append(_decision(representative, number, candidate=candidate, method="EXACT_GOVERNED_ALIAS", verification="CANONICAL_MATCH", action="UNCHANGED"))
            else:
                report.existing_capacity_conflicts.append(number)
                report.mappings.append(_decision(representative, number, candidate=candidate, method="EXACT_GOVERNED_ALIAS", verification="EXISTING_CAPACITY_CONFLICT", action="REVIEW_REQUIRED", reason="CATALOG_CAPACITY_DIFFERS_FROM_SOURCE"))
            continue
        inactive = [machine for machine in inactive_plant if machine.normalized_machine_number == number or number in {_normalise_machine(alias) for alias in machine.governed_aliases}]
        if inactive:
            report.mappings.append(_decision(representative, number, candidate=inactive[0], method="EXACT_CANONICAL_MACHINE_NUMBER", verification="INACTIVE_MACHINE", action="REVIEW_REQUIRED", reason="ONLY_INACTIVE_CANONICAL_MACHINE_MATCH"))
        elif number in cross_plant_numbers:
            report.mappings.append(_decision(representative, number, candidate=None, method="NONE", verification="UNMAPPED", action="REJECT", reason="CROSS_PLANT_CANONICAL_COLLISION"))
        else:
            report.mappings.append(_decision(representative, number, candidate=None, method="NONE", verification="UNMAPPED", action="REVIEW_REQUIRED", reason="NO_CANONICAL_MACHINE_MATCH"))

    report.canonical_machines_absent_from_workbook = [
        {"identity": machine.identity, "machine_number": machine.machine_number}
        for machine in sorted(active_plant, key=lambda item: (item.normalized_machine_number or item.machine_number, item.identity))
        if machine.identity not in selected_identities
    ]
    return report


def write_immutable_catalog_dry_run(report: CatalogCapacityDryRun, directory: str | Path) -> Path:
    """Write an immutable machine-readable report with no raw workbook rows."""
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"catalog-capacity-dry-run-{report.source_sha256[:12]}-{report.catalog_sha256[:12]}.json"
    with target.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report.to_dict(), indent=2, sort_keys=True, default=str) + "\n")
    return target
