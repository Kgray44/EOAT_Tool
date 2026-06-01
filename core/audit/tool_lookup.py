from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.audit.uninstalled import UNINSTALLED_MACHINE_CONTEXT_FIELDS, has_meaningful_identifier, normalize_identifier
from core.paths import resolve_project_paths
from core.tool_fields import LEGACY_TOOL_FIELD, TOOL_FIELD
from core.workbook_cache import row_dicts_cached

SAFE_UNINSTALLED_TOOL_LOOKUP_FIELDS = (
    TOOL_FIELD,
    "Part Family",
    "Part Name/Description",
    "EOAT Type",
    "EOAT Moves",
    "Connection Type",
    "Number of Parts Picked",
    "# of Cylinders",
    "Cylinder Type",
    "# of Cups",
    "Cup Type/Material",
    "Cup Diameter/Size",
    "Vacuum Generator Type",
    "# of Grippers",
    "Gripper Type",
    "Gripper Model",
    "Gripper Size",
    "EOAT Vacuum Circuits",
    "EOAT Pressure Circuits",
    "EOAT Interchangeable Circuits",
    "Sensors Present?",
    "Sensor Type",
    "Sensor Brand/Model",
    "Vacuum Confirmation Present?",
    "Part-Present Detection Present?",
    "Electrical/Wiring Present?",
    "Quick Disconnects Present?",
    "Pneumatic Quick Disconnect Type",
    "Electrical Quick Disconnect Type",
    "Tubing Condition",
    "Tubing Routing Notes",
    "Cable Management Condition",
    "Mounting Hardware Condition",
    "EOAT Alignment Condition",
    "Fastener/Locking Hardware Present?",
    "Known Issues",
    "Drop/Mis-Pick History",
    "Maintenance Frequency",
    "Cycle Time Concern?",
    "Scrap/Quality Concern?",
    "Changeover Difficulty",
    "Spare Parts Identified?",
    "Drawing/CAD Available?",
    "BOM Available?",
    "Process Binder Complete?",
)
_UNSAFE_LOOKUP_FIELDS = UNINSTALLED_MACHINE_CONTEXT_FIELDS | {
    "Audit ID",
    "Audit Date",
    "Auditor",
    "Status",
    "Priority",
    "Pilot Candidate?",
    "Follow-Up Needed",
    "Photos Taken?",
    "Photo Folder/Link",
    "Notes",
    "Robot Notes",
    "Source Audit ID",
    "Compatibility Source",
}


@dataclass(frozen=True)
class ToolLookupResult:
    tool_number: str
    matched: bool
    fields: dict[str, str]
    warnings: tuple[str, ...] = ()
    source: str = ""
    match_count: int = 0


def lookup_tool_details(project_root: str | Path, tool_number: Any) -> ToolLookupResult:
    tool_text = normalize_identifier(tool_number)
    if not has_meaningful_identifier(tool_text):
        return ToolLookupResult(
            tool_number=tool_text,
            matched=False,
            fields={},
            warnings=("Enter a Tool # to look up existing EOAT details.",),
        )
    workbook_path = resolve_project_paths(project_root).master_workbook
    try:
        rows = row_dicts_cached(workbook_path, "EOAT Inventory")
    except Exception as exc:
        return ToolLookupResult(
            tool_number=tool_text,
            matched=False,
            fields={},
            warnings=(f"Tool lookup source could not be read: {exc}",),
            source=str(workbook_path),
        )

    folded_tool = _tool_key(tool_text)
    matches = [row for row in rows if _tool_key(row.get(TOOL_FIELD) or row.get(LEGACY_TOOL_FIELD)) == folded_tool]
    if not matches:
        return ToolLookupResult(
            tool_number=tool_text,
            matched=False,
            fields={},
            warnings=("Tool # was not found in the existing data source. You can continue manually.",),
            source=str(workbook_path),
        )

    fields: dict[str, str] = {}
    for row in sorted(matches, key=_row_sort_key, reverse=True):
        for field_name in SAFE_UNINSTALLED_TOOL_LOOKUP_FIELDS:
            if field_name in _UNSAFE_LOOKUP_FIELDS or field_name in fields:
                continue
            value = normalize_identifier(row.get(field_name))
            if has_meaningful_identifier(value):
                fields[field_name] = value
    fields[TOOL_FIELD] = tool_text
    return ToolLookupResult(
        tool_number=tool_text,
        matched=True,
        fields=fields,
        source=str(workbook_path),
        match_count=len(matches),
    )


def _tool_key(value: Any) -> str:
    return " ".join(normalize_identifier(value).casefold().split())


def _row_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (normalize_identifier(row.get("Audit Date")), normalize_identifier(row.get("Audit ID")))


__all__ = [
    "SAFE_UNINSTALLED_TOOL_LOOKUP_FIELDS",
    "ToolLookupResult",
    "lookup_tool_details",
]
