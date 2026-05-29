from __future__ import annotations

import time
from pathlib import Path

from .analysis_common import write_timestamped_report
from .final_common import DeliverableStatus, safe_rows, status_table_markdown
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory
from .workbook_io import workbook_sheet_names

TOOL_ID = "final_deliverable_check"
TOOL_NAME = "Final Deliverable Checker"


def _files(folder: Path, patterns: tuple[str, ...] = ("*.md", "*.docx", "*.pdf", "*.xlsx", "*.csv", "*.png", "*.pptx")) -> list[Path]:
    if not folder.exists():
        return []
    found: list[Path] = []
    for pattern in patterns:
        found.extend(path for path in folder.rglob(pattern) if path.is_file())
    return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)


def check_deliverables(project_root: str | Path) -> tuple[list[DeliverableStatus], list[str]]:
    paths = resolve_project_paths(project_root)
    warnings: list[str] = []
    statuses: list[DeliverableStatus] = []

    workbook_ok = paths.master_workbook.exists()
    inventory_rows, warning = safe_rows(project_root, "EOAT Inventory")
    if warning:
        warnings.append(warning)
    workbook_evidence = [str(paths.master_workbook)] if workbook_ok else []
    workbook_status = "Found" if workbook_ok and inventory_rows else ("Partial" if workbook_ok else "Missing")
    workbook_notes = f"{len(inventory_rows)} EOAT Inventory row(s)." if workbook_ok else "Master workbook missing."
    if workbook_ok:
        try:
            sheets = workbook_sheet_names(paths.master_workbook)
            if "EOAT Inventory" not in sheets:
                workbook_status = "Partial"
                workbook_notes = "Workbook exists but EOAT Inventory sheet was not found."
        except Exception as exc:
            workbook_status = "Needs review"
            workbook_notes = f"Workbook exists but could not be inspected: {exc}"
    statuses.append(DeliverableStatus("EOAT inventory database", workbook_status, workbook_evidence, workbook_notes))

    guideline_files = _files(paths.standards / "EOAT_Design_Guideline_Draft")
    statuses.append(DeliverableStatus("EOAT standard design guideline", "Found" if guideline_files else "Missing", [str(p) for p in guideline_files[:3]], "Looked in 03_Standards/EOAT_Design_Guideline_Draft."))

    pm_files = _files(paths.pm_generated_checklists)
    template_files = _files(paths.standards / "PM_Checklist_Draft")
    pm_status = "Found" if pm_files else ("Partial" if template_files else "Missing")
    statuses.append(DeliverableStatus("PM checklist", pm_status, [str(p) for p in (pm_files or template_files)[:3]], "Generated checklists count as found; templates alone are partial."))

    fmea_rows, _ = safe_rows(project_root, "FMEA Draft")
    fmea_reports = _files(paths.fmea_reports)
    fmea_status = "Found" if fmea_rows and fmea_reports else ("Partial" if fmea_rows or fmea_reports else "Missing")
    statuses.append(DeliverableStatus("FMEA-lite risk assessment", fmea_status, [str(p) for p in fmea_reports[:3]], f"{len(fmea_rows)} FMEA Draft row(s)."))

    pilot_reports = _files(paths.pilot_project / "Pilot_Reports") + _files(paths.pilot_project / "Candidate_Cells")
    before_after = _files(paths.pilot_project / "Before_After_Data")
    pilot_status = "Found" if pilot_reports and before_after else ("Partial" if pilot_reports or before_after else "Missing")
    statuses.append(DeliverableStatus("Pilot optimization project/report", pilot_status, [str(p) for p in (pilot_reports + before_after)[:3]], "Before/after data is required before claiming pilot results."))

    kpi_rows, _ = safe_rows(project_root, "KPI Baseline")
    kpi_reports = _files(paths.kpi_dashboard_exports)
    kpi_status = "Found" if kpi_rows and kpi_reports else ("Partial" if kpi_rows or kpi_reports else "Missing")
    statuses.append(DeliverableStatus("KPI dashboard/report", kpi_status, [str(p) for p in kpi_reports[:3]], f"{len(kpi_rows)} KPI Baseline row(s)."))

    training_files = _files(paths.training_materials) + _files(paths.standards / "Work_Instructions")
    statuses.append(DeliverableStatus("Training materials", "Found" if training_files else "Missing", [str(p) for p in training_files[:3]], "Looked in final handoff training and standards work instruction folders."))

    bom_reports = _files(paths.bom_standardization_reports)
    statuses.append(DeliverableStatus("BOM/spare parts standardization report", "Found" if bom_reports else "Missing", [str(p) for p in bom_reports[:3]], "BOM analysis reports are evidence; verified part numbers still require source confirmation."))

    doc_gap = _files(paths.documentation_gap_reports)
    statuses.append(DeliverableStatus("Documentation gap report", "Found" if doc_gap else "Missing", [str(p) for p in doc_gap[:3]], "Looked in Documentation_Gap_Reports."))

    package_exec_files = [path for path in paths.final_handoff.glob("Final_Handoff_Package_*/Executive_Summary.md") if path.is_file()] if paths.final_handoff.exists() else []
    exec_files = _files(paths.executive_summary) + sorted(package_exec_files, key=lambda path: path.stat().st_mtime, reverse=True)
    statuses.append(DeliverableStatus("Executive summary", "Found" if exec_files else "Missing", [str(p) for p in exec_files[:3]], "Looked in 06_Final_Handoff/Executive_Summary and Phase 11 packages."))

    pres_packages = [path for path in paths.presentation_assets_root.glob("Presentation_Assets_*") if path.is_dir()] if paths.presentation_assets_root.exists() else []
    statuses.append(DeliverableStatus("Final presentation assets", "Found" if pres_packages else "Missing", [str(p) for p in pres_packages[:3]], "Looked for Auto_Exported_Content packages."))

    recommendation_files = _files(paths.final_report) + _files(paths.presentation_assets_root, ("final_recommendations.md", "*.md"))
    statuses.append(DeliverableStatus("Final recommendations", "Found" if recommendation_files else "Missing", [str(p) for p in recommendation_files[:3]], "Recommendations must remain evidence-based."))

    legacy_packages = [path for path in paths.handoff_package_root.glob("Final_Handoff_*") if path.is_dir()] if paths.handoff_package_root.exists() else []
    phase11_packages = [path for path in paths.final_handoff.glob("Final_Handoff_Package_*") if path.is_dir()] if paths.final_handoff.exists() else []
    handoff_packages = sorted([*phase11_packages, *legacy_packages], key=lambda path: path.stat().st_mtime, reverse=True)
    statuses.append(DeliverableStatus("Handoff package", "Found" if handoff_packages else "Missing", [str(p) for p in handoff_packages[:3]], "Looked in 06_Final_Handoff for Phase 11 packages and legacy Handoff_Package outputs."))
    return statuses, warnings


