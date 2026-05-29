from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .analysis_common import table_from_counts, table_from_rows, write_timestamped_report
from .bad_actor_detector import detect_bad_actors
from .fmea_analysis import analyze_fmea
from .kpi_analysis import analyze_kpis
from .logging import log_tool_run
from .paths import resolve_project_paths
from .pilot_scoring import rank_pilot_candidates
from .result import ToolResult
from .risk_heatmap import RISK_LEVEL_CRITICAL, RISK_LEVEL_HIGH, build_risk_heatmap


@dataclass(frozen=True)
class RiskInsightSummary:
    metrics: dict[str, Any]
    top_risks: list[dict[str, Any]] = field(default_factory=list)
    top_pilot_candidates: list[dict[str, Any]] = field(default_factory=list)
    top_bad_actors: list[dict[str, Any]] = field(default_factory=list)
    top_heatmap_cells: list[dict[str, Any]] = field(default_factory=list)
    kpi_data_gaps: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [
            "# Integrated Risk Insight Report",
            "",
            "## Summary",
            *[f"- {key}: {value}" for key, value in self.metrics.items()],
            "",
            "## Top FMEA Risks",
            *table_from_rows(self.top_risks, ["FMEA ID", "Press/Machine #", "Failure Mode", "RPN", "Recommended Action"]),
            "",
            "## Top Pilot Candidates",
            *table_from_rows(
                self.top_pilot_candidates,
                ["Rank", "Candidate ID", "Press/Machine #", "Main Problem", "Total Score", "Confidence", "Missing Data"],
            ),
            "",
            "## Top Bad Actors",
            *table_from_rows(
                self.top_bad_actors,
                ["Machine", "Score", "Issue Count", "High Priority Count", "Critical Priority Count", "Missing Evidence", "Recommended Action"],
            ),
            "",
            "## Risk Heat Map Signals",
            *table_from_rows(
                self.top_heatmap_cells,
                ["Machine", "Failure Mode", "Risk Level", "Risk Score", "Evidence Count", "Recommended Action"],
            ),
            "",
            "## KPI Data Gaps",
            *table_from_counts(self.kpi_data_gaps, "Field"),
            "",
            "## Warnings",
            *([f"- {warning}" for warning in self.warnings] if self.warnings else ["No source warnings reported."]),
            "",
            "## Recommended Actions",
            *[f"- {action}" for action in self.recommended_actions],
            "",
            "## Evidence Rules",
            "- This report combines existing local analyses and does not modify the workbook.",
            "- KPI or pilot impact should not be claimed without before/after evidence.",
            "- Missing-source warnings should be resolved before final handoff decisions.",
        ]
        return "\n".join(lines) + "\n"


def build_risk_insight_summary(project_root: str | Path) -> RiskInsightSummary:
    warnings: list[str] = []
    fmea, fmea_error = analyze_fmea(project_root)
    pilot, pilot_error = rank_pilot_candidates(project_root)
    kpi, kpi_error = analyze_kpis(project_root)
    heatmap = build_risk_heatmap(project_root)
    bad_actors = detect_bad_actors(project_root)
    for error in [fmea_error, pilot_error, kpi_error]:
        if error:
            warnings.append(error.summary)
            warnings.extend(error.errors)
    warnings.extend(heatmap.warnings)
    warnings.extend(bad_actors.warnings)
    top_risks = list((fmea.ranked_rows if fmea else [])[:5])
    top_candidates = list((pilot.ranked_candidates if pilot else [])[:5])
    top_heatmap_cells = [
        {
            "Machine": cell.machine,
            "Failure Mode": cell.failure_mode,
            "Risk Level": cell.risk_level,
            "Risk Score": cell.risk_score,
            "Evidence Count": cell.evidence_count,
            "Recommended Action": cell.recommended_action,
        }
        for cell in sorted(
            [cell for cell in heatmap.cells if cell.risk_level in {RISK_LEVEL_CRITICAL, RISK_LEVEL_HIGH}],
            key=lambda item: (-item.risk_score, item.machine, item.failure_mode),
        )[:8]
    ]
    top_bad_actors = [
        {
            "Machine": item.machine,
            "Score": item.score,
            "Issue Count": item.issue_count,
            "High Priority Count": item.high_priority_count,
            "Critical Priority Count": item.critical_priority_count,
            "Missing Evidence": "; ".join(item.missing_evidence),
            "Recommended Action": item.recommended_action,
        }
        for item in bad_actors.rankings[:8]
        if item.score > 0
    ]
    kpi_gaps = dict(kpi.missing_fields) if kpi else {}
    metrics = {
        "top_risk_count": len(top_risks),
        "pilot_candidate_count": len(top_candidates),
        "top_bad_actor_count": len(top_bad_actors),
        "risk_heatmap_high_or_critical_count": len(top_heatmap_cells),
        "missing_kpi_fields_total": sum(kpi_gaps.values()),
        "top_rpn": fmea.metrics.get("top_rpn", 0) if fmea else 0,
        "top_pilot_score": top_candidates[0].get("Total Score", 0) if top_candidates else 0,
        "top_bad_actor_score": top_bad_actors[0].get("Score", 0) if top_bad_actors else 0,
        "kpi_rows": kpi.metrics.get("kpi_rows", 0) if kpi else 0,
    }
    return RiskInsightSummary(
        metrics=metrics,
        top_risks=top_risks,
        top_pilot_candidates=top_candidates,
        top_bad_actors=top_bad_actors,
        top_heatmap_cells=top_heatmap_cells,
        kpi_data_gaps=kpi_gaps,
        warnings=warnings,
        recommended_actions=_recommended_actions(metrics, warnings),
    )


def generate_risk_insights_report(project_root: str | Path, log_activity: bool = True) -> ToolResult:
    start = time.perf_counter()
    summary = build_risk_insight_summary(project_root)
    folder = resolve_project_paths(project_root).risk_insights_reports
    try:
        report = write_timestamped_report(folder, "Risk_Insight_Report", summary.to_markdown())
    except Exception as exc:
        return ToolResult.fail("risk_insights", "Risk Insights", "Could not write risk insight report.", errors=[str(exc)])
    result = ToolResult.ok(
        "risk_insights",
        "Risk Insights",
        "Generated integrated risk insight report.",
        details=["Workbook was not modified.", f"Report: {report}"],
        warnings=summary.warnings,
        files_created=[str(report)],
        output_reports=[str(report)],
        metrics=summary.metrics,
        structured_data=summary.to_dict(),
        duration_seconds=time.perf_counter() - start,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result


def _recommended_actions(metrics: dict[str, Any], warnings: list[str]) -> list[str]:
    actions: list[str] = []
    if warnings:
        actions.append("Resolve missing workbook inputs before treating risk insights as complete.")
    if metrics.get("top_rpn", 0):
        actions.append("Review the highest RPN FMEA entries and confirm recommended actions.")
    if metrics.get("pilot_candidate_count", 0):
        actions.append("Use the top pilot candidates as the first review set, then verify missing evidence and KPI baselines.")
    if metrics.get("top_bad_actor_score", 0):
        actions.append("Review the highest bad-actor machine score and confirm missing evidence before prioritizing corrective work.")
    if metrics.get("risk_heatmap_high_or_critical_count", 0):
        actions.append("Use high/critical heat-map cells to focus failure-mode follow-up discussions.")
    if metrics.get("missing_kpi_fields_total", 0):
        actions.append("Fill missing KPI baseline fields before defending pilot ROI.")
    if not actions:
        actions.append("Add FMEA, KPI, or pilot candidate data to generate risk insights.")
    return actions
