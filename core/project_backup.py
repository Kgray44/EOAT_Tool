from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

from .logging import log_tool_run
from .constants import TOOLKIT_ROOT
from .paths import resolve_project_paths
from .reports import list_recent_files
from .result import ToolResult
from .safe_files import ensure_directory, safe_copy_file, safe_write_text


TOOL_ID = "project_backup"
TOOL_NAME = "EOAT Project Backup"


def _stamp() -> str:
    return time.strftime("%Y-%m-%d_%H%M%S")


def _backup_root(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).project_admin / "Backups"


def _skip_for_light(path: Path, include_photos: bool) -> bool:
    parts = {part.lower() for part in path.parts}
    if "__pycache__" in parts or ".git" in parts or ".venv" in parts or "venv" in parts or "backups" in parts:
        return True
    if path.name.startswith("~$"):
        return True
    if not include_photos and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic", ".mov", ".mp4"}:
        return True
    if "handoff_package" in parts and not include_photos:
        return True
    return False


def backup_project(project_root: str | Path, mode: str = "workbook", include_photos: bool = False) -> ToolResult:
    paths = resolve_project_paths(project_root)
    mode = mode.lower()
    files_created: list[str] = []
    warnings: list[str] = []
    details: list[str] = []
    started = time.perf_counter()
    root = ensure_directory(_backup_root(project_root))

    if mode == "workbook":
        folder = ensure_directory(root / "Workbook_Backups")
        if not paths.master_workbook.exists():
            return ToolResult.fail(TOOL_ID, TOOL_NAME, "Master workbook is missing.", errors=[str(paths.master_workbook)])
        target = safe_copy_file(paths.master_workbook, folder / f"EOAT_Master_Tracker_backup_{_stamp()}.xlsx", overwrite=False)
        files_created.append(str(target))
        details.append("Workbook backup created.")
    elif mode == "config":
        folder = ensure_directory(root / "Config_Backups" / f"Config_Backup_{_stamp()}")
        candidates = [TOOLKIT_ROOT / "config" / "user_config.json", paths.project_admin / "project_schedule_week1.json", paths.project_admin / "task_progress_week1.json"]
        for source in candidates:
            if source.exists():
                target = safe_copy_file(source, folder / source.name, overwrite=False)
                files_created.append(str(target))
        details.append("Config/schedule backup created.")
    elif mode == "reports-index":
        folder = ensure_directory(root / "Report_Index_Backups")
        report_files = []
        for report_folder in [paths.daily_reports, paths.weekly_reports, paths.validation_reports, paths.audit_progress_reports, paths.issue_analysis_reports, paths.documentation_gap_reports, paths.fmea_reports, paths.kpi_dashboard_exports, paths.final_report]:
            report_files.extend(str(path) for path in list_recent_files(report_folder, limit=100))
        target = safe_write_text(folder / f"Report_Index_{_stamp()}.json", json.dumps(report_files, indent=2), overwrite=False)
        files_created.append(str(target))
        details.append(f"Indexed {len(report_files)} report file(s).")
    elif mode == "light":
        folder = ensure_directory(root / "Light_Project_Backups")
        zip_path = folder / f"EOAT_Project_Light_Backup_{_stamp()}.zip"
        count = 0
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in paths.project_root.rglob("*"):
                if path.is_file() and not _skip_for_light(path, include_photos):
                    try:
                        archive.write(path, path.relative_to(paths.project_root))
                        count += 1
                    except (OSError, PermissionError) as exc:
                        warnings.append(f"Skipped unreadable file during light backup: {path} ({exc})")
        files_created.append(str(zip_path))
        details.append(f"Light project backup zip created with {count} file(s).")
    else:
        return ToolResult.fail(TOOL_ID, TOOL_NAME, f"Unknown backup mode: {mode}", errors=["Use workbook, config, reports-index, or light."])

    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        f"Backup mode '{mode}' completed.",
        details=details,
        warnings=warnings,
        files_created=files_created,
        output_reports=files_created,
        metrics={"mode": mode, "files_created": len(files_created), "include_photos": include_photos},
        duration_seconds=time.perf_counter() - started,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result
