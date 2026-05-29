from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .analysis_common import parse_score, table_from_rows, write_timestamped_csv, write_timestamped_report
from .audit_compatibility import machine_from_audit_row, normalize_machine_token, text_value
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory
from .workbook_cache import row_dicts_cached as row_dicts

TOOL_ID = "risk_heatmap"
TOOL_NAME = "Risk Heat Map"

RISK_LEVEL_MISSING = "Missing Evidence"
RISK_LEVEL_LOW = "Low"
RISK_LEVEL_MEDIUM = "Medium"
RISK_LEVEL_HIGH = "High"
RISK_LEVEL_CRITICAL = "Critical"

FAILURE_MODES: tuple[str, ...] = (
    "vacuum loss",
    "misalignment",
    "tubing failure",
    "sensor failure",
    "mechanical wear",
    "cable management issue",
    "quick disconnect issue",
    "drop/mis-pick",
    "changeover error",
    "documentation gap",
    "pneumatic circuit mismatch",
    "gripper wear",
    "cylinder issue",
)

FAILURE_MODE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "vacuum loss": ("vacuum loss", "vacuum drop", "vacuum drops", "vacuum leak", "leak", "venturi", "suction"),
    "misalignment": ("misalignment", "misaligned", "alignment", "eoat alignment"),
    "tubing failure": ("tubing", "tube", "hose", "air line", "pneumatic line", "rub", "leak"),
    "sensor failure": ("sensor", "part-present", "part present", "signal", "reed switch", "vacuum switch"),
    "mechanical wear": ("mechanical wear", "wear", "worn", "loose", "hardware", "fastener", "damaged"),
    "cable management issue": ("cable", "wiring", "wire", "electrical", "cable management"),
    "quick disconnect issue": ("quick disconnect", "disconnect", "qd", "m12", "push-to-connect"),
    "drop/mis-pick": ("drop", "drops", "mis-pick", "mispick", "mis pick", "part drop", "part drops"),
    "changeover error": ("changeover", "setup", "ati", "dovetail", "wrong tool"),
    "documentation gap": ("documentation", "bom", "cad", "drawing", "process binder", "spare parts"),
    "pneumatic circuit mismatch": ("pneumatic circuit", "robot vacuum circuit", "eoat vacuum circuit", "pressure circuit", "circuit mismatch"),
    "gripper wear": ("gripper", "jaw", "finger", "gripper wear"),
    "cylinder issue": ("cylinder", "actuator", "linear cylinder", "rotary cylinder"),
}

AUDIT_TEXT_FIELDS = (
    "Known Issues",
    "Drop/Mis-Pick History",
    "Tubing Routing Notes",
    "Notes",
    "Tubing Condition",
    "Cable Management Condition",
    "Mounting Hardware Condition",
    "EOAT Alignment Condition",
    "Changeover Difficulty",
)
ISSUE_TEXT_FIELDS = ("Issue Category", "Issue Description", "Suspected Cause", "Evidence/Observation", "Impact", "Notes")
FMEA_TEXT_FIELDS = ("Failure Mode", "Failure Effect", "Potential Cause", "Recommended Action", "Notes")


@dataclass(frozen=True)
class RiskEvidence:
    failure_mode: str
    machine: str
    source_type: str
    source_id: str
    description: str
    score: int
    audit_id: str = ""
    evidence_status: str = "observed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RiskHeatmapCell:
    machine: str
    failure_mode: str
    risk_score: int
    risk_level: str
    evidence_count: int
    evidence: tuple[RiskEvidence, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    recommended_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = [item.to_dict() for item in self.evidence]
        return data


@dataclass(frozen=True)
class RiskHeatmapSummary:
    machines: list[str] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=lambda: list(FAILURE_MODES))
    cells: list[RiskHeatmapCell] = field(default_factory=list)
    evidence: list[RiskEvidence] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def cell(self, machine: str, failure_mode: str) -> RiskHeatmapCell | None:
        machine_key = normalize_machine_token(machine)
        mode = _normalize(failure_mode)
        for cell in self.cells:
            if cell.machine == machine_key and cell.failure_mode == mode:
                return cell
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "machines": list(self.machines),
            "failure_modes": list(self.failure_modes),
            "cells": [cell.to_dict() for cell in self.cells],
            "evidence": [item.to_dict() for item in self.evidence],
            "metrics": dict(self.metrics),
            "warnings": list(self.warnings),
        }


