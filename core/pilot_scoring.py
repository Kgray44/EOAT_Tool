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


@dataclass
class PilotRankingSummary:
    metrics: dict[str, Any]
    ranked_candidates: list[dict[str, Any]] = field(default_factory=list)

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# Pilot Candidate Ranking Report",
                "",
                "## Executive Summary",
                f"- Candidates evaluated: {self.metrics.get('candidates_evaluated', 0)}",
                f"- Top candidate: {self.metrics.get('top_candidate', 'No data yet')}",
                "",
                "## Ranked Candidates",
                *table_from_rows(self.ranked_candidates, ["Rank", "Candidate ID", "Press/Machine #", "Main Problem", "Total Score", "Confidence", "Missing Data"]),
                "",
                "## Scoring Method",
                "- Impact score: 0-30",
                "- Frequency/reliability score: 0-20",
                "- Measurement clarity score: 0-15",
                "- Ease of implementation score: 0-15",
                "- Safety/quality urgency score: 0-10",
                "- Standardization value score: 0-10",
                "",
                "## Recommended Top 1-2 Pilot Candidates",
                *table_from_rows(self.ranked_candidates[:2], ["Rank", "Press/Machine #", "Total Score", "Confidence", "Recommended Action"]),
                "",
                "## Next Data To Collect",
                "- Confirm downtime, drops, scrap, and maintenance baseline data.",
                "- Add before/after measurement plan before final pilot selection.",
            ]
        ) + "\n"


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
        "Safety/Quality Risk": "Yes" if str(row.get("Scrap/Quality Concern?") or "").lower() == "yes" else "",
        "Expected KPI Improvement": "",
        "Recommended Action": "Review as pilot candidate from EOAT Inventory flag.",
        "Approval Status": "",
        "Notes": "Suggested from EOAT Inventory.",
    }


def rank_pilot_candidates(project_root: str | Path) -> tuple[PilotRankingSummary | None, ToolResult | None]:
    workbook = resolve_project_paths(project_root).master_workbook
    if not workbook.exists():
        return None, ToolResult.fail("pilot_candidate_ranking", "Pilot Candidate Ranking Tool", "Master workbook is missing.", errors=[str(workbook)])
    try:
        candidates = row_dicts(workbook, "Pilot Candidates")
        inventory = [repair_legacy_audit_lookup_shift(row) for row in row_dicts(workbook, "EOAT Inventory")]
        issues = row_dicts(workbook, "Issue Log")
        kpis = row_dicts(workbook, "KPI Baseline")
        photos = row_dicts(workbook, "Photo Index")
    except Exception as exc:
        return None, ToolResult.fail("pilot_candidate_ranking", "Pilot Candidate Ranking Tool", "Could not read workbook.", errors=[str(exc)])
    if not candidates:
        candidates = [
            _candidate_from_inventory(row)
            for row in inventory
            if str(row.get("Pilot Candidate?") or "").lower() in {"yes", "maybe"} or str(row.get("Status") or "").lower() == "candidate for pilot"
        ]
    ranked = []
    photo_press = {str(row.get("Press/Machine #") or "") for row in photos}
    for candidate in candidates:
        press = str(candidate.get("Press/Machine #") or "")
        related_issues = [row for row in issues if str(row.get("Press/Machine #") or "") == press]
        related_kpi = [row for row in kpis if str(row.get("Press/Machine #") or "") == press]
        related_audit = [row for row in inventory if str(row.get("Press/Machine #") or "") == press]
        issue_count = len(related_issues)
        downtime = sum(numeric(row.get("Downtime Minutes")) for row in related_kpi)
        drops = sum(numeric(row.get("Part Drops")) for row in related_kpi)
        scrap = sum(numeric(row.get("Scrap Quantity")) for row in related_kpi)
        impact = min(30, int(downtime / 10) + int(drops * 2) + int(scrap / 10) + (10 if candidate.get("Estimated Impact") else 0))
        frequency = min(20, issue_count * 5 + int(drops))
        measurement = min(15, (8 if related_kpi else 0) + (4 if candidate.get("Expected KPI Improvement") else 0) + (3 if press in photo_press else 0))
        ease_text = str(candidate.get("Ease of Implementation") or "").lower()
        ease = 10 if "easy" in ease_text else 7 if "medium" in ease_text or "moderate" in ease_text else 5 if ease_text else 3
        safety = 10 if candidate.get("Safety/Quality Risk") else 0
        standard = 10 if related_audit or candidate.get("EOAT Type") else 3
        total = impact + frequency + measurement + ease + safety + standard
        evidence_count = sum(bool(item) for item in [related_issues, related_kpi, related_audit, press in photo_press, candidate.get("Expected KPI Improvement")])
        confidence = "High" if evidence_count >= 4 else "Medium" if evidence_count >= 2 else "Low"
        missing = []
        if not related_issues:
            missing.append("issue evidence")
        if not related_kpi:
            missing.append("KPI baseline")
        if not related_audit:
            missing.append("audit data")
        if press not in photo_press:
            missing.append("photos")
        ranked.append(
            {
                **candidate,
                "Issue Count": issue_count,
                "Total Score": total,
                "Impact Score": impact,
                "Frequency Score": frequency,
                "Measurement Score": measurement,
                "Ease Score": ease,
                "Safety Score": safety,
                "Standardization Score": standard,
                "Confidence": confidence,
                "Missing Data": ", ".join(missing) or "None obvious",
            }
        )
    ranked.sort(key=lambda row: int(row.get("Total Score") or 0), reverse=True)
    for index, row in enumerate(ranked, start=1):
        row["Rank"] = index
    summary = PilotRankingSummary(
        metrics={
            "candidates_evaluated": len(ranked),
            "top_candidate": ranked[0].get("Press/Machine #", "No data yet") if ranked else "No data yet",
            "top_score": ranked[0].get("Total Score", 0) if ranked else 0,
        },
        ranked_candidates=ranked,
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
        return ToolResult.fail("pilot_candidate_ranking", "Pilot Candidate Ranking Tool", "Could not write report.", errors=[str(exc)])
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
