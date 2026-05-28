from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.audit_compatibility import normalize_entry_type, text_value
from core.audit_constants import ENTRY_TYPE_AUDITED, ENTRY_TYPE_COMPATIBLE, ENTRY_TYPE_FIELD, SOURCE_AUDIT_ID_FIELD
from core.paths import resolve_project_paths
from core.workbook_io import row_dicts

PROTECTED_SYNC_FIELDS = {
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
    "Compatibility Source",
}

PROTECTED_SYNC_NAME_PARTS = (
    "created",
    "timestamp",
    "row id",
    "internal",
    "override",
)


@dataclass(frozen=True)
class CompatibilityImpactPreview:
    source_audit_id: str
    compatible_row_count: int = 0
    compatible_audit_ids: tuple[str, ...] = ()
    fields_likely_to_propagate: tuple[str, ...] = ()
    will_sync_linked_rows: bool = False
    will_run_autorun: bool = False
    will_refresh_press_view: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_impact(self) -> bool:
        return self.compatible_row_count > 0 and self.will_sync_linked_rows


def compatibility_sync_fields(headers: list[str]) -> list[str]:
    fields: list[str] = []
    for header in headers:
        normalized = str(header or "").strip().lower()
        if not normalized:
            continue
        if header in PROTECTED_SYNC_FIELDS:
            continue
        if any(part in normalized for part in PROTECTED_SYNC_NAME_PARTS):
            continue
        fields.append(header)
    return fields


def build_compatibility_impact_preview(
    project_root: str | Path,
    source_audit_id: str,
    proposed_entry: dict[str, Any] | None = None,
) -> CompatibilityImpactPreview:
    audit_id = str(source_audit_id or "").strip()
    if not audit_id:
        return CompatibilityImpactPreview(source_audit_id="", warnings=("No source audit ID was provided.",))
    workbook_path = resolve_project_paths(project_root).master_workbook
    if not workbook_path.exists():
        return CompatibilityImpactPreview(source_audit_id=audit_id, warnings=(f"Master workbook is missing: {workbook_path}",))
    rows = row_dicts(workbook_path, "EOAT Inventory")
    source = next((row for row in rows if text_value(row.get("Audit ID")) == audit_id), None)
    entry_type = normalize_entry_type((proposed_entry or source or {}).get(ENTRY_TYPE_FIELD))
    will_sync = entry_type == ENTRY_TYPE_AUDITED
    will_autorun = entry_type == ENTRY_TYPE_AUDITED
    if source is None:
        return CompatibilityImpactPreview(
            source_audit_id=audit_id,
            will_run_autorun=will_autorun,
            will_refresh_press_view=True,
            warnings=(f"Source audit ID is not currently saved: {audit_id}",),
        )
    linked_rows = [
        row
        for row in rows
        if text_value(row.get(SOURCE_AUDIT_ID_FIELD)) == audit_id
        and normalize_entry_type(row.get(ENTRY_TYPE_FIELD)) == ENTRY_TYPE_COMPATIBLE
    ]
    headers = list(rows[0].keys()) if rows else list((proposed_entry or source).keys())
    return CompatibilityImpactPreview(
        source_audit_id=audit_id,
        compatible_row_count=len(linked_rows),
        compatible_audit_ids=tuple(text_value(row.get("Audit ID")) for row in linked_rows if text_value(row.get("Audit ID"))),
        fields_likely_to_propagate=tuple(compatibility_sync_fields(headers)),
        will_sync_linked_rows=will_sync and bool(linked_rows),
        will_run_autorun=will_autorun,
        will_refresh_press_view=True,
    )
