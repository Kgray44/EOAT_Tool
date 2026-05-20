from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable

from .deliverable_check import check_deliverables
from .final_common import unique_package_dir
from .logging import log_tool_run
from .paths import resolve_project_paths
from .reports import list_recent_files
from .result import ToolResult
from .safe_files import ensure_directory, safe_copy_file, safe_write_text


TOOL_ID = "final_handoff_builder"
TOOL_NAME = "Final Handoff Builder"


HANDOFF_FOLDERS = {
    "database": "01_EOAT_Database",
    "standards": "02_Standards",
    "pm": "03_PM_Checklists",
    "fmea": "04_FMEA",
    "kpi": "05_KPI_Reports",
    "pilot": "06_Pilot_Project",
    "training": "07_Training_Materials",
    "executive": "08_Executive_Summary",
    "presentation": "09_Presentation",
    "admin": "10_Project_Admin",
    "reference": "11_Reference_Reports",
}


def _existing(files: Iterable[Path]) -> list[Path]:
    return [path for path in files if path.exists() and path.is_file()]


def _latest_from(folder: Path, limit: int = 8) -> list[Path]:
    return list_recent_files(folder, limit=limit)


def _recursive_recent(folder: Path, limit: int = 8) -> list[Path]:
    if not folder.exists():
        return []
    files = [path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in {".md", ".txt", ".json", ".docx", ".pdf", ".csv", ".png", ".xlsx", ".pptx"}]
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
        "standards": _latest_from(paths.documentation_gap_reports) + _latest_from(paths.bom_standardization_reports),
        "pm": _latest_from(paths.pm_generated_checklists, 20),
        "fmea": _latest_from(paths.fmea_reports, 10),
        "kpi": _latest_from(paths.kpi_dashboard_exports, 10),
        "pilot": _latest_from(paths.pilot_project / "Candidate_Cells", 10) + _latest_from(paths.pilot_project / "Pilot_Reports", 10),
        "training": _latest_from(paths.training_materials, 10) + _latest_from(paths.standards / "Work_Instructions", 10),
        "executive": _latest_from(paths.executive_summary, 10) + _latest_from(paths.final_report, 10),
        "presentation": _recursive_recent(paths.presentation_assets_root, 20),
        "admin": _latest_from(paths.validation_reports, 5),
        "reference": _latest_from(paths.issue_analysis_reports, 5) + _latest_from(paths.audit_progress_reports, 5),
    }
    if include_weekly_reports:
        sources["admin"].extend(_latest_from(paths.weekly_reports, 12))
    if include_daily_reports:
        sources["admin"].extend(_latest_from(paths.daily_reports, 20))
    if include_mentor_briefs:
        sources["admin"].extend(_latest_from(paths.mentor_briefs, 12))
    if include_photo_files and paths.cell_photos.exists():
        photos = [path for path in paths.cell_photos.rglob("*") if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic"}]
        sources["reference"].extend(sorted(photos, key=lambda path: path.stat().st_mtime, reverse=True)[:100])
    return sources


def _copy_sources(package: Path, sources: dict[str, list[Path]]) -> tuple[list[str], list[dict[str, str]]]:
    files_created: list[str] = []
    manifest: list[dict[str, str]] = []
    for key, files in sources.items():
        target_dir = ensure_directory(package / HANDOFF_FOLDERS[key])
        used_names: set[str] = set()
        for source in files:
            name = source.name
            if name in used_names:
                name = f"{source.stem}_{len(used_names) + 1}{source.suffix}"
            used_names.add(name)
            target = safe_copy_file(source, target_dir / name, overwrite=False)
            files_created.append(str(target))
            manifest.append({"Source": str(source), "Package Path": str(target)})
    return files_created, manifest


def _index_markdown(package: Path | None, manifest: list[dict[str, str]], missing: list[str], dry_run: bool) -> str:
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
        "## Contents Overview",
    ]
    for folder in HANDOFF_FOLDERS.values():
        lines.append(f"- {folder}")
    lines.extend(["", "## Deliverable Checklist"])
    checklist = [
        "EOAT inventory database",
        "EOAT standard design guideline",
        "PM checklist",
        "FMEA-lite risk assessment",
        "Pilot optimization report/results",
        "KPI dashboard/report",
        "Training materials",
        "BOM/spare parts standardization report",
        "Documentation gap report",
        "Executive summary",
        "Final presentation assets",
        "Final recommendations",
    ]
    lines.extend(f"- {item}" for item in checklist)
    lines.extend(["", "## Files Included"])
    if manifest:
        lines.extend(f"- {Path(row['Package Path']).name} from {row['Source']}" for row in manifest)
    else:
        lines.append("- No files copied." if dry_run else "- No files were available to copy.")
    lines.extend(["", "## Missing or Not Yet Available"])
    lines.extend([f"- {item}" for item in missing] or ["- None flagged by deliverable check."])
    lines.extend(
        [
            "",
            "## How to Use This Handoff Package",
            "- Start with this index and the final project summary draft.",
            "- Use the EOAT database as the structured source of audit data.",
            "- Use report folders as supporting evidence, not as unsupported claims.",
            "- Review missing deliverables before final submission.",
            "",
            "## Known Limitations",
            "- This package copies available files only; it does not certify that missing data is complete.",
            "- KPI and pilot results should not be claimed without before/after evidence.",
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
    sources = collect_handoff_sources(project_root, include_daily_reports, include_weekly_reports, include_mentor_briefs, include_photo_files)
    statuses, warnings = check_deliverables(project_root)
    missing = [item.name for item in statuses if item.status == "Missing"]
    manifest: list[dict[str, str]] = []
    files_created: list[str] = []
    package: Path | None = None
    if dry_run:
        index_path = paths.handoff_package_root / f"Final_Handoff_Dry_Run_{time.strftime('%Y-%m-%d_%H%M%S')}.md"
        index = _index_markdown(None, [{"Source": str(src), "Package Path": f"DRY-RUN/{HANDOFF_FOLDERS[key]}/{src.name}"} for key, files in sources.items() for src in files], missing, dry_run=True)
        safe_write_text(index_path, index, overwrite=False)
        files_created.append(str(index_path))
        output_reports = [str(index_path)]
    else:
        package = unique_package_dir(paths.handoff_package_root, "Final_Handoff")
        missing = [item for item in missing if item != "Handoff package"]
        for folder in HANDOFF_FOLDERS.values():
            ensure_directory(package / folder)
        copied, manifest = _copy_sources(package, sources)
        files_created.extend(copied)
        index_path = safe_write_text(package / "HANDOFF_INDEX.md", _index_markdown(package, manifest, missing, dry_run=False), overwrite=False)
        files_created.append(str(index_path))
        output_reports = [str(index_path)]

    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Built final handoff package dry-run." if dry_run else "Built final handoff package.",
        details=[f"Dry run: {dry_run}", f"Files considered: {sum(len(files) for files in sources.values())}"],
        warnings=warnings + ([f"Missing deliverables: {', '.join(missing)}"] if missing else []),
        files_created=files_created,
        output_reports=output_reports,
        metrics={"dry_run": dry_run, "files_copied": len(manifest), "missing_deliverables": len(missing), "package": str(package) if package else ""},
        duration_seconds=time.perf_counter() - start,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result
