from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .analysis_common import table_from_rows, write_timestamped_csv, write_timestamped_report
from .audit.relationships import is_compatibility_row, is_physical_audit_row, source_audit_for_compatibility_row
from .audit_compatibility import (
    COMPATIBILITY_SOURCE_FIELD,
    ENTRY_TYPE_FIELD,
    SOURCE_AUDIT_ID_FIELD,
    _can_sync_compatibility_field,
    machine_from_audit_row,
    normalize_machine_token,
    part_description_from_row,
    part_number_from_row,
    text_value,
)
from .bom_standardization import analyze_bom_standardization
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory
from .workbook_cache import row_dicts_cached as row_dicts

STATE_COMPATIBLE = "Compatible"
STATE_NOT_COMPATIBLE = "Not Compatible"
STATE_UNKNOWN = "Unknown"
STATE_CONFLICT = "Conflict"
STATE_NEEDS_REVIEW = "Needs Review"

# Compatibility alias retained for older callers/tests. Physical audit IDs are still
# exposed separately on each cell, so "Compatible" does not erase provenance.
STATE_AUDITED = STATE_COMPATIBLE
STATE_MISSING = STATE_UNKNOWN

COLUMN_MODE_TOOL = "tool"
COLUMN_MODE_PART_FAMILY = "part_family"
COLUMN_MODE_SOURCE_AUDIT = "source_audit"
COLUMN_MODES = (COLUMN_MODE_TOOL, COLUMN_MODE_PART_FAMILY, COLUMN_MODE_SOURCE_AUDIT)

TOOL_ID = "compatibility_matrix"
TOOL_NAME = "Compatibility Matrix 2.0"

CONFLICT_FIELDS = ("EOAT Type", "Part Family", "Part Name/Description", "Connection Type")
EXPLICIT_NOT_COMPATIBLE_FIELDS = ("Compatibility Status", "Compatible?", "Status")


@dataclass(frozen=True)
class CompatibilityMatrixColumn:
    key: str
    label: str
    column_type: str
    source_audit_id: str = ""
    tool: str = ""
    part_family: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompatibilityMatrixCell:
    machine: str
    column_key: str
    column_label: str
    column_type: str
    compatibility_status: str
    source_audit_id: str = ""
    compatibility_source: str = ""
    fields_copied: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    missing_data: tuple[str, ...] = ()
    recommended_action: str = ""
    physical_audit_ids: tuple[str, ...] = ()
    compatibility_audit_ids: tuple[str, ...] = ()
    audit_ids: tuple[str, ...] = ()
    details: tuple[str, ...] = ()

    @property
    def state(self) -> str:
        return self.compatibility_status

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompatibilityMatrixRow:
    machine: str
    cells: tuple[CompatibilityMatrixCell, ...]

    @property
    def machine_states(self) -> dict[str, str]:
        return {cell.column_label: cell.compatibility_status for cell in self.cells}

    @property
    def audited_machines(self) -> tuple[str, ...]:
        return (self.machine,) if any(cell.physical_audit_ids for cell in self.cells) else ()

    @property
    def compatible_machines(self) -> tuple[str, ...]:
        return (self.machine,) if any(cell.compatibility_audit_ids for cell in self.cells) else ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "machine": self.machine,
            "machine_states": self.machine_states,
            "audited_machines": self.audited_machines,
            "compatible_machines": self.compatible_machines,
            "cells": [cell.to_dict() for cell in self.cells],
        }


@dataclass(frozen=True)
class CompatibilityMatrixSummary:
    machines: list[str] = field(default_factory=list)
    columns: list[CompatibilityMatrixColumn] = field(default_factory=list)
    rows: list[CompatibilityMatrixRow] = field(default_factory=list)
    standardization_opportunities: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    column_mode: str = COLUMN_MODE_TOOL

    @property
    def cells(self) -> list[CompatibilityMatrixCell]:
        return [cell for row in self.rows for cell in row.cells]

    def cell(self, machine: str, column_key_or_label: str) -> CompatibilityMatrixCell | None:
        machine_key = normalize_machine_token(machine)
        target = str(column_key_or_label or "").strip().casefold()
        for row in self.rows:
            if row.machine != machine_key:
                continue
            for cell in row.cells:
                if cell.column_key.casefold() == target or cell.column_label.casefold() == target:
                    return cell
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "machines": list(self.machines),
            "columns": [column.to_dict() for column in self.columns],
            "rows": [row.to_dict() for row in self.rows],
            "standardization_opportunities": list(self.standardization_opportunities),
            "metrics": dict(self.metrics),
            "warnings": list(self.warnings),
            "column_mode": self.column_mode,
        }


