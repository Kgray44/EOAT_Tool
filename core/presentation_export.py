from __future__ import annotations

import time
from pathlib import Path

from .analysis_common import table_from_rows
from .final_common import (
    make_simple_docx,
    metrics_markdown,
    recent_report_map,
    report_references_markdown,
    safe_rows,
    top_fmea_risks,
    top_issue_categories,
    unique_package_dir,
    workbook_metrics,
)
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory, safe_write_text


TOOL_ID = "final_presentation_helper"
TOOL_NAME = "Final Presentation Builder Helper"

SLIDES = [
    "Title Slide",
    "Project Objective and Scope",
    "Why EOAT Standardization Matters",
    "Audit Methodology",
    "EOAT Inventory / Audit Coverage",
    "Common EOAT Issues Found",
    "Documentation and Standardization Gaps",
    "FMEA-Lite Risk Results",
    "Pilot Candidate Selection Method",
    "Pilot Improvement Overview",
    "Before/After KPI Results",
    "PM Checklist and Maintenance Standard",
    "BOM / Spare Parts Standardization",
    "Training and Work Instruction Materials",
    "Final Recommendations",
    "Handoff Package and Next Steps",
    "Questions",
]


def _write(package: Path, relative: str, text: str) -> Path:
    return safe_write_text(package / relative, text, overwrite=False)


def _slide_outline(metrics: dict, warnings: list[str]) -> str:
    lines = ["# EOAT Final Presentation Slide Outline", ""]
    for index, slide in enumerate(SLIDES, start=1):
        lines.append(f"## {index}. {slide}")
        if slide == "EOAT Inventory / Audit Coverage":
            lines.extend(metrics_markdown(metrics))
        elif slide == "Pilot Improvement Overview":
            lines.append("- Add pilot implementation details only after the pilot is selected and completed.")
        elif slide == "Before/After KPI Results":
            lines.append("- Use before/after data only if measured KPI data exists. Do not claim improvement without evidence.")
        else:
            lines.append("- Add concise evidence-backed talking points.")
        lines.append("")
    if warnings:
        lines.extend(["## Missing Data Notes", *[f"- {warning}" for warning in warnings]])
    return "\n".join(lines) + "\n"


def _summary_doc(title: str, body_lines: list[str]) -> str:
    return "\n".join([f"# {title}", "", *body_lines]) + "\n"


