from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .analysis_common import table_from_rows
from .compatibility_health import validate_compatibility_health
from .final_common import (
    report_references_markdown,
    safe_rows,
    top_fmea_risks,
    top_issue_categories,
    workbook_metrics,
)
from .kpi_analysis import analyze_kpis
from .logging import log_tool_run
from .open_items import OpenItem, list_open_items, open_items_summary
from .paths import resolve_project_paths
from .photo_evidence import evidence_coverage_for_project
from .project_data_service import ProjectDataService
from .reports import list_recent_files
from .result import ToolResult
from .risk_insights import build_risk_insight_summary
from .safe_files import ensure_directory, safe_write_text
from .standards_compliance import analyze_standards_compliance
from .validation import validate_project_foundation
from .validation_findings import findings_from_result

READY = "ready"
DRAFT = "draft"
MISSING = "missing"
NEEDS_REVIEW = "needs review"
NOT_APPLICABLE = "not applicable"

READINESS_TOOL_NAME = "Final Handoff Readiness"


@dataclass(frozen=True)
class FinalDeliverableReadiness:
    key: str
    label: str
    status: str
    evidence: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    recommended_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FinalHandoffReadinessSummary:
    deliverables: tuple[FinalDeliverableReadiness, ...]
    metrics: dict[str, int]

    def to_markdown(self) -> str:
        rows = [
            {
                "Deliverable": item.label,
                "Status": item.status,
                "Evidence": "; ".join(item.evidence[:3]),
                "Warnings": "; ".join(item.warnings),
                "Recommended Action": item.recommended_action,
            }
            for item in self.deliverables
        ]
        lines = [
            "# Final Deliverable Readiness",
            "",
            "## Summary",
            *[f"- {key}: {value}" for key, value in self.metrics.items()],
            "",
            "## Checklist",
            *table_from_rows(rows, ["Deliverable", "Status", "Evidence", "Warnings", "Recommended Action"]),
            "",
            "## Readiness Rules",
            "- Ready means current evidence exists in the private project root.",
            "- Draft means partial evidence exists but should be reviewed before final handoff.",
            "- Needs review means the output exists or can be generated, but unresolved evidence or open-item risk remains.",
            "- Missing means no current evidence was found.",
            "- Not applicable means no carryover/output is needed based on current local evidence.",
        ]
        return "\n".join(lines) + "\n"


def technical_appendix_dir(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).final_handoff / "Technical_Appendix"


def open_items_carryover_dir(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).final_handoff / "Open_Items_Carryover"


def deliverable_readiness_dir(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).final_handoff / "Deliverable_Readiness"


def machine_summary_dir(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).machine_summaries


def build_final_handoff_readiness(project_root: str | Path) -> FinalHandoffReadinessSummary:
    paths = resolve_project_paths(project_root)
    inventory, _inventory_warning = safe_rows(project_root, "EOAT Inventory")
    fmea_rows, _fmea_warning = safe_rows(project_root, "FMEA Draft")
    kpi_rows, _kpi_warning = safe_rows(project_root, "KPI Baseline")
    open_items = _safe_open_items(project_root)
    deliverables = (
        _eoat_database(paths.master_workbook, inventory),
        _standards_guidelines(project_root),
        _pm_checklist_package(project_root),
        _fmea_output(project_root, fmea_rows),
        _kpi_output(project_root, kpi_rows),
        _pilot_output(project_root),
        _training_materials(project_root),
        _documentation_gap_summary(project_root),
        _open_items_carryover(project_root, open_items),
        _executive_summary(project_root),
        _technical_appendix(project_root),
        _machine_summary_report(project_root),
    )
    metrics = {
        READY: sum(1 for item in deliverables if item.status == READY),
        DRAFT: sum(1 for item in deliverables if item.status == DRAFT),
        NEEDS_REVIEW: sum(1 for item in deliverables if item.status == NEEDS_REVIEW),
        MISSING: sum(1 for item in deliverables if item.status == MISSING),
        NOT_APPLICABLE: sum(1 for item in deliverables if item.status == NOT_APPLICABLE),
    }
    return FinalHandoffReadinessSummary(deliverables=deliverables, metrics=metrics)


