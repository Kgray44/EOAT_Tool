from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .analysis_common import numeric, table_from_rows, write_timestamped_report
from .audit_entries import repair_legacy_audit_lookup_shift
from .fmea_suggestions import build_fmea_suggestions
from .logging import log_tool_run
from .open_items import list_open_items
from .paths import resolve_project_paths
from .photo_evidence import evidence_coverage_for_audit
from .pilot_scoring import rank_pilot_candidates
from .result import ToolResult
from .safe_files import ensure_directory
from .standards_compliance import score_audit_compliance
from .workbook_io import row_dicts


@dataclass(frozen=True)
class PilotEvidencePacket:
    candidate_id: str
    audit_id: str
    machine: str
    eoat_type: str
    known_issues: str
    failure_modes: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    standards_gaps: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    kpi_context: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    photo_evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    open_items: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    expected_improvement_area: str = ""
    implementation_difficulty: str = ""
    risks: tuple[str, ...] = field(default_factory=tuple)
    recommended_next_action: str = ""

    def to_markdown(self) -> str:
        risk_lines = [f"- {risk}" for risk in self.risks] if self.risks else ["- No explicit risks found in current local evidence. Review manually before selection."]
        lines = [
            f"# Pilot Candidate Evidence Packet - {self.candidate_id or self.audit_id or self.machine or 'Unassigned'}",
            "",
            "## Candidate Context",
            f"- Candidate ID: {self.candidate_id or 'N/A'}",
            f"- Audit ID: {self.audit_id or 'N/A'}",
            f"- Press/Machine #: {self.machine or 'N/A'}",
            f"- EOAT Type: {self.eoat_type or 'N/A'}",
            f"- Known Issues: {self.known_issues or 'None documented'}",
            "",
            "## Failure Modes For Review",
            *table_from_rows(list(self.failure_modes), ["Failure Mode", "Evidence", "Suggested Severity", "Suggested Frequency", "Suggested Detectability"]),
            "",
            "## Standards Gaps",
            *table_from_rows(list(self.standards_gaps), ["Category", "Status", "Reason", "Recommended Action"]),
            "",
            "## Downtime / Scrap / Cycle-Time Context",
            *table_from_rows(list(self.kpi_context), ["Metric", "Value", "Source"]),
            "",
            "## Photo / Evidence Coverage",
            *table_from_rows(list(self.photo_evidence), ["Category", "Required", "Present", "Status", "Warning"]),
            "",
            "## Open Items",
            *table_from_rows(list(self.open_items), ["Source", "Severity", "Title", "Status", "Recommended Action"]),
            "",
            "## Analysis Notes",
            f"- Expected improvement area: {self.expected_improvement_area or 'Review required; no quantified improvement claimed.'}",
            f"- Implementation difficulty: {self.implementation_difficulty or 'Unknown / review required'}",
            "",
            "## Risks",
            *risk_lines,
            "",
            "## Recommended Next Action",
            self.recommended_next_action,
            "",
            "## Guardrail",
            "This packet summarizes available local evidence. It does not claim pilot success, ROI, downtime reduction, scrap reduction, or final engineering approval.",
        ]
        return "\n".join(lines) + "\n"


