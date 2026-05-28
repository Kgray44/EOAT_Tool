from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .audit_compatibility import machine_from_audit_row, normalize_entry_type, normalize_machine_token, part_number_from_row
from .audit_constants import ENTRY_TYPE_COMPATIBLE
from .bom_standardization import analyze_bom_standardization
from .paths import resolve_project_paths
from .workbook_cache import row_dicts_cached as row_dicts

STATE_AUDITED = "Audited"
STATE_COMPATIBLE = "Compatible"
STATE_MISSING = "Missing"


@dataclass(frozen=True)
class CompatibilityMatrixRow:
    tool: str
    eoat_type: str
    machine_states: dict[str, str]
    audited_machines: tuple[str, ...] = ()
    compatible_machines: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompatibilityMatrixSummary:
    machines: list[str] = field(default_factory=list)
    rows: list[CompatibilityMatrixRow] = field(default_factory=list)
    standardization_opportunities: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "machines": list(self.machines),
            "rows": [row.to_dict() for row in self.rows],
            "standardization_opportunities": list(self.standardization_opportunities),
            "metrics": dict(self.metrics),
            "warnings": list(self.warnings),
        }


def build_compatibility_matrix(project_root: str | Path) -> CompatibilityMatrixSummary:
    workbook = resolve_project_paths(project_root).master_workbook
    warnings: list[str] = []
    if not workbook.exists():
        return CompatibilityMatrixSummary(metrics={"tools": 0, "machines": 0}, warnings=[f"Master workbook is missing: {workbook}"])
    try:
        rows = row_dicts(workbook, "EOAT Inventory")
    except Exception as exc:
        return CompatibilityMatrixSummary(metrics={"tools": 0, "machines": 0}, warnings=[f"Could not read EOAT Inventory: {exc}"])
    machines = sorted({_machine(row) for row in rows if _machine(row)}, key=_machine_sort_key)
    by_tool: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        tool = part_number_from_row(row) or str(row.get("Tool #") or "").strip()
        if not tool:
            continue
        by_tool.setdefault(tool, []).append(row)
    matrix_rows: list[CompatibilityMatrixRow] = []
    for tool, tool_rows in sorted(by_tool.items(), key=lambda item: item[0].casefold()):
        states = {machine: STATE_MISSING for machine in machines}
        audited: set[str] = set()
        compatible: set[str] = set()
        eoat_type = ""
        for row in tool_rows:
            machine = _machine(row)
            if not machine:
                continue
            eoat_type = eoat_type or str(row.get("EOAT Type") or "")
            if normalize_entry_type(row.get("Entry Type")) == ENTRY_TYPE_COMPATIBLE:
                compatible.add(machine)
                if states.get(machine) != STATE_AUDITED:
                    states[machine] = STATE_COMPATIBLE
            else:
                audited.add(machine)
                states[machine] = STATE_AUDITED
        matrix_rows.append(
            CompatibilityMatrixRow(
                tool=tool,
                eoat_type=eoat_type,
                machine_states=states,
                audited_machines=tuple(sorted(audited, key=_machine_sort_key)),
                compatible_machines=tuple(sorted(compatible, key=_machine_sort_key)),
            )
        )
    bom_data, bom_warnings, _details = analyze_bom_standardization(project_root)
    warnings.extend(bom_warnings)
    opportunities = list(bom_data.get("opportunities") or [])
    metrics = {
        "tools": len(matrix_rows),
        "machines": len(machines),
        "audited_cells": sum(1 for row in matrix_rows for state in row.machine_states.values() if state == STATE_AUDITED),
        "compatible_cells": sum(1 for row in matrix_rows for state in row.machine_states.values() if state == STATE_COMPATIBLE),
        "missing_cells": sum(1 for row in matrix_rows for state in row.machine_states.values() if state == STATE_MISSING),
        "standardization_opportunities": len(opportunities),
    }
    return CompatibilityMatrixSummary(machines=machines, rows=matrix_rows, standardization_opportunities=opportunities, metrics=metrics, warnings=warnings)


def _machine(row: dict[str, Any]) -> str:
    return normalize_machine_token(machine_from_audit_row(row)) or normalize_machine_token(row.get("Press/Machine #"))


def _machine_sort_key(machine: str) -> tuple[int, int | str]:
    return (0, int(machine)) if str(machine).isdigit() else (1, str(machine).casefold())

