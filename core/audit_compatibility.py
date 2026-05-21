from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .audit_by_press import refresh_audit_by_press_view
from .audit_constants import (
    COMPATIBILITY_SOURCE_FIELD,
    COMPATIBILITY_SOURCE_PRESS_CAPACITY,
    ENTRY_TYPE_AUDITED,
    ENTRY_TYPE_COMPATIBLE,
    ENTRY_TYPE_FIELD,
    SOURCE_AUDIT_ID_FIELD,
)
from .audit_entries import _ensure_inventory_headers
from .paths import get_press_capacity_file, resolve_project_paths
from .result import ToolResult
from .safe_files import backup_file
from .tool_fields import TOOL_FIELD
from .workbook_io import next_empty_row, row_dicts, worksheet_headers, write_row_by_headers
from .workbook_schema import get_expected_headers

CAPACITY_SHEET_NAME = "Capacity"
RELATIONSHIP_KEY_SEPARATOR = "\u241f"
PART_NUMBER_FIELDS = ["NGW Part Number", "Selected Part Number", TOOL_FIELD, "Part Number"]
PART_DESCRIPTION_FIELDS = ["NGW Part Description", "Selected Part Description", "Part Name/Description", "Part Family"]
MASTER_MACHINE_FIELDS = ["Press/Machine #", "Machine No.", "Machine Number", "Press"]
CONFLICT_FIELDS = ["NGW Part Description", "Selected Part Description", "Part Name/Description", "EOAT Type"]


@dataclass(frozen=True)
class RequiredRelationship:
    machine_no: str
    part_number: str
    part_description: str = ""
    source_row: int = 0

    @property
    def key(self) -> tuple[str, str]:
        return relationship_key(self.machine_no, self.part_number)


@dataclass(frozen=True)
class SourceAuditOption:
    audit_id: str
    label: str
    row: dict[str, Any]


@dataclass(frozen=True)
class CompatibilityCandidate:
    machine_no: str
    part_number: str
    part_description: str
    existing_status: str
    recommended_action: str
    existing_audit_ids: tuple[str, ...] = ()

    @property
    def can_create(self) -> bool:
        return self.recommended_action == "Create Compatible Entry"


