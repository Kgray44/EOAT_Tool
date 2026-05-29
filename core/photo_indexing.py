from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import backup_file, ensure_directory, safe_copy_file
from .workbook_cache import invalidate_workbook_cache
from .workbook_io import next_empty_row, row_dicts, write_row_by_headers
from .workbook_schema import get_expected_headers

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic"}

PHOTO_VIEW_FOLDERS = {
    "Overall": "Overall",
    "Overall EOAT": "Overall",
    "Robot Connection": "Robot_Connection",
    "Tool Connection": "Tool_Connection",
    "EOAT-Side Pneumatic Circuits": "EOAT_Side_Pneumatic_Circuits",
    "EOAT-Side Pneumatics": "EOAT_Side_Pneumatics",
    "Robot-Side Pneumatics": "Robot_Side_Pneumatics",
    "Vacuum Cups / Grippers": "Vacuum_Cups_Grippers",
    "Grippers": "Grippers",
    "Vacuum Cups": "Vacuum_Cups",
    "Cylinders": "Cylinders",
    "Tubing Routing": "Tubing_Routing",
    "Sensors": "Sensors",
    "Sensor Mounting": "Sensor_Mounting",
    "Quick Disconnects": "Quick_Disconnects",
    "Mounting Hardware": "Mounting_Hardware",
    "Cable Management": "Cable_Management",
    "Wear / Damage": "Wear_Damage",
    "Wear/Damage": "Wear_Damage",
    "Tool Label / ID Plate": "Tool_Label_ID_Plate",
    "Process Binder Reference": "Process_Binder_Reference",
    "Process Binder/Documentation Reference": "Process_Binder_Documentation_Reference",
    "Other": "Other",
}

PHOTO_VIEW_FILENAME = {
    "Overall": "Overall",
    "Overall EOAT": "OverallEOAT",
    "Robot Connection": "RobotConnection",
    "Tool Connection": "ToolConnection",
    "EOAT-Side Pneumatic Circuits": "EOATPneumaticCircuits",
    "EOAT-Side Pneumatics": "EOATSidePneumatics",
    "Robot-Side Pneumatics": "RobotSidePneumatics",
    "Vacuum Cups / Grippers": "VacuumCupsGrippers",
    "Grippers": "Grippers",
    "Vacuum Cups": "VacuumCups",
    "Cylinders": "Cylinders",
    "Tubing Routing": "TubingRouting",
    "Sensors": "Sensors",
    "Sensor Mounting": "SensorMounting",
    "Quick Disconnects": "QuickDisconnects",
    "Mounting Hardware": "MountingHardware",
    "Cable Management": "CableManagement",
    "Wear / Damage": "WearDamage",
    "Wear/Damage": "WearDamage",
    "Tool Label / ID Plate": "ToolLabelIDPlate",
    "Process Binder Reference": "ProcessBinderReference",
    "Process Binder/Documentation Reference": "ProcessBinderDocumentationReference",
    "Other": "Other",
}


@dataclass(frozen=True)
class PhotoPlanItem:
    source: Path
    target: Path
    photo_id: str
    collision_avoided: bool = False


def sanitize_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value.strip())
    return cleaned or "Unknown"


def incoming_photo_dir(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).incoming_photos


def list_incoming_photos(project_root: str | Path) -> list[Path]:
    folder = incoming_photo_dir(project_root)
    if not folder.exists():
        return []
    return sorted(path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS)


def destination_folder(project_root: str | Path, view_type: str) -> Path:
    folder_name = PHOTO_VIEW_FOLDERS.get(view_type, sanitize_filename_part(view_type))
    return resolve_project_paths(project_root).cell_photos / folder_name


def generate_photo_id(project_root: str | Path, taken_date: str | None = None) -> str:
    taken_date = taken_date or date.today().isoformat()
    compact = taken_date.replace("-", "")
    workbook_path = resolve_project_paths(project_root).master_workbook
    rows = row_dicts(workbook_path, "Photo Index") if workbook_path.exists() else []
    prefix = f"PHO-{compact}-"
    max_number = 0
    for row in rows:
        value = str(row.get("Photo ID") or "")
        if value.startswith(prefix):
            try:
                max_number = max(max_number, int(value.rsplit("-", 1)[1]))
            except ValueError:
                continue
    return f"{prefix}{max_number + 1:03d}"


def _next_existing_photo_sequence(project_root: str | Path, taken_date: str, plant_area: str, press_machine: str, view_type: str) -> int:
    folder = destination_folder(project_root, view_type)
    stem_prefix = (
        f"{sanitize_filename_part(plant_area)}_"
        f"{sanitize_filename_part(press_machine)}_EOAT_"
        f"{taken_date}_{PHOTO_VIEW_FILENAME.get(view_type, sanitize_filename_part(view_type))}_"
    )
    max_number = 0
    if folder.exists():
        for item in folder.iterdir():
            if not item.is_file() or not item.stem.startswith(stem_prefix):
                continue
            try:
                max_number = max(max_number, int(item.stem.rsplit("_", 1)[1]))
            except ValueError:
                continue
    return max_number + 1