def build_compatibility_matrix(project_root: str | Path, *, column_mode: str = COLUMN_MODE_TOOL) -> CompatibilityMatrixSummary:
    column_mode = _normalize_column_mode(column_mode)
    workbook = resolve_project_paths(project_root).master_workbook
    warnings: list[str] = []
    if not workbook.exists():
        return CompatibilityMatrixSummary(metrics={"tools": 0, "machines": 0}, warnings=[f"Master workbook is missing: {workbook}"], column_mode=column_mode)
    try:
        inventory_rows = [dict(row) for row in row_dicts(workbook, "EOAT Inventory")]
    except Exception as exc:
        return CompatibilityMatrixSummary(metrics={"tools": 0, "machines": 0}, warnings=[f"Could not read EOAT Inventory: {exc}"], column_mode=column_mode)

    rows_with_keys = [_row_with_key(row, column_mode) for row in inventory_rows]
    machines = sorted({_machine(item["row"]) for item in rows_with_keys if _machine(item["row"])}, key=_machine_sort_key)
    columns = _build_columns(rows_with_keys, column_mode)
    source_by_id = {text_value(row.get("Audit ID")): row for row in inventory_rows if text_value(row.get("Audit ID"))}
    cells_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in rows_with_keys:
        machine = _machine(item["row"])
        column_key = item["column"].key if item["column"] else ""
        if not machine or not column_key:
            continue
        cells_by_pair.setdefault((machine, column_key), []).append(item["row"])

    matrix_rows: list[CompatibilityMatrixRow] = []
    for machine in machines:
        cells = tuple(_build_cell(machine, column, cells_by_pair.get((machine, column.key), []), inventory_rows, source_by_id) for column in columns)
        matrix_rows.append(CompatibilityMatrixRow(machine=machine, cells=cells))

    bom_data, bom_warnings, _details = analyze_bom_standardization(project_root)
    warnings.extend(bom_warnings)
    opportunities = list(bom_data.get("opportunities") or [])
    metrics = _metrics(matrix_rows, columns, machines)
    metrics["standardization_opportunities"] = len(opportunities)
    metrics["physical_rows"] = sum(1 for row in inventory_rows if is_physical_audit_row(row))
    metrics["compatibility_rows"] = sum(1 for row in inventory_rows if is_compatibility_row(row))
    metrics["created_compatibility_rows"] = 0
    return CompatibilityMatrixSummary(
        machines=machines,
        columns=columns,
        rows=matrix_rows,
        standardization_opportunities=opportunities,
        metrics=metrics,
        warnings=warnings,
        column_mode=column_mode,
    )


def export_compatibility_matrix(
    project_root: str | Path,
    *,
    column_mode: str = COLUMN_MODE_TOOL,
    log_activity: bool = True,
) -> ToolResult:
    started = time.perf_counter()
    paths = resolve_project_paths(project_root)
    output_dir = ensure_directory(paths.audit_progress_reports / "Compatibility_Matrix")
    summary = build_compatibility_matrix(project_root, column_mode=column_mode)
    markdown = compatibility_matrix_markdown(summary)
    md_path = write_timestamped_report(output_dir, f"Compatibility_Matrix_{summary.column_mode}", markdown)
    csv_rows = compatibility_matrix_csv_rows(summary)
    csv_path = write_timestamped_csv(output_dir, f"Compatibility_Matrix_{summary.column_mode}", csv_rows) if csv_rows else None
    files = [str(md_path), *(str(csv_path) for csv_path in [csv_path] if csv_path is not None)]
    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Exported compatibility matrix.",
        details=[f"Column mode: {summary.column_mode}", f"Machines: {len(summary.machines)}", f"Columns: {len(summary.columns)}"],
        warnings=summary.warnings,
        files_created=files,
        output_reports=files,
        metrics=summary.metrics,
        structured_data=summary.to_dict(),
        duration_seconds=time.perf_counter() - started,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result


def compatibility_matrix_csv_rows(summary: CompatibilityMatrixSummary) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for matrix_row in summary.rows:
        for cell in matrix_row.cells:
            rows.append(
                {
                    "Machine": cell.machine,
                    "Column": cell.column_label,
                    "Column Type": cell.column_type,
                    "Compatibility Status": cell.compatibility_status,
                    "Source Audit ID": cell.source_audit_id,
                    "Compatibility Source": cell.compatibility_source,
                    "Physical Audit IDs": "; ".join(cell.physical_audit_ids),
                    "Compatibility Audit IDs": "; ".join(cell.compatibility_audit_ids),
                    "Fields Copied": "; ".join(cell.fields_copied),
                    "Conflicts": "; ".join(cell.conflicts),
                    "Missing Data Preventing Decision": "; ".join(cell.missing_data),
                    "Recommended Action": cell.recommended_action,
                }
            )
    return rows