def build_leadership_summary_markdown(project_root: str | Path) -> str:
    metrics, warnings = workbook_metrics(project_root)
    issues = top_issue_categories(project_root)
    risks = top_fmea_risks(project_root)
    risk_insights = _safe_risk_insights(project_root)
    readiness = build_final_handoff_readiness(project_root)
    open_summary = _safe_open_summary(project_root)
    kpi, _kpi_error = analyze_kpis(project_root)
    pilot_status = _pilot_status_text(project_root)
    kpi_status = _kpi_status_text(kpi)
    lines = [
        "# Executive Summary",
        "",
        "## Project Objective",
        "Improve EOAT documentation, standardization readiness, maintenance planning, risk visibility, and evidence-based pilot selection.",
        "",
        "## Work Completed",
        *[f"- {key}: {value}" for key, value in metrics.items()],
        f"- Final deliverables ready: {readiness.metrics.get(READY, 0)} of {len(readiness.deliverables)}",
        "",
        "## Major Findings",
        *table_from_rows(issues, ["Issue Category", "Count"]),
        "",
        "## FMEA / Risk Review",
        *table_from_rows(risks, ["Press/Machine #", "Failure Mode", "RPN", "Recommended Action"]),
        "",
        "## Integrated Risk Insight",
        *_risk_insight_summary_lines(risk_insights),
        "",
        "## Pilot Recommendation / Results",
        pilot_status,
        "",
        "## KPI Impact",
        kpi_status,
        "",
        "## Remaining Risks",
        f"- Unresolved open items: {open_summary.get('total_open_items', 0)}",
        f"- Critical open items: {open_summary.get('critical_open_items', 0)}",
        f"- Missing-evidence open items: {open_summary.get('missing_evidence_count', 0)}",
        *[f"- Missing data note: {warning}" for warning in warnings],
        "",
        "## Next Steps",
        "- Review unresolved open items and decide ownership after handoff.",
        "- Confirm KPI/pilot evidence before claiming measurable impact.",
        "- Keep FMEA, PM, BOM, and standards outputs tied to verified source evidence.",
        "- Use machine summaries for cell-level handoff context, but leave missing evidence marked as missing.",
    ]
    return "\n".join(lines) + "\n"


def build_machine_summary_report_markdown(project_root: str | Path) -> str:
    service = ProjectDataService(project_root)
    machines = service.list_machines()
    rows: list[dict[str, Any]] = []
    recommendations: list[str] = []
    warnings: list[str] = []
    for machine in machines:
        context = service.get_machine_360(machine)
        rows.append(
            {
                "Machine": context.display_name,
                "Physical Audits": context.metrics.get("physical_audit_count", 0),
                "Compatible Rows": context.metrics.get("compatible_entry_count", 0),
                "Open Items": context.metrics.get("open_item_count", 0),
                "Missing Evidence": context.metrics.get("missing_required_photo_evidence", 0),
                "KPI Rows": context.kpi_signals.get("rows", 0),
                "Highest RPN": context.risk_fmea.get("highest_rpn", 0),
                "PM Due": context.pm_status.get("due_now", 0),
                "Recommended Action": "; ".join(context.recommended_actions[:2]),
            }
        )
        recommendations.extend(f"{context.display_name}: {action}" for action in context.recommended_actions[:2])
        warnings.extend(f"{context.display_name}: {warning}" for warning in context.warnings[:2])
    lines = [
        "# Machine Summary Report",
        "",
        "## Scope",
        f"- Machines found from EOAT Inventory: {len(machines)}",
        "- Source type: local workbook/project evidence only.",
        "- No KPI impact, financial value, or pilot result is claimed unless source evidence exists.",
        "",
        "## Source And Confidence Labels",
        "- Physical audit counts are audit-observed workbook data.",
        "- Compatibility counts are workbook-derived rows and do not count as physical verification.",
        "- KPI rows are source-labeled in KPI reports; missing KPI rows remain missing here.",
        "- Missing photo evidence remains listed as missing and is not treated as complete.",
        "- Recommended actions are generated from available evidence and should be reviewed by the project owner.",
        "",
        "## Machine Summary",
        *table_from_rows(
            rows,
            [
                "Machine",
                "Physical Audits",
                "Compatible Rows",
                "Open Items",
                "Missing Evidence",
                "KPI Rows",
                "Highest RPN",
                "PM Due",
                "Recommended Action",
            ],
        ),
        "",
        "## Recommendations",
    ]
    lines.extend(f"- {item}" for item in recommendations[:25])
    if not recommendations:
        lines.append("- No machine-specific recommendations were generated from current evidence.")
    lines.extend(["", "## Missing Evidence And Warnings"])
    lines.extend(f"- {item}" for item in warnings[:25])
    if not warnings:
        lines.append("- No machine data access warnings were reported.")
    if not machines:
        lines.extend(["", "## Missing Data", "- No machines were found in EOAT Inventory."])
    return "\n".join(lines) + "\n"


