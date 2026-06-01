from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .analysis_common import table_from_counts, table_from_rows, write_timestamped_csv, write_timestamped_report
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory
from .workbook_io import row_dicts

CRITICAL_FIELDS = [
    "Press/Machine #",
    "EOAT Type",
    "Status",
    "Drawing/CAD Available?",
    "BOM Available?",
    "Process Binder Complete?",
]
IMPORTANT_FIELDS = [
    "Photos Taken?",
    "Spare Parts Identified?",
    "Sensor Type",
    "Sensor Brand/Model",
    "Tubing Condition",
    "Cable Management Condition",
    "Maintenance Frequency",
]
NICE_FIELDS = [
    "Known Issues",
    "Priority",
    "Notes",
    "Pneumatic Quick Disconnect Type",
    "Electrical Quick Disconnect Type",
]


@dataclass
class DocumentationGapSummary:
    metrics: dict[str, Any]
    gap_rows: list[dict[str, Any]] = field(default_factory=list)
    top_eoats: list[dict[str, Any]] = field(default_factory=list)
    missing_field_counts: dict[str, int] = field(default_factory=dict)

    def to_markdown(self) -> str:
        return (
            "\n".join(
                [
                    "# EOAT Documentation Gap Report",
                    "",
                    "## Executive Summary",
                    f"- EOATs scanned: {self.metrics.get('eoats_scanned', 0)}",
                    f"- Total gaps: {self.metrics.get('total_gaps', 0)}",
                    f"- Critical gaps: {self.metrics.get('critical_gaps', 0)}",
                    f"- Important gaps: {self.metrics.get('important_gaps', 0)}",
                    "",
                    "## Top EOATs By Gap Count",
                    *table_from_rows(
                        self.top_eoats,
                        ["Audit ID", "Press/Machine #", "Gap Count", "Critical", "Important", "Nice-to-have"],
                    ),
                    "",
                    "## Top Missing Fields",
                    *table_from_counts(self.missing_field_counts, "Missing Field"),
                    "",
                    "## Gap Table",
                    *table_from_rows(
                        self.gap_rows[:50], ["Audit ID", "Press/Machine #", "Gap Field", "Severity", "Reason"]
                    ),
                    "",
                    "## Recommended Follow-Up Actions",
                    "- Collect missing CAD/BOM/process binder status for critical gaps.",
                    "- Link photos or update Photo Index for cells marked as photographed.",
                    "- Fill sensor, cup, gripper, tubing, and cable condition details during the next floor walk.",
                ]
            )
            + "\n"
        )


def _gap_row(row: dict[str, Any], field: str, severity: str, reason: str) -> dict[str, Any]:
    return {
        "Audit ID": row.get("Audit ID", ""),
        "Press/Machine #": row.get("Press/Machine #", ""),
        "Plant/Area": row.get("Plant/Area", ""),
        "Gap Field": field,
        "Severity": severity,
        "Reason": reason,
    }


