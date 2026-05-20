from __future__ import annotations

import time
from pathlib import Path

from .analysis_common import table_from_rows, write_timestamped_report
from .final_common import make_simple_docx, metrics_markdown, recent_report_map, report_references_markdown, top_fmea_risks, top_issue_categories, workbook_metrics
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory


TOOL_ID = "final_project_summary"
TOOL_NAME = "Final Project Summary Compiler"


def build_final_summary_markdown(project_root: str | Path, notes: str = "") -> tuple[str, list[str], dict]:
    metrics, warnings = workbook_metrics(project_root)
    reports = recent_report_map(project_root)
    issues = top_issue_categories(project_root)
    risks = top_fmea_risks(project_root)
    lines = [
        "# Final Project Summary Draft",
        "",
        "## 1. Project Title",
        "Nolato Summer 2026 EOAT Standardization and Optimization Project",
        "",
        "## 2. Business Objective",
        "Improve EOAT documentation, standardization, maintenance readiness, and evidence-based optimization planning.",
        "",
        "## 3. Scope",
        "Robotic EOAT systems used in injection molding, with emphasis on audit data, PM standards, BOM/spares visibility, risk assessment, and pilot candidate selection.",
        "",
        "## 4. Project Timeline",
        "Use weekly summaries and project schedule files as the source of truth for final timeline details.",
        "",
        "## 5. Methods",
        "- EOAT inventory audit",
        "- Issue logging and operator/technician interviews",
        "- FMEA-lite risk review",
        "- KPI baseline tracking where data is available",
        "- PM checklist and BOM/spares standardization drafts",
        "",
        "## 6. EOAT Audit Summary",
        *metrics_markdown(metrics),
        "",
        "## 7. KPI Baseline and Measurement Approach",
        "KPI baseline records available: " + str(metrics.get("KPI records available", 0)),
        "Not available yet: before/after pilot validation data should be added only when measured.",
        "",
        "## 8. Common Issues Found",
        *table_from_rows(issues, ["Issue Category", "Count"]),
        "",
        "## 9. FMEA-Lite Summary",
        *table_from_rows(risks, ["Press/Machine #", "Failure Mode", "RPN", "Recommended Action"]),
        "",
        "## 10. Documentation and Standardization Gaps",
        "Reference the latest documentation gap and BOM/spare parts reports listed in the appendix.",
        "",
        "## 11. Pilot Candidate Selection",
        "Pilot candidate ranking reports should be used for the final selection narrative. Do not claim pilot completion without pilot report evidence.",
        "",
        "## 12. Pilot Implementation Summary",
        "Not available yet unless a pilot report and before/after data have been added to the project.",
        "",
        "## 13. Before/After Pilot Results",
        "Not available yet unless before/after KPI or pilot validation data exists.",
        "",
        "## 14. PM Standardization Output",
        "Generated PM checklist outputs are referenced in the appendix and handoff package.",
        "",
        "## 15. BOM and Spare Parts Standardization Output",
        "BOM/spare standardization reports are evidence of observed data gaps and common documented components; verified part numbers still require source confirmation.",
        "",
        "## 16. Training / Work Instruction Output",
        "Training materials should be added under 06_Final_Handoff/Training_Materials when available.",
        "",
        "## 17. Final Recommendations",
        "- Continue filling audit documentation gaps for high-priority and pilot-candidate EOATs.",
        "- Use FMEA and issue trends to prioritize maintenance and standardization work.",
        "- Confirm spare part details from approved documentation before standardizing part numbers.",
        "- Complete KPI before/after evidence before claiming measurable improvement.",
        "",
        "## 18. Handoff Package Contents",
        "Use the generated HANDOFF_INDEX.md as the source of truth for package contents.",
        "",
        "## 19. Remaining Open Items",
        "- Missing deliverables identified by the Final Deliverable Checker.",
        "- Any action items still open in the master workbook.",
        "",
        "## 20. Appendix / Source Reports",
        *report_references_markdown(reports),
    ]
    if warnings:
        lines.extend(["", "## Missing Data Notes", *[f"- {warning}" for warning in warnings]])
    if notes.strip():
        lines.extend(["", "## Manual Notes", notes.strip()])
    metrics = {**metrics, "top_issue_categories": len(issues), "top_fmea_risks": len(risks)}
    return "\n".join(lines) + "\n", warnings, metrics


def generate_final_project_summary(project_root: str | Path, include_docx: bool = False, notes: str = "") -> ToolResult:
    start = time.perf_counter()
    paths = resolve_project_paths(project_root)
    ensure_directory(paths.final_report)
    markdown, warnings, metrics = build_final_summary_markdown(project_root, notes=notes)
    report = write_timestamped_report(paths.final_report, "Final_Project_Summary_Draft", markdown)
    files_created = [str(report)]
    output_reports = [str(report)]
    if include_docx:
        docx = make_simple_docx(report, markdown)
        if docx:
            files_created.append(str(docx))
            output_reports.append(str(docx))
        else:
            warnings.append("DOCX output requested, but python-docx is unavailable.")
    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Generated final project summary draft.",
        details=[f"Summary draft: {report}"],
        warnings=warnings,
        files_created=files_created,
        output_reports=output_reports,
        metrics=metrics,
        duration_seconds=time.perf_counter() - start,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result
