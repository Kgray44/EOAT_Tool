from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .analysis_common import count_by, numeric, table_from_counts, table_from_rows, write_timestamped_report
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory
from .workbook_io import row_dicts

KPI_REQUIRED_FIELDS = [
    "Date",
    "Press/Machine #",
    "Downtime Minutes",
    "Part Drops",
    "Mis-Picks",
    "Scrap Quantity",
    "Cycle Time",
    "Maintenance Event Count",
]
KPI_METRIC_FIELDS = ["Downtime Minutes", "Part Drops", "Mis-Picks", "Scrap Quantity", "Maintenance Event Count"]
KPI_SOURCE_TYPES = ["actual measured data", "audit-observed data", "estimated/subjective data", "missing data"]


@dataclass(frozen=True)
class KpiTruthLabel:
    metric: str
    source_type: str
    date_range: str
    record_count: int
    total_records: int
    confidence: str
    missing_data_warning: str
    source_breakdown: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "Metric": self.metric,
            "Source Type": self.source_type,
            "Date Range": self.date_range,
            "Record Count": self.record_count,
            "Total Records": self.total_records,
            "Confidence": self.confidence,
            "Missing Data Warning": self.missing_data_warning,
            "Source Breakdown": _format_source_breakdown(self.source_breakdown),
        }

    def card_detail(self) -> str:
        return (
            f"Source: {self.source_type}\n"
            f"Range: {self.date_range}\n"
            f"Records: {self.record_count}/{self.total_records}\n"
            f"Confidence: {self.confidence}\n"
            f"Missing: {self.missing_data_warning}"
        )


@dataclass
class KpiSummary:
    metrics: dict[str, Any]
    by_press: list[dict[str, Any]] = field(default_factory=list)
    scrap_reasons: dict[str, int] = field(default_factory=dict)
    missing_fields: dict[str, int] = field(default_factory=dict)
    truth_labels: list[KpiTruthLabel] = field(default_factory=list)
    missing_data_warnings: list[str] = field(default_factory=list)

    @property
    def truth_by_metric(self) -> dict[str, KpiTruthLabel]:
        return {label.metric: label for label in self.truth_labels}

    def card_truth(self, metric: str) -> KpiTruthLabel | None:
        return self.truth_by_metric.get(metric)

    def to_markdown(self) -> str:
        truth_rows = [label.to_dict() for label in self.truth_labels]
        return (
            "\n".join(
                [
                    "# KPI Dashboard Report",
                    "",
                    "## Executive Summary",
                    f"- KPI rows: {self.metrics.get('kpi_rows', 0)}",
                    f"- Total downtime minutes: {self.metrics.get('total_downtime_minutes', 0)}",
                    f"- Part drops: {self.metrics.get('part_drops', 0)}",
                    f"- Mis-picks: {self.metrics.get('mis_picks', 0)}",
                    f"- Overall KPI confidence: {self.metrics.get('overall_confidence', 'Missing')}",
                    f"- Date range: {self.metrics.get('date_range', 'No dated records')}",
                    "",
                    "## KPI By Press/Machine #",
                    *table_from_rows(
                        self.by_press,
                        [
                            "Press/Machine #",
                            "Downtime Minutes",
                            "Part Drops",
                            "Mis-Picks",
                            "Scrap Quantity",
                            "Maintenance Events",
                            "Source Type",
                            "Date Range",
                            "Record Count",
                            "Confidence",
                            "Missing Data Warning",
                        ],
                    ),
                    "",
                    "## KPI Truth And Confidence",
                    *table_from_rows(
                        truth_rows,
                        [
                            "Metric",
                            "Source Type",
                            "Date Range",
                            "Record Count",
                            "Total Records",
                            "Confidence",
                            "Missing Data Warning",
                            "Source Breakdown",
                        ],
                    ),
                    "",
                    "## Scrap Reasons",
                    *table_from_counts(self.scrap_reasons, "Scrap Reason"),
                    "",
                    "## Missing KPI Data",
                    *table_from_counts(self.missing_fields, "Field"),
                    "",
                    "## Missing-Data Warnings",
                    *(
                        [f"- {warning}" for warning in self.missing_data_warnings]
                        if self.missing_data_warnings
                        else ["No missing-data warnings."]
                    ),
                    "",
                    "## Recommended Next Steps",
                    "- Collect baseline downtime, drops, mis-picks, scrap, cycle time, and maintenance data for candidate pilot cells.",
                    "- Confirm whether downtime is EOAT-related for each KPI row.",
                ]
            )
            + "\n"
        )


