from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from core.audit_compatibility import (
    machine_from_audit_row,
    normalize_entry_type,
    normalize_machine_token,
    part_number_from_row,
    text_value,
)
from core.audit_constants import (
    AUTOFILLED_COMPATIBILITY_METADATA_FIELDS,
    ENTRY_TYPE_AUDITED,
    ENTRY_TYPE_COMPATIBLE,
    ENTRY_TYPE_FIELD,
    SOURCE_AUDIT_ID_FIELD,
)


@dataclass(frozen=True)
class SourceAuditLookup:
    source_audit: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    warning_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MachineRelationshipSummary:
    machine_number: str
    physical_audits: list[dict[str, Any]] = field(default_factory=list)
    compatibility_entries: list[dict[str, Any]] = field(default_factory=list)
    linked_compatibility_entries: list[dict[str, Any]] = field(default_factory=list)
    warnings: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_physical_audit_row(row: dict[str, Any]) -> bool:
    return normalize_entry_type(row.get(ENTRY_TYPE_FIELD)) == ENTRY_TYPE_AUDITED


def is_compatibility_row(row: dict[str, Any]) -> bool:
    return normalize_entry_type(row.get(ENTRY_TYPE_FIELD)) == ENTRY_TYPE_COMPATIBLE


def physical_audits_for_machine(rows: Iterable[dict[str, Any]], machine_number: str) -> list[dict[str, Any]]:
    target = normalize_machine_token(machine_number)
    return [
        dict(row)
        for row in rows
        if is_physical_audit_row(row) and normalize_machine_token(machine_from_audit_row(row)) == target
    ]


def compatibility_entries_for_machine(rows: Iterable[dict[str, Any]], machine_number: str) -> list[dict[str, Any]]:
    target = normalize_machine_token(machine_number)
    return [
        dict(row)
        for row in rows
        if is_compatibility_row(row) and normalize_machine_token(machine_from_audit_row(row)) == target
    ]


def compatibility_entries_for_source_audit(
    rows: Iterable[dict[str, Any]], source_audit_id: str
) -> list[dict[str, Any]]:
    source_id = text_value(source_audit_id)
    if not source_id:
        return []
    return [
        dict(row)
        for row in rows
        if is_compatibility_row(row) and text_value(row.get(SOURCE_AUDIT_ID_FIELD)) == source_id
    ]


def source_audit_for_compatibility_row(
    rows: Iterable[dict[str, Any]],
    compatibility_row: dict[str, Any],
) -> SourceAuditLookup:
    if not is_compatibility_row(compatibility_row):
        return SourceAuditLookup(
            warnings=("Row is not a compatibility row.",), warning_codes=("not_compatibility_row",)
        )
    source_id = text_value(compatibility_row.get(SOURCE_AUDIT_ID_FIELD))
    audit_id = text_value(compatibility_row.get("Audit ID")) or "compatibility row"
    if not source_id:
        return SourceAuditLookup(
            warnings=(f"Compatible row {audit_id} is missing Source Audit ID.",),
            warning_codes=("missing_source_metadata",),
        )
    all_rows = list(rows)
    source = next((row for row in all_rows if text_value(row.get("Audit ID")) == source_id), None)
    if source is None:
        return SourceAuditLookup(
            warnings=(f"Compatible row {audit_id} references missing source audit {source_id}.",),
            warning_codes=("source_not_found",),
        )
    if not is_physical_audit_row(source):
        return SourceAuditLookup(
            source_audit=dict(source),
            warnings=(
                f"Compatible row {audit_id} references {source_id}, but that row is not a physical audit source.",
            ),
            warning_codes=("source_not_physical",),
        )
    return SourceAuditLookup(source_audit=dict(source))


def relationship_summary_for_machine(rows: Iterable[dict[str, Any]], machine_number: str) -> MachineRelationshipSummary:
    row_list = [dict(row) for row in rows]
    machine = normalize_machine_token(machine_number)
    physical = physical_audits_for_machine(row_list, machine)
    compatible = compatibility_entries_for_machine(row_list, machine)
    linked: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_linked: set[tuple[str, str]] = set()
    for row in physical:
        source_id = text_value(row.get("Audit ID"))
        for linked_row in compatibility_entries_for_source_audit(row_list, source_id):
            key = (text_value(linked_row.get("Audit ID")), normalize_machine_token(machine_from_audit_row(linked_row)))
            if key in seen_linked:
                continue
            seen_linked.add(key)
            linked.append(dict(linked_row))
    for row in compatible:
        lookup = source_audit_for_compatibility_row(row_list, row)
        warnings.extend(lookup.warnings)
    metrics = {
        "physical_audit_count": len(physical),
        "compatibility_entry_count": len(compatible),
        "linked_compatibility_count": len(linked),
        "verified_physical_count": len(physical),
        "physical_verification_excludes_compatibility": True,
        "missing_source_metadata_count": sum(1 for warning in warnings if "missing Source Audit ID" in warning),
        "tools": sorted(
            {_part for _part in (part_number_from_row(row) for row in [*physical, *compatible]) if _part},
            key=str.casefold,
        ),
    }
    return MachineRelationshipSummary(
        machine_number=machine,
        physical_audits=physical,
        compatibility_entries=compatible,
        linked_compatibility_entries=sorted(
            linked,
            key=lambda row: (
                normalize_machine_token(machine_from_audit_row(row)),
                text_value(row.get("Audit ID")).casefold(),
            ),
        ),
        warnings=tuple(dict.fromkeys(warnings)),
        metrics=metrics,
    )


def compatibility_metadata_is_blank_or_system(row: dict[str, Any]) -> bool:
    return all(not text_value(row.get(field)) for field in AUTOFILLED_COMPATIBILITY_METADATA_FIELDS)


__all__ = [
    "MachineRelationshipSummary",
    "SourceAuditLookup",
    "compatibility_entries_for_machine",
    "compatibility_entries_for_source_audit",
    "compatibility_metadata_is_blank_or_system",
    "is_compatibility_row",
    "is_physical_audit_row",
    "physical_audits_for_machine",
    "relationship_summary_for_machine",
    "source_audit_for_compatibility_row",
]
