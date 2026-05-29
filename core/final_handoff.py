from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable

from .final_handoff_readiness import (
    MISSING,
    NEEDS_REVIEW,
    FinalHandoffReadinessSummary,
    build_final_handoff_readiness,
    export_machine_summary_report,
    export_deliverable_readiness,
    export_leadership_summary,
    export_open_items_carryover,
    export_technical_appendix,
)
from .logging import log_tool_run
from .paths import resolve_project_paths
from .reports import list_recent_files
from .result import ToolResult
from .safe_files import ensure_directory, safe_copy_file, safe_write_text


TOOL_ID = "final_handoff_builder"
TOOL_NAME = "Final Handoff Builder"


HANDOFF_FOLDERS = {
    "database": "01_EOAT_Database",
    "robot_info": "01_EOAT_Database",
    "standard_guidelines": "02_Standards",
    "bom_spares": "02_Standards",
    "standards": "02_Standards",
    "pm": "03_PM_Checklists",
    "fmea": "04_FMEA",
    "kpi": "05_KPI_Reports",
    "pilot": "06_Pilot_Project",
    "work_instructions": "07_Training_Materials",
    "training": "07_Training_Materials",
    "risk": "08_Risk_Insights",
    "executive": "08_Executive_Summary",
    "presentation": "09_Presentation",
    "admin": "10_Project_Admin",
    "reference": "11_Reference_Reports",
    "change_validation": "12_Change_Validation",
    "qr_labels": "13_QR_Labels",
    "machine_summaries": "14_Machine_Summaries",
    "photos_evidence": "15_Photo_Evidence",
}

PACKAGE_FOLDERS = {
    "database": "EOAT_Database",
    "robot_info": "EOAT_Database",
    "standard_guidelines": "Standards",
    "bom_spares": "Standards",
    "standards": "Standards",
    "pm": "PM_Checklists",
    "fmea": "FMEA",
    "kpi": "KPI",
    "pilot": "Pilot_Candidates",
    "work_instructions": "Training_Materials",
    "training": "Training_Materials",
    "risk": "Risk_Insights",
    "executive": "Executive_Backup",
    "presentation": "Presentation",
    "admin": "Validation",
    "reference": "Reference",
    "change_validation": "Change_Validation",
    "qr_labels": "QR_Labels",
    "machine_summaries": "Machine_Summaries",
    "photos_evidence": "Photo_Evidence",
}

REQUIRED_PACKAGE_FOLDERS = (
    "FMEA",
    "KPI",
    "PM_Checklists",
    "Pilot_Candidates",
    "Standards",
    "Validation",
)


def _existing(files: Iterable[Path]) -> list[Path]:
    return [path for path in files if path.exists() and path.is_file()]


def _latest_from(folder: Path, limit: int = 8) -> list[Path]:
    return list_recent_files(folder, limit=limit)


def _recursive_recent(folder: Path, limit: int = 8) -> list[Path]:
    if not folder.exists():
        return []
    files = [path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in {".md", ".txt", ".json", ".docx", ".pdf", ".csv", ".png", ".svg", ".xlsx", ".pptx"}]
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)[:limit]


