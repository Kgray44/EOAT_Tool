from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .analysis_common import numeric, table_from_rows, write_timestamped_report
from .audit_entries import repair_legacy_audit_lookup_shift
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory
from .tool_fields import LEGACY_TOOL_FIELD, TOOL_FIELD
from .workbook_io import row_dicts

DEFAULT_PILOT_SCORE_WEIGHTS: dict[str, float] = {
    "downtime_reliability": 0.30,
    "quality_scrap": 0.25,
    "ease": 0.15,
    "safety_maintenance": 0.15,
    "standardization": 0.15,
}

PILOT_SCORE_LABELS: dict[str, str] = {
    "downtime_reliability": "Downtime/Reliability",
    "quality_scrap": "Quality/Scrap",
    "ease": "Ease",
    "safety_maintenance": "Safety/Maintenance",
    "standardization": "Standardization",
}

PILOT_SCORE_FIELDS: dict[str, str] = {
    "downtime_reliability": "Downtime/Reliability Score",
    "quality_scrap": "Quality/Scrap Score",
    "ease": "Ease Score",
    "safety_maintenance": "Safety/Maintenance Score",
    "standardization": "Standardization Score",
}


@dataclass
class PilotRankingSummary:
    metrics: dict[str, Any]
    ranked_candidates: list[dict[str, Any]] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=lambda: DEFAULT_PILOT_SCORE_WEIGHTS.copy())
    sensitivity_rows: list[dict[str, Any]] = field(default_factory=list)

    def to_markdown(self) -> str:
        weight_lines = [
            f"- {PILOT_SCORE_LABELS[key]}: {round(value * 100)}%"
            for key, value in self.weights.items()
            if key in PILOT_SCORE_LABELS
        ]
        return (
            "\n".join(
                [
                    "# Pilot Candidate Ranking Report",
                    "",
                    "## Executive Summary",
                    f"- Candidates evaluated: {self.metrics.get('candidates_evaluated', 0)}",
                    f"- Top candidate: {self.metrics.get('top_candidate', 'No data yet')}",
                    f"- Top score: {self.metrics.get('top_score', 0)}",
                    "",
                    "## Ranked Candidates",
                    *table_from_rows(
                        self.ranked_candidates,
                        [
                            "Rank",
                            "Candidate ID",
                            "Press/Machine #",
                            "Main Problem",
                            "Total Score",
                            "Confidence",
                            "Missing Evidence",
                        ],
                    ),
                    "",
                    "## Score Explanations",
                    *table_from_rows(
                        self.ranked_candidates,
                        [
                            "Rank",
                            "Candidate ID",
                            "Downtime/Reliability Score",
                            "Quality/Scrap Score",
                            "Ease Score",
                            "Safety/Maintenance Score",
                            "Standardization Score",
                            "Score Explanation",
                        ],
                    ),
                    "",
                    "## Scoring Method",
                    *weight_lines,
                    "- Scores are evidence weighted. Missing evidence is shown separately and does not become fake certainty.",
                    "- Weights can be adjusted by callers; values are normalized before scoring.",
                    "",
                    "## Sensitivity Analysis",
                    *table_from_rows(
                        self.sensitivity_rows,
                        ["Candidate ID", "Press/Machine #", "Most Sensitive Weight", "Approx +/-10pt Weight Swing"],
                    ),
                    "",
                    "## Recommended Top 1-2 Pilot Candidates",
                    *table_from_rows(
                        self.ranked_candidates[:2],
                        ["Rank", "Press/Machine #", "Total Score", "Confidence", "Recommended Action"],
                    ),
                    "",
                    "## Next Data To Collect",
                    "- Confirm downtime, drops, scrap, and maintenance baseline data.",
                    "- Add before/after measurement plan before final pilot selection.",
                ]
            )
            + "\n"
        )