def build_risk_heatmap(project_root: str | Path) -> RiskHeatmapSummary:
    paths = resolve_project_paths(project_root)
    workbook = paths.master_workbook
    if not workbook.exists():
        return RiskHeatmapSummary(metrics={"machines": 0, "evidence_count": 0}, warnings=[f"Master workbook is missing: {workbook}"])
    warnings: list[str] = []
    audit_rows = _safe_rows(workbook, "EOAT Inventory", warnings)
    issue_rows = _safe_rows(workbook, "Issue Log", warnings)
    fmea_rows = _safe_rows(workbook, "FMEA Draft", warnings)
    kpi_rows = _safe_rows(workbook, "KPI Baseline", warnings)
    machines = _all_machines(audit_rows, issue_rows, fmea_rows, kpi_rows)
    evidence = [
        *_evidence_from_audits(audit_rows),
        *_evidence_from_issues(issue_rows),
        *_evidence_from_fmea(fmea_rows),
        *_evidence_from_kpis(kpi_rows),
    ]
    by_pair: dict[tuple[str, str], list[RiskEvidence]] = {}
    for item in evidence:
        by_pair.setdefault((item.machine, item.failure_mode), []).append(item)
    cells: list[RiskHeatmapCell] = []
    for machine in machines:
        for mode in FAILURE_MODES:
            mode_evidence = tuple(sorted(by_pair.get((machine, mode), []), key=lambda item: (-item.score, item.source_type, item.source_id)))
            risk_score = sum(item.score for item in mode_evidence)
            level = _risk_level(risk_score, len(mode_evidence))
            missing = () if mode_evidence else (f"No local evidence found for {mode} on machine {machine}.",)
            cells.append(
                RiskHeatmapCell(
                    machine=machine,
                    failure_mode=mode,
                    risk_score=risk_score,
                    risk_level=level,
                    evidence_count=len(mode_evidence),
                    evidence=mode_evidence,
                    missing_evidence=missing,
                    recommended_action=_recommended_action(level, mode),
                )
            )
    metrics = {
        "machines": len(machines),
        "failure_modes": len(FAILURE_MODES),
        "evidence_count": len(evidence),
        "critical_cells": sum(1 for cell in cells if cell.risk_level == RISK_LEVEL_CRITICAL),
        "high_cells": sum(1 for cell in cells if cell.risk_level == RISK_LEVEL_HIGH),
        "missing_evidence_cells": sum(1 for cell in cells if cell.risk_level == RISK_LEVEL_MISSING),
    }
    return RiskHeatmapSummary(machines=machines, cells=cells, evidence=evidence, metrics=metrics, warnings=warnings)


def export_risk_heatmap_report(project_root: str | Path, *, log_activity: bool = True) -> ToolResult:
    start = time.perf_counter()
    paths = resolve_project_paths(project_root)
    output_dir = ensure_directory(paths.risk_insights_reports)
    summary = build_risk_heatmap(project_root)
    markdown = risk_heatmap_markdown(summary)
    report = write_timestamped_report(output_dir, "Risk_Heat_Map", markdown)
    csv_rows = risk_heatmap_csv_rows(summary)
    csv_path = write_timestamped_csv(output_dir, "Risk_Heat_Map_Details", csv_rows) if csv_rows else None
    files = [str(report), *(str(csv_path) for csv_path in [csv_path] if csv_path is not None)]
    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Generated evidence-based risk heat map.",
        details=["No workbook rows were modified.", f"Report: {report}"],
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


def risk_heatmap_csv_rows(summary: RiskHeatmapSummary) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cell in summary.cells:
        if cell.evidence:
            for item in cell.evidence:
                rows.append(
                    {
                        "Machine": cell.machine,
                        "Failure Mode": cell.failure_mode,
                        "Risk Level": cell.risk_level,
                        "Risk Score": cell.risk_score,
                        "Evidence Count": cell.evidence_count,
                        "Source Type": item.source_type,
                        "Source ID": item.source_id,
                        "Audit ID": item.audit_id,
                        "Evidence": item.description,
                        "Evidence Score": item.score,
                        "Missing Evidence": "",
                        "Recommended Action": cell.recommended_action,
                    }
                )
        else:
            rows.append(
                {
                    "Machine": cell.machine,
                    "Failure Mode": cell.failure_mode,
                    "Risk Level": cell.risk_level,
                    "Risk Score": cell.risk_score,
                    "Evidence Count": 0,
                    "Source Type": "",
                    "Source ID": "",
                    "Audit ID": "",
                    "Evidence": "",
                    "Evidence Score": 0,
                    "Missing Evidence": "; ".join(cell.missing_evidence),
                    "Recommended Action": cell.recommended_action,
                }
            )
    return rows