def build_technical_appendix_markdown(project_root: str | Path) -> str:
    metrics, warnings = workbook_metrics(project_root)
    validation = validate_project_foundation(project_root)
    validation_findings = findings_from_result(validation)
    standards, standards_error = analyze_standards_compliance(project_root)
    kpi, kpi_error = analyze_kpis(project_root)
    risk_insights = _safe_risk_insights(project_root)
    compatibility = validate_compatibility_health(resolve_project_paths(project_root).master_workbook)
    open_items = _safe_open_items(project_root)
    photo_coverages = _safe_photo_coverages(project_root)
    reports = _report_map(project_root)
    standards_rows = []
    if standards is not None:
        for audit in standards.audits:
            for category in [*audit.failed_standards, *audit.warnings, *audit.unknown_items]:
                standards_rows.append(
                    {
                        "Audit ID": audit.audit_id,
                        "Press/Machine #": audit.machine,
                        "Category": category.label,
                        "Status": category.status,
                        "Reason": category.reason,
                    }
                )
    photo_rows = [
        {
            "Audit ID": coverage.audit_id,
            "Press/Machine #": coverage.machine,
            "Missing Required": coverage.missing_required_count,
            "Follow-Up Needed": coverage.follow_up_needed_count,
        }
        for coverage in photo_coverages
    ]
    open_rows = [_open_item_row(item) for item in open_items[:50]]
    lines = [
        "# Technical Appendix",
        "",
        "## Audit Coverage",
        *[f"- {key}: {value}" for key, value in metrics.items()],
        "",
        "## Validation Findings Summary",
        f"- Validation success: {validation.success}",
        f"- Findings: {len(validation_findings)}",
        *table_from_rows(
            [
                {
                    "Severity": finding.severity,
                    "Category": finding.category,
                    "Audit ID": finding.audit_id,
                    "Machine": finding.machine_number,
                    "Message": finding.message,
                }
                for finding in validation_findings[:30]
            ],
            ["Severity", "Category", "Audit ID", "Machine", "Message"],
        ),
        "",
        "## Standards Gaps",
        "Standards analysis unavailable."
        if standards_error
        else f"- Audits scored: {standards.metrics.get('audits_scored', 0) if standards else 0}",
        *table_from_rows(standards_rows[:40], ["Audit ID", "Press/Machine #", "Category", "Status", "Reason"]),
        "",
        "## FMEA Details",
        *table_from_rows(
            top_fmea_risks(project_root, limit=20), ["Press/Machine #", "Failure Mode", "RPN", "Recommended Action"]
        ),
        "",
        "## Integrated Risk Insight",
        *_risk_insight_summary_lines(risk_insights),
        "",
        "## PM/BOM Findings",
        *report_references_markdown(
            {
                "PM Checklists": reports["PM Checklists"],
                "BOM": reports["BOM"],
                "Risk Insights": reports["Risk Insights"],
            }
        ),
        "",
        "## KPI Dashboard / Export",
        "KPI analysis unavailable." if kpi_error else f"- KPI rows: {kpi.metrics.get('kpi_rows', 0) if kpi else 0}",
        "KPI impact is not claimed unless before/after pilot evidence is available.",
        "",
        "## Photo / Evidence References",
        *table_from_rows(photo_rows[:40], ["Audit ID", "Press/Machine #", "Missing Required", "Follow-Up Needed"]),
        "",
        "## Open Items",
        *table_from_rows(
            open_rows,
            ["Source", "Severity", "Category", "Title", "Status", "Audit ID", "Machine", "Recommended Action"],
        ),
        "",
        "## Compatibility Health Summary",
        f"- Compatibility findings: {len(compatibility)}",
        *table_from_rows(
            [
                {
                    "Severity": finding.severity,
                    "Audit ID": finding.audit_id,
                    "Machine": finding.machine_number,
                    "Message": finding.message,
                }
                for finding in compatibility[:20]
            ],
            ["Severity", "Audit ID", "Machine", "Message"],
        ),
        "",
        "## Source Report References",
        *report_references_markdown(reports),
    ]
    if warnings:
        lines.extend(["", "## Missing Data Notes", *[f"- {warning}" for warning in warnings]])
    return "\n".join(lines) + "\n"