def compatibility_matrix_markdown(summary: CompatibilityMatrixSummary) -> str:
    lines = [
        "# Compatibility Matrix 2.0",
        "",
        "## Summary",
        f"- Column mode: {summary.column_mode}",
        f"- Machines: {len(summary.machines)}",
        f"- Columns: {len(summary.columns)}",
        f"- Compatible cells: {summary.metrics.get('compatible_cells', 0)}",
        f"- Conflict cells: {summary.metrics.get('conflict_cells', 0)}",
        f"- Needs review cells: {summary.metrics.get('needs_review_cells', 0)}",
        f"- Unknown cells: {summary.metrics.get('unknown_cells', 0)}",
        "",
        "## Matrix",
    ]
    if not summary.rows or not summary.columns:
        lines.append("No matrix data available.")
    else:
        header = ["Machine", *[column.label for column in summary.columns]]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for row in summary.rows:
            status_by_key = {cell.column_key: cell.compatibility_status for cell in row.cells}
            lines.append("| " + " | ".join([row.machine, *[status_by_key.get(column.key, STATE_UNKNOWN) for column in summary.columns]]) + " |")
    lines.extend(["", "## Cell Details"])
    lines.extend(
        table_from_rows(
            compatibility_matrix_csv_rows(summary),
            [
                "Machine",
                "Column",
                "Compatibility Status",
                "Source Audit ID",
                "Compatibility Source",
                "Physical Audit IDs",
                "Compatibility Audit IDs",
                "Conflicts",
                "Missing Data Preventing Decision",
                "Recommended Action",
            ],
        )
    )
    if summary.standardization_opportunities:
        lines.extend(["", "## Related Standardization Opportunities"])
        lines.extend(f"- {item}" for item in summary.standardization_opportunities)
    return "\n".join(lines) + "\n"


def _build_cell(
    machine: str,
    column: CompatibilityMatrixColumn,
    matching_rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
    source_by_id: dict[str, dict[str, Any]],
) -> CompatibilityMatrixCell:
    physical_rows = [row for row in matching_rows if is_physical_audit_row(row)]
    compatibility_rows = [row for row in matching_rows if is_compatibility_row(row)]
    audit_ids = tuple(_sorted_texts(text_value(row.get("Audit ID")) for row in matching_rows))
    physical_ids = tuple(_sorted_texts(text_value(row.get("Audit ID")) for row in physical_rows))
    compatibility_ids = tuple(_sorted_texts(text_value(row.get("Audit ID")) for row in compatibility_rows))
    source_ids = tuple(_sorted_texts(text_value(row.get(SOURCE_AUDIT_ID_FIELD)) for row in compatibility_rows))
    compatibility_sources = tuple(_sorted_texts(text_value(row.get(COMPATIBILITY_SOURCE_FIELD)) for row in compatibility_rows))
    conflicts = list(_cell_conflicts(physical_rows, compatibility_rows, column, source_by_id))
    missing_data = list(_missing_data(compatibility_rows, all_rows))
    fields_copied = tuple(_sorted_texts(_copied_fields(compatibility_rows, source_by_id)))
    explicit_not_compatible = any(_explicit_not_compatible(row) for row in matching_rows)

    if explicit_not_compatible:
        state = STATE_NOT_COMPATIBLE
    elif conflicts:
        state = STATE_CONFLICT
    elif missing_data:
        state = STATE_NEEDS_REVIEW
    elif physical_rows or compatibility_rows:
        state = STATE_COMPATIBLE
    else:
        state = STATE_UNKNOWN

    return CompatibilityMatrixCell(
        machine=machine,
        column_key=column.key,
        column_label=column.label,
        column_type=column.column_type,
        compatibility_status=state,
        source_audit_id="; ".join(source_ids),
        compatibility_source="; ".join(compatibility_sources),
        fields_copied=fields_copied,
        conflicts=tuple(conflicts),
        missing_data=tuple(missing_data),
        recommended_action=_recommended_action(state, bool(physical_rows), bool(compatibility_rows)),
        physical_audit_ids=physical_ids,
        compatibility_audit_ids=compatibility_ids,
        audit_ids=audit_ids,
        details=tuple(_details_for_cell(physical_rows, compatibility_rows)),
    )