def analyze_kpis(project_root: str | Path) -> tuple[KpiSummary | None, ToolResult | None]:
    workbook = resolve_project_paths(project_root).master_workbook
    if not workbook.exists():
        return None, ToolResult.fail(
            "kpi_dashboard_builder", "KPI Dashboard Builder", "Master workbook is missing.", errors=[str(workbook)]
        )
    try:
        kpis = row_dicts(workbook, "KPI Baseline")
    except Exception as exc:
        return None, ToolResult.fail(
            "kpi_dashboard_builder", "KPI Dashboard Builder", "Could not read KPI Baseline.", errors=[str(exc)]
        )
    totals = defaultdict(
        lambda: {
            "Downtime Minutes": 0.0,
            "Part Drops": 0.0,
            "Mis-Picks": 0.0,
            "Scrap Quantity": 0.0,
            "Maintenance Events": 0.0,
        }
    )
    by_press_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    missing = Counter()
    for row in kpis:
        press = str(row.get("Press/Machine #") or "Blank")
        by_press_rows[press].append(row)
        totals[press]["Downtime Minutes"] += numeric(row.get("Downtime Minutes"))
        totals[press]["Part Drops"] += numeric(row.get("Part Drops"))
        totals[press]["Mis-Picks"] += numeric(row.get("Mis-Picks"))
        totals[press]["Scrap Quantity"] += numeric(row.get("Scrap Quantity"))
        totals[press]["Maintenance Events"] += numeric(row.get("Maintenance Event Count"))
        for field in KPI_REQUIRED_FIELDS:
            if not str(row.get(field) or "").strip():
                missing[field] += 1
    truth_labels = [_truth_label_for_metric(kpis, field) for field in KPI_METRIC_FIELDS]
    press_truth = {press: _truth_label_for_press(press, rows) for press, rows in by_press_rows.items()}
    by_press = [
        {
            "Press/Machine #": press,
            **values,
            "Source Type": press_truth[press].source_type,
            "Date Range": press_truth[press].date_range,
            "Record Count": f"{press_truth[press].record_count}/{press_truth[press].total_records}",
            "Confidence": press_truth[press].confidence,
            "Missing Data Warning": press_truth[press].missing_data_warning,
        }
        for press, values in totals.items()
    ]
    by_press.sort(key=lambda row: float(row["Downtime Minutes"]), reverse=True)
    date_range = _date_range_for_rows(kpis)
    missing_data_warnings = [
        label.missing_data_warning for label in truth_labels if label.missing_data_warning != "None obvious"
    ]
    if not kpis:
        missing_data_warnings.append("No KPI Baseline rows found.")
    summary = KpiSummary(
        metrics={
            "kpi_rows": len(kpis),
            "total_downtime_minutes": sum(numeric(row.get("Downtime Minutes")) for row in kpis),
            "eoat_related_downtime_minutes": sum(
                numeric(row.get("Downtime Minutes"))
                for row in kpis
                if str(row.get("EOAT-Related Downtime?") or "").lower() == "yes"
            ),
            "part_drops": sum(numeric(row.get("Part Drops")) for row in kpis),
            "mis_picks": sum(numeric(row.get("Mis-Picks")) for row in kpis),
            "scrap_quantity": sum(numeric(row.get("Scrap Quantity")) for row in kpis),
            "maintenance_event_count": sum(numeric(row.get("Maintenance Event Count")) for row in kpis),
            "missing_kpi_fields_total": sum(missing.values()),
            "overall_confidence": _overall_confidence(truth_labels),
            "date_range": date_range,
            "measured_record_count": sum(
                label.source_breakdown.get("actual measured data", 0) for label in truth_labels
            ),
            "audit_observed_record_count": sum(
                label.source_breakdown.get("audit-observed data", 0) for label in truth_labels
            ),
            "estimated_subjective_record_count": sum(
                label.source_breakdown.get("estimated/subjective data", 0) for label in truth_labels
            ),
            "missing_metric_record_count": sum(label.source_breakdown.get("missing data", 0) for label in truth_labels),
        },
        by_press=by_press,
        scrap_reasons=count_by(kpis, "Scrap Reason"),
        missing_fields=dict(missing),
        truth_labels=truth_labels,
        missing_data_warnings=missing_data_warnings,
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
        return ToolResult.fail(
            "kpi_dashboard_builder", "KPI Dashboard Builder", "Could not write report.", errors=[str(exc)]
        )
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


def _truth_label_for_metric(rows: list[dict[str, Any]], metric: str) -> KpiTruthLabel:
    total_records = len(rows)
    source_counts: Counter[str] = Counter()
    dated_rows: list[dict[str, Any]] = []
    for row in rows:
        if _is_missing_value(row.get(metric)):
            source_counts["missing data"] += 1
            continue
        source_type = _classify_kpi_source(row, metric)
        source_counts[source_type] += 1
        dated_rows.append(row)
    record_count = total_records - source_counts["missing data"]
    missing_count = source_counts["missing data"]
    warning = _missing_warning(metric, missing_count, total_records)
    source_type = _aggregate_source_type(source_counts)
    return KpiTruthLabel(
        metric=metric,
        source_type=source_type,
        date_range=_date_range_for_rows(dated_rows),
        record_count=record_count,
        total_records=total_records,
        confidence=_confidence_for_counts(source_counts, total_records),
        missing_data_warning=warning,
        source_breakdown={key: int(source_counts.get(key, 0)) for key in KPI_SOURCE_TYPES},
    )


def _truth_label_for_press(press: str, rows: list[dict[str, Any]]) -> KpiTruthLabel:
    source_counts: Counter[str] = Counter()
    dated_rows: list[dict[str, Any]] = []
    for row in rows:
        row_has_value = False
        for metric in KPI_METRIC_FIELDS:
            if _is_missing_value(row.get(metric)):
                source_counts["missing data"] += 1
                continue
            row_has_value = True
            source_counts[_classify_kpi_source(row, metric)] += 1
        if row_has_value:
            dated_rows.append(row)
    total_metric_slots = len(rows) * len(KPI_METRIC_FIELDS)
    return KpiTruthLabel(
        metric=press,
        source_type=_aggregate_source_type(source_counts),
        date_range=_date_range_for_rows(dated_rows),
        record_count=total_metric_slots - source_counts["missing data"],
        total_records=total_metric_slots,
        confidence=_confidence_for_counts(source_counts, total_metric_slots),
        missing_data_warning=_missing_warning("KPI metric fields", source_counts["missing data"], total_metric_slots),
        source_breakdown={key: int(source_counts.get(key, 0)) for key in KPI_SOURCE_TYPES},
    )


def _classify_kpi_source(row: dict[str, Any], metric: str) -> str:
    text = " ".join(
        str(row.get(field) or "") for field in ["Data Source", "Notes", "Maintenance Notes", "Scrap Reason"]
    ).casefold()
    value_text = str(row.get(metric) or "").casefold()
    combined = f"{text} {value_text}"
    if any(
        token in combined
        for token in ["estimate", "estimated", "approx", "about ", "~", "rough", "subjective", "assumed", "guess"]
    ):
        return "estimated/subjective data"
    if any(
        token in combined
        for token in [
            "mes",
            "plc",
            "historian",
            "counter",
            "meter",
            "sensor",
            "measured",
            "automatic",
            "export",
            "system",
            "shift log extract",
        ]
    ):
        return "actual measured data"
    if any(
        token in combined
        for token in [
            "audit",
            "observed",
            "manual",
            "operator",
            "technician",
            "maintenance",
            "interview",
            "shift notes",
            "visual",
        ]
    ):
        return "audit-observed data"
    return "audit-observed data"


def _aggregate_source_type(source_counts: Counter[str]) -> str:
    non_missing = {key: count for key, count in source_counts.items() if key != "missing data" and count}
    if not non_missing:
        return "missing data"
    if len(non_missing) == 1:
        return next(iter(non_missing))
    ordered = [key for key in KPI_SOURCE_TYPES if key in non_missing]
    return f"mixed: {', '.join(ordered)}"


def _confidence_for_counts(source_counts: Counter[str], total_records: int) -> str:
    if total_records <= 0:
        return "Missing"
    non_missing = total_records - source_counts["missing data"]
    if non_missing <= 0:
        return "Missing"
    missing_ratio = source_counts["missing data"] / total_records
    measured_ratio = source_counts["actual measured data"] / non_missing
    estimated_ratio = source_counts["estimated/subjective data"] / non_missing
    if missing_ratio == 0 and measured_ratio >= 0.75:
        return "High"
    if missing_ratio <= 0.25 and estimated_ratio <= 0.25:
        return "Medium" if measured_ratio < 0.75 else "High"
    if missing_ratio < 0.75 and estimated_ratio < 0.75:
        return "Low"
    return "Low"


def _overall_confidence(labels: list[KpiTruthLabel]) -> str:
    if not labels:
        return "Missing"
    scores = {"High": 3, "Medium": 2, "Low": 1, "Missing": 0}
    average = sum(scores.get(label.confidence, 0) for label in labels) / len(labels)
    if average >= 2.6:
        return "High"
    if average >= 1.6:
        return "Medium"
    if average > 0:
        return "Low"
    return "Missing"


def _missing_warning(metric: str, missing_count: int, total_records: int) -> str:
    if total_records <= 0:
        return f"No KPI Baseline records available for {metric}."
    if missing_count <= 0:
        return "None obvious"
    return f"{missing_count} of {total_records} record(s) missing {metric}."


def _date_range_for_rows(rows: list[dict[str, Any]]) -> str:
    dates = sorted(parsed for row in rows if (parsed := _parse_date(row.get("Date"))) is not None)
    if not dates:
        return "No dated records"
    first = dates[0].isoformat()
    last = dates[-1].isoformat()
    return first if first == last else f"{first} to {last}"


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"]:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _is_missing_value(value: Any) -> bool:
    return not str(value or "").strip()


def _format_source_breakdown(source_breakdown: dict[str, int]) -> str:
    parts = [f"{source}: {count}" for source, count in source_breakdown.items() if count]
    return ", ".join(parts) or "missing data: 0"


__all__ = [
    "KPI_METRIC_FIELDS",
    "KPI_SOURCE_TYPES",
    "KpiSummary",
    "KpiTruthLabel",
    "analyze_kpis",
    "generate_kpi_dashboard_report",
]
