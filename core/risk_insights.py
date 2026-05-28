from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .fmea_analysis import analyze_fmea
from .kpi_analysis import analyze_kpis
from .pilot_scoring import rank_pilot_candidates


@dataclass(frozen=True)
class RiskInsightSummary:
    metrics: dict[str, Any]
    top_risks: list[dict[str, Any]] = field(default_factory=list)
    top_pilot_candidates: list[dict[str, Any]] = field(default_factory=list)
    kpi_data_gaps: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_risk_insight_summary(project_root: str | Path) -> RiskInsightSummary:
    warnings: list[str] = []
    fmea, fmea_error = analyze_fmea(project_root)
    pilot, pilot_error = rank_pilot_candidates(project_root)
    kpi, kpi_error = analyze_kpis(project_root)
    for error in [fmea_error, pilot_error, kpi_error]:
        if error:
            warnings.append(error.summary)
            warnings.extend(error.errors)
    top_risks = list((fmea.ranked_rows if fmea else [])[:5])
    top_candidates = list((pilot.ranked_candidates if pilot else [])[:5])
    kpi_gaps = dict(kpi.missing_fields) if kpi else {}
    metrics = {
        "top_risk_count": len(top_risks),
        "pilot_candidate_count": len(top_candidates),
        "missing_kpi_fields_total": sum(kpi_gaps.values()),
        "top_rpn": fmea.metrics.get("top_rpn", 0) if fmea else 0,
        "top_pilot_score": top_candidates[0].get("Total Score", 0) if top_candidates else 0,
        "kpi_rows": kpi.metrics.get("kpi_rows", 0) if kpi else 0,
    }
    return RiskInsightSummary(
        metrics=metrics,
        top_risks=top_risks,
        top_pilot_candidates=top_candidates,
        kpi_data_gaps=kpi_gaps,
        warnings=warnings,
        recommended_actions=_recommended_actions(metrics, warnings),
    )


def _recommended_actions(metrics: dict[str, Any], warnings: list[str]) -> list[str]:
    actions: list[str] = []
    if warnings:
        actions.append("Resolve missing workbook inputs before treating risk insights as complete.")
    if metrics.get("top_rpn", 0):
        actions.append("Review the highest RPN FMEA entries and confirm recommended actions.")
    if metrics.get("pilot_candidate_count", 0):
        actions.append("Use the top pilot candidates as the first review set, then verify missing evidence and KPI baselines.")
    if metrics.get("missing_kpi_fields_total", 0):
        actions.append("Fill missing KPI baseline fields before defending pilot ROI.")
    if not actions:
        actions.append("Add FMEA, KPI, or pilot candidate data to generate risk insights.")
    return actions