def _cell_conflicts(
    physical_rows: list[dict[str, Any]],
    compatibility_rows: list[dict[str, Any]],
    column: CompatibilityMatrixColumn,
    source_by_id: dict[str, dict[str, Any]],
) -> Iterable[str]:
    for field_name in CONFLICT_FIELDS:
        values = {text_value(row.get(field_name)).casefold(): text_value(row.get(field_name)) for row in [*physical_rows, *compatibility_rows] if text_value(row.get(field_name))}
        if len(values) > 1:
            yield f"Conflicting {field_name}: {', '.join(sorted(values.values(), key=str.casefold))}"
    source_ids = {text_value(row.get(SOURCE_AUDIT_ID_FIELD)) for row in compatibility_rows if text_value(row.get(SOURCE_AUDIT_ID_FIELD))}
    if len(source_ids) > 1:
        yield f"Multiple source audit IDs: {', '.join(sorted(source_ids, key=str.casefold))}"
    if column.column_type == COLUMN_MODE_TOOL:
        for row in compatibility_rows:
            source_id = text_value(row.get(SOURCE_AUDIT_ID_FIELD))
            source_row = source_by_id.get(source_id)
            if not source_row:
                continue
            source_tool = part_number_from_row(source_row)
            row_tool = part_number_from_row(row)
            if source_tool and row_tool and source_tool.casefold() != row_tool.casefold():
                yield f"Source audit {source_id} tool {source_tool} differs from compatibility row tool {row_tool}."


def _missing_data(compatibility_rows: list[dict[str, Any]], all_rows: list[dict[str, Any]]) -> Iterable[str]:
    for row in compatibility_rows:
        audit_id = text_value(row.get("Audit ID")) or "compatibility row"
        if not text_value(row.get(SOURCE_AUDIT_ID_FIELD)):
            yield f"{audit_id} is missing Source Audit ID."
        if not text_value(row.get(COMPATIBILITY_SOURCE_FIELD)):
            yield f"{audit_id} is missing Compatibility Source."
        lookup = source_audit_for_compatibility_row(all_rows, row)
        for warning in lookup.warnings:
            yield warning


def _copied_fields(compatibility_rows: list[dict[str, Any]], source_by_id: dict[str, dict[str, Any]]) -> Iterable[str]:
    for row in compatibility_rows:
        source = source_by_id.get(text_value(row.get(SOURCE_AUDIT_ID_FIELD)))
        if not source:
            continue
        for field_name, value in row.items():
            if not _can_sync_compatibility_field(field_name):
                continue
            if text_value(value) and text_value(value) == text_value(source.get(field_name)):
                yield field_name


def _details_for_cell(physical_rows: list[dict[str, Any]], compatibility_rows: list[dict[str, Any]]) -> Iterable[str]:
    for row in physical_rows:
        yield f"Physical audit {text_value(row.get('Audit ID')) or '(no Audit ID)'}"
    for row in compatibility_rows:
        source = text_value(row.get(SOURCE_AUDIT_ID_FIELD)) or "missing source"
        yield f"Compatibility row {text_value(row.get('Audit ID')) or '(no Audit ID)'} from {source}"


def _build_columns(rows_with_keys: list[dict[str, Any]], column_mode: str) -> list[CompatibilityMatrixColumn]:
    columns: dict[str, CompatibilityMatrixColumn] = {}
    for item in rows_with_keys:
        column = item["column"]
        if column is None:
            continue
        columns[column.key] = column
    return sorted(columns.values(), key=lambda column: _column_sort_key(column.label))


def _row_with_key(row: dict[str, Any], column_mode: str) -> dict[str, Any]:
    return {"row": row, "column": _column_for_row(row, column_mode)}


def _column_for_row(row: dict[str, Any], column_mode: str) -> CompatibilityMatrixColumn | None:
    if column_mode == COLUMN_MODE_SOURCE_AUDIT:
        source_id = text_value(row.get("Audit ID")) if is_physical_audit_row(row) else text_value(row.get(SOURCE_AUDIT_ID_FIELD))
        if not source_id:
            return None
        tool = part_number_from_row(row)
        description = part_description_from_row(row)
        label = " | ".join(piece for piece in [source_id, tool, description] if piece)
        return CompatibilityMatrixColumn(key=f"source::{source_id.casefold()}", label=label, column_type=column_mode, source_audit_id=source_id, tool=tool)
    if column_mode == COLUMN_MODE_PART_FAMILY:
        part_family = text_value(row.get("Part Family")) or part_description_from_row(row) or part_number_from_row(row)
        if not part_family:
            return None
        return CompatibilityMatrixColumn(key=f"family::{part_family.casefold()}", label=part_family, column_type=column_mode, part_family=part_family)
    tool = part_number_from_row(row)
    if not tool:
        return None
    description = part_description_from_row(row)
    label = " | ".join(piece for piece in [tool, description] if piece)
    return CompatibilityMatrixColumn(key=f"tool::{tool.casefold()}", label=label, column_type=COLUMN_MODE_TOOL, tool=tool)


