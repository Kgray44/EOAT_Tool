from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .analysis_common import (
    OPEN_STATUSES,
    parse_score,
    table_from_rows,
    write_timestamped_csv,
    write_timestamped_report,
)
from .audit_compatibility import machine_from_audit_row, normalize_machine_token, text_value
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory
from .workbook_cache import row_dicts_cached as row_dicts

TOOL_ID = "bad_actor_detector"
TOOL_NAME = "Bad Actor Detector"

BAD_ACTOR_SCORE_FORMULA = (
    "score = issue_count*4 + high_priority_count*6 + critical_priority_count*10 "
    "+ follow_up_count*3 + drop_history*5 + scrap_concern*4 + cycle_time_concern*3 "
    "+ maintenance_frequency + documentation_gap_penalty"
)


@dataclass(frozen=True)
class BadActorScore:
    machine: str
    score: int
    issue_count: int = 0
    high_priority_count: int = 0
    critical_priority_count: int = 0
    follow_up_count: int = 0
    drop_history: int = 0
    scrap_concern: int = 0
    cycle_time_concern: int = 0
    maintenance_frequency: int = 0
    documentation_gap_penalty: int = 0
    formula: str = BAD_ACTOR_SCORE_FORMULA
    evidence: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    recommended_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BadActorSummary:
    rankings: list[BadActorScore] = field(default_factory=list)
    score_formula: str = BAD_ACTOR_SCORE_FORMULA
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rankings": [score.to_dict() for score in self.rankings],
            "score_formula": self.score_formula,
            "metrics": dict(self.metrics),
            "warnings": list(self.warnings),
        }


def detect_bad_actors(project_root: str | Path) -> BadActorSummary:
    paths = resolve_project_paths(project_root)
    workbook = paths.master_workbook
    if not workbook.exists():
        return BadActorSummary(metrics={"machines": 0}, warnings=[f"Master workbook is missing: {workbook}"])
    warnings: list[str] = []
    audit_rows = _safe_rows(workbook, "EOAT Inventory", warnings)
    issue_rows = _safe_rows(workbook, "Issue Log", warnings)
    kpi_rows = _safe_rows(workbook, "KPI Baseline", warnings)
    fmea_rows = _safe_rows(workbook, "FMEA Draft", warnings)
    machines = _all_machines(audit_rows, issue_rows, kpi_rows, fmea_rows)
    rankings = [_score_machine(machine, audit_rows, issue_rows, kpi_rows, fmea_rows) for machine in machines]
    rankings.sort(key=lambda item: (-item.score, _machine_sort_key(item.machine)))
    metrics = {
        "machines": len(rankings),
        "bad_actor_count": sum(1 for item in rankings if item.score > 0),
        "top_score": rankings[0].score if rankings else 0,
        "missing_evidence_sources": sum(len(item.missing_evidence) for item in rankings),
    }
    return BadActorSummary(rankings=rankings, metrics=metrics, warnings=warnings)


def export_bad_actor_report(project_root: str | Path, *, log_activity: bool = True) -> ToolResult:
    start = time.perf_counter()
    paths = resolve_project_paths(project_root)
    output_dir = ensure_directory(paths.risk_insights_reports)
    summary = detect_bad_actors(project_root)
    report = write_timestamped_report(output_dir, "Bad_Actor_Detector", bad_actor_markdown(summary))
    csv_rows = bad_actor_csv_rows(summary)
    csv_path = write_timestamped_csv(output_dir, "Bad_Actor_Detector_Details", csv_rows) if csv_rows else None
    files = [str(report), *(str(csv_path) for csv_path in [csv_path] if csv_path is not None)]
    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Generated bad actor detector report.",
        details=["No workbook rows were modified.", f"Report: {report}", f"Formula: {summary.score_formula}"],
        warnings=summary.warnings,
        files_created=files,
        output_reports=files,
        metrics=summary.metrics,
        structured_data=summary.to_dict(),
        duration_seconds=time.perf_counter() - start,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result


def bad_actor_csv_rows(summary: BadActorSummary) -> list[dict[str, Any]]:
    return [
        {
            "Machine": item.machine,
            "Score": item.score,
            "Issue Count": item.issue_count,
            "High Priority Count": item.high_priority_count,
            "Critical Priority Count": item.critical_priority_count,
            "Follow-Up Count": item.follow_up_count,
            "Drop History": item.drop_history,
            "Scrap Concern": item.scrap_concern,
            "Cycle Time Concern": item.cycle_time_concern,
            "Maintenance Frequency": item.maintenance_frequency,
            "Documentation Gap Penalty": item.documentation_gap_penalty,
            "Formula": item.formula,
            "Evidence": "; ".join(item.evidence),
            "Missing Evidence": "; ".join(item.missing_evidence),
            "Recommended Action": item.recommended_action,
        }
        for item in summary.rankings
    ]