@dataclass
class CompatibilityCandidateResult:
    source: SourceAuditOption | None
    candidates: list[CompatibilityCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class SyncResult:
    source_audit_id: str
    updated_count: int = 0
    skipped_count: int = 0
    missing_source: bool = False
    warning_messages: list[str] = field(default_factory=list)
    backup_path: str | None = None


PROTECTED_COMPATIBILITY_SYNC_FIELDS = {
    "Audit ID",
    "Audit Date",
    "Auditor",
    "Plant/Area",
    "Press/Machine #",
    "Machine No.",
    "Machine Number",
    "Press",
    "Robot Type",
    "Robot Model/Controller",
    ENTRY_TYPE_FIELD,
    SOURCE_AUDIT_ID_FIELD,
    COMPATIBILITY_SOURCE_FIELD,
}


PROTECTED_COMPATIBILITY_SYNC_NAME_PARTS = (
    "created",
    "timestamp",
    "row id",
    "internal",
    "override",
)


def text_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.upper() == "N/A" else text


def normalize_entry_type(value: Any) -> str:
    text = text_value(value).lower()
    if text == ENTRY_TYPE_COMPATIBLE.lower():
        return ENTRY_TYPE_COMPATIBLE
    return ENTRY_TYPE_AUDITED


def is_unknown_entry_type(row: dict[str, Any]) -> bool:
    return not text_value(row.get(ENTRY_TYPE_FIELD))


def normalize_machine_token(value: Any) -> str:
    text = text_value(value)
    if not text:
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    numeric = re.fullmatch(r"\d+(?:\.0+)?", text)
    if numeric:
        return str(int(float(text)))
    prefixed = re.fullmatch(r"(?:press|machine|p|m)\s*[-#]?\s*(\d+)", text, flags=re.IGNORECASE)
    if prefixed:
        return prefixed.group(1)
    return text


def parse_machine_tokens(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, int):
        return [str(value)] if value > 0 else []
    if isinstance(value, float):
        return [str(int(value))] if value.is_integer() and value > 0 else [str(value).strip()]
    tokens: list[str] = []
    for raw_token in str(value).split(","):
        token = normalize_machine_token(raw_token)
        if token:
            tokens.append(token)
    return sort_machine_tokens(tokens)


def sort_machine_tokens(tokens: list[str]) -> list[str]:
    unique = list(dict.fromkeys(token for token in tokens if token))

    def key(token: str) -> tuple[int, int | str]:
        return (0, int(token)) if token.isdigit() else (1, token.lower())

    return sorted(unique, key=key)


def relationship_key(machine_no: Any, part_number: Any) -> tuple[str, str]:
    return normalize_machine_token(machine_no), text_value(part_number).upper()


def relationship_label(machine_no: Any, part_number: Any) -> str:
    machine, part = relationship_key(machine_no, part_number)
    return f"{machine}{RELATIONSHIP_KEY_SEPARATOR}{part}"


def part_number_from_row(row: dict[str, Any]) -> str:
    for field_name in PART_NUMBER_FIELDS:
        value = text_value(row.get(field_name))
        if value:
            return value
    return ""


def part_description_from_row(row: dict[str, Any]) -> str:
    for field_name in PART_DESCRIPTION_FIELDS:
        value = text_value(row.get(field_name))
        if value:
            return value
    return ""


def machine_from_audit_row(row: dict[str, Any]) -> str:
    for field_name in MASTER_MACHINE_FIELDS:
        tokens = parse_machine_tokens(row.get(field_name))
        if tokens:
            return tokens[0]
    return ""


def machine_sort_key(value: Any) -> tuple[int, int | str, str]:
    tokens = parse_machine_tokens(value)
    first = tokens[0] if tokens else ""
    if first.isdigit():
        return (0, int(first), first)
    return (1, first.lower(), first)


def audit_row_machine_sort_key(row: dict[str, Any]) -> tuple[int, int | str, str]:
    for field_name in MASTER_MACHINE_FIELDS:
        tokens = parse_machine_tokens(row.get(field_name))
        if tokens:
            first = tokens[0]
            if first.isdigit():
                return (0, int(first), first)
            return (1, first.lower(), first)
    return (1, "", "")


def audit_option_label(row: dict[str, Any]) -> str:
    audit_id = text_value(row.get("Audit ID"))
    machine = machine_from_audit_row(row)
    machine_label = f"Machine {machine}" if machine else ""
    part_number = part_number_from_row(row)
    description = part_description_from_row(row)
    entry_type = normalize_entry_type(row.get(ENTRY_TYPE_FIELD))
    return " | ".join(piece for piece in [audit_id, machine_label, part_number, description, entry_type] if piece)


def find_capacity_file(project_root_or_path: str | Path) -> Path:
    path = Path(project_root_or_path)
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        return path
    return get_press_capacity_file(path)


def list_audited_source_options(project_root_or_master_path: str | Path) -> list[SourceAuditOption]:
    master_path = _master_path(project_root_or_master_path)
    options: list[SourceAuditOption] = []
    for row in row_dicts(master_path, "EOAT Inventory"):
        if normalize_entry_type(row.get(ENTRY_TYPE_FIELD)) != ENTRY_TYPE_AUDITED:
            continue
        audit_id = text_value(row.get("Audit ID"))
        if not audit_id:
            continue
        options.append(SourceAuditOption(audit_id=audit_id, label=audit_option_label(row), row=row))
    return sorted(options, key=lambda option: (audit_row_machine_sort_key(option.row), option.audit_id.lower()))


def list_audit_options(project_root_or_master_path: str | Path) -> list[SourceAuditOption]:
    master_path = _master_path(project_root_or_master_path)
    options: list[SourceAuditOption] = []
    for row in row_dicts(master_path, "EOAT Inventory"):
        audit_id = text_value(row.get("Audit ID"))
        if not audit_id:
            continue
        options.append(SourceAuditOption(audit_id=audit_id, label=audit_option_label(row), row=row))
    return sorted(options, key=lambda option: (audit_row_machine_sort_key(option.row), option.audit_id.lower()))


def build_compatibility_candidates(
    project_root_or_master_path: str | Path,
    source_audit_id: str,
    press_capacity_path: str | Path | None = None,
) -> CompatibilityCandidateResult:
    master_path = _master_path(project_root_or_master_path)
    capacity_path = Path(press_capacity_path) if press_capacity_path else find_capacity_file(project_root_or_master_path)
    inventory = row_dicts(master_path, "EOAT Inventory")
    source_row = next((row for row in inventory if text_value(row.get("Audit ID")) == source_audit_id), None)
    if not source_row:
        return CompatibilityCandidateResult(source=None, errors=[f"Source audit ID not found: {source_audit_id}"])
    if normalize_entry_type(source_row.get(ENTRY_TYPE_FIELD)) != ENTRY_TYPE_AUDITED:
        return CompatibilityCandidateResult(source=None, errors=[f"Source audit ID is not an audited row: {source_audit_id}"])

    source_option = SourceAuditOption(
        audit_id=source_audit_id,
        label=" | ".join(
            piece
            for piece in [
                source_audit_id,
                machine_from_audit_row(source_row),
                part_number_from_row(source_row),
                part_description_from_row(source_row),
                text_value(source_row.get("EOAT Type")),
            ]
            if piece
        ),
        row=source_row,
    )
    part_number = part_number_from_row(source_row)
    if not part_number:
        return CompatibilityCandidateResult(source=source_option, errors=["Source audit row does not have an NGW Part Number / Tool #."])

    required, warnings = load_required_relationships(capacity_path)
    source_part_key = text_value(part_number).upper()
    matching_required = [relationship for relationship in required if relationship.key[1] == source_part_key]
    if not matching_required:
        return CompatibilityCandidateResult(
            source=source_option,
            warnings=[*warnings, f"No Press Capacity relationships found for part {part_number}."],
        )

    by_key = summarize_master_relationships(inventory)
    candidates: list[CompatibilityCandidate] = []
    for relationship in matching_required:
        status = by_key.get(relationship.key, [])
        entry_types = {item["entry_type"] for item in status}
        audit_ids = tuple(text_value(item["row"].get("Audit ID")) for item in status if text_value(item["row"].get("Audit ID")))
        conflict = relationship_has_conflict(status, relationship)
        if conflict:
            existing_status = "Conflict"
            action = "Conflict / Review Needed"
        elif ENTRY_TYPE_AUDITED in entry_types:
            existing_status = "Audited"
            action = "Already Audited"
        elif ENTRY_TYPE_COMPATIBLE in entry_types:
            compatible_source_ids = {
                text_value(item["row"].get(SOURCE_AUDIT_ID_FIELD))
                for item in status
                if item["entry_type"] == ENTRY_TYPE_COMPATIBLE
            }
            existing_status = "Compatible"
            if compatible_source_ids and compatible_source_ids <= {source_audit_id}:
                action = "Already Compatible - Linked to this source"
            else:
                action = "Already Compatible - Different Source / Review Needed"
        elif status:
            existing_status = ", ".join(sorted(entry_types))
            action = "Conflict / Review Needed"
        else:
            existing_status = ""
            action = "Create Compatible Entry"
        candidates.append(
            CompatibilityCandidate(
                machine_no=relationship.machine_no,
                part_number=relationship.part_number,
                part_description=relationship.part_description,
                existing_status=existing_status,
                recommended_action=action,
                existing_audit_ids=audit_ids,
            )
        )
    return CompatibilityCandidateResult(source=source_option, candidates=sorted(candidates, key=lambda item: _machine_sort_key(item.machine_no)), warnings=warnings)


def sync_compatible_rows_from_source(master_audit_path: str | Path, source_audit_id: str) -> SyncResult:
    result = SyncResult(source_audit_id=str(source_audit_id))
    master_path = _master_path(master_audit_path)
    if not master_path.exists():
        result.missing_source = True
        result.warning_messages.append(f"Master workbook is missing: {master_path}")
        return result

    workbook = None
    try:
        workbook = load_workbook(master_path)
        if "EOAT Inventory" not in workbook.sheetnames:
            result.missing_source = True
            result.warning_messages.append("EOAT Inventory sheet is missing.")
            return result
        ws = workbook["EOAT Inventory"]
        _ensure_inventory_headers(ws, get_expected_headers("EOAT Inventory"))
        headers = worksheet_headers(ws)
        source_row_number = _find_audit_row_number(ws, headers, source_audit_id)
        if source_row_number is None:
            result.missing_source = True
            return result

        source_row = _worksheet_row_dict(ws, headers, source_row_number)
        if normalize_entry_type(source_row.get(ENTRY_TYPE_FIELD)) != ENTRY_TYPE_AUDITED:
            result.skipped_count += 1
            result.warning_messages.append(f"Source audit ID is not an audited row: {source_audit_id}")
            return result

        linked_rows: list[int] = []
        if SOURCE_AUDIT_ID_FIELD not in headers or ENTRY_TYPE_FIELD not in headers:
            return result
        source_col = headers.index(SOURCE_AUDIT_ID_FIELD) + 1
        entry_type_col = headers.index(ENTRY_TYPE_FIELD) + 1
        for row_number in range(2, ws.max_row + 1):
            if row_number == source_row_number:
                continue
            if text_value(ws.cell(row=row_number, column=source_col).value) != str(source_audit_id):
                continue
            entry_type = normalize_entry_type(ws.cell(row=row_number, column=entry_type_col).value)
            if entry_type == ENTRY_TYPE_COMPATIBLE:
                linked_rows.append(row_number)
            else:
                result.skipped_count += 1

        if not linked_rows:
            return result

        result.backup_path = str(backup_file(master_path, master_path.parent / "_backups"))
        copy_fields = [header for header in headers if _can_sync_compatibility_field(header)]
        for row_number in linked_rows:
            for header in copy_fields:
                ws.cell(row=row_number, column=headers.index(header) + 1).value = source_row.get(header)
            result.updated_count += 1
        refresh_audit_by_press_view(workbook)
        workbook.save(master_path)
        return result
    except Exception as exc:
        result.warning_messages.append(f"Could not update linked compatibility rows: {exc}")
        return result
    finally:
        if workbook is not None:
            workbook.close()


def create_compatibility_entries(
    project_root: str | Path,
    source_audit_id: str,
    machine_numbers: list[str],
    press_capacity_path: str | Path | None = None,
) -> ToolResult:
    started = time.perf_counter()
    paths = resolve_project_paths(project_root)
    master_path = paths.master_workbook
    if not master_path.exists():
        return ToolResult.fail("compatibility_entry", "Compatibility Entry", "Master workbook is missing.", errors=[str(master_path)])

    selected = set(parse_machine_tokens(",".join(str(machine) for machine in machine_numbers)))
    if not selected:
        return ToolResult.fail("compatibility_entry", "Compatibility Entry", "No compatible machines were selected.")

    candidate_result = build_compatibility_candidates(project_root, source_audit_id, press_capacity_path)
    if candidate_result.errors:
        return ToolResult.fail("compatibility_entry", "Compatibility Entry", "Could not build compatibility candidates.", errors=candidate_result.errors)
    source = candidate_result.source
    if source is None:
        return ToolResult.fail("compatibility_entry", "Compatibility Entry", "Source audit row is missing.")

    selected_candidates = [candidate for candidate in candidate_result.candidates if candidate.machine_no in selected]
    create_candidates = [candidate for candidate in selected_candidates if candidate.can_create]
    skipped_audited = sum(1 for candidate in selected_candidates if candidate.recommended_action == "Already Audited")
    skipped_compatible = sum(1 for candidate in selected_candidates if candidate.recommended_action.startswith("Already Compatible"))
    conflicts = sum(1 for candidate in selected_candidates if candidate.recommended_action == "Conflict / Review Needed")
    if not create_candidates:
        return ToolResult.ok(
            "compatibility_entry",
            "Compatibility Entry",
            "No compatibility entries were created.",
            details=_creation_summary(0, skipped_audited, skipped_compatible, conflicts),
            warnings=candidate_result.warnings,
            metrics={
                "created": 0,
                "skipped_already_audited": skipped_audited,
                "skipped_already_compatible": skipped_compatible,
                "conflicts": conflicts,
            },
            duration_seconds=time.perf_counter() - started,
        )

    workbook = None
    try:
        backup = backup_file(master_path, master_path.parent / "_backups")
        workbook = load_workbook(master_path)
        if "EOAT Inventory" not in workbook.sheetnames:
            raise ValueError("EOAT Inventory sheet is missing.")
        ws = workbook["EOAT Inventory"]
        _ensure_inventory_headers(ws, get_expected_headers("EOAT Inventory"))
        headers = worksheet_headers(ws)
        existing_ids = {
            text_value(ws.cell(row=row_number, column=headers.index("Audit ID") + 1).value)
            for row_number in range(2, ws.max_row + 1)
            if "Audit ID" in headers
        }
        new_ids = _generate_audit_ids(existing_ids, len(create_candidates))
        created = 0
        for audit_id, candidate in zip(new_ids, create_candidates):
            new_row = dict(source.row)
            new_row["Audit ID"] = audit_id
            new_row["Audit Date"] = ""
            new_row["Auditor"] = ""
            new_row["Press/Machine #"] = candidate.machine_no
            new_row[TOOL_FIELD] = candidate.part_number
            if candidate.part_description:
                new_row["Part Name/Description"] = candidate.part_description
            if text_value(new_row.get("Status")).lower() == "audited":
                new_row["Status"] = "Complete"
            new_row[ENTRY_TYPE_FIELD] = ENTRY_TYPE_COMPATIBLE
            new_row[SOURCE_AUDIT_ID_FIELD] = source.audit_id
            new_row[COMPATIBILITY_SOURCE_FIELD] = COMPATIBILITY_SOURCE_PRESS_CAPACITY
            write_row_by_headers(ws, next_empty_row(ws), new_row)
            created += 1
        refresh_audit_by_press_view(workbook)
        workbook.save(master_path)
        workbook.close()
    except Exception as exc:
        if workbook is not None:
            try:
                workbook.close()
            except Exception:
                pass
        return ToolResult.fail(
            "compatibility_entry",
            "Compatibility Entry",
            "Could not create compatibility entries.",
            errors=[str(exc)],
            warnings=candidate_result.warnings,
            duration_seconds=time.perf_counter() - started,
        )

    return ToolResult.ok(
        "compatibility_entry",
        "Compatibility Entry",
        f"Created {created} compatibility entries.",
        details=[*_creation_summary(created, skipped_audited, skipped_compatible, conflicts), f"Workbook backup: {backup}"],
        warnings=candidate_result.warnings,
        files_created=[str(backup)],
        files_modified=[str(master_path)],
        metrics={
            "created": created,
            "skipped_already_audited": skipped_audited,
            "skipped_already_compatible": skipped_compatible,
            "conflicts": conflicts,
        },
        duration_seconds=time.perf_counter() - started,
    )


def load_required_relationships(press_capacity_path: str | Path) -> tuple[list[RequiredRelationship], list[str]]:
    path = Path(press_capacity_path)
    if not path.exists():
        return [], [f"Press Capacity reference file not found: {path}"]
    workbook = None
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet_name = _find_sheet_name(workbook.sheetnames, CAPACITY_SHEET_NAME, ["capacity"])
        if sheet_name is None:
            return [], [f"Press Capacity sheet not found: {CAPACITY_SHEET_NAME}"]
        ws = workbook[sheet_name]
        header_map: dict[str, int] | None = None
        relationships: dict[tuple[str, str], RequiredRelationship] = {}
        for row_number, values in enumerate(ws.iter_rows(values_only=True), start=1):
            values = list(values)
            maybe_header = _capacity_header_map(values)
            if maybe_header:
                header_map = maybe_header
                continue
            if header_map is None:
                continue
            part_number = text_value(_value_for(values, header_map, "NGW Part Number"))
            if not part_number:
                continue
            description = text_value(_value_for(values, header_map, "NGW Part Description"))
            for machine_no in parse_machine_tokens(_value_for(values, header_map, "Machine No.")):
                key = relationship_key(machine_no, part_number)
                relationships.setdefault(
                    key,
                    RequiredRelationship(
                        machine_no=key[0],
                        part_number=part_number,
                        part_description=description,
                        source_row=row_number,
                    ),
                )
        return sorted(relationships.values(), key=lambda item: (_machine_sort_key(item.machine_no), item.part_number.upper())), []
    except Exception as exc:
        return [], [f"Press Capacity workbook could not be read: {exc}"]
    finally:
        if workbook is not None:
            workbook.close()


def summarize_master_relationships(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows, start=2):
        part_number = part_number_from_row(row)
        if not part_number:
            continue
        for machine_no in parse_machine_tokens(row.get("Press/Machine #")):
            key = relationship_key(machine_no, part_number)
            by_key[key].append({"row_number": index, "row": row, "entry_type": normalize_entry_type(row.get(ENTRY_TYPE_FIELD))})
    return dict(by_key)


def relationship_has_conflict(existing_rows: list[dict[str, Any]], required: RequiredRelationship | None = None) -> bool:
    if not existing_rows:
        return False
    if required and required.part_description:
        descriptions = {part_description_from_row(item["row"]) for item in existing_rows if part_description_from_row(item["row"])}
        if descriptions and required.part_description not in descriptions:
            return True
    for field_name in ["EOAT Type"]:
        values = {text_value(item["row"].get(field_name)).lower() for item in existing_rows if text_value(item["row"].get(field_name))}
        if len(values) > 1:
            return True
    descriptions = {part_description_from_row(item["row"]).lower() for item in existing_rows if part_description_from_row(item["row"])}
    return len(descriptions) > 1


def _can_sync_compatibility_field(header: str) -> bool:
    normalized = header.strip().lower()
    if not normalized:
        return False
    if header in PROTECTED_COMPATIBILITY_SYNC_FIELDS:
        return False
    return not any(part in normalized for part in PROTECTED_COMPATIBILITY_SYNC_NAME_PARTS)


def _find_audit_row_number(ws, headers: list[str], audit_id: str) -> int | None:
    if "Audit ID" not in headers:
        return None
    audit_id_col = headers.index("Audit ID") + 1
    for row_number in range(2, ws.max_row + 1):
        if text_value(ws.cell(row=row_number, column=audit_id_col).value) == str(audit_id):
            return row_number
    return None


def _worksheet_row_dict(ws, headers: list[str], row_number: int) -> dict[str, Any]:
    return {header: ws.cell(row=row_number, column=index).value for index, header in enumerate(headers, start=1)}


def _master_path(project_root_or_master_path: str | Path) -> Path:
    path = Path(project_root_or_master_path)
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        return path
    return resolve_project_paths(path).master_workbook


def _generate_audit_ids(existing_ids: set[str], count: int) -> list[str]:
    compact = date.today().isoformat().replace("-", "")
    prefix = f"AUD-{compact}-"
    max_number = 0
    for value in existing_ids:
        if value.startswith(prefix):
            try:
                max_number = max(max_number, int(value.rsplit("-", 1)[1]))
            except ValueError:
                continue
    audit_ids = []
    for offset in range(1, count + 1):
        audit_id = f"{prefix}{max_number + offset:03d}"
        while audit_id in existing_ids:
            max_number += 1
            audit_id = f"{prefix}{max_number + offset:03d}"
        audit_ids.append(audit_id)
        existing_ids.add(audit_id)
    return audit_ids


def _creation_summary(created: int, skipped_audited: int, skipped_compatible: int, conflicts: int) -> list[str]:
    return [
        f"Created {created} compatibility entries.",
        f"Skipped {skipped_audited} already-audited relationships.",
        f"Skipped {skipped_compatible} already-compatible relationships.",
        f"{conflicts} conflicts need review.",
    ]


def _machine_sort_key(machine_no: str) -> tuple[int, int | str]:
    return (0, int(machine_no)) if str(machine_no).isdigit() else (1, str(machine_no).lower())


def _find_sheet_name(sheet_names: list[str], preferred: str, words: list[str]) -> str | None:
    if preferred in sheet_names:
        return preferred
    preferred_norm = _norm(preferred)
    for sheet_name in sheet_names:
        if _norm(sheet_name) == preferred_norm:
            return sheet_name
    for sheet_name in sheet_names:
        normalized = _norm(sheet_name)
        if all(word in normalized for word in words):
            return sheet_name
    return None


def _capacity_header_map(values: list[Any]) -> dict[str, int] | None:
    aliases = {
        "Machine No.": ["Machine No.", "Machine No", "Machine #", "Machine Number", "Press", "Press #"],
        "NGW Part Number": ["NGW Part Number", "Part Number", "Part #", "NGW Part #"],
        "NGW Part Description": ["NGW Part Description", "Part Description", "Description"],
    }
    normalized_values = [_norm(value) for value in values]
    machine_headers = {_norm(alias) for alias in aliases["Machine No."]}
    if not any(value in machine_headers for value in normalized_values):
        return None
    mapping: dict[str, int] = {}
    for logical, names in aliases.items():
        normalized_names = {_norm(name) for name in names}
        for index, normalized in enumerate(normalized_values):
            if normalized in normalized_names:
                mapping[logical] = index
                break
    required = {"Machine No.", "NGW Part Number"}
    return mapping if required.issubset(mapping) else None


def _value_for(values: list[Any], header_map: dict[str, int], field_name: str) -> Any:
    index = header_map.get(field_name)
    if index is None or index >= len(values):
        return ""
    return values[index]


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", text_value(value).lower())