def preview_photo_intake(
    project_root: str | Path,
    photo_paths: list[str | Path],
    plant_area: str,
    press_machine: str,
    date_taken: str,
    view_type: str,
) -> list[PhotoPlanItem]:
    folder = destination_folder(project_root, view_type)
    sequence = _next_existing_photo_sequence(project_root, date_taken, plant_area, press_machine, view_type)
    plan: list[PhotoPlanItem] = []
    photo_sequence = 1
    for source_raw in photo_paths:
        source = Path(source_raw)
        ext = ".jpg" if source.suffix.lower() == ".jpeg" else source.suffix.lower()
        if ext not in SUPPORTED_IMAGE_EXTENSIONS:
            continue
        collision_avoided = False
        while True:
            filename = (
                f"{sanitize_filename_part(plant_area)}_"
                f"{sanitize_filename_part(press_machine)}_EOAT_"
                f"{date_taken}_{PHOTO_VIEW_FILENAME.get(view_type, sanitize_filename_part(view_type))}_"
                f"{sequence:03d}{ext}"
            )
            target = folder / filename
            if not target.exists() and target not in [item.target for item in plan]:
                break
            collision_avoided = True
            sequence += 1
        plan.append(
            PhotoPlanItem(
                source=source,
                target=target,
                photo_id=f"PHO-{date_taken.replace('-', '')}-{photo_sequence:03d}",
                collision_avoided=collision_avoided,
            )
        )
        sequence += 1
        photo_sequence += 1
    return plan


def intake_photos(
    project_root: str | Path,
    photo_paths: list[str | Path],
    plant_area: str,
    press_machine: str,
    date_taken: str,
    view_type: str,
    related_audit_id: str = "",
    related_issue_id: str = "",
    description: str = "",
    notes: str = "",
    copy_mode: bool = True,
    log_activity: bool = True,
) -> ToolResult:
    started = time.perf_counter()
    paths = resolve_project_paths(project_root)
    workbook_path = paths.master_workbook
    if not workbook_path.exists():
        return ToolResult.fail("photo_intake", "EOAT Photo Intake and Renaming Tool", "Master workbook is missing.", errors=[str(workbook_path)])
    if not photo_paths:
        return ToolResult.fail("photo_intake", "EOAT Photo Intake and Renaming Tool", "No photos selected.")
    for field_name, value in {"Plant/Area": plant_area, "Press/Machine #": press_machine, "Date Taken": date_taken, "EOAT Area Shown": view_type}.items():
        if not str(value).strip():
            return ToolResult.fail("photo_intake", "EOAT Photo Intake and Renaming Tool", f"Missing required field: {field_name}")

    plan = preview_photo_intake(project_root, photo_paths, plant_area, press_machine, date_taken, view_type)
    if not plan:
        return ToolResult.fail("photo_intake", "EOAT Photo Intake and Renaming Tool", "No supported image files selected.")
    missing = [str(item.source) for item in plan if not item.source.exists()]
    if missing:
        return ToolResult.fail("photo_intake", "EOAT Photo Intake and Renaming Tool", "Some selected photos are missing.", errors=missing)

    workbook = None
    moved_or_copied: list[str] = []
    try:
        ensure_directory(destination_folder(project_root, view_type))
        for item in plan:
            if item.target.exists():
                raise FileExistsError(f"Target already exists: {item.target}")

        backup = backup_file(workbook_path, workbook_path.parent / "_backups")
        for item in plan:
            if copy_mode:
                safe_copy_file(item.source, item.target, overwrite=False)
            else:
                shutil.move(str(item.source), str(item.target))
            moved_or_copied.append(str(item.target))

        workbook = load_workbook(workbook_path)
        if "Photo Index" not in workbook.sheetnames:
            raise ValueError("Photo Index sheet is missing.")
        ws = workbook["Photo Index"]
        rows_written: list[int] = []
        rows = row_dicts(workbook_path, "Photo Index")
        next_photo_number = 1
        prefix = f"PHO-{date_taken.replace('-', '')}-"
        for row in rows:
            value = str(row.get("Photo ID") or "")
            if value.startswith(prefix):
                try:
                    next_photo_number = max(next_photo_number, int(value.rsplit("-", 1)[1]) + 1)
                except ValueError:
                    continue
        for item in plan:
            photo_id = f"{prefix}{next_photo_number:03d}"
            next_photo_number += 1
            row_number = next_empty_row(ws)
            data = {header: "" for header in get_expected_headers("Photo Index")}
            data.update(
                {
                    "Photo ID": photo_id,
                    "Date Taken": date_taken,
                    "Plant/Area": plant_area,
                    "Press/Machine #": press_machine,
                    "EOAT Area Shown": view_type,
                    "Photo Filename": item.target.name,
                    "Folder Path": str(item.target.parent),
                    "Description": description,
                    "Related Audit ID": related_audit_id,
                    "Related Issue ID": related_issue_id,
                    "Notes": notes,
                }
            )
            write_row_by_headers(ws, row_number, data)
            rows_written.append(row_number)
        workbook.save(workbook_path)
        workbook.close()
        invalidate_workbook_cache(workbook_path)
    except Exception as exc:
        if workbook is not None:
            try:
                workbook.close()
            except Exception:
                pass
        return ToolResult.fail(
            "photo_intake",
            "EOAT Photo Intake and Renaming Tool",
            "Photo intake failed.",
            errors=[str(exc)],
            files_created=moved_or_copied,
            duration_seconds=time.perf_counter() - started,
        )

    result = ToolResult.ok(
        "photo_intake",
        "EOAT Photo Intake and Renaming Tool",
        f"{'Copied' if copy_mode else 'Moved'} and indexed {len(plan)} photo(s).",
        details=[f"{item.source} -> {item.target}" for item in plan] + [f"Workbook backup: {backup}"],
        warnings=["Filename collision avoided for one or more photos."] if any(item.collision_avoided for item in plan) else [],
        files_created=[str(backup), *moved_or_copied],
        files_modified=[str(workbook_path)],
        metrics={"photo_count": len(plan), "copy_mode": copy_mode},
        duration_seconds=time.perf_counter() - started,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result