def bad_actor_markdown(summary: BadActorSummary) -> str:
    rows = bad_actor_csv_rows(summary)
    lines = [
        "# Bad Actor Detector",
        "",
        "## Evidence Rules",
        "- Scores are calculated only from local workbook evidence.",
        "- Missing source evidence is listed separately and is not converted into fake certainty.",
        "- The detector does not modify workbook rows.",
        "",
        "## Score Formula",
        f"`{summary.score_formula}`",
        "",
        "## Rankings",
        *table_from_rows(
            rows,
            [
                "Machine",
                "Score",
                "Issue Count",
                "High Priority Count",
                "Critical Priority Count",
                "Follow-Up Count",
                "Drop History",
                "Scrap Concern",
                "Cycle Time Concern",
                "Maintenance Frequency",
                "Documentation Gap Penalty",
                "Missing Evidence",
                "Recommended Action",
            ],
        ),
    ]
    if summary.warnings:
        lines.extend(["", "## Warnings", *[f"- {warning}" for warning in summary.warnings]])
    return "\n".join(lines) + "\n"


def _score_machine(
    machine: str,
    audit_rows: list[dict[str, Any]],
    issue_rows: list[dict[str, Any]],
    kpi_rows: list[dict[str, Any]],
    fmea_rows: list[dict[str, Any]],
) -> BadActorScore:
    audits = [row for row in audit_rows if _machine(row) == machine]
    issues = [row for row in issue_rows if _machine(row) == machine]
    kpis = [row for row in kpi_rows if _machine(row) == machine]
    fmeas = [row for row in fmea_rows if _machine(row) == machine]
    issue_count = len(issues)
    high_priority_count = _high_priority_count(audits, issues, fmeas)
    critical_priority_count = _critical_priority_count(audits, issues, fmeas)
    follow_up_count = _follow_up_count(audits, issues)
    drop_history = _drop_history_count(audits, issues, kpis)
    scrap_concern = _scrap_concern_count(audits, kpis)
    cycle_time_concern = _cycle_time_concern_count(audits, kpis)
    maintenance_frequency = sum(_maintenance_frequency_points(row.get("Maintenance Frequency")) for row in audits)
    documentation_gap_penalty = _documentation_gap_penalty(audits)
    score = (
        issue_count * 4
        + high_priority_count * 6
        + critical_priority_count * 10
        + follow_up_count * 3
        + drop_history * 5
        + scrap_concern * 4
        + cycle_time_concern * 3
        + maintenance_frequency
        + documentation_gap_penalty
    )
    evidence = tuple(_evidence_lines(audits, issues, kpis, fmeas))
    missing = tuple(_missing_evidence_lines(audits, issues, kpis, fmeas))
    return BadActorScore(
        machine=machine,
        score=score,
        issue_count=issue_count,
        high_priority_count=high_priority_count,
        critical_priority_count=critical_priority_count,
        follow_up_count=follow_up_count,
        drop_history=drop_history,
        scrap_concern=scrap_concern,
        cycle_time_concern=cycle_time_concern,
        maintenance_frequency=maintenance_frequency,
        documentation_gap_penalty=documentation_gap_penalty,
        evidence=evidence,
        missing_evidence=missing,
        recommended_action=_recommended_action(score, missing),
    )


def _high_priority_count(audits: list[dict[str, Any]], issues: list[dict[str, Any]], fmeas: list[dict[str, Any]]) -> int:
    audit_count = sum(1 for row in audits if text_value(row.get("Priority")).casefold() == "high")
    issue_count = sum(1 for row in issues if (parse_score(row.get("Severity")) or 0) >= 7)
    fmea_count = sum(1 for row in fmeas if _rpn(row) >= 100)
    return audit_count + issue_count + fmea_count


def _critical_priority_count(audits: list[dict[str, Any]], issues: list[dict[str, Any]], fmeas: list[dict[str, Any]]) -> int:
    audit_count = sum(1 for row in audits if text_value(row.get("Priority")).casefold() == "critical")
    issue_count = sum(1 for row in issues if (parse_score(row.get("Severity")) or 0) >= 9)
    fmea_count = sum(1 for row in fmeas if _rpn(row) >= 200)
    return audit_count + issue_count + fmea_count


def _follow_up_count(audits: list[dict[str, Any]], issues: list[dict[str, Any]]) -> int:
    audit_count = sum(1 for row in audits if text_value(row.get("Follow-Up Needed")).casefold() == "yes")
    issue_count = sum(1 for row in issues if text_value(row.get("Status")).casefold() in OPEN_STATUSES or bool(text_value(row.get("Follow-Up Date"))))
    return audit_count + issue_count


def _drop_history_count(audits: list[dict[str, Any]], issues: list[dict[str, Any]], kpis: list[dict[str, Any]]) -> int:
    audit_count = sum(1 for row in audits if _has_signal(row.get("Drop/Mis-Pick History")) or _has_yes(row.get("Scrap/Quality Concern?")))
    issue_count = sum(1 for row in issues if any(token in _issue_text(row) for token in ("drop", "mis-pick", "mispick", "mis pick")))
    kpi_count = sum(1 for row in kpis if _numeric(row.get("Part Drops")) > 0 or _numeric(row.get("Mis-Picks")) > 0)
    return audit_count + issue_count + kpi_count