def build_pilot_evidence_packet(
    project_root: str | Path,
    *,
    candidate_id: str = "",
    audit_id: str = "",
    machine: str = "",
) -> tuple[PilotEvidencePacket | None, ToolResult | None]:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return None, ToolResult.fail("pilot_evidence_packet", "Pilot Candidate Evidence Packet", "Master workbook is missing.", errors=[str(paths.master_workbook)])
    try:
        inventory = [repair_legacy_audit_lookup_shift(row) for row in row_dicts(paths.master_workbook, "EOAT Inventory")]
        candidates = row_dicts(paths.master_workbook, "Pilot Candidates")
        kpis = row_dicts(paths.master_workbook, "KPI Baseline")
    except Exception as exc:
        return None, ToolResult.fail("pilot_evidence_packet", "Pilot Candidate Evidence Packet", "Could not read workbook context.", errors=[str(exc)])
    candidate, audit = _resolve_candidate(candidate_id, audit_id, machine, candidates, inventory, project_root)
    if candidate is None and audit is None:
        return None, ToolResult.fail("pilot_evidence_packet", "Pilot Candidate Evidence Packet", "No matching pilot candidate or audit row found.")
    machine_value = _text(machine or (candidate or {}).get("Press/Machine #") or (audit or {}).get("Press/Machine #"))
    audit_id_value = _text(audit_id or (audit or {}).get("Audit ID") or (candidate or {}).get("Candidate ID"))
    eoat_type = _text((audit or candidate or {}).get("EOAT Type"))
    known_issues = _text((audit or {}).get("Known Issues") or (candidate or {}).get("Main Problem"))
    standards = _standards_rows(project_root, audit)
    fmea_rows = _fmea_rows(project_root, audit_id_value, machine_value)
    photo_rows = _photo_rows(project_root, audit_id_value, audit)
    open_rows = _open_item_rows(project_root, audit_id_value, machine_value)
    kpi_rows = _kpi_rows(kpis, machine_value, audit)
    risks = _risk_lines(standards, photo_rows, open_rows, fmea_rows)
    packet = PilotEvidencePacket(
        candidate_id=_text((candidate or {}).get("Candidate ID") or candidate_id),
        audit_id=audit_id_value,
        machine=machine_value,
        eoat_type=eoat_type,
        known_issues=known_issues,
        failure_modes=tuple(fmea_rows),
        standards_gaps=tuple(standards),
        kpi_context=tuple(kpi_rows),
        photo_evidence=tuple(photo_rows),
        open_items=tuple(open_rows),
        expected_improvement_area=_text((candidate or {}).get("Expected KPI Improvement")) or _expected_improvement_area(audit, kpi_rows),
        implementation_difficulty=_text((candidate or {}).get("Ease of Implementation")) or "Unknown / review required",
        risks=tuple(risks),
        recommended_next_action="Review the evidence packet, confirm missing baseline/evidence items, and edit FMEA values before final pilot selection.",
    )
    return packet, None