def build_open_items_carryover_markdown(project_root: str | Path) -> str:
    items = _safe_open_items(project_root)
    rows = [_open_item_row(item) for item in items]
    lines = [
        "# Open Items Carryover",
        "",
        "## Summary",
        f"- Unresolved open items: {len(items)}",
        "",
        "## Carryover Items",
        *table_from_rows(
            rows,
            [
                "Source",
                "Severity",
                "Category",
                "Title",
                "Status",
                "Audit ID",
                "Machine",
                "Field",
                "Due Date",
                "Recommended Action",
            ],
        ),
        "",
        "## Handoff Note",
        "These unresolved items should be assigned an owner or explicitly dismissed after review. They are not hidden by the final package builder.",
    ]
    return "\n".join(lines) + "\n"


def export_leadership_summary(
    project_root: str | Path,
    output_dir: str | Path | None = None,
    *,
    filename: str | None = None,
    log_activity: bool = True,
) -> ToolResult:
    return _export_markdown(
        project_root,
        "leadership_summary_export",
        "Leadership Summary Export",
        build_leadership_summary_markdown(project_root),
        Path(output_dir) if output_dir else resolve_project_paths(project_root).executive_summary,
        filename or ("Executive_Summary.md" if output_dir else f"Executive_Summary_{time.strftime('%Y%m%d_%H%M')}.md"),
        log_activity,
    )


def export_technical_appendix(
    project_root: str | Path,
    output_dir: str | Path | None = None,
    *,
    filename: str | None = None,
    log_activity: bool = True,
) -> ToolResult:
    return _export_markdown(
        project_root,
        "technical_appendix_export",
        "Technical Appendix Export",
        build_technical_appendix_markdown(project_root),
        Path(output_dir) if output_dir else technical_appendix_dir(project_root),
        filename
        or ("Technical_Appendix.md" if output_dir else f"Technical_Appendix_{time.strftime('%Y%m%d_%H%M')}.md"),
        log_activity,
    )


def export_open_items_carryover(
    project_root: str | Path,
    output_dir: str | Path | None = None,
    *,
    filename: str | None = None,
    log_activity: bool = True,
) -> ToolResult:
    return _export_markdown(
        project_root,
        "open_items_carryover_export",
        "Open Items Carryover Export",
        build_open_items_carryover_markdown(project_root),
        Path(output_dir) if output_dir else open_items_carryover_dir(project_root),
        filename
        or ("Open_Items_Carryover.md" if output_dir else f"Open_Items_Carryover_{time.strftime('%Y%m%d_%H%M')}.md"),
        log_activity,
    )


def export_deliverable_readiness(
    project_root: str | Path,
    output_dir: str | Path | None = None,
    *,
    filename: str | None = None,
    log_activity: bool = True,
) -> ToolResult:
    readiness = build_final_handoff_readiness(project_root)
    return _export_markdown(
        project_root,
        "final_readiness_export",
        "Final Deliverable Readiness Export",
        readiness.to_markdown(),
        Path(output_dir) if output_dir else deliverable_readiness_dir(project_root),
        filename
        or ("Deliverable_Readiness.md" if output_dir else f"Deliverable_Readiness_{time.strftime('%Y%m%d_%H%M')}.md"),
        log_activity,
        metrics=readiness.metrics,
    )