def normalize_pilot_weights(weights: dict[str, Any] | None = None) -> dict[str, float]:
    selected = DEFAULT_PILOT_SCORE_WEIGHTS.copy()
    for key, value in (weights or {}).items():
        internal_key = _weight_key(key)
        if internal_key not in selected:
            continue
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            continue
        selected[internal_key] = max(0.0, numeric_value)
    total = sum(selected.values())
    if total <= 0:
        return DEFAULT_PILOT_SCORE_WEIGHTS.copy()
    return {key: value / total for key, value in selected.items()}


def _candidate_from_inventory(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "Candidate ID": row.get("Audit ID", ""),
        "Date Added": "",
        "Plant/Area": row.get("Plant/Area", ""),
        "Press/Machine #": row.get("Press/Machine #", ""),
        "Robot Type": row.get("Robot Type", ""),
        TOOL_FIELD: row.get(TOOL_FIELD, "") or row.get(LEGACY_TOOL_FIELD, ""),
        "Part Family": row.get("Part Family", ""),
        "EOAT Type": row.get("EOAT Type", ""),
        "Main Problem": row.get("Known Issues", "") or row.get("Status", ""),
        "Evidence": row.get("Notes", ""),
        "Estimated Impact": row.get("Priority", ""),
        "Ease of Implementation": "",
        "Safety/Quality Risk": "Yes" if _yes(row.get("Scrap/Quality Concern?")) else "",
        "Expected KPI Improvement": "",
        "Recommended Action": "Review as pilot candidate from EOAT Inventory flag.",
        "Approval Status": "",
        "Notes": "Suggested from EOAT Inventory.",
    }


def rank_pilot_candidates(
    project_root: str | Path, weights: dict[str, Any] | None = None
) -> tuple[PilotRankingSummary | None, ToolResult | None]:
    workbook = resolve_project_paths(project_root).master_workbook
    if not workbook.exists():
        return None, ToolResult.fail(
            "pilot_candidate_ranking",
            "Pilot Candidate Ranking Tool",
            "Master workbook is missing.",
            errors=[str(workbook)],
        )
    try:
        candidates = row_dicts(workbook, "Pilot Candidates")
        inventory = [repair_legacy_audit_lookup_shift(row) for row in row_dicts(workbook, "EOAT Inventory")]
        issues = row_dicts(workbook, "Issue Log")
        kpis = row_dicts(workbook, "KPI Baseline")
        photos = row_dicts(workbook, "Photo Index")
    except Exception as exc:
        return None, ToolResult.fail(
            "pilot_candidate_ranking", "Pilot Candidate Ranking Tool", "Could not read workbook.", errors=[str(exc)]
        )
    if not candidates:
        candidates = [
            _candidate_from_inventory(row)
            for row in inventory
            if str(row.get("Pilot Candidate?") or "").lower() in {"yes", "maybe"}
            or str(row.get("Status") or "").lower() == "candidate for pilot"
        ]
    selected_weights = normalize_pilot_weights(weights)
    ranked: list[dict[str, Any]] = []
    photo_press = {str(row.get("Press/Machine #") or "") for row in photos}
    for candidate in candidates:
        press = str(candidate.get("Press/Machine #") or "")
        related_issues = [row for row in issues if str(row.get("Press/Machine #") or "") == press]
        related_kpi = [row for row in kpis if str(row.get("Press/Machine #") or "") == press]
        related_audit = [row for row in inventory if str(row.get("Press/Machine #") or "") == press]
        component_scores = _component_scores(
            candidate, related_issues, related_kpi, related_audit, press in photo_press
        )
        total = round(sum(component_scores[key] * selected_weights[key] for key in DEFAULT_PILOT_SCORE_WEIGHTS))
        evidence_count = sum(
            bool(item)
            for item in [
                related_issues,
                related_kpi,
                related_audit,
                press in photo_press,
                candidate.get("Expected KPI Improvement"),
                candidate.get("Ease of Implementation"),
            ]
        )
        confidence = "High" if evidence_count >= 4 else "Medium" if evidence_count >= 2 else "Low"
        missing = _missing_evidence(candidate, related_issues, related_kpi, related_audit, press in photo_press)
        baseline = _baseline_metrics(related_kpi)
        explanation = _score_explanation(component_scores, baseline, related_issues, candidate, related_audit)
        row = {
            **candidate,
            **baseline,
            "Issue Count": len(related_issues),
            "Total Score": total,
            "Impact Score": round(
                (component_scores["downtime_reliability"] * 0.55) + (component_scores["quality_scrap"] * 0.45)
            ),
            "Frequency Score": min(
                100, len(related_issues) * 20 + baseline["Baseline Part Drops"] * 4 + baseline["Baseline Mis-Picks"] * 4
            ),
            "Measurement Score": min(
                100,
                (35 if related_kpi else 0)
                + (25 if candidate.get("Expected KPI Improvement") else 0)
                + (20 if press in photo_press else 0),
            ),
            "Safety Score": component_scores["safety_maintenance"],
            "Confidence": confidence,
            "Missing Evidence": ", ".join(missing) or "None obvious",
            "Missing Data": ", ".join(missing) or "None obvious",
            "Score Explanation": explanation,
        }
        for key, field in PILOT_SCORE_FIELDS.items():
            row[field] = component_scores[key]
        row["Sensitivity Analysis"] = _candidate_sensitivity(row, component_scores, selected_weights)
        ranked.append(row)
    ranked.sort(key=lambda row: int(row.get("Total Score") or 0), reverse=True)
    for index, row in enumerate(ranked, start=1):
        row["Rank"] = index
    sensitivity_rows = [_sensitivity_row(row, selected_weights) for row in ranked]
    summary = PilotRankingSummary(
        metrics={
            "candidates_evaluated": len(ranked),
            "top_candidate": ranked[0].get("Press/Machine #", "No data yet") if ranked else "No data yet",
            "top_score": ranked[0].get("Total Score", 0) if ranked else 0,
        },
        ranked_candidates=ranked,
        weights=selected_weights,
        sensitivity_rows=sensitivity_rows,
    )
    return summary, None