def risk_heatmap_markdown(summary: RiskHeatmapSummary) -> str:
    matrix_rows: list[dict[str, Any]] = []
    for machine in summary.machines:
        row: dict[str, Any] = {"Machine": machine}
        for mode in summary.failure_modes:
            cell = summary.cell(machine, mode)
            row[mode] = f"{cell.risk_level} ({cell.risk_score})" if cell else RISK_LEVEL_MISSING
        matrix_rows.append(row)
    detail_rows = risk_heatmap_csv_rows(summary)
    lines = [
        "# Risk Heat Map",
        "",
        "## Evidence Rules",
        "- Risk is only scored from local workbook evidence.",
        "- Missing evidence is shown as missing, not converted into a risk claim.",
        "- The report does not modify workbook rows.",
        "",
        "## Summary",
        *[f"- {key}: {value}" for key, value in summary.metrics.items()],
        "",
        "## Heat Map",
        *table_from_rows(matrix_rows, ["Machine", *summary.failure_modes]),
        "",
        "## Evidence Details",
        *table_from_rows(
            detail_rows[:100],
            ["Machine", "Failure Mode", "Risk Level", "Risk Score", "Source Type", "Source ID", "Evidence", "Missing Evidence", "Recommended Action"],
        ),
    ]
    if summary.warnings:
        lines.extend(["", "## Warnings", *[f"- {warning}" for warning in summary.warnings]])
    return "\n".join(lines) + "\n"


def _evidence_from_audits(rows: list[dict[str, Any]]) -> list[RiskEvidence]:
    evidence: list[RiskEvidence] = []
    for row in rows:
        machine = _machine(row)
        if not machine:
            continue
        audit_id = text_value(row.get("Audit ID"))
        haystack = _joined_text(row, AUDIT_TEXT_FIELDS)
        evidence.extend(_keyword_evidence(haystack, machine, "audit", audit_id, audit_id, _audit_score(row)))
        evidence.extend(_documentation_gap_evidence(row, machine, audit_id))
        mismatch = _pneumatic_mismatch_text(row)
        if mismatch:
            evidence.append(RiskEvidence("pneumatic circuit mismatch", machine, "audit", audit_id, mismatch, 8, audit_id=audit_id))
    return evidence


def _evidence_from_issues(rows: list[dict[str, Any]]) -> list[RiskEvidence]:
    evidence: list[RiskEvidence] = []
    for row in rows:
        machine = normalize_machine_token(row.get("Press/Machine #"))
        if not machine:
            continue
        issue_id = text_value(row.get("Issue ID"))
        haystack = _joined_text(row, ISSUE_TEXT_FIELDS)
        severity = parse_score(row.get("Severity")) or 5
        evidence.extend(_keyword_evidence(haystack, machine, "issue", issue_id, "", max(4, min(12, severity))))
    return evidence


def _evidence_from_fmea(rows: list[dict[str, Any]]) -> list[RiskEvidence]:
    evidence: list[RiskEvidence] = []
    for row in rows:
        machine = normalize_machine_token(row.get("Press/Machine #"))
        if not machine:
            continue
        fmea_id = text_value(row.get("FMEA ID"))
        haystack = _joined_text(row, FMEA_TEXT_FIELDS)
        rpn = parse_score(row.get("RPN")) or _rpn_from_scores(row)
        score = 10 if rpn >= 200 else 7 if rpn >= 100 else 5 if rpn else 3
        evidence.extend(_keyword_evidence(haystack, machine, "fmea", fmea_id, "", score))
    return evidence


def _evidence_from_kpis(rows: list[dict[str, Any]]) -> list[RiskEvidence]:
    evidence: list[RiskEvidence] = []
    for row in rows:
        machine = normalize_machine_token(row.get("Press/Machine #"))
        if not machine:
            continue
        kpi_id = text_value(row.get("KPI ID"))
        drops = _numeric(row.get("Part Drops"))
        mispicks = _numeric(row.get("Mis-Picks"))
        scrap = _numeric(row.get("Scrap Quantity"))
        if drops or mispicks:
            evidence.append(RiskEvidence("drop/mis-pick", machine, "kpi", kpi_id, f"Part drops={drops:g}; mis-picks={mispicks:g}.", min(12, int(drops + mispicks) or 1), audit_id=""))
        if scrap:
            evidence.append(RiskEvidence("drop/mis-pick", machine, "kpi", kpi_id, f"Scrap quantity={scrap:g}; reason={text_value(row.get('Scrap Reason')) or 'not recorded'}.", min(8, int(scrap) or 1)))
    return evidence