def _markdown(statuses: list[DeliverableStatus], warnings: list[str]) -> str:
    counts = {status: sum(1 for item in statuses if item.status == status) for status in ["Found", "Partial", "Needs review", "Missing", "Not applicable"]}
    missing = [item for item in statuses if item.status == "Missing"]
    partial = [item for item in statuses if item.status in {"Partial", "Needs review"}]
    lines = [
        "# Final Deliverable Check",
        "",
        "## Executive Summary",
        *[f"- {key}: {value}" for key, value in counts.items() if value],
    ]
    if warnings:
        lines.extend(f"- Warning: {warning}" for warning in warnings)
    lines.extend(["", "## Deliverable Status Table"])
    lines.extend(status_table_markdown(statuses))
    lines.extend(["", "## Missing Deliverables"])
    lines.extend([f"- {item.name}: {item.notes}" for item in missing] or ["- None."])
    lines.extend(["", "## Partial / Needs Review Deliverables"])
    lines.extend([f"- {item.name}: {item.notes}" for item in partial] or ["- None."])
    lines.extend(["", "## Found Deliverables"])
    lines.extend([f"- {item.name}" for item in statuses if item.status == "Found"] or ["- None."])
    lines.extend(["", "## Recommended Final Actions"])
    lines.extend(
        [
            "- Fill missing deliverables or explicitly mark them not available before final review.",
            "- Avoid claiming KPI or pilot improvement without supporting before/after evidence.",
            "- Generate presentation assets and final summary before building the final handoff package.",
        ]
    )
    lines.extend(["", "## Evidence / File Paths"])
    for item in statuses:
        lines.append(f"### {item.name}")
        if item.evidence:
            lines.extend(f"- {path}" for path in item.evidence)
        else:
            lines.append("- No file evidence found.")
    return "\n".join(lines) + "\n"


def run_final_deliverable_check(project_root: str | Path, log_activity: bool = True) -> ToolResult:
    start = time.perf_counter()
    paths = resolve_project_paths(project_root)
    ensure_directory(paths.handoff_package_root)
    statuses, warnings = check_deliverables(project_root)
    report = write_timestamped_report(paths.handoff_package_root, "Final_Deliverable_Check", _markdown(statuses, warnings))
    metrics = {status: sum(1 for item in statuses if item.status == status) for status in {"Found", "Partial", "Needs review", "Missing", "Not applicable"}}
    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Generated final deliverable check.",
        details=[f"Checked {len(statuses)} deliverables.", f"Report: {report}"],
        warnings=warnings,
        files_created=[str(report)],
        output_reports=[str(report)],
        metrics=metrics,
        duration_seconds=time.perf_counter() - start,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result