def generate_pilot_ranking_report(project_root: str | Path, log_activity: bool = True) -> ToolResult:
    summary, error = rank_pilot_candidates(project_root)
    if error:
        return error
    assert summary is not None
    folder = resolve_project_paths(project_root).pilot_project / "Candidate_Cells"
    ensure_directory(folder)
    try:
        report = write_timestamped_report(folder, "Pilot_Candidate_Ranking", summary.to_markdown())
    except Exception as exc:
        return ToolResult.fail(
            "pilot_candidate_ranking", "Pilot Candidate Ranking Tool", "Could not write report.", errors=[str(exc)]
        )
    result = ToolResult.ok(
        "pilot_candidate_ranking",
        "Pilot Candidate Ranking Tool",
        "Generated pilot candidate ranking report.",
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


def _component_scores(
    candidate: dict[str, Any],
    issues: list[dict[str, Any]],
    kpis: list[dict[str, Any]],
    audits: list[dict[str, Any]],
    has_photos: bool,
) -> dict[str, int]:
    baseline = _baseline_metrics(kpis)
    downtime = baseline["Baseline Downtime Minutes"]
    drops = baseline["Baseline Part Drops"]
    mispicks = baseline["Baseline Mis-Picks"]
    scrap = baseline["Baseline Scrap Quantity"]
    maintenance_events = baseline["Baseline Maintenance Events"]
    downtime_reliability = min(
        100,
        int(downtime * 1.2)
        + int(drops * 6)
        + int(mispicks * 6)
        + len(issues) * 12
        + int(maintenance_events * 8)
        + _impact_boost(candidate.get("Estimated Impact")),
    )
    quality_scrap = min(
        100,
        int(scrap * 5)
        + int(drops * 4)
        + int(mispicks * 4)
        + (20 if _truthy(candidate.get("Safety/Quality Risk")) else 0)
        + _audit_yes_count(audits, "Scrap/Quality Concern?") * 15,
    )
    ease = _ease_score(candidate.get("Ease of Implementation"))
    if not candidate.get("Ease of Implementation") and has_photos:
        ease = max(ease, 50)
    safety_maintenance = min(
        100,
        (25 if _truthy(candidate.get("Safety/Quality Risk")) else 0)
        + int(maintenance_events * 12)
        + _priority_score(candidate.get("Estimated Impact"))
        + _audit_yes_count(audits, "Follow-Up Needed") * 10
        + _maintenance_frequency_score(audits),
    )
    standardization = min(
        100,
        (25 if candidate.get("Required Parts/Resources") else 0)
        + (20 if candidate.get("EOAT Type") else 0)
        + (15 if len(audits) > 1 else 0)
        + _documentation_gap_score(audits)
        + (10 if has_photos else 0),
    )
    return {
        "downtime_reliability": downtime_reliability,
        "quality_scrap": quality_scrap,
        "ease": ease,
        "safety_maintenance": safety_maintenance,
        "standardization": standardization,
    }


def _baseline_metrics(kpis: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "Baseline Downtime Minutes": round(sum(numeric(row.get("Downtime Minutes")) for row in kpis), 2),
        "Baseline Part Drops": round(sum(numeric(row.get("Part Drops")) for row in kpis), 2),
        "Baseline Mis-Picks": round(sum(numeric(row.get("Mis-Picks")) for row in kpis), 2),
        "Baseline Scrap Quantity": round(sum(numeric(row.get("Scrap Quantity")) for row in kpis), 2),
        "Baseline Maintenance Events": round(sum(numeric(row.get("Maintenance Event Count")) for row in kpis), 2),
    }


def _missing_evidence(
    candidate: dict[str, Any],
    issues: list[dict[str, Any]],
    kpis: list[dict[str, Any]],
    audits: list[dict[str, Any]],
    has_photos: bool,
) -> list[str]:
    missing = []
    if not issues:
        missing.append("issue evidence")
    if not kpis:
        missing.append("KPI baseline")
    if not audits:
        missing.append("audit data")
    if not has_photos:
        missing.append("photos")
    if not candidate.get("Expected KPI Improvement"):
        missing.append("expected KPI improvement")
    if not candidate.get("Ease of Implementation"):
        missing.append("implementation ease")
    return missing


def _score_explanation(
    scores: dict[str, int],
    baseline: dict[str, float],
    issues: list[dict[str, Any]],
    candidate: dict[str, Any],
    audits: list[dict[str, Any]],
) -> str:
    parts = [
        f"{PILOT_SCORE_LABELS['downtime_reliability']} {scores['downtime_reliability']}: {baseline['Baseline Downtime Minutes']} downtime min, {baseline['Baseline Part Drops']} drops, {len(issues)} issue(s)",
        f"{PILOT_SCORE_LABELS['quality_scrap']} {scores['quality_scrap']}: {baseline['Baseline Scrap Quantity']} scrap qty, {baseline['Baseline Mis-Picks']} mis-picks",
        f"{PILOT_SCORE_LABELS['ease']} {scores['ease']}: {candidate.get('Ease of Implementation') or 'not stated'}",
        f"{PILOT_SCORE_LABELS['safety_maintenance']} {scores['safety_maintenance']}: {baseline['Baseline Maintenance Events']} maintenance event(s)",
        f"{PILOT_SCORE_LABELS['standardization']} {scores['standardization']}: {len(audits)} related audit row(s)",
    ]
    return "; ".join(parts)


def _sensitivity_row(row: dict[str, Any], weights: dict[str, float]) -> dict[str, Any]:
    component_scores = {key: float(row.get(field, 0) or 0) for key, field in PILOT_SCORE_FIELDS.items()}
    return {
        "Candidate ID": row.get("Candidate ID", ""),
        "Press/Machine #": row.get("Press/Machine #", ""),
        "Most Sensitive Weight": _most_sensitive_weight(component_scores, weights),
        "Approx +/-10pt Weight Swing": _sensitivity_swing(component_scores, float(row.get("Total Score") or 0)),
    }


def _candidate_sensitivity(row: dict[str, Any], component_scores: dict[str, int], weights: dict[str, float]) -> str:
    sensitive = _most_sensitive_weight({key: float(value) for key, value in component_scores.items()}, weights)
    swing = _sensitivity_swing(
        {key: float(value) for key, value in component_scores.items()}, float(row.get("Total Score") or 0)
    )
    return f"Most sensitive to {sensitive}; +/-10 weight points changes score by about {swing}."


def _most_sensitive_weight(component_scores: dict[str, float], weights: dict[str, float]) -> str:
    if not component_scores:
        return "No score components"
    total = sum(component_scores.get(key, 0.0) * weights.get(key, 0.0) for key in component_scores)
    key = max(component_scores, key=lambda item: abs(component_scores[item] - total))
    return PILOT_SCORE_LABELS.get(key, key)


def _sensitivity_swing(component_scores: dict[str, float], total_score: float) -> float:
    if not component_scores:
        return 0.0
    swing = max(abs(score - total_score) * 0.10 for score in component_scores.values())
    return round(swing, 1)


def _weight_key(key: Any) -> str:
    text = str(key).strip().casefold().replace(" ", "_").replace("/", "_").replace("-", "_")
    aliases = {
        "downtime": "downtime_reliability",
        "downtime_reliability": "downtime_reliability",
        "downtime_reliability_score": "downtime_reliability",
        "quality": "quality_scrap",
        "quality_scrap": "quality_scrap",
        "quality_scrap_score": "quality_scrap",
        "ease": "ease",
        "ease_score": "ease",
        "safety": "safety_maintenance",
        "maintenance": "safety_maintenance",
        "safety_maintenance": "safety_maintenance",
        "standardization": "standardization",
        "standardization_score": "standardization",
    }
    return aliases.get(text, text)


def _truthy(value: Any) -> bool:
    text = str(value or "").strip().casefold()
    return text not in {"", "no", "n", "false", "0", "none", "low"}


def _yes(value: Any) -> bool:
    return str(value or "").strip().casefold() == "yes"


def _impact_boost(value: Any) -> int:
    text = str(value or "").casefold()
    if "critical" in text:
        return 25
    if "high" in text:
        return 20
    if "medium" in text or "moderate" in text:
        return 12
    if "low" in text:
        return 5
    return 0


def _priority_score(value: Any) -> int:
    text = str(value or "").casefold()
    if "critical" in text:
        return 30
    if "high" in text:
        return 22
    if "medium" in text or "moderate" in text:
        return 12
    if "low" in text:
        return 4
    return 0


def _ease_score(value: Any) -> int:
    text = str(value or "").casefold()
    if "easy" in text or "low" in text or "simple" in text:
        return 85
    if "medium" in text or "moderate" in text:
        return 60
    if "hard" in text or "complex" in text or "difficult" in text:
        return 30
    if text:
        return 50
    return 40


def _audit_yes_count(audits: list[dict[str, Any]], field: str) -> int:
    return sum(1 for row in audits if _yes(row.get(field)))


def _maintenance_frequency_score(audits: list[dict[str, Any]]) -> int:
    score = 0
    for row in audits:
        text = str(row.get("Maintenance Frequency") or "").casefold()
        if "daily" in text:
            score += 20
        elif "weekly" in text:
            score += 14
        elif "monthly" in text:
            score += 7
    return min(35, score)


def _documentation_gap_score(audits: list[dict[str, Any]]) -> int:
    gap_fields = ["Spare Parts Identified?", "Drawing/CAD Available?", "BOM Available?", "Process Binder Complete?"]
    score = 0
    for row in audits:
        for field in gap_fields:
            if str(row.get(field) or "").strip().casefold() in {"no", "missing", "unknown", ""}:
                score += 7
    return min(30, score)


__all__ = [
    "DEFAULT_PILOT_SCORE_WEIGHTS",
    "PILOT_SCORE_LABELS",
    "PilotRankingSummary",
    "generate_pilot_ranking_report",
    "normalize_pilot_weights",
    "rank_pilot_candidates",
]