def _keyword_evidence(haystack: str, machine: str, source_type: str, source_id: str, audit_id: str, score: int) -> list[RiskEvidence]:
    normalized = haystack.casefold()
    found: list[RiskEvidence] = []
    for mode, keywords in FAILURE_MODE_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            found.append(RiskEvidence(mode, machine, source_type, source_id, _excerpt(haystack), score, audit_id=audit_id))
    return found


def _documentation_gap_evidence(row: dict[str, Any], machine: str, audit_id: str) -> list[RiskEvidence]:
    fields = ("Spare Parts Identified?", "BOM Available?", "Drawing/CAD Available?", "Process Binder Complete?")
    missing = [field for field in fields if _is_no_or_missing(row.get(field))]
    if not missing:
        return []
    return [RiskEvidence("documentation gap", machine, "audit", audit_id, f"Missing/negative documentation fields: {', '.join(missing)}.", 3 * len(missing), audit_id=audit_id)]


def _pneumatic_mismatch_text(row: dict[str, Any]) -> str:
    pairs = [
        ("Robot Vacuum Circuits", "EOAT Vacuum Circuits"),
        ("Robot Pressure Circuits", "EOAT Pressure Circuits"),
        ("Robot Interchangeable Circuits", "EOAT Interchangeable Circuits"),
    ]
    mismatches: list[str] = []
    for robot_field, eoat_field in pairs:
        robot = _numeric(row.get(robot_field))
        eoat = _numeric(row.get(eoat_field))
        if robot and eoat and robot != eoat:
            mismatches.append(f"{robot_field}={robot:g} vs {eoat_field}={eoat:g}")
    return "; ".join(mismatches)


def _risk_level(score: int, evidence_count: int) -> str:
    if evidence_count <= 0:
        return RISK_LEVEL_MISSING
    if score >= 24:
        return RISK_LEVEL_CRITICAL
    if score >= 14:
        return RISK_LEVEL_HIGH
    if score >= 6:
        return RISK_LEVEL_MEDIUM
    return RISK_LEVEL_LOW


def _recommended_action(level: str, failure_mode: str) -> str:
    if level == RISK_LEVEL_MISSING:
        return f"No local evidence found for {failure_mode}; do not claim this risk without audit/issue/FMEA/KPI evidence."
    if level in {RISK_LEVEL_CRITICAL, RISK_LEVEL_HIGH}:
        return f"Review {failure_mode} evidence with maintenance/engineering and create follow-up actions."
    return f"Monitor {failure_mode} evidence and keep workbook observations current."


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


def _audit_score(row: dict[str, Any]) -> int:
    priority = text_value(row.get("Priority")).casefold()
    if priority == "critical":
        return 12
    if priority == "high":
        return 8
    if text_value(row.get("Follow-Up Needed")).casefold() == "yes":
        return 6
    return 4


def _rpn_from_scores(row: dict[str, Any]) -> int:
    severity = parse_score(row.get("Severity")) or 0
    frequency = parse_score(row.get("Frequency")) or 0
    detectability = parse_score(row.get("Detectability")) or 0
    return severity * frequency * detectability


def _joined_text(row: dict[str, Any], fields: Iterable[str]) -> str:
    return " | ".join(text_value(row.get(field)) for field in fields if text_value(row.get(field)))


def _excerpt(text: str, limit: int = 180) -> str:
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _is_no_or_missing(value: Any) -> bool:
    text = text_value(value).casefold()
    return text in {"", "no", "n/a", "na", "unknown", "unknown / not checked", "not checked"}


def _numeric(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        parsed = parse_score(value)
        return float(parsed or 0)


def _machine_sort_key(machine: str) -> tuple[int, int | str]:
    return (0, int(machine)) if str(machine).isdigit() else (1, str(machine).casefold())


def _normalize(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().split())


__all__ = [
    "FAILURE_MODES",
    "RiskEvidence",
    "RiskHeatmapCell",
    "RiskHeatmapSummary",
    "RISK_LEVEL_CRITICAL",
    "RISK_LEVEL_HIGH",
    "RISK_LEVEL_LOW",
    "RISK_LEVEL_MEDIUM",
    "RISK_LEVEL_MISSING",
    "build_risk_heatmap",
    "export_risk_heatmap_report",
    "risk_heatmap_csv_rows",
    "risk_heatmap_markdown",
]