def export_machine_summary_report(
    project_root: str | Path,
    output_dir: str | Path | None = None,
    *,
    filename: str | None = None,
    log_activity: bool = True,
) -> ToolResult:
    return _export_markdown(
        project_root,
        "machine_summary_report",
        "Machine Summary Report",
        build_machine_summary_report_markdown(project_root),
        Path(output_dir) if output_dir else machine_summary_dir(project_root),
        filename
        or ("Machine_Summary_Report.md" if output_dir else f"Machine_Summary_Report_{time.strftime('%Y%m%d_%H%M')}.md"),
        log_activity,
    )


def _export_markdown(
    project_root: str | Path,
    tool_id: str,
    tool_name: str,
    markdown: str,
    output_dir: Path,
    filename: str,
    log_activity: bool,
    *,
    metrics: dict[str, Any] | None = None,
) -> ToolResult:
    started = time.perf_counter()
    ensure_directory(output_dir)
    path = _safe_output_path(output_dir / filename)
    try:
        saved = safe_write_text(path, markdown, overwrite=False)
    except Exception as exc:
        return ToolResult.fail(tool_id, tool_name, f"Could not write {filename}.", errors=[str(exc)])
    result = ToolResult.ok(
        tool_id,
        tool_name,
        f"Generated {filename}.",
        files_created=[str(saved)],
        output_reports=[str(saved)],
        metrics=metrics or {},
        duration_seconds=time.perf_counter() - started,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result


def _safe_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")


def _eoat_database(workbook: Path, inventory: list[dict[str, Any]]) -> FinalDeliverableReadiness:
    if not workbook.exists():
        return FinalDeliverableReadiness(
            "eoat_database",
            "EOAT Database",
            MISSING,
            recommended_action="Restore or create the EOAT master tracker workbook.",
        )
    if not inventory:
        return FinalDeliverableReadiness(
            "eoat_database",
            "EOAT Database",
            DRAFT,
            (str(workbook),),
            ("Workbook exists but no EOAT Inventory rows were found.",),
            "Complete or import audit rows.",
        )
    return FinalDeliverableReadiness(
        "eoat_database",
        "EOAT Database",
        READY,
        (str(workbook),),
        recommended_action="Review workbook before final distribution.",
    )


def _standards_guidelines(project_root: str | Path) -> FinalDeliverableReadiness:
    paths = resolve_project_paths(project_root)
    guideline_files = _files(paths.standards / "EOAT_Design_Guideline_Draft")
    standards_reports = _files(paths.documentation_gap_reports) + _files(paths.bom_standardization_reports)
    if guideline_files:
        return FinalDeliverableReadiness(
            "standards_guidelines",
            "Standards Guidelines",
            READY,
            tuple(str(path) for path in guideline_files[:3]),
            recommended_action="Confirm mentor-approved guideline status.",
        )
    if standards_reports:
        return FinalDeliverableReadiness(
            "standards_guidelines",
            "Standards Guidelines",
            DRAFT,
            tuple(str(path) for path in standards_reports[:3]),
            ("Reports exist, but no guideline draft file was found.",),
            "Create or add the standards guideline draft.",
        )
    return FinalDeliverableReadiness(
        "standards_guidelines",
        "Standards Guidelines",
        MISSING,
        recommended_action="Create the standards guideline draft or document why it is unavailable.",
    )


def _pm_checklist_package(project_root: str | Path) -> FinalDeliverableReadiness:
    paths = resolve_project_paths(project_root)
    checklists = _files(paths.pm_generated_checklists)
    templates = _files(paths.standards / "PM_Checklist_Draft")
    if checklists:
        return FinalDeliverableReadiness(
            "pm_checklist_package",
            "PM Checklist Package",
            READY,
            tuple(str(path) for path in checklists[:3]),
            recommended_action="Review generated PM checklist coverage.",
        )
    if templates:
        return FinalDeliverableReadiness(
            "pm_checklist_package",
            "PM Checklist Package",
            DRAFT,
            tuple(str(path) for path in templates[:3]),
            ("Only templates were found.",),
            "Generate audit-specific PM checklists where needed.",
        )
    return FinalDeliverableReadiness(
        "pm_checklist_package", "PM Checklist Package", MISSING, recommended_action="Generate PM checklist outputs."
    )


def _fmea_output(project_root: str | Path, rows: list[dict[str, Any]]) -> FinalDeliverableReadiness:
    reports = _files(resolve_project_paths(project_root).fmea_reports)
    if rows and reports:
        return FinalDeliverableReadiness(
            "fmea_output",
            "FMEA Output",
            READY,
            tuple(str(path) for path in reports[:3]),
            recommended_action="Confirm FMEA rows remain draft/reviewed as appropriate.",
        )
    if rows or reports:
        return FinalDeliverableReadiness(
            "fmea_output",
            "FMEA Output",
            DRAFT,
            tuple(str(path) for path in reports[:3]),
            ("FMEA rows or report output are incomplete.",),
            "Generate/review the FMEA report and accepted draft rows.",
        )
    return FinalDeliverableReadiness(
        "fmea_output", "FMEA Output", MISSING, recommended_action="Generate FMEA analysis output."
    )


def _kpi_output(project_root: str | Path, rows: list[dict[str, Any]]) -> FinalDeliverableReadiness:
    reports = _files(resolve_project_paths(project_root).kpi_dashboard_exports)
    if rows and reports:
        return FinalDeliverableReadiness(
            "kpi_dashboard_export",
            "KPI Dashboard/Export",
            READY,
            tuple(str(path) for path in reports[:3]),
            ("KPI impact still requires before/after evidence before claims.",),
            "Review KPI baseline versus any pilot evidence.",
        )
    if rows or reports:
        return FinalDeliverableReadiness(
            "kpi_dashboard_export",
            "KPI Dashboard/Export",
            DRAFT,
            tuple(str(path) for path in reports[:3]),
            ("Only KPI rows or reports were found.",),
            "Generate KPI export or complete baseline data.",
        )
    return FinalDeliverableReadiness(
        "kpi_dashboard_export",
        "KPI Dashboard/Export",
        MISSING,
        warnings=("KPI impact unavailable.",),
        recommended_action="Add KPI baseline/export if required; do not claim impact without evidence.",
    )


def _pilot_output(project_root: str | Path) -> FinalDeliverableReadiness:
    paths = resolve_project_paths(project_root)
    before_after = _files(paths.pilot_project / "Before_After_Data")
    pilot_reports = _files(paths.pilot_project / "Pilot_Reports")
    candidate_packets = _files(paths.pilot_project / "Candidate_Cells")
    if before_after and pilot_reports:
        return FinalDeliverableReadiness(
            "pilot_results_or_packets",
            "Pilot Results or Pilot Candidate Packets",
            READY,
            tuple(str(path) for path in (pilot_reports + before_after)[:3]),
            recommended_action="Review before/after evidence before stating pilot results.",
        )
    if candidate_packets:
        return FinalDeliverableReadiness(
            "pilot_results_or_packets",
            "Pilot Results or Pilot Candidate Packets",
            DRAFT,
            tuple(str(path) for path in candidate_packets[:3]),
            ("Pilot candidate packets exist; final pilot results are unavailable unless before/after data is added.",),
            "Use candidate packets as recommendation evidence only.",
        )
    return FinalDeliverableReadiness(
        "pilot_results_or_packets",
        "Pilot Results or Pilot Candidate Packets",
        MISSING,
        warnings=("Pilot results unavailable.",),
        recommended_action="Generate pilot candidate evidence packets or add pilot results when measured.",
    )


def _training_materials(project_root: str | Path) -> FinalDeliverableReadiness:
    paths = resolve_project_paths(project_root)
    files = _files(paths.training_materials) + _files(paths.standards / "Work_Instructions")
    if files:
        return FinalDeliverableReadiness(
            "training_materials",
            "Training Materials",
            READY,
            tuple(str(path) for path in files[:3]),
            recommended_action="Confirm training materials are appropriate for final audience.",
        )
    return FinalDeliverableReadiness(
        "training_materials",
        "Training Materials",
        MISSING,
        recommended_action="Add training/work instruction material or mark as unavailable.",
    )


def _documentation_gap_summary(project_root: str | Path) -> FinalDeliverableReadiness:
    files = _files(resolve_project_paths(project_root).documentation_gap_reports)
    if files:
        return FinalDeliverableReadiness(
            "documentation_gap_summary",
            "Documentation Gap Summary",
            READY,
            tuple(str(path) for path in files[:3]),
            recommended_action="Review open documentation gaps before handoff.",
        )
    return FinalDeliverableReadiness(
        "documentation_gap_summary",
        "Documentation Gap Summary",
        MISSING,
        recommended_action="Generate documentation gap summary.",
    )


def _open_items_carryover(project_root: str | Path, items: list[OpenItem]) -> FinalDeliverableReadiness:
    files = _files(open_items_carryover_dir(project_root)) + _package_files(project_root, "Open_Items_Carryover.md")
    if files:
        return FinalDeliverableReadiness(
            "open_items_carryover",
            "Open Items Carryover",
            READY,
            tuple(str(path) for path in files[:3]),
            warnings=((f"{len(items)} unresolved item(s) remain.",) if items else ()),
            recommended_action="Assign ownership for unresolved carryover items.",
        )
    if items:
        return FinalDeliverableReadiness(
            "open_items_carryover",
            "Open Items Carryover",
            NEEDS_REVIEW,
            warnings=(f"{len(items)} unresolved open item(s) need carryover export.",),
            recommended_action="Export open items carryover.",
        )
    return FinalDeliverableReadiness(
        "open_items_carryover",
        "Open Items Carryover",
        READY,
        warnings=("No unresolved open items found.",),
        recommended_action="No carryover export is required unless new items are added.",
    )


def _executive_summary(project_root: str | Path) -> FinalDeliverableReadiness:
    files = _files(resolve_project_paths(project_root).executive_summary) + _package_files(
        project_root, "Executive_Summary.md"
    )
    if files:
        return FinalDeliverableReadiness(
            "executive_summary",
            "Executive Summary",
            READY,
            tuple(str(path) for path in files[:3]),
            recommended_action="Review wording for leadership audience.",
        )
    return FinalDeliverableReadiness(
        "executive_summary", "Executive Summary", MISSING, recommended_action="Export leadership summary."
    )


def _technical_appendix(project_root: str | Path) -> FinalDeliverableReadiness:
    files = _files(technical_appendix_dir(project_root)) + _package_files(project_root, "Technical_Appendix.md")
    if files:
        return FinalDeliverableReadiness(
            "technical_appendix",
            "Technical Appendix",
            READY,
            tuple(str(path) for path in files[:3]),
            recommended_action="Review appendix for source evidence completeness.",
        )
    return FinalDeliverableReadiness(
        "technical_appendix", "Technical Appendix", MISSING, recommended_action="Export technical appendix."
    )


def _machine_summary_report(project_root: str | Path) -> FinalDeliverableReadiness:
    files = _files(machine_summary_dir(project_root)) + _package_files(project_root, "Machine_Summary_Report.md")
    if files:
        return FinalDeliverableReadiness(
            "machine_summary_report",
            "Machine Summary Report",
            READY,
            tuple(str(path) for path in files[:3]),
            recommended_action="Review machine-level recommendations before handoff.",
        )
    return FinalDeliverableReadiness(
        "machine_summary_report",
        "Machine Summary Report",
        MISSING,
        recommended_action="Generate machine summary report.",
    )


def _safe_open_items(project_root: str | Path) -> list[OpenItem]:
    try:
        return list_open_items(project_root, include_validation=True)
    except Exception:
        return []


def _safe_open_summary(project_root: str | Path) -> dict[str, int]:
    try:
        return open_items_summary(project_root)
    except Exception:
        return {"total_open_items": 0, "critical_open_items": 0, "missing_evidence_count": 0}


def _safe_photo_coverages(project_root: str | Path):
    try:
        return evidence_coverage_for_project(project_root)
    except Exception:
        return []


def _safe_risk_insights(project_root: str | Path):
    try:
        return build_risk_insight_summary(project_root)
    except Exception:
        return None


def _risk_insight_summary_lines(summary: Any) -> list[str]:
    if summary is None:
        return ["Risk insight summary unavailable."]
    lines = [
        f"- Top FMEA risks shown: {summary.metrics.get('top_risk_count', 0)}",
        f"- Pilot candidates shown: {summary.metrics.get('pilot_candidate_count', 0)}",
        f"- KPI rows available: {summary.metrics.get('kpi_rows', 0)}",
        f"- Missing KPI fields: {summary.metrics.get('missing_kpi_fields_total', 0)}",
    ]
    if summary.recommended_actions:
        lines.extend(["", "Recommended actions:"])
        lines.extend(f"- {action}" for action in summary.recommended_actions[:5])
    if summary.warnings:
        lines.extend(["", "Source warnings:"])
        lines.extend(f"- {warning}" for warning in summary.warnings[:5])
    return lines


def _open_item_row(item: OpenItem) -> dict[str, Any]:
    return {
        "Source": item.source,
        "Severity": item.severity,
        "Category": item.category,
        "Title": item.title,
        "Status": item.status,
        "Audit ID": item.audit_id,
        "Machine": item.machine,
        "Field": item.field,
        "Due Date": item.due_date,
        "Recommended Action": item.recommended_action,
    }


def _pilot_status_text(project_root: str | Path) -> str:
    paths = resolve_project_paths(project_root)
    before_after = _files(paths.pilot_project / "Before_After_Data")
    pilot_reports = _files(paths.pilot_project / "Pilot_Reports")
    packets = _files(paths.pilot_project / "Candidate_Cells")
    if before_after and pilot_reports:
        return "Pilot result evidence is present. Review the before/after source files before stating final results."
    if packets:
        return "Pilot candidate packets/rankings are available. Final pilot results are unavailable unless before/after data is added."
    return "Pilot recommendation/results unavailable. Do not claim pilot completion or impact without source evidence."


def _kpi_status_text(kpi_summary: Any) -> str:
    if kpi_summary is None or not kpi_summary.metrics.get("kpi_rows"):
        return "KPI impact unavailable. No measurable impact is claimed."
    return (
        f"KPI baseline rows available: {kpi_summary.metrics.get('kpi_rows', 0)}. "
        "Before/after KPI impact is unavailable unless pilot validation evidence is added; no impact number is claimed here."
    )


def _report_map(project_root: str | Path) -> dict[str, list[Path]]:
    paths = resolve_project_paths(project_root)
    return {
        "Audit Progress": list_recent_files(paths.audit_progress_reports, 5),
        "Issue Analysis": list_recent_files(paths.issue_analysis_reports, 5),
        "Documentation Gaps": list_recent_files(paths.documentation_gap_reports, 5),
        "Standards": list_recent_files(paths.documentation_gap_reports, 5)
        + list_recent_files(paths.bom_standardization_reports, 5),
        "FMEA": list_recent_files(paths.fmea_reports, 5),
        "Pilot Candidates": list_recent_files(paths.pilot_project / "Candidate_Cells", 5),
        "KPI": list_recent_files(paths.kpi_dashboard_exports, 5),
        "Risk Insights": list_recent_files(paths.risk_insights_reports, 5),
        "PM Checklists": list_recent_files(paths.pm_generated_checklists, 5),
        "BOM": list_recent_files(paths.bom_standardization_reports, 5),
        "Validation": list_recent_files(paths.validation_reports, 5),
    }


def _files(
    folder: Path,
    patterns: tuple[str, ...] = ("*.md", "*.docx", "*.pdf", "*.xlsx", "*.csv", "*.png", "*.pptx", "*.json"),
) -> list[Path]:
    if not folder.exists():
        return []
    found: list[Path] = []
    for pattern in patterns:
        found.extend(path for path in folder.rglob(pattern) if path.is_file())
    return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)


def _package_files(project_root: str | Path, filename: str) -> list[Path]:
    root = resolve_project_paths(project_root).final_handoff
    if not root.exists():
        return []
    return sorted(
        [path for path in root.glob(f"Final_Handoff_Package_*/{filename}") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


__all__ = [
    "DRAFT",
    "FinalDeliverableReadiness",
    "FinalHandoffReadinessSummary",
    "MISSING",
    "NEEDS_REVIEW",
    "NOT_APPLICABLE",
    "READY",
    "build_final_handoff_readiness",
    "build_leadership_summary_markdown",
    "build_machine_summary_report_markdown",
    "build_open_items_carryover_markdown",
    "build_technical_appendix_markdown",
    "deliverable_readiness_dir",
    "export_deliverable_readiness",
    "export_leadership_summary",
    "export_machine_summary_report",
    "export_open_items_carryover",
    "export_technical_appendix",
    "machine_summary_dir",
    "open_items_carryover_dir",
    "technical_appendix_dir",
]
