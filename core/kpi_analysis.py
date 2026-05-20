from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .analysis_common import count_by, numeric, table_from_counts, table_from_rows, write_timestamped_report
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory
from .workbook_io import row_dicts

KPI_REQUIRED_FIELDS = ["Date", "Press/Machine #", "Downtime Minutes", "Part Drops", "Mis-Picks", "Scrap Quantity", "Cycle Time", "Maintenance Event Count"]


@dataclass
class KpiSummary:
    metrics: dict[str, Any]
    by_press: list[dict[str, Any]] = field(default_factory=list)
    scrap_reasons: dict[str, int] = field(default_factory=dict)
    missing_fields: dict[str, int] = field(default_factory=dict)

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# KPI Dashboard Report",
                "",
                "## Executive Summary",
                f"- KPI rows: {self.metrics.get('kpi_rows', 0)}",
                f"- Total downtime minutes: {self.metrics.get('total_downtime_minutes', 0)}",
                f"- Part drops: {self.metrics.get('part_drops', 0)}",
                f"- Mis-picks: {self.metrics.get('mis_picks', 0)}",
                "",
                "## KPI By Press/Machine #",
                *table_from_rows(self.by_press, ["Press/Machine #", "Downtime Minutes", "Part Drops", "Mis-Picks", "Scrap Quantity", "Maintenance Events"]),
                "",
                "## Scrap Reasons",
                *table_from_counts(self.scrap_reasons, "Scrap Reason"),
                "",
                "## Missing KPI Data",
                *table_from_counts(self.missing_fields, "Field"),
                "",
                "## Recommended Next Steps",
                "- Collect baseline downtime, drops, mis-picks, scrap, cycle time, and maintenance data for candidate pilot cells.",
                "- Confirm whether downtime is EOAT-related for each KPI row.",
            ]
        ) + "\n"


def analyze_kpis(project_root: str | Path) -> tuple[KpiSummary | None, ToolResult | None]:
    workbook = resolve_project_paths(project_root).master_workbook
    if not workbook.exists():
        return None, ToolResult.fail("kpi_dashboard_builder", "KPI Dashboard Builder", "Master workbook is missing.", errors=[str(workbook)])
    try:
        kpis = row_dicts(workbook, "KPI Baseline")
    except Exception as exc:
        return None, ToolResult.fail("kpi_dashboard_builder", "KPI Dashboard Builder", "Could not read KPI Baseline.", errors=[str(exc)])
    totals = defaultdict(lambda: {"Downtime Minutes": 0.0, "Part Drops": 0.0, "Mis-Picks": 0.0, "Scrap Quantity": 0.0, "Maintenance Events": 0.0})
    missing = Counter()
    for row in kpis:
        press = str(row.get("Press/Machine #") or "Blank")
        totals[press]["Downtime Minutes"] += numeric(row.get("Downtime Minutes"))
        totals[press]["Part Drops"] += numeric(row.get("Part Drops"))
        totals[press]["Mis-Picks"] += numeric(row.get("Mis-Picks"))
        totals[press]["Scrap Quantity"] += numeric(row.get("Scrap Quantity"))
        totals[press]["Maintenance Events"] += numeric(row.get("Maintenance Event Count"))
        for field in KPI_REQUIRED_FIELDS:
            if not str(row.get(field) or "").strip():
                missing[field] += 1
    by_press = [{"Press/Machine #": press, **values} for press, values in totals.items()]
    by_press.sort(key=lambda row: float(row["Downtime Minutes"]), reverse=True)
    summary = KpiSummary(
        metrics={
            "kpi_rows": len(kpis),
            "total_downtime_minutes": sum(numeric(row.get("Downtime Minutes")) for row in kpis),
            "eoat_related_downtime_minutes": sum(numeric(row.get("Downtime Minutes")) for row in kpis if str(row.get("EOAT-Related Downtime?") or "").lower() == "yes"),
            "part_drops": sum(numeric(row.get("Part Drops")) for row in kpis),
            "mis_picks": sum(numeric(row.get("Mis-Picks")) for row in kpis),
            "scrap_quantity": sum(numeric(row.get("Scrap Quantity")) for row in kpis),
            "maintenance_event_count": sum(numeric(row.get("Maintenance Event Count")) for row in kpis),
            "missing_kpi_fields_total": sum(missing.values()),
        },
        by_press=by_press,
        scrap_reasons=count_by(kpis, "Scrap Reason"),
        missing_fields=dict(missing),
    )
    return summary, None


def generate_kpi_dashboard_report(project_root: str | Path, log_activity: bool = True) -> ToolResult:
    summary, error = analyze_kpis(project_root)
    if error:
        return error
    assert summary is not None
    folder = resolve_project_paths(project_root).kpi_dashboard_exports
    ensure_directory(folder)
    try:
        report = write_timestamped_report(folder, "KPI_Dashboard_Report", summary.to_markdown())
    except Exception as exc:
        return ToolResult.fail("kpi_dashboard_builder", "KPI Dashboard Builder", "Could not write report.", errors=[str(exc)])
    result = ToolResult.ok(
        "kpi_dashboard_builder",
        "KPI Dashboard Builder",
        "Generated KPI dashboard report.",
        details=[f"Report: {report}"],
        files_created=[str(report)],
        output_reports=[str(report)],
        metrics=summary.metrics,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result

