from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analysis_common import numeric, table_from_rows, write_timestamped_report
from .logging import log_tool_run
from .paths import resolve_project_paths
from .pilot_scoring import rank_pilot_candidates
from .result import ToolResult
from .safe_files import ensure_directory, safe_write_text


@dataclass(frozen=True)
class PilotROIResult:
    candidate_id: str
    machine: str
    mode: str
    assumption_timestamp: str
    annualized_savings_estimate: float | str
    estimate_label: str
    assumptions: dict[str, Any] = field(default_factory=dict)
    missing_evidence: str = ""
    score_summary: str = ""
    justification: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "Candidate ID": self.candidate_id,
            "Press/Machine #": self.machine,
            "ROI Mode": self.mode,
            "Annualized Savings Estimate": self.annualized_savings_estimate,
            "Estimate Label": self.estimate_label,
            "Assumption Timestamp": self.assumption_timestamp,
            "Missing Evidence": self.missing_evidence,
            "Score Summary": self.score_summary,
            "Justification": self.justification,
        }


@dataclass(frozen=True)
class PilotROISummary:
    generated_at: str
    assumptions: dict[str, Any]
    results: list[PilotROIResult]

    def to_markdown(self) -> str:
        rows = [result.to_dict() for result in self.results]
        assumptions = self.assumptions or {}
        assumption_lines = [f"- {key}: {value}" for key, value in sorted(assumptions.items())] or ["- No financial assumptions supplied; qualitative mode only."]
        return "\n".join(
            [
                "# Pilot ROI and Justification Report",
                "",
                f"Generated: {self.generated_at}",
                "",
                "## Assumptions",
                *assumption_lines,
                "",
                "## Candidate ROI",
                *table_from_rows(rows, ["Candidate ID", "Press/Machine #", "ROI Mode", "Annualized Savings Estimate", "Estimate Label", "Missing Evidence"]),
                "",
                "## Justification Paragraphs",
                *[f"### {result.candidate_id or result.machine or 'Candidate'}\n\n{result.justification}" for result in self.results],
            ]
        ) + "\n"


def pilot_roi_assumptions_path(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).project_data / "pilot_roi_assumptions.json"


