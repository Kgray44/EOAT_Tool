from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any

from .analysis_common import table_from_counts, table_from_rows, write_timestamped_csv, write_timestamped_report
from .audit_entries import repair_legacy_audit_lookup_shift
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory
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


def _markdown(data: dict[str, Any], warnings: list[str]) -> str:
    rows = data["rows"]
    counts = data["counts"]
    missing_rows = data["missing_rows"]
    opportunities = data["opportunities"]
    lines = [
        "# BOM and Spare Parts Standardization Report",
        "",
        "## Executive Summary",
        f"- EOAT records scanned: {len(rows)}",
        f"- EOATs missing BOM/spare/documentation fields: {len(missing_rows)}",
    ]
    if warnings:
        lines.extend(f"- Warning: {warning}" for warning in warnings)
    lines.extend(["", "## Common Vacuum Cup Information"])
    lines.extend(table_from_counts(counts.get("vacuum cup materials", {}), "Cup Type/Material"))
    lines.extend(["", "### Cup Sizes"])
    lines.extend(table_from_counts(counts.get("vacuum cup sizes", {}), "Cup Diameter/Size"))
    lines.extend(["", "## Common Sensor Information"])
    lines.extend(table_from_counts(counts.get("sensor types", {}), "Sensor Type"))
    lines.extend(["", "### Sensor Brands/Models"])
    lines.extend(table_from_counts(counts.get("sensor brands/models", {}), "Sensor Brand/Model"))
    lines.extend(["", "## Common Quick Disconnect Information"])
    lines.extend(table_from_counts(counts.get("quick disconnects", {}), "Pneumatic Quick Disconnect Type"))
    lines.extend(["", "## Common Gripper/Vacuum Generator Information"])
    lines.extend(table_from_counts(counts.get("gripper types", {}), "Gripper Type"))
    lines.extend(["", "### Vacuum Generators"])
    lines.extend(table_from_counts(counts.get("vacuum generator types", {}), "Vacuum Generator Type"))
    lines.extend(["", "## Missing BOM and Spare Parts Data"])
    lines.extend(table_from_rows(missing_rows[:25], ["Audit ID", "Press/Machine #", "EOAT Type", "Missing Field Count", "Missing Fields"]))
    lines.extend(["", "## Standardization Opportunities"])
    lines.extend(f"- {item}" for item in opportunities)
    lines.extend(
        [
            "",
            "## Recommended Follow-Up Actions",
            "- Confirm missing BOM/CAD/process binder status for high-priority EOATs.",
            "- Record actual manufacturer part numbers only after verifying the physical component or approved documentation.",
            "- Group common cups, sensors, quick disconnects, and gripper components for mentor review.",
        ]
    )
    return "\n".join(lines) + "\n"


def generate_bom_standardization_report(project_root: str | Path) -> ToolResult:
    start = time.perf_counter()
    paths = resolve_project_paths(project_root)
    ensure_directory(paths.bom_standardization_reports)
    data, warnings, details = analyze_bom_standardization(project_root)
    markdown = _markdown(data, warnings)
    report = write_timestamped_report(paths.bom_standardization_reports, "BOM_Standardization_Report", markdown)
    files_created = [str(report)]
    if data["rows"]:
        common_rows: list[dict[str, Any]] = []
        for label, values in data["counts"].items():
            for value, count in values.items():
                common_rows.append({"Category": label, "Value": value, "Count": count})
        if common_rows:
            files_created.append(str(write_timestamped_csv(paths.bom_standardization_reports, "Common_Parts_Summary", common_rows)))
        if data["missing_rows"]:
            files_created.append(str(write_timestamped_csv(paths.bom_standardization_reports, "Missing_BOM_Data", data["missing_rows"])))

    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Generated BOM/spare parts standardization report.",
        details=details,
        warnings=warnings,
        files_created=files_created,
        output_reports=files_created,
        metrics={
            "inventory_rows": len(data["rows"]),
            "missing_data_rows": len(data["missing_rows"]),
            "opportunity_count": len(data["opportunities"]),
        },
        duration_seconds=time.perf_counter() - start,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result
