from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .analysis_common import OPEN_STATUSES, count_by, parse_score, table_from_counts, table_from_rows, write_timestamped_report
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory
from .workbook_io import row_dicts

EXPECTED_ISSUE_CATEGORIES = [
    "Vacuum loss",
    "Part drop",
    "Mis-pick",
    "Sensor issue",
    "Tubing issue",
    "Cable routing issue",
    "Mechanical wear",
    "Alignment issue",
    "Quick disconnect issue",
    "Fastener/hardware issue",
    "Documentation missing",
    "Safety concern",
    "Other",
]

FMEA_CATEGORY_SUGGESTIONS = {
    "Vacuum loss": "Vacuum loss causing part drop, mis-pick, scrap, or downtime.",
    "Part drop": "Part handling failure resulting in dropped part and production interruption.",
    "Mis-pick": "Incorrect part pickup due to alignment, cup placement, sensor, or robot position issue.",
    "Sensor issue": "Sensor detection failure causing false confirmation or missed part detection.",
    "Tubing issue": "Pneumatic tubing failure causing vacuum or gripper performance loss.",
    "Cable routing issue": "Cable routing failure causing intermittent sensor or EOAT signal faults.",
    "Mechanical wear": "Mechanical EOAT wear causing inconsistent grip or misalignment.",
    "Alignment issue": "EOAT alignment drift causing poor pickup or placement.",
    "Quick disconnect issue": "Quick disconnect mismatch or wear causing setup/reliability problems.",
    "Fastener/hardware issue": "Loose or missing hardware causing EOAT movement or damage.",
    "Documentation missing": "Missing documentation causing inconsistent maintenance or setup.",
    "Safety concern": "EOAT condition creates safety or ergonomic risk.",
}


@dataclass
class IssueAnalysisSummary:
    metrics: dict[str, Any]
    category_counts: dict[str, int] = field(default_factory=dict)
    press_counts: dict[str, int] = field(default_factory=dict)
    eoat_type_counts: dict[str, int] = field(default_factory=dict)
    robot_type_counts: dict[str, int] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    high_priority_issues: list[dict[str, Any]] = field(default_factory=list)
    missing_risk_rows: list[dict[str, Any]] = field(default_factory=list)
    suggested_fmea: list[dict[str, Any]] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            "# EOAT Issue Analysis Report",
            "",
            "## Executive Summary",
            f"- Issues logged: {self.metrics.get('issues_logged', 0)}",
            f"- Open issues: {self.metrics.get('open_issues', 0)}",
            f"- High-priority issues: {self.metrics.get('high_priority_count', 0)}",
            f"- Missing risk ranking rows: {self.metrics.get('missing_risk_count', 0)}",
            "",
            "## Issue Counts",
            "",
            "### By Category",
            *table_from_counts(self.category_counts, "Issue Category"),
            "",
            "### By Press/Machine #",
            *table_from_counts(self.press_counts, "Press/Machine #"),
            "",
            "### By EOAT Type",
            *table_from_counts(self.eoat_type_counts, "EOAT Type"),
            "",
            "### By Robot Type",
            *table_from_counts(self.robot_type_counts, "Robot Type"),
            "",
            "## Open/Resolved Status Summary",
            *table_from_counts(self.status_counts, "Status"),
            "",
            "## Missing Risk Ranking Data",
            *table_from_rows(self.missing_risk_rows, ["Issue ID", "Press/Machine #", "Issue Category", "Missing Fields"]),
            "",
            "## Suggested FMEA Candidate Failure Modes",
            *table_from_rows(self.suggested_fmea, ["Issue Category", "Issue Count", "Suggested Failure Mode"]),
            "",
            "## Recommended Follow-Up Actions",
            "- Add severity/frequency/detectability to open or recurring issues.",
            "- Convert repeated issue categories into FMEA-lite rows.",
            "- Review top problem cells with mentor before choosing pilot candidates.",
        ]
        if not self.metrics.get("issues_logged"):
            lines.insert(4, "- No issues logged yet. Start with Issue Log entries or audit/interview observations.")
        return "\n".join(lines) + "\n"


def analyze_issues(project_root: str | Path) -> tuple[IssueAnalysisSummary | None, ToolResult | None]:
    workbook = resolve_project_paths(project_root).master_workbook
    if not workbook.exists():
        return None, ToolResult.fail("issue_analysis", "Issue Analysis Tool", "Master workbook is missing.", errors=[str(workbook)])
    try:
        issues = row_dicts(workbook, "Issue Log")
    except Exception as exc:
        return None, ToolResult.fail("issue_analysis", "Issue Analysis Tool", "Could not read Issue Log.", errors=[str(exc)])

    category_counts = count_by(issues, "Issue Category")
    press_counts = count_by(issues, "Press/Machine #")
    eoat_type_counts = count_by(issues, "EOAT Type")
    robot_type_counts = count_by(issues, "Robot Type")
    status_counts = count_by(issues, "Status")
    missing_rows: list[dict[str, Any]] = []
    high_priority: list[dict[str, Any]] = []
    for row in issues:
        missing = [field for field in ["Severity", "Frequency", "Detectability"] if parse_score(row.get(field)) is None]
        if missing:
            missing_rows.append(
                {
                    "Issue ID": row.get("Issue ID", ""),
                    "Press/Machine #": row.get("Press/Machine #", ""),
                    "Issue Category": row.get("Issue Category", ""),
                    "Missing Fields": ", ".join(missing),
                }
            )
        sev = parse_score(row.get("Severity")) or 0
        freq = parse_score(row.get("Frequency")) or 0
        det = parse_score(row.get("Detectability")) or 0
        if sev * freq * det >= 125 or sev >= 8:
            high_priority.append(row)
    suggested = [
        {
            "Issue Category": category,
            "Issue Count": count,
            "Suggested Failure Mode": FMEA_CATEGORY_SUGGESTIONS.get(category, f"Recurring {category.lower()} failure mode."),
        }
        for category, count in sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))
        if category != "Blank"
    ]
    open_issues = sum(1 for row in issues if str(row.get("Status") or "").strip().lower() in OPEN_STATUSES)
    summary = IssueAnalysisSummary(
        metrics={
            "issues_logged": len(issues),
            "open_issues": open_issues,
            "resolved_or_closed_issues": max(0, len(issues) - open_issues),
            "high_priority_count": len(high_priority),
            "missing_risk_count": len(missing_rows),
            "top_issue_category": next(iter(sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))), ("No data yet", 0))[0],
        },
        category_counts=category_counts,
        press_counts=press_counts,
        eoat_type_counts=eoat_type_counts,
        robot_type_counts=robot_type_counts,
        status_counts=status_counts,
        high_priority_issues=high_priority,
        missing_risk_rows=missing_rows,
        suggested_fmea=suggested,
    )
    return summary, None


def generate_issue_analysis_report(project_root: str | Path, log_activity: bool = True) -> ToolResult:
    summary, error = analyze_issues(project_root)
    if error:
        return error
    assert summary is not None
    folder = resolve_project_paths(project_root).issue_analysis_reports
    ensure_directory(folder)
    try:
        report = write_timestamped_report(folder, "Issue_Analysis", summary.to_markdown())
    except Exception as exc:
        return ToolResult.fail("issue_analysis", "Issue Analysis Tool", "Could not write report.", errors=[str(exc)])
    result = ToolResult.ok(
        "issue_analysis",
        "Issue Analysis Tool",
        "Generated issue analysis report.",
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