def collect_handoff_sources(
    project_root: str | Path,
    include_daily_reports: bool = False,
    include_weekly_reports: bool = True,
    include_mentor_briefs: bool = False,
    include_photo_files: bool = False,
) -> dict[str, list[Path]]:
    paths = resolve_project_paths(project_root)
    sources: dict[str, list[Path]] = {
        "database": _existing([paths.master_workbook]),
        "robot_info": _existing([paths.robot_info_workbook]),
        "standard_guidelines": _recursive_recent(paths.standards / "EOAT_Design_Guideline_Draft", 10),
        "bom_spares": _latest_from(paths.bom_standardization_reports, 10),
        "standards": _latest_from(paths.documentation_gap_reports),
        "pm": _latest_from(paths.pm_generated_checklists, 20),
        "fmea": _latest_from(paths.fmea_reports, 10),
        "kpi": _latest_from(paths.kpi_dashboard_exports, 10),
        "pilot": _latest_from(paths.pilot_project / "Candidate_Cells", 10) + _latest_from(paths.pilot_project / "Pilot_Reports", 10),
        "work_instructions": _recursive_recent(paths.work_instructions, 20),
        "training": _latest_from(paths.training_materials, 10),
        "risk": _latest_from(paths.risk_insights_reports, 10),
        "executive": _latest_from(paths.executive_summary, 10) + _latest_from(paths.final_report, 10),
        "presentation": _recursive_recent(paths.presentation_assets_root, 20),
        "admin": _latest_from(paths.validation_reports, 5),
        "reference": _latest_from(paths.issue_analysis_reports, 5) + _latest_from(paths.audit_progress_reports, 5),
        "change_validation": _recursive_recent(paths.change_validation, 10),
        "qr_labels": _recursive_recent(paths.qr_labels, 10),
        "machine_summaries": _latest_from(paths.machine_summaries, 10) + _latest_from(paths.project_admin / "Machine_360_Summaries", 10),
        "photos_evidence": [],
    }
    if include_weekly_reports:
        sources["admin"].extend(_latest_from(paths.weekly_reports, 12))
    if include_daily_reports:
        sources["admin"].extend(_latest_from(paths.daily_reports, 20))
    if include_mentor_briefs:
        sources["admin"].extend(_latest_from(paths.mentor_briefs, 12))
    if include_photo_files and paths.cell_photos.exists():
        photos = [path for path in paths.cell_photos.rglob("*") if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic"}]
        sources["photos_evidence"].extend(sorted(photos, key=lambda path: path.stat().st_mtime, reverse=True)[:100])
    return sources


def _package_dir_name(key: str, *, dry_run: bool = False) -> str:
    if dry_run:
        return PACKAGE_FOLDERS.get(key, HANDOFF_FOLDERS.get(key, "Reference"))
    return PACKAGE_FOLDERS.get(key, "Reference")


def _unique_final_handoff_package_dir(parent: Path) -> Path:
    root = ensure_directory(parent)
    stamp = time.strftime("%Y%m%d_%H%M")
    candidate = root / f"Final_Handoff_Package_{stamp}"
    if not candidate.exists():
        return ensure_directory(candidate)
    for index in range(2, 1000):
        indexed = root / f"Final_Handoff_Package_{stamp}_{index}"
        if not indexed.exists():
            return ensure_directory(indexed)
    return ensure_directory(root / f"Final_Handoff_Package_{int(time.time())}")


def _copy_sources(package: Path, sources: dict[str, list[Path]]) -> tuple[list[str], list[dict[str, str]]]:
    files_created: list[str] = []
    manifest: list[dict[str, str]] = []
    for key, files in sources.items():
        target_dir = ensure_directory(package / _package_dir_name(key))
        used_names: set[str] = set()
        for source in files:
            name = source.name
            if name in used_names:
                name = f"{source.stem}_{len(used_names) + 1}{source.suffix}"
            used_names.add(name)
            target = safe_copy_file(source, target_dir / name, overwrite=False)
            files_created.append(str(target))
            manifest.append({"Category": key, "Source": str(source), "Package Path": str(target)})
    return files_created, manifest


def _readiness_gaps(readiness: FinalHandoffReadinessSummary) -> list[str]:
    return [
        f"{item.label}: {item.status}; {item.recommended_action}"
        for item in readiness.deliverables
        if item.status in {MISSING, NEEDS_REVIEW}
    ]


def _readiness_warnings(readiness: FinalHandoffReadinessSummary) -> list[str]:
    warnings: list[str] = []
    for item in readiness.deliverables:
        warnings.extend(f"{item.label}: {warning}" for warning in item.warnings)
    return warnings


def _index_markdown(
    package: Path | None,
    manifest: list[dict[str, str]],
    readiness: FinalHandoffReadinessSummary,
    dry_run: bool,
) -> str:
    package_name = package.name if package else "Dry run only"
    lines = [
        "# Final Handoff Package Index",
        "",
        f"Package: {package_name}",
        f"Dry run: {'Yes' if dry_run else 'No'}",
        "",
        "## Project Objective",
        "Support EOAT standardization, documentation, PM readiness, risk review, KPI tracking, and final project handoff.",
        "",
        "## Root Deliverables",
        "- Executive_Summary.md",
        "- Technical_Appendix.md",
        "- Open_Items_Carryover.md",
        "- Deliverable_Readiness.md",
        "",
        "## Handoff Link Map",
        *_handoff_link_table(package, manifest, readiness),
        "",
        "## Truth And Evidence Labels",
        "- Missing evidence remains listed as missing or needs review; this package does not certify blank evidence as complete.",
        "- Estimated or subjective KPI/pilot data must remain labeled in the source report. No financial or performance impact is invented in this index.",
        "- Compatibility rows and physical audit rows should be interpreted using the workbook entry type and source metadata.",
        "",
        "## Contents Overview",
    ]
    for folder in REQUIRED_PACKAGE_FOLDERS:
        lines.append(f"- {folder}")
    optional_folders = sorted({folder for folder in PACKAGE_FOLDERS.values()} - set(REQUIRED_PACKAGE_FOLDERS))
    if optional_folders:
        lines.extend(["", "## Additional Evidence Folders"])
        lines.extend(f"- {folder}" for folder in optional_folders)
    lines.extend(["", "## Deliverable Readiness"])
    for item in readiness.deliverables:
        lines.append(f"- {item.label}: {item.status}")
    lines.extend(["", "## Files Included"])
    if manifest:
        lines.extend(f"- {Path(row['Package Path']).name} from {row['Source']}" for row in manifest)
    else:
        lines.append("- No files copied." if dry_run else "- No files were available to copy.")
    lines.extend(["", "## Missing or Needs Review"])
    lines.extend([f"- {item}" for item in _readiness_gaps(readiness)] or ["- None flagged by final readiness model."])
    lines.extend(
        [
            "",
            "## How to Use This Handoff Package",
            "- Start with Executive_Summary.md for leadership-facing context.",
            "- Use Technical_Appendix.md for evidence, validation, standards, FMEA, KPI, and compatibility details.",
            "- Use the EOAT database as the structured source of audit data.",
            "- Use report folders as supporting evidence, not as unsupported claims.",
            "- Review missing deliverables before final submission.",
            "",
            "## Known Limitations",
            "- This package copies available files only; it does not certify that missing data is complete.",
            "- KPI and pilot results should not be claimed without before/after evidence.",
            "- Generated outputs are local/private project artifacts and should not be committed to the repository.",
            "",
            "## Recommended Next Steps",
            "- Fill missing deliverables or document why they are not applicable.",
            "- Review the final package with mentor/supervisor before final handoff.",
            "",
            "## Original Source Locations",
        ]
    )
    if manifest:
        lines.extend(f"- {row['Source']}" for row in manifest)
    else:
        lines.append("- See dry-run output and deliverable check.")
    return "\n".join(lines) + "\n"


def _handoff_link_table(package: Path | None, manifest: list[dict[str, str]], readiness: FinalHandoffReadinessSummary) -> list[str]:
    rows = _handoff_link_rows(package, manifest, readiness)
    columns = ["Deliverable", "Status", "Link", "Evidence Label"]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_escape_table(row[column]) for column in columns) + " |")
    return lines