def scan_documentation_gaps(project_root: str | Path) -> tuple[DocumentationGapSummary | None, ToolResult | None]:
    workbook = resolve_project_paths(project_root).master_workbook
    if not workbook.exists():
        return None, ToolResult.fail(
            "documentation_gap_scanner",
            "EOAT Documentation Gap Scanner",
            "Master workbook is missing.",
            errors=[str(workbook)],
        )
    try:
        inventory = row_dicts(workbook, "EOAT Inventory")
        photos = row_dicts(workbook, "Photo Index")
    except Exception as exc:
        return None, ToolResult.fail(
            "documentation_gap_scanner", "EOAT Documentation Gap Scanner", "Could not read workbook.", errors=[str(exc)]
        )
    photo_audit_ids = {str(row.get("Related Audit ID") or "") for row in photos if row.get("Related Audit ID")}
    gaps: list[dict[str, Any]] = []
    for row in inventory:
        for field in CRITICAL_FIELDS:
            if not str(row.get(field) or "").strip():
                gaps.append(_gap_row(row, field, "Critical", "Required documentation/status field is blank."))
        for field in IMPORTANT_FIELDS:
            if not str(row.get(field) or "").strip():
                gaps.append(_gap_row(row, field, "Important", "Important standardization field is blank."))
        for field in NICE_FIELDS:
            if not str(row.get(field) or "").strip():
                gaps.append(_gap_row(row, field, "Nice-to-have", "Useful detail is blank."))
        eoat_type = str(row.get("EOAT Type") or "").lower()
        if "vacuum" in eoat_type:
            for field in ["Cup Type/Material", "Cup Diameter/Size"]:
                if not str(row.get(field) or "").strip():
                    gaps.append(_gap_row(row, field, "Important", "Vacuum EOAT is missing cup details."))
        if "gripper" in eoat_type or "hybrid" in eoat_type:
            if not str(row.get("Gripper Type") or "").strip():
                gaps.append(
                    _gap_row(row, "Gripper Type", "Important", "Mechanical/hybrid EOAT is missing gripper type.")
                )
        if (
            str(row.get("Photos Taken?") or "").lower() == "yes"
            and str(row.get("Audit ID") or "") not in photo_audit_ids
        ):
            gaps.append(
                _gap_row(
                    row,
                    "Photo Index mismatch",
                    "Important",
                    "Photos Taken? is Yes but no Photo Index row links this Audit ID.",
                )
            )
    by_audit: dict[str, Counter] = {}
    for gap in gaps:
        key = str(gap.get("Audit ID") or gap.get("Press/Machine #") or "Unknown")
        by_audit.setdefault(key, Counter())
        by_audit[key][str(gap["Severity"])] += 1
    top_eoats = []
    for key, counter in by_audit.items():
        row = next(
            (
                item
                for item in inventory
                if str(item.get("Audit ID") or item.get("Press/Machine #") or "Unknown") == key
            ),
            {},
        )
        total = sum(counter.values())
        top_eoats.append(
            {
                "Audit ID": row.get("Audit ID", key),
                "Press/Machine #": row.get("Press/Machine #", ""),
                "Gap Count": total,
                "Critical": counter["Critical"],
                "Important": counter["Important"],
                "Nice-to-have": counter["Nice-to-have"],
            }
        )
    top_eoats.sort(key=lambda item: int(item["Gap Count"]), reverse=True)
    missing_counts = dict(Counter(str(gap["Gap Field"]) for gap in gaps))
    summary = DocumentationGapSummary(
        metrics={
            "eoats_scanned": len(inventory),
            "total_gaps": len(gaps),
            "critical_gaps": sum(1 for gap in gaps if gap["Severity"] == "Critical"),
            "important_gaps": sum(1 for gap in gaps if gap["Severity"] == "Important"),
            "nice_to_have_gaps": sum(1 for gap in gaps if gap["Severity"] == "Nice-to-have"),
        },
        gap_rows=gaps,
        top_eoats=top_eoats[:15],
        missing_field_counts=missing_counts,
    )
    return summary, None


def generate_documentation_gap_report(
    project_root: str | Path, write_csv: bool = True, log_activity: bool = True
) -> ToolResult:
    summary, error = scan_documentation_gaps(project_root)
    if error:
        return error
    assert summary is not None
    folder = resolve_project_paths(project_root).documentation_gap_reports
    ensure_directory(folder)
    try:
        report = write_timestamped_report(folder, "Documentation_Gap_Report", summary.to_markdown())
        outputs = [str(report)]
        files = [str(report)]
        if write_csv:
            csv_path = write_timestamped_csv(folder, "Documentation_Gap_Table", summary.gap_rows)
            outputs.append(str(csv_path))
            files.append(str(csv_path))
    except Exception as exc:
        return ToolResult.fail(
            "documentation_gap_scanner", "EOAT Documentation Gap Scanner", "Could not write report.", errors=[str(exc)]
        )
    result = ToolResult.ok(
        "documentation_gap_scanner",
        "EOAT Documentation Gap Scanner",
        "Generated documentation gap report.",
        details=[f"Report: {report}"],
        files_created=files,
        output_reports=outputs,
        metrics=summary.metrics,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result