def load_pilot_roi_assumptions(project_root: str | Path) -> dict[str, Any]:
    path = pilot_roi_assumptions_path(project_root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    assumptions = payload.get("assumptions", {}) if isinstance(payload, dict) else {}
    return assumptions if isinstance(assumptions, dict) else {}


def save_pilot_roi_assumptions(project_root: str | Path, assumptions: dict[str, Any], *, candidate_id: str = "") -> Path:
    path = pilot_roi_assumptions_path(project_root)
    payload = {
        "updated_at": _now(),
        "candidate_id": candidate_id,
        "assumptions": dict(assumptions),
    }
    return safe_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n", overwrite=True)


def build_pilot_roi(
    project_root: str | Path,
    *,
    candidate_id: str = "",
    assumptions: dict[str, Any] | None = None,
) -> tuple[PilotROISummary | None, ToolResult | None]:
    ranking, error = rank_pilot_candidates(project_root)
    if error:
        return None, error
    assert ranking is not None
    selected_assumptions = dict(load_pilot_roi_assumptions(project_root))
    if assumptions is not None:
        selected_assumptions.update(assumptions)
    rows = ranking.ranked_candidates
    if candidate_id:
        rows = [row for row in rows if str(row.get("Candidate ID") or "") == candidate_id]
    generated_at = _now()
    results = [_roi_result_for_candidate(row, selected_assumptions, generated_at) for row in rows]
    return PilotROISummary(generated_at=generated_at, assumptions=selected_assumptions, results=results), None


def export_pilot_roi_report(
    project_root: str | Path,
    *,
    candidate_id: str = "",
    assumptions: dict[str, Any] | None = None,
    log_activity: bool = True,
) -> ToolResult:
    if assumptions is not None:
        save_pilot_roi_assumptions(project_root, assumptions, candidate_id=candidate_id)
    summary, error = build_pilot_roi(project_root, candidate_id=candidate_id, assumptions=assumptions)
    if error:
        return error
    assert summary is not None
    folder = resolve_project_paths(project_root).pilot_project / "Candidate_Cells"
    ensure_directory(folder)
    try:
        report = write_timestamped_report(folder, "Pilot_ROI_Justification", summary.to_markdown())
    except Exception as exc:
        return ToolResult.fail("pilot_roi", "Pilot ROI Tool", "Could not write pilot ROI report.", errors=[str(exc)])
    result = ToolResult.ok(
        "pilot_roi",
        "Pilot ROI Tool",
        "Generated pilot ROI justification report.",
        details=[f"Report: {report}", "Workbook was not modified."],
        files_created=[str(report)],
        output_reports=[str(report)],
        metrics={"candidate_count": len(summary.results), "quantitative_count": sum(result.mode == "quantitative_estimate" for result in summary.results)},
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result


def _roi_result_for_candidate(row: dict[str, Any], assumptions: dict[str, Any], timestamp: str) -> PilotROIResult:
    estimate, basis = _annualized_estimate(row, assumptions)
    mode = "quantitative_estimate" if estimate is not None else "qualitative"
    estimate_value: float | str = round(estimate, 2) if estimate is not None else ""
    label = "Estimated annual savings from supplied assumptions." if estimate is not None else "Qualitative only; no dollar assumptions supplied."
    candidate_id = str(row.get("Candidate ID") or "")
    machine = str(row.get("Press/Machine #") or "")
    missing = str(row.get("Missing Evidence") or row.get("Missing Data") or "")
    score_summary = f"Score {row.get('Total Score', 0)} with confidence {row.get('Confidence', 'Unknown')}."
    justification = _justification(row, mode, estimate_value, label, basis, missing)
    return PilotROIResult(
        candidate_id=candidate_id,
        machine=machine,
        mode=mode,
        assumption_timestamp=timestamp,
        annualized_savings_estimate=estimate_value,
        estimate_label=label,
        assumptions=dict(assumptions),
        missing_evidence=missing,
        score_summary=score_summary,
        justification=justification,
    )


def _annualized_estimate(row: dict[str, Any], assumptions: dict[str, Any]) -> tuple[float | None, str]:
    pieces: list[float] = []
    basis: list[str] = []
    hourly_downtime_cost = _money(assumptions.get("hourly_downtime_cost"))
    direct_minutes = _number_or_none(assumptions.get("expected_downtime_reduction_minutes_per_year"))
    if hourly_downtime_cost is not None and direct_minutes is not None:
        pieces.append((direct_minutes / 60.0) * hourly_downtime_cost)
        basis.append("downtime minutes/year x hourly downtime cost")
    elif hourly_downtime_cost is not None:
        percent = _number_or_none(assumptions.get("expected_downtime_reduction_percent"))
        periods = _number_or_none(assumptions.get("baseline_periods_per_year"))
        if percent is not None and periods is not None:
            baseline_minutes = numeric(row.get("Baseline Downtime Minutes"))
            pieces.append((baseline_minutes * (percent / 100.0) * periods / 60.0) * hourly_downtime_cost)
            basis.append("baseline downtime x reduction percent x periods/year x hourly cost")

    scrap_cost = _money(assumptions.get("scrap_cost_per_piece"))
    direct_scrap = _number_or_none(assumptions.get("expected_scrap_reduction_pieces_per_year"))
    if scrap_cost is not None and direct_scrap is not None:
        pieces.append(direct_scrap * scrap_cost)
        basis.append("scrap pieces/year x scrap cost")
    elif scrap_cost is not None:
        percent = _number_or_none(assumptions.get("expected_scrap_reduction_percent"))
        periods = _number_or_none(assumptions.get("baseline_periods_per_year"))
        if percent is not None and periods is not None:
            baseline_scrap = numeric(row.get("Baseline Scrap Quantity"))
            pieces.append(baseline_scrap * (percent / 100.0) * periods * scrap_cost)
            basis.append("baseline scrap x reduction percent x periods/year x scrap cost")

    if not pieces:
        return None, ""
    return sum(pieces), "; ".join(basis)


def _justification(row: dict[str, Any], mode: str, estimate: float | str, label: str, basis: str, missing: str) -> str:
    candidate = row.get("Candidate ID") or row.get("Press/Machine #") or "This candidate"
    problem = row.get("Main Problem") or "the documented EOAT opportunity"
    score = row.get("Total Score", 0)
    confidence = row.get("Confidence", "Unknown")
    if mode == "quantitative_estimate":
        roi_sentence = f"The financial estimate is ${estimate} annualized, labeled as an estimate because it depends only on the supplied assumptions ({basis})."
    else:
        roi_sentence = "No financial value was calculated because cost or reduction assumptions were not supplied."
    missing_sentence = f"Remaining evidence gaps: {missing}." if missing and missing != "None obvious" else "No obvious evidence gaps were flagged by the scoring engine."
    return (
        f"{candidate} is a pilot candidate for {problem}. It scored {score} with {confidence} confidence based on the current issue, KPI, audit, photo, and implementation evidence. "
        f"{roi_sentence} {missing_sentence} {label}"
    )


def _number_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _money(value: Any) -> float | None:
    number = _number_or_none(str(value).replace("$", "").replace(",", "") if value is not None else None)
    return number if number is not None and number >= 0 else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


__all__ = [
    "PilotROIResult",
    "PilotROISummary",
    "build_pilot_roi",
    "export_pilot_roi_report",
    "load_pilot_roi_assumptions",
    "pilot_roi_assumptions_path",
    "save_pilot_roi_assumptions",
]