def _handoff_link_rows(package: Path | None, manifest: list[dict[str, str]], readiness: FinalHandoffReadinessSummary) -> list[dict[str, str]]:
    readiness_by_key = {item.key: item for item in readiness.deliverables}
    specs = [
        ("Final master tracker", ("database",), "eoat_database", "Structured workbook evidence"),
        ("Robot Info workbook", ("robot_info",), "", "Optional robot-side workbook; missing stays missing"),
        ("FMEA", ("fmea",), "fmea_output", "Draft/review status comes from FMEA source rows and reports"),
        ("KPI dashboard", ("kpi",), "kpi_dashboard_export", "Measured, observed, estimated, or missing source labels apply from KPI report"),
        ("PM checklist package", ("pm",), "pm_checklist_package", "Generated PM package evidence"),
        ("BOM/spares report", ("bom_spares",), "", "Standardization candidate evidence; recommendations require review"),
        ("Standard design guidelines", ("standard_guidelines", "standards"), "standards_guidelines", "Guideline/report evidence"),
        ("Work instructions", ("work_instructions",), "training_materials", "Generated from actual audit data; missing docs remain marked"),
        ("Pilot report", ("pilot",), "pilot_results_or_packets", "Candidate/ROI evidence only unless before-after data exists"),
        ("Training materials", ("training",), "training_materials", "Training package evidence"),
        ("Photos/evidence", ("photos_evidence", "reference"), "", "Photo files only included when explicitly requested"),
        ("Open issues", ("open_issues", "admin"), "open_items_carryover", "Carryover/open item evidence"),
        ("Recommendations", ("executive", "risk"), "executive_summary", "Evidence-based recommendations; no fake impact metrics"),
        ("Machine summary report", ("machine_summaries",), "machine_summary_report", "Machine 360 summary from available local data"),
    ]
    return [
        {
            "Deliverable": label,
            "Status": _link_status(manifest, keys, readiness_by_key.get(readiness_key)),
            "Link": _link_target(package, manifest, keys),
            "Evidence Label": evidence_label,
        }
        for label, keys, readiness_key, evidence_label in specs
    ]


def _link_status(manifest: list[dict[str, str]], keys: tuple[str, ...], readiness_item) -> str:
    if _first_manifest(manifest, keys):
        return "Included"
    if readiness_item is not None:
        return readiness_item.status
    return "Missing"


def _link_target(package: Path | None, manifest: list[dict[str, str]], keys: tuple[str, ...]) -> str:
    row = _first_manifest(manifest, keys)
    if row is None:
        return "Not available in this package"
    package_path = Path(row["Package Path"])
    if package and package_path.is_absolute():
        try:
            rel = package_path.relative_to(package)
        except ValueError:
            rel = package_path
    else:
        rel = package_path
    label = rel.name if isinstance(rel, Path) else str(rel)
    return f"[{label}]({str(rel).replace(chr(92), '/')})"