def generate_pilot_evidence_packet(
    project_root: str | Path,
    *,
    candidate_id: str = "",
    audit_id: str = "",
    machine: str = "",
    log_activity: bool = True,
) -> ToolResult:
    started = time.perf_counter()
    packet, error = build_pilot_evidence_packet(project_root, candidate_id=candidate_id, audit_id=audit_id, machine=machine)
    if error:
        return error
    assert packet is not None
    folder = ensure_directory(resolve_project_paths(project_root).pilot_project / "Candidate_Cells")
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", packet.candidate_id or packet.audit_id or packet.machine or "pilot_candidate").strip("_")
    try:
        report = write_timestamped_report(folder, f"Pilot_Evidence_Packet_{safe_name}", packet.to_markdown())
    except Exception as exc:
        return ToolResult.fail("pilot_evidence_packet", "Pilot Candidate Evidence Packet", "Could not write pilot evidence packet.", errors=[str(exc)])
    result = ToolResult.ok(
        "pilot_evidence_packet",
        "Pilot Candidate Evidence Packet",
        "Generated pilot candidate evidence packet.",
        details=[f"Packet: {report}"],
        files_created=[str(report)],
        output_reports=[str(report)],
        metrics={"failure_modes": len(packet.failure_modes), "standards_gaps": len(packet.standards_gaps), "open_items": len(packet.open_items)},
        duration_seconds=time.perf_counter() - started,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result


def _resolve_candidate(
    candidate_id: str,
    audit_id: str,
    machine: str,
    candidates: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    project_root: str | Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    candidate = _find_candidate(candidates, candidate_id, machine)
    audit = _find_audit(inventory, audit_id or candidate_id, machine or _text((candidate or {}).get("Press/Machine #")))
    if candidate is None and not any([candidate_id, audit_id, machine]):
        ranking, _error = rank_pilot_candidates(project_root)
        if ranking and ranking.ranked_candidates:
            top = ranking.ranked_candidates[0]
            candidate = top
            audit = _find_audit(inventory, _text(top.get("Candidate ID")), _text(top.get("Press/Machine #")))
    return candidate, audit


def _find_candidate(candidates: list[dict[str, Any]], candidate_id: str, machine: str) -> dict[str, Any] | None:
    target_id = _text(candidate_id).casefold()
    target_machine = _text(machine).casefold()
    for row in candidates:
        if target_id and _text(row.get("Candidate ID")).casefold() == target_id:
            return row
        if target_machine and _text(row.get("Press/Machine #")).casefold() == target_machine:
            return row
    return None


def _find_audit(inventory: list[dict[str, Any]], audit_id: str, machine: str) -> dict[str, Any] | None:
    target_id = _text(audit_id).casefold()
    target_machine = _text(machine).casefold()
    for row in inventory:
        if target_id and _text(row.get("Audit ID")).casefold() == target_id:
            return row
        if target_machine and _text(row.get("Press/Machine #")).casefold() == target_machine:
            return row
    return None


def _standards_rows(project_root: str | Path, audit: dict[str, Any] | None) -> list[dict[str, Any]]:
    if audit is None:
        return []
    compliance = score_audit_compliance(project_root, audit)
    rows = []
    for category in [*compliance.failed_standards, *compliance.warnings, *compliance.unknown_items]:
        rows.append({"Category": category.label, "Status": category.status, "Reason": category.reason, "Recommended Action": category.recommended_action})
    return rows


def _fmea_rows(project_root: str | Path, audit_id: str, machine: str) -> list[dict[str, Any]]:
    rows = []
    for suggestion in build_fmea_suggestions(project_root):
        if audit_id and suggestion.get("Audit ID") == audit_id or machine and suggestion.get("Press/Machine #") == machine:
            rows.append(suggestion)
    return rows[:12]


def _photo_rows(project_root: str | Path, audit_id: str, audit: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not audit_id:
        return []
    coverage = evidence_coverage_for_audit(project_root, audit_id, row=audit)
    if coverage is None:
        return []
    return [
        {
            "Category": status.label,
            "Required": "Yes" if status.required else "No",
            "Present": "Yes" if status.present else "No",
            "Status": status.status,
            "Warning": status.warning,
        }
        for status in coverage.statuses
        if status.applies or status.required
    ]


def _open_item_rows(project_root: str | Path, audit_id: str, machine: str) -> list[dict[str, Any]]:
    try:
        items = list_open_items(project_root, include_validation=True)
    except Exception:
        return []
    rows = []
    for item in items:
        if audit_id and item.audit_id == audit_id or machine and item.machine == machine:
            rows.append({"Source": item.source, "Severity": item.severity, "Title": item.title, "Status": item.status, "Recommended Action": item.recommended_action})
    return rows[:15]


def _kpi_rows(kpis: list[dict[str, Any]], machine: str, audit: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = []
    related = [row for row in kpis if _text(row.get("Press/Machine #")).casefold() == machine.casefold()] if machine else []
    metrics = {
        "Downtime Minutes": sum(numeric(row.get("Downtime Minutes")) for row in related),
        "Scrap Quantity": sum(numeric(row.get("Scrap Quantity")) for row in related),
        "Part Drops": sum(numeric(row.get("Part Drops")) for row in related),
        "Mis-Picks": sum(numeric(row.get("Mis-Picks")) for row in related),
    }
    for metric, value in metrics.items():
        if value:
            rows.append({"Metric": metric, "Value": value, "Source": "KPI Baseline"})
    if audit is not None:
        for field in ["Cycle Time Concern?", "Scrap/Quality Concern?"]:
            if _text(audit.get(field)):
                rows.append({"Metric": field, "Value": _text(audit.get(field)), "Source": "EOAT Inventory"})
    if not rows:
        rows.append({"Metric": "Baseline KPI evidence", "Value": "Not available", "Source": "No claim made"})
    return rows


def _risk_lines(standards: list[dict[str, Any]], photo_rows: list[dict[str, Any]], open_rows: list[dict[str, Any]], fmea_rows: list[dict[str, Any]]) -> list[str]:
    risks: list[str] = []
    risks.extend(f"Standards gap: {row['Category']} ({row['Status']})" for row in standards[:5])
    risks.extend(f"Missing photo evidence: {row['Category']}" for row in photo_rows if row.get("Required") == "Yes" and row.get("Present") == "No")
    risks.extend(f"Open item: {row['Title']}" for row in open_rows[:5])
    risks.extend(f"Review FMEA mode: {row.get('Failure Mode')}" for row in fmea_rows[:5])
    return list(dict.fromkeys(risks))


def _expected_improvement_area(audit: dict[str, Any] | None, kpi_rows: list[dict[str, Any]]) -> str:
    if audit is not None:
        if _text(audit.get("Cycle Time Concern?")).casefold() == "yes":
            return "Cycle time stability / changeover review"
        if _text(audit.get("Scrap/Quality Concern?")).casefold() == "yes":
            return "Quality and scrap reduction review"
        if _text(audit.get("Known Issues")):
            return "Reliability issue reduction review"
    if any(row.get("Metric") in {"Downtime Minutes", "Part Drops", "Mis-Picks"} and row.get("Value") != "Not available" for row in kpi_rows):
        return "Reliability and uptime review"
    return "Review required; no quantified improvement claimed"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


__all__ = ["PilotEvidencePacket", "build_pilot_evidence_packet", "generate_pilot_evidence_packet"]
