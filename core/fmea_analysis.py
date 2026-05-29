from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .analysis_common import parse_score, table_from_rows, write_timestamped_report
from .fmea_suggestions import build_fmea_suggestions
from .issue_analysis import FMEA_CATEGORY_SUGGESTIONS
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory
from .workbook_io import row_dicts

FMEA_MAPPINGS = {
    "Vacuum loss": ("Vacuum loss", "Part drop, mis-pick, scrap, downtime", "Worn cup, leaking tubing, poor seal, vacuum generator issue", "Operator observation, vacuum confirmation sensor if present", "Standardize cup selection, inspect tubing, verify vacuum sensor"),
    "Mis-pick": ("Incorrect part pickup", "Scrap, downstream jam, robot fault, downtime", "EOAT misalignment, poor cup placement, sensor failure, robot position drift", "Operator observation, robot alarm if present", "Verify EOAT alignment, add/standardize part-present detection"),
    "Tubing issue": ("Pneumatic tubing failure", "Vacuum loss, gripper failure, intermittent part handling", "Pinch point, abrasion, poor routing, heat exposure", "Visual inspection", "Standardize tubing routing and PM inspection"),
    "Sensor issue": ("Sensor detection failure", "Robot continues without part confirmation or false reject", "Damaged sensor, misalignment, loose cable, poor mounting", "Sensor check, operator response", "Standardize sensor mounting and verification process"),
    "Mechanical wear": ("Mechanical EOAT wear", "Poor pickup, misalignment, inconsistent grip", "Worn fingers, loose hardware, repeated impacts", "Visual inspection", "Add rebuild/inspection standard and locking hardware"),
}


@dataclass
class FmeaSummary:
    metrics: dict[str, Any]
    ranked_rows: list[dict[str, Any]] = field(default_factory=list)
    missing_risk_rows: list[dict[str, Any]] = field(default_factory=list)
    missing_action_rows: list[dict[str, Any]] = field(default_factory=list)
    suggestions: list[dict[str, Any]] = field(default_factory=list)

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# FMEA-Lite Report",
                "",
                "## Executive Summary",
                f"- Existing FMEA rows: {self.metrics.get('existing_fmea_rows', 0)}",
                f"- Suggested new entries: {self.metrics.get('suggested_entries', 0)}",
                f"- Rows missing risk ranking: {self.metrics.get('missing_risk_rows', 0)}",
                "",
                "## Existing FMEA Ranking",
                *table_from_rows(self.ranked_rows[:15], ["FMEA ID", "Press/Machine #", "Failure Mode", "RPN", "Recommended Action"]),
                "",
                "## Top 5 Risks By RPN",
                *table_from_rows(self.ranked_rows[:5], ["FMEA ID", "Failure Mode", "RPN", "Recommended Action"]),
                "",
                "## Missing Risk Ranking Data",
                *table_from_rows(self.missing_risk_rows, ["FMEA ID", "Failure Mode", "Missing Fields"]),
                "",
                "## Suggested New FMEA Entries",
                *table_from_rows(
                    self.suggestions,
                    [
                        "Failure Mode",
                        "Confidence",
                        "Calculated RPN",
                        "Evidence",
                        "Suggested Severity",
                        "Suggested Frequency",
                        "Suggested Detectability",
                        "Suggested Mitigation",
                        "Review Status",
                    ],
                ),
                "",
                "## Recommended Mitigations",
                "- Fill missing severity/frequency/detectability values.",
                "- Add recommended actions for rows with high RPN.",
                "- Review suggested entries before applying anything to the workbook.",
            ]
        ) + "\n"


def analyze_fmea(project_root: str | Path) -> tuple[FmeaSummary | None, ToolResult | None]:
    workbook = resolve_project_paths(project_root).master_workbook
    if not workbook.exists():
        return None, ToolResult.fail("fmea_lite_builder", "FMEA-Lite Builder", "Master workbook is missing.", errors=[str(workbook)])
    try:
        fmea_rows = row_dicts(workbook, "FMEA Draft")
        issues = row_dicts(workbook, "Issue Log")
    except Exception as exc:
        return None, ToolResult.fail("fmea_lite_builder", "FMEA-Lite Builder", "Could not read workbook.", errors=[str(exc)])
    ranked = []
    missing_risk = []
    missing_action = []
    for row in fmea_rows:
        sev = parse_score(row.get("Severity"))
        freq = parse_score(row.get("Frequency"))
        det = parse_score(row.get("Detectability"))
        missing = [field for field, value in [("Severity", sev), ("Frequency", freq), ("Detectability", det)] if value is None]
        row_copy = dict(row)
        if missing:
            missing_risk.append({"FMEA ID": row.get("FMEA ID", ""), "Failure Mode": row.get("Failure Mode", ""), "Missing Fields": ", ".join(missing)})
            rpn = parse_score(row.get("RPN")) or 0
        else:
            rpn = int(sev or 0) * int(freq or 0) * int(det or 0)
        row_copy["RPN"] = rpn
        ranked.append(row_copy)
        if not str(row.get("Recommended Action") or "").strip():
            missing_action.append({"FMEA ID": row.get("FMEA ID", ""), "Failure Mode": row.get("Failure Mode", ""), "Missing Fields": "Recommended Action"})
    ranked.sort(key=lambda item: int(item.get("RPN") or 0), reverse=True)
    suggestions = build_fmea_suggestions(project_root)
    summary = FmeaSummary(
        metrics={
            "existing_fmea_rows": len(fmea_rows),
            "suggested_entries": len(suggestions),
            "missing_risk_rows": len(missing_risk),
            "missing_recommended_action_rows": len(missing_action),
            "top_rpn": ranked[0].get("RPN", 0) if ranked else 0,
            "top_failure_mode": ranked[0].get("Failure Mode", "No data yet") if ranked else "No data yet",
        },
        ranked_rows=ranked,
        missing_risk_rows=missing_risk,
        missing_action_rows=missing_action,
        suggestions=suggestions,
    )
    return summary, None


def generate_fmea_report(project_root: str | Path, log_activity: bool = True) -> ToolResult:
    summary, error = analyze_fmea(project_root)
    if error:
        return error
    assert summary is not None
    folder = resolve_project_paths(project_root).fmea_reports
    ensure_directory(folder)
    try:
        report = write_timestamped_report(folder, "FMEA_Lite_Report", summary.to_markdown())
    except Exception as exc:
        return ToolResult.fail("fmea_lite_builder", "FMEA-Lite Builder", "Could not write report.", errors=[str(exc)])
    result = ToolResult.ok(
        "fmea_lite_builder",
        "FMEA-Lite Builder",
        "Generated FMEA-lite report.",
        details=[f"Report: {report}", "Workbook was not modified."],
        files_created=[str(report)],
        output_reports=[str(report)],
        metrics=summary.metrics,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result