def _first_manifest(manifest: list[dict[str, str]], keys: tuple[str, ...]) -> dict[str, str] | None:
    return next((row for row in manifest if row.get("Category") in keys), None)


def _escape_table(value: str) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _export_manifest_rows(result: ToolResult, package: Path) -> list[dict[str, str]]:
    category = {
        "leadership_summary_export": "executive",
        "technical_appendix_export": "reference",
        "open_items_carryover_export": "open_issues",
        "final_readiness_export": "reference",
        "machine_summary_report": "machine_summaries",
    }.get(result.tool_id, "reference")
    rows: list[dict[str, str]] = []
    for path_text in result.files_created:
        path = Path(path_text)
        if path.exists() and path.is_file():
            rows.append({"Category": category, "Source": "generated during handoff build", "Package Path": str(path)})
    return rows


def build_final_handoff_package(
    project_root: str | Path,
    include_daily_reports: bool = False,
    include_weekly_reports: bool = True,
    include_mentor_briefs: bool = False,
    include_photo_files: bool = False,
    dry_run: bool = False,
) -> ToolResult:
    start = time.perf_counter()
    paths = resolve_project_paths(project_root)
    ensure_directory(paths.handoff_package_root)
    ensure_directory(paths.final_handoff)
    sources = collect_handoff_sources(project_root, include_daily_reports, include_weekly_reports, include_mentor_briefs, include_photo_files)
    readiness = build_final_handoff_readiness(project_root)
    manifest: list[dict[str, str]] = []
    files_created: list[str] = []
    package: Path | None = None
    if dry_run:
        index_path = paths.handoff_package_root / f"Final_Handoff_Dry_Run_{time.strftime('%Y-%m-%d_%H%M%S')}.md"
        dry_manifest = [
            {"Category": key, "Source": str(src), "Package Path": f"DRY-RUN/{_package_dir_name(key, dry_run=True)}/{src.name}"}
            for key, files in sources.items()
            for src in files
        ]
        index = _index_markdown(None, dry_manifest, readiness, dry_run=True)
        safe_write_text(index_path, index, overwrite=False)
        files_created.append(str(index_path))
        output_reports = [str(index_path)]
    else:
        package = _unique_final_handoff_package_dir(paths.final_handoff)
        for folder in (*REQUIRED_PACKAGE_FOLDERS, *PACKAGE_FOLDERS.values()):
            ensure_directory(package / folder)
        export_manifest: list[dict[str, str]] = []
        for export_result in [
            export_leadership_summary(project_root, output_dir=package, log_activity=False),
            export_technical_appendix(project_root, output_dir=package, log_activity=False),
            export_open_items_carryover(project_root, output_dir=package, log_activity=False),
            export_machine_summary_report(project_root, output_dir=package / "Machine_Summaries", filename="Machine_Summary_Report.md", log_activity=False),
        ]:
            files_created.extend(export_result.files_created)
            export_manifest.extend(_export_manifest_rows(export_result, package))
        readiness = build_final_handoff_readiness(project_root)
        readiness_result = export_deliverable_readiness(project_root, output_dir=package, log_activity=False)
        files_created.extend(readiness_result.files_created)
        export_manifest.extend(_export_manifest_rows(readiness_result, package))
        sources = collect_handoff_sources(project_root, include_daily_reports, include_weekly_reports, include_mentor_briefs, include_photo_files)
        copied, manifest = _copy_sources(package, sources)
        manifest = [*export_manifest, *manifest]
        files_created.extend(copied)
        index_path = safe_write_text(package / "HANDOFF_INDEX.md", _index_markdown(package, manifest, readiness, dry_run=False), overwrite=False)
        files_created.append(str(index_path))
        output_reports = [str(index_path), *(path for path in files_created if Path(path).name in {"Executive_Summary.md", "Technical_Appendix.md", "Open_Items_Carryover.md", "Deliverable_Readiness.md"})]

    missing = _readiness_gaps(readiness)
    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Built final handoff package dry-run." if dry_run else "Built final handoff package.",
        details=[f"Dry run: {dry_run}", f"Files considered: {sum(len(files) for files in sources.values())}"],
        warnings=_readiness_warnings(readiness) + ([f"Missing or needs-review deliverables: {', '.join(missing)}"] if missing else []),
        files_created=files_created,
        output_reports=output_reports,
        metrics={"dry_run": dry_run, "files_copied": len(manifest), "missing_or_needs_review_deliverables": len(missing), "package": str(package) if package else ""},
        duration_seconds=time.perf_counter() - start,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result
