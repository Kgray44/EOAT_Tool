from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .audit_entries import repair_legacy_audit_lookup_shift
from .gripper_fields import CUP_COUNT_FIELD
from .paths import resolve_project_paths
from .result import ToolResult
from .standardization import generate_standardization_report
from .workbook_io import row_dicts


TOOL_ID = "bom_spares_standardization"
TOOL_NAME = "BOM and Spare Parts Standardization Tool"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _count(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    values = [_clean(row.get(field)) for row in rows if _clean(row.get(field))]
    return dict(Counter(values))


def _missing_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = [
        "Spare Parts Identified?",
        "BOM Available?",
        "Drawing/CAD Available?",
        "Process Binder Complete?",
        CUP_COUNT_FIELD,
        "Cup Type/Material",
        "Cup Diameter/Size",
        "Sensor Type",
        "Sensor Brand/Model",
        "Pneumatic Quick Disconnect Type",
        "Electrical Quick Disconnect Type",
        "Gripper Type",
        "Vacuum Generator Type",
    ]
    missing: list[dict[str, Any]] = []
    for row in rows:
        missing_fields = [field for field in fields if not _clean(row.get(field))]
        if missing_fields:
            missing.append(
                {
                    "Audit ID": _clean(row.get("Audit ID")),
                    "Plant/Area": _clean(row.get("Plant/Area")),
                    "Press/Machine #": _clean(row.get("Press/Machine #")),
                    "EOAT Type": _clean(row.get("EOAT Type")),
                    "Missing Field Count": len(missing_fields),
                    "Missing Fields": ", ".join(missing_fields),
                }
            )
    return sorted(missing, key=lambda row: int(row["Missing Field Count"]), reverse=True)


def _opportunities(rows: list[dict[str, Any]], counts: dict[str, dict[str, int]], missing_rows: list[dict[str, Any]]) -> list[str]:
    opportunities: list[str] = []
    if not rows:
        return ["Start by auditing representative EOATs before standardizing parts."]
    for label, values in counts.items():
        common = [(key, value) for key, value in values.items() if value >= 2]
        if common:
            joined = ", ".join(f"{key} ({value})" for key, value in sorted(common, key=lambda item: -item[1])[:3])
            opportunities.append(f"Review common {label}: {joined}.")
    missing_bom = [row for row in missing_rows if "BOM Available?" in row["Missing Fields"]]
    missing_spares = [row for row in missing_rows if "Spare Parts Identified?" in row["Missing Fields"]]
    if missing_bom:
        opportunities.append(f"Confirm BOM status for {len(missing_bom)} EOAT record(s).")
    if missing_spares:
        opportunities.append(f"Document spare parts status for {len(missing_spares)} EOAT record(s).")
    if not opportunities:
        opportunities.append("No obvious standardization opportunity was detected from current workbook fields.")
    return opportunities


def analyze_bom_standardization(project_root: str | Path) -> tuple[dict[str, Any], list[str], list[str]]:
    paths = resolve_project_paths(project_root)
    warnings: list[str] = []
    if not paths.master_workbook.exists():
        return {"rows": [], "counts": {}, "missing_rows": [], "opportunities": []}, [f"Master workbook not found: {paths.master_workbook}"], []
    try:
        rows = [repair_legacy_audit_lookup_shift(row) for row in row_dicts(paths.master_workbook, "EOAT Inventory")]
    except Exception as exc:
        return {"rows": [], "counts": {}, "missing_rows": [], "opportunities": []}, [f"Could not read EOAT Inventory: {exc}"], []

    counts = {
        "vacuum cup counts": _count(rows, CUP_COUNT_FIELD),
        "vacuum cup materials": _count(rows, "Cup Type/Material"),
        "vacuum cup sizes": _count(rows, "Cup Diameter/Size"),
        "sensor types": _count(rows, "Sensor Type"),
        "sensor brands/models": _count(rows, "Sensor Brand/Model"),
        "quick disconnects": _count(rows, "Pneumatic Quick Disconnect Type"),
        "electrical quick disconnects": _count(rows, "Electrical Quick Disconnect Type"),
        "gripper types": _count(rows, "Gripper Type"),
        "vacuum generator types": _count(rows, "Vacuum Generator Type"),
    }
    missing_rows = _missing_table(rows)
    opportunities = _opportunities(rows, counts, missing_rows)
    details = [f"Read {len(rows)} EOAT Inventory row(s)."]
    return {"rows": rows, "counts": counts, "missing_rows": missing_rows, "opportunities": opportunities}, warnings, details


def generate_bom_standardization_report(project_root: str | Path) -> ToolResult:
    return generate_standardization_report(project_root)