def _metrics(rows: list[CompatibilityMatrixRow], columns: list[CompatibilityMatrixColumn], machines: list[str]) -> dict[str, Any]:
    cells = [cell for row in rows for cell in row.cells]
    return {
        "tools": len(columns),
        "columns": len(columns),
        "machines": len(machines),
        "compatible_cells": sum(1 for cell in cells if cell.compatibility_status == STATE_COMPATIBLE),
        "not_compatible_cells": sum(1 for cell in cells if cell.compatibility_status == STATE_NOT_COMPATIBLE),
        "unknown_cells": sum(1 for cell in cells if cell.compatibility_status == STATE_UNKNOWN),
        "conflict_cells": sum(1 for cell in cells if cell.compatibility_status == STATE_CONFLICT),
        "needs_review_cells": sum(1 for cell in cells if cell.compatibility_status == STATE_NEEDS_REVIEW),
        "physical_verified_cells": sum(1 for cell in cells if cell.physical_audit_ids),
        "compatibility_row_cells": sum(1 for cell in cells if cell.compatibility_audit_ids),
    }


def _recommended_action(state: str, has_physical: bool, has_compatibility: bool) -> str:
    if state == STATE_NOT_COMPATIBLE:
        return "Do not treat this machine/tool pairing as compatible unless engineering approves a change."
    if state == STATE_CONFLICT:
        return "Review conflicting workbook rows before relying on this compatibility decision."
    if state == STATE_NEEDS_REVIEW:
        return "Fill missing compatibility metadata or inspect the source audit before relying on this cell."
    if state == STATE_COMPATIBLE and has_physical:
        return "Use the physical audit as the verified source of truth."
    if state == STATE_COMPATIBLE and has_compatibility:
        return "Compatibility is represented by an existing compatibility row; verify source before changing rules."
    return "No compatibility entry exists. Audit the machine or create a reviewed compatibility row if appropriate."


def _explicit_not_compatible(row: dict[str, Any]) -> bool:
    for field_name in EXPLICIT_NOT_COMPATIBLE_FIELDS:
        text = text_value(row.get(field_name)).casefold()
        if text in {"not compatible", "incompatible", "no", "blocked"}:
            return True
    return False


def _machine(row: dict[str, Any]) -> str:
    return normalize_machine_token(machine_from_audit_row(row)) or normalize_machine_token(row.get("Press/Machine #"))


def _machine_sort_key(machine: str) -> tuple[int, int | str]:
    return (0, int(machine)) if str(machine).isdigit() else (1, str(machine).casefold())


def _column_sort_key(label: str) -> tuple[int, int | str, str]:
    text = str(label or "")
    first = text.split("|", 1)[0].strip()
    return (0, int(first), text.casefold()) if first.isdigit() else (1, first.casefold(), text.casefold())


def _sorted_texts(values: Iterable[str]) -> list[str]:
    return sorted({value for value in values if value}, key=str.casefold)


def _normalize_column_mode(column_mode: str) -> str:
    mode = str(column_mode or COLUMN_MODE_TOOL).strip().casefold().replace("-", "_").replace(" ", "_")
    if mode in {"tools", "tool"}:
        return COLUMN_MODE_TOOL
    if mode in {"part_family", "part_families", "families", "family"}:
        return COLUMN_MODE_PART_FAMILY
    if mode in {"source", "source_audit", "source_audits", "audit"}:
        return COLUMN_MODE_SOURCE_AUDIT
    return COLUMN_MODE_TOOL


__all__ = [
    "COLUMN_MODE_PART_FAMILY",
    "COLUMN_MODE_SOURCE_AUDIT",
    "COLUMN_MODE_TOOL",
    "COLUMN_MODES",
    "CompatibilityMatrixCell",
    "CompatibilityMatrixColumn",
    "CompatibilityMatrixRow",
    "CompatibilityMatrixSummary",
    "STATE_AUDITED",
    "STATE_COMPATIBLE",
    "STATE_CONFLICT",
    "STATE_MISSING",
    "STATE_NEEDS_REVIEW",
    "STATE_NOT_COMPATIBLE",
    "STATE_UNKNOWN",
    "build_compatibility_matrix",
    "compatibility_matrix_csv_rows",
    "compatibility_matrix_markdown",
    "export_compatibility_matrix",
]