def export_presentation_assets(project_root: str | Path, include_docx: bool = False) -> ToolResult:
    start = time.perf_counter()
    paths = resolve_project_paths(project_root)
    package = unique_package_dir(paths.presentation_assets_root, "Presentation_Assets")
    subfolders = {
        "outline": ensure_directory(package / "01_Slide_Outline"),
        "kpi": ensure_directory(package / "02_KPI_Charts"),
        "audit": ensure_directory(package / "03_Audit_Metrics"),
        "fmea": ensure_directory(package / "04_FMEA_Risks"),
        "pilot": ensure_directory(package / "05_Pilot_Results"),
        "standards": ensure_directory(package / "06_Standards_PM_BOM"),
        "photos": ensure_directory(package / "07_Photo_References"),
        "recommendations": ensure_directory(package / "08_Final_Recommendations"),
    }
    metrics, warnings = workbook_metrics(project_root)
    report_map = recent_report_map(project_root)
    issues = top_issue_categories(project_root)
    fmea_risks = top_fmea_risks(project_root)
    photos, photo_warning = safe_rows(project_root, "Photo Index")
    if photo_warning:
        warnings.append(photo_warning)
    pilots, pilot_warning = safe_rows(project_root, "Pilot Candidates")
    if pilot_warning:
        warnings.append(pilot_warning)
    kpis, kpi_warning = safe_rows(project_root, "KPI Baseline")
    if kpi_warning:
        warnings.append(kpi_warning)

    files_created: list[str] = []
    outline = _slide_outline(metrics, warnings)
    outline_path = _write(subfolders["outline"], "slide_outline.md", outline)
    files_created.append(str(outline_path))
    if include_docx:
        docx = make_simple_docx(outline_path, outline)
        if docx:
            files_created.append(str(docx))
        else:
            warnings.append("DOCX output requested, but python-docx is unavailable.")

    files_created.append(str(_write(subfolders["outline"], "executive_summary_for_slides.md", _summary_doc("Executive Summary for Slides", [
        "This summary is generated from available workbook rows and report outputs.",
        *metrics_markdown(metrics),
        "Missing or incomplete data is called out rather than inferred.",
    ]))))
    files_created.append(str(_write(subfolders["audit"], "audit_metrics_summary.md", _summary_doc("Audit Metrics Summary", metrics_markdown(metrics)))))
    files_created.append(str(_write(subfolders["fmea"], "fmea_top_risks_summary.md", _summary_doc("FMEA Top Risks Summary", table_from_rows(fmea_risks, ["Press/Machine #", "Failure Mode", "RPN", "Recommended Action"]) if fmea_risks else ["No FMEA risk rows are available yet."]))))
    files_created.append(str(_write(subfolders["pilot"], "pilot_results_summary.md", _summary_doc("Pilot Results Summary", [
        f"Pilot candidate rows available: {len(pilots)}",
        "No before/after pilot validation result is claimed unless source KPI or pilot report evidence exists.",
        "If pilot reports are missing, treat this section as a placeholder for final validation.",
    ]))))
    files_created.append(str(_write(subfolders["kpi"], "kpi_summary.md", _summary_doc("KPI Summary", [
        f"KPI baseline records available: {len(kpis)}",
        "KPI baseline data not available yet." if not kpis else "Use the KPI Dashboard outputs as the evidence source for final slides.",
        "No before/after pilot validation data is assumed by this exporter.",
    ]))))
    files_created.append(str(_write(subfolders["standards"], "standardization_summary.md", _summary_doc("Standardization Summary", [
        "PM checklist and BOM/spare part report references are listed below.",
        *report_references_markdown({"PM Checklists": report_map["PM Checklists"], "BOM": report_map["BOM"], "Documentation Gaps": report_map["Documentation Gaps"]}),
    ]))))
    files_created.append(str(_write(subfolders["recommendations"], "final_recommendations.md", _summary_doc("Final Recommendations", [
        "- Review recurring EOAT issues and convert validated themes into standards.",
        "- Keep PM/BOM recommendations tied to observed audit data and verified part documentation.",
        "- Complete KPI/pilot evidence before claiming measurable improvement.",
        "- Use the final handoff package as the source of truth for next-owner follow-up.",
    ]))))
    files_created.append(str(_write(subfolders["photos"], "photo_references.md", _summary_doc("Photo References", [
        f"Photos indexed in workbook: {len(photos)}",
        "This package references photos through the Photo Index by default; it does not copy large photo folders.",
        *table_from_rows(photos[:20], ["Photo ID", "Press/Machine #", "EOAT Area Shown", "Photo Filename", "Folder Path"]),
    ]))))

    asset_index = "\n".join(
        [
            "# Presentation Asset Index",
            "",
            f"Package: {package.name}",
            "",
            "## Contents",
            *[f"- {Path(path).relative_to(package)}" for path in files_created if Path(path).is_relative_to(package)],
            "",
            "## Key Metrics",
            *metrics_markdown(metrics),
            "",
            "## Top Issue Categories",
            *table_from_rows(issues, ["Issue Category", "Count"]),
            "",
            "## Source Report References",
            *report_references_markdown(report_map),
            "",
            "## Missing Data / Honesty Notes",
            *(f"- {warning}" for warning in warnings),
            "- Pilot and KPI improvement claims require before/after evidence before final presentation use.",
        ]
    ) + "\n"
    index_path = safe_write_text(package / "PRESENTATION_ASSET_INDEX.md", asset_index, overwrite=False)
    files_created.append(str(index_path))

    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Created presentation asset package.",
        details=[f"Package: {package}"],
        warnings=warnings,
        files_created=files_created,
        output_reports=[str(index_path), str(outline_path)],
        metrics={**metrics, "asset_files": len(files_created), "package": str(package)},
        duration_seconds=time.perf_counter() - start,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result
