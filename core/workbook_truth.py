from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .audit_constants import (
    COMPATIBILITY_SOURCE_FIELD,
    ENTRY_TYPE_COMPATIBLE,
    ENTRY_TYPE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_FIELD,
    SOURCE_AUDIT_ID_FIELD,
)
from .audit_field_rules import is_na_value
from .paths import resolve_project_paths
from .workbook_cache import row_dicts_cached as row_dicts

TRUTH_MISSING = "missing"
TRUTH_UNKNOWN = "unknown_not_checked"
TRUTH_NOT_APPLICABLE = "not_applicable"
TRUTH_COMPATIBILITY_DERIVED = "compatibility_derived"
TRUTH_ESTIMATED = "estimated"
TRUTH_MEASURED = "measured_or_user_entered"
TRUTH_SYSTEM = "system_metadata"

SYSTEM_FIELDS = {ENTRY_TYPE_FIELD, SOURCE_AUDIT_ID_FIELD, COMPATIBILITY_SOURCE_FIELD, MANUAL_COMPLETION_OVERRIDE_FIELD}
ESTIMATED_FIELDS = {"Estimated EOAT Weight", "Expected KPI Improvement"}


@dataclass(frozen=True)
class TruthCell:
    row_index: int
    audit_id: str
    machine: str
    field: str
    value: str
    truth_state: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkbookTruthSummary:
    metrics: dict[str, Any]
    state_counts: dict[str, int] = field(default_factory=dict)
    field_state_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_truth_cell(row: dict[str, Any], field: str, value: Any) -> TruthCell:
    text = "" if value is None else str(value).strip()
    entry_type = str(row.get(ENTRY_TYPE_FIELD) or "").strip().casefold()
    audit_id = str(row.get("Audit ID") or "").strip()
    machine = str(row.get("Press/Machine #") or "").strip()
    if not text:
        state = TRUTH_MISSING
        reason = "Cell is blank."
    elif text.casefold() in {"unknown / not checked", "unknown", "not checked"}:
        state = TRUTH_UNKNOWN
        reason = "Cell explicitly records an unknown/not-checked audit state."
    elif is_na_value(text):
        state = TRUTH_NOT_APPLICABLE
        reason = "Cell is marked not applicable."
    elif field in SYSTEM_FIELDS:
        state = TRUTH_SYSTEM
        reason = "Cell is app/system metadata."
    elif entry_type == ENTRY_TYPE_COMPATIBLE.casefold():
        state = TRUTH_COMPATIBILITY_DERIVED
        reason = "Compatible row value is inherited or derived from a source audit."
    elif field in ESTIMATED_FIELDS or field.casefold().startswith("estimated"):
        state = TRUTH_ESTIMATED
        reason = "Field is explicitly estimated."
    else:
        state = TRUTH_MEASURED
        reason = "Value is treated as user-entered physical audit data."
    return TruthCell(row_index=int(row.get("_row_index") or 0), audit_id=audit_id, machine=machine, field=field, value=text, truth_state=state, reason=reason)


def analyze_truth_from_rows(rows: Iterable[dict[str, Any]], fields: Iterable[str] | None = None) -> WorkbookTruthSummary:
    state_counts: Counter[str] = Counter()
    field_state_counts: dict[str, Counter[str]] = {}
    row_count = 0
    for row_index, raw_row in enumerate(rows, start=2):
        row = dict(raw_row)
        row.setdefault("_row_index", row_index)
        row_count += 1
        selected_fields = list(fields) if fields is not None else [field for field in row if not field.startswith("_")]
        for field in selected_fields:
            cell = classify_truth_cell(row, field, row.get(field))
            state_counts[cell.truth_state] += 1
            field_state_counts.setdefault(field, Counter())[cell.truth_state] += 1
    return WorkbookTruthSummary(
        metrics={
            "rows_scanned": row_count,
            "cells_scanned": sum(state_counts.values()),
            "truth_states": len(state_counts),
        },
        state_counts=dict(state_counts),
        field_state_counts={field: dict(counts) for field, counts in field_state_counts.items()},
    )


def analyze_workbook_truth(project_root: str | Path, sheet_name: str = "EOAT Inventory", fields: Iterable[str] | None = None) -> WorkbookTruthSummary:
    workbook = resolve_project_paths(project_root).master_workbook
    if not workbook.exists():
        return WorkbookTruthSummary(metrics={"rows_scanned": 0, "cells_scanned": 0, "truth_states": 0}, warnings=[f"Master workbook is missing: {workbook}"])
    try:
        rows = row_dicts(workbook, sheet_name)
    except Exception as exc:
        return WorkbookTruthSummary(metrics={"rows_scanned": 0, "cells_scanned": 0, "truth_states": 0}, warnings=[f"Could not read {sheet_name}: {exc}"])
    return analyze_truth_from_rows(rows, fields=fields)