def _scrap_concern_count(audits: list[dict[str, Any]], kpis: list[dict[str, Any]]) -> int:
    return sum(1 for row in audits if _has_yes(row.get("Scrap/Quality Concern?"))) + sum(1 for row in kpis if _numeric(row.get("Scrap Quantity")) > 0)


def _cycle_time_concern_count(audits: list[dict[str, Any]], kpis: list[dict[str, Any]]) -> int:
    audit_count = sum(1 for row in audits if _has_yes(row.get("Cycle Time Concern?")))
    kpi_count = sum(1 for row in kpis if _numeric(row.get("Cycle Time")) > 0 and _has_signal(row.get("Notes")))
    return audit_count + kpi_count


def _maintenance_frequency_points(value: Any) -> int:
    text = text_value(value).casefold()
    if not text:
        return 0
    if "daily" in text or "shift" in text:
        return 6
    if "weekly" in text:
        return 4
    if "monthly" in text:
        return 2
    if "quarter" in text or "annual" in text:
        return 1
    return 1


def _documentation_gap_penalty(audits: list[dict[str, Any]]) -> int:
    fields = ("Spare Parts Identified?", "BOM Available?", "Drawing/CAD Available?", "Process Binder Complete?")
    return sum(2 for row in audits for field in fields if _is_no_or_missing(row.get(field)))


def _evidence_lines(audits: list[dict[str, Any]], issues: list[dict[str, Any]], kpis: list[dict[str, Any]], fmeas: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    if audits:
        lines.append(f"{len(audits)} EOAT audit row(s).")
    if issues:
        lines.append(f"{len(issues)} Issue Log row(s).")
    if kpis:
        lines.append(f"{len(kpis)} KPI row(s).")
    if fmeas:
        lines.append(f"{len(fmeas)} FMEA row(s).")
    return lines


def _missing_evidence_lines(audits: list[dict[str, Any]], issues: list[dict[str, Any]], kpis: list[dict[str, Any]], fmeas: list[dict[str, Any]]) -> list[str]:
    missing: list[str] = []
    if not audits:
        missing.append("No EOAT Inventory audit evidence for this machine.")
    if not issues:
        missing.append("No Issue Log evidence for this machine.")
    if not kpis:
        missing.append("No KPI baseline evidence for this machine.")
    if not fmeas:
        missing.append("No FMEA evidence for this machine.")
    return missing


def _recommended_action(score: int, missing: tuple[str, ...]) -> str:
    if score >= 50:
        return "Treat as top bad-actor candidate; review evidence and assign corrective actions."
    if score >= 25:
        return "Review as elevated risk and confirm missing evidence before prioritizing."
    if score > 0:
        return "Monitor and keep evidence current before making a pilot decision."
    if missing:
        return "No bad-actor score from current evidence; collect missing sources before claiming low risk."
    return "No current bad-actor signals."


def _all_machines(*sources: list[dict[str, Any]]) -> list[str]:
    machines = {machine for rows in sources for row in rows for machine in [_machine(row)] if machine}
    return sorted(machines, key=_machine_sort_key)


def _safe_rows(workbook: Path, sheet_name: str, warnings: list[str]) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in row_dicts(workbook, sheet_name)]
    except Exception as exc:
        warnings.append(f"Could not read {sheet_name}: {exc}")
        return []


def _machine(row: dict[str, Any]) -> str:
    return normalize_machine_token(machine_from_audit_row(row)) or normalize_machine_token(row.get("Press/Machine #"))


def _issue_text(row: dict[str, Any]) -> str:
    fields = ("Issue Category", "Issue Description", "Suspected Cause", "Evidence/Observation", "Impact", "Notes")
    return " ".join(text_value(row.get(field)).casefold() for field in fields)


def _rpn(row: dict[str, Any]) -> int:
    direct = parse_score(row.get("RPN"))
    if direct is not None:
        return direct
    severity = parse_score(row.get("Severity")) or 0
    frequency = parse_score(row.get("Frequency")) or 0
    detectability = parse_score(row.get("Detectability")) or 0
    return severity * frequency * detectability


def _is_no_or_missing(value: Any) -> bool:
    text = text_value(value).casefold()
    return text in {"", "no", "n/a", "na", "unknown", "unknown / not checked", "not checked"}


def _has_yes(value: Any) -> bool:
    return text_value(value).casefold() == "yes"


def _has_signal(value: Any) -> bool:
    text = text_value(value).casefold()
    return bool(text) and text not in {"no", "none", "n/a", "na", "unknown", "unknown / not checked", "not checked", "no issue observed.", "no issues observed"}


def _numeric(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        parsed = parse_score(value)
        return float(parsed or 0)


def _machine_sort_key(machine: str) -> tuple[int, int | str]:
    return (0, int(machine)) if str(machine).isdigit() else (1, str(machine).casefold())


__all__ = [
    "BAD_ACTOR_SCORE_FORMULA",
    "BadActorScore",
    "BadActorSummary",
    "bad_actor_csv_rows",
    "bad_actor_markdown",
    "detect_bad_actors",
    "export_bad_actor_report",
]
