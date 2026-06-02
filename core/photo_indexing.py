from __future__ import annotations

import re
import shutil
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import backup_file, ensure_directory, safe_copy_file
from .tool_fields import TOOL_FIELD
from .workbook_cache import invalidate_workbook_cache
from .workbook_io import next_empty_row, row_dicts, worksheet_headers, write_row_by_headers
from .workbook_schema import get_expected_headers

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic"}
LINKED_AUDIT_FIELD_HEADER = "Linked Audit Field"

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
    view_type: str = ""
    description: str = ""
    related_audit_id: str = ""
    related_issue_id: str = ""
    linked_audit_field: str = ""
    tool_number: str = ""


def sanitize_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value.strip())
    return cleaned or "Unknown"


def sanitize_date_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9-]+", "", _text(value))
    return cleaned or "Unknown"


def normalize_machine_filename_part(value: str) -> str:
    text = re.sub(r"^(?:press|machine)\s*[-#:]*\s*", "", _text(value), flags=re.IGNORECASE)
    cleaned = sanitize_filename_part(text)
    return f"Machine{cleaned}"


def build_photo_filename_stem(
    plant_area: str, press_machine: str, tool_number: str, date_taken: str, view_type: str
) -> str:
    parts = [
        sanitize_filename_part(plant_area),
        normalize_machine_filename_part(press_machine),
    ]
    clean_tool = sanitize_filename_part(tool_number) if _text(tool_number) else ""
    if clean_tool:
        parts.append(f"Tool{clean_tool}")
    parts.extend(
        [
            "EOAT",
            sanitize_date_filename_part(date_taken),
            PHOTO_VIEW_FILENAME.get(view_type, sanitize_filename_part(view_type)),
        ]
    )
    return "_".join(part for part in parts if part)


def incoming_photo_dir(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).incoming_photos


def list_incoming_photos(project_root: str | Path) -> list[Path]:
    folder = incoming_photo_dir(project_root)
    if not folder.exists():
        return []
    return sorted(
        path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    )


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


def _next_existing_photo_sequence(
    project_root: str | Path, taken_date: str, plant_area: str, press_machine: str, view_type: str, tool_number: str = ""
) -> int:
    folder = destination_folder(project_root, view_type)
    stem_prefix = f"{build_photo_filename_stem(plant_area, press_machine, tool_number, taken_date, view_type)}_"
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
    tool_number: str = "",
    per_photo_metadata: list[Mapping[str, Any]] | None = None,
) -> list[PhotoPlanItem]:
    if per_photo_metadata is None and not isinstance(tool_number, str):
        per_photo_metadata = tool_number
        tool_number = ""
    plan: list[PhotoPlanItem] = []
    next_sequences: dict[tuple[str, str], int] = {}
    photo_sequence = 1
    for item_data in _photo_items(
        photo_paths,
        view_type=view_type,
        tool_number=tool_number,
        per_photo_metadata=per_photo_metadata,
    ):
        source = Path(item_data["source"])
        item_view_type = item_data["view_type"] or view_type
        item_tool_number = item_data["tool_number"]
        if not item_view_type:
            continue
        folder = destination_folder(project_root, item_view_type)
        sequence_key = (item_view_type, item_tool_number)
        if sequence_key not in next_sequences:
            next_sequences[sequence_key] = _next_existing_photo_sequence(
                project_root, date_taken, plant_area, press_machine, item_view_type, item_tool_number
            )
        sequence = next_sequences[sequence_key]
        ext = ".jpg" if source.suffix.lower() == ".jpeg" else source.suffix.lower()
        if ext not in SUPPORTED_IMAGE_EXTENSIONS:
            continue
        collision_avoided = False
        stem = build_photo_filename_stem(plant_area, press_machine, item_tool_number, date_taken, item_view_type)
        while True:
            filename = f"{stem}_{sequence:03d}{ext}"
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
                view_type=item_view_type,
                description=item_data["description"],
                related_audit_id=item_data["related_audit_id"],
                related_issue_id=item_data["related_issue_id"],
                linked_audit_field=item_data["linked_audit_field"],
                tool_number=item_tool_number,
            )
        )
        sequence += 1
        next_sequences[sequence_key] = sequence
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
    linked_audit_field: str = "",
    tool_number: str = "",
    per_photo_metadata: list[Mapping[str, Any]] | None = None,
    copy_mode: bool = True,
    log_activity: bool = True,
) -> ToolResult:
    started = time.perf_counter()
    paths = resolve_project_paths(project_root)
    workbook_path = paths.master_workbook
    if not workbook_path.exists():
        return ToolResult.fail(
            "photo_intake",
            "EOAT Photo Intake and Renaming Tool",
            "Master workbook is missing.",
            errors=[str(workbook_path)],
        )
    if not photo_paths:
        return ToolResult.fail("photo_intake", "EOAT Photo Intake and Renaming Tool", "No photos selected.")
    for field_name, value in {
        "Plant/Area": plant_area,
        "Press/Machine #": press_machine,
        "Date Taken": date_taken,
    }.items():
        if not str(value).strip():
            return ToolResult.fail(
                "photo_intake", "EOAT Photo Intake and Renaming Tool", f"Missing required field: {field_name}"
            )

    metadata = _photo_items(
        photo_paths,
        view_type=view_type,
        related_audit_id=related_audit_id,
        related_issue_id=related_issue_id,
        description=description,
        linked_audit_field=linked_audit_field,
        tool_number=tool_number,
        per_photo_metadata=per_photo_metadata,
    )
    if any(not item["view_type"] for item in metadata):
        return ToolResult.fail(
            "photo_intake", "EOAT Photo Intake and Renaming Tool", "Missing required field: EOAT Area Shown"
        )
    selected_photo_paths = [item["source"] for item in metadata]
    plan = preview_photo_intake(
        project_root,
        selected_photo_paths,
        plant_area,
        press_machine,
        date_taken,
        view_type,
        tool_number=tool_number,
        per_photo_metadata=metadata,
    )
    if not plan:
        return ToolResult.fail(
            "photo_intake", "EOAT Photo Intake and Renaming Tool", "No supported image files selected."
        )
    missing = [str(item.source) for item in plan if not item.source.exists()]
    if missing:
        return ToolResult.fail(
            "photo_intake", "EOAT Photo Intake and Renaming Tool", "Some selected photos are missing.", errors=missing
        )

    workbook = None
    moved_or_copied: list[str] = []
    try:
        for folder in sorted({item.target.parent for item in plan}):
            ensure_directory(folder)
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
        _ensure_headers(ws, get_expected_headers("Photo Index"))
        audit_rows_by_id = _audit_rows_by_id(workbook)
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
            audit_row = audit_rows_by_id.get(_text(item.related_audit_id).casefold(), {})
            data.update(
                {
                    "Photo ID": photo_id,
                    "Date Taken": date_taken,
                    "Plant/Area": plant_area,
                    "Press/Machine #": press_machine,
                    TOOL_FIELD: item.tool_number or _text(audit_row.get(TOOL_FIELD)),
                    "EOAT Area Shown": item.view_type,
                    "Photo Filename": item.target.name,
                    "Folder Path": str(item.target.parent),
                    "Description": item.description,
                    "Related Audit ID": item.related_audit_id,
                    "Related Issue ID": item.related_issue_id,
                    LINKED_AUDIT_FIELD_HEADER: item.linked_audit_field,
                    "Notes": notes,
                }
            )
            write_row_by_headers(ws, row_number, data)
            rows_written.append(row_number)
        audit_update_details, audit_update_warnings, updated_audit_rows = _update_related_audit_rows(workbook, plan)
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
        details=[f"{item.source} -> {item.target}" for item in plan]
        + [f"Workbook backup: {backup}"]
        + audit_update_details,
        warnings=(
            ["Filename collision avoided for one or more photos."] if any(item.collision_avoided for item in plan) else []
        )
        + audit_update_warnings,
        files_created=[str(backup), *moved_or_copied],
        files_modified=[str(workbook_path)],
        metrics={"photo_count": len(plan), "copy_mode": copy_mode, "audit_rows_updated": updated_audit_rows},
        duration_seconds=time.perf_counter() - started,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result


def _photo_items(
    photo_paths: list[str | Path],
    *,
    view_type: str,
    related_audit_id: str = "",
    related_issue_id: str = "",
    description: str = "",
    linked_audit_field: str = "",
    tool_number: str = "",
    per_photo_metadata: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for index, source_raw in enumerate(photo_paths):
        override = per_photo_metadata[index] if per_photo_metadata and index < len(per_photo_metadata) else {}
        include = override.get("include", True)
        if isinstance(include, str) and include.strip().casefold() in {"false", "0", "no"}:
            continue
        if include is False:
            continue
        source = Path(override.get("source") or override.get("path") or source_raw)
        items.append(
            {
                "source": str(source),
                "view_type": _text(override.get("view_type") or override.get("EOAT Area Shown") or view_type),
                "related_audit_id": _text(
                    override.get("related_audit_id") or override.get("Related Audit ID") or related_audit_id
                ),
                "related_issue_id": _text(
                    override.get("related_issue_id") or override.get("Related Issue ID") or related_issue_id
                ),
                "description": _text(override.get("description") or override.get("Description") or description),
                "linked_audit_field": _text(
                    override.get("linked_audit_field")
                    or override.get(LINKED_AUDIT_FIELD_HEADER)
                    or linked_audit_field
                ),
                "tool_number": _text(override.get("tool_number") or override.get(TOOL_FIELD) or tool_number),
            }
        )
    return items


def _ensure_headers(ws, expected_headers: list[str]) -> list[str]:
    headers = worksheet_headers(ws)
    added: list[str] = []
    for header in expected_headers:
        if header in headers:
            continue
        ws.cell(row=1, column=len(headers) + 1).value = header
        headers.append(header)
        added.append(header)
    return added


def _audit_rows_by_id(workbook) -> dict[str, dict[str, object]]:
    if "EOAT Inventory" not in workbook.sheetnames:
        return {}
    ws = workbook["EOAT Inventory"]
    headers = worksheet_headers(ws)
    positions = {header: index for index, header in enumerate(headers)}
    rows: dict[str, dict[str, object]] = {}
    if "Audit ID" not in positions:
        return rows
    for row in ws.iter_rows(min_row=2, values_only=True):
        data = {header: row[index] for header, index in positions.items() if index < len(row)}
        audit_id = _text(data.get("Audit ID")).casefold()
        if audit_id:
            rows[audit_id] = data
    return rows


def _update_related_audit_rows(workbook, plan: list[PhotoPlanItem]) -> tuple[list[str], list[str], int]:
    grouped: dict[str, set[str]] = {}
    for item in plan:
        audit_id = _text(item.related_audit_id)
        if not audit_id:
            continue
        grouped.setdefault(audit_id, set()).add(str(item.target.parent))
    if not grouped:
        return [], [], 0
    if "EOAT Inventory" not in workbook.sheetnames:
        return [], ["Related audit rows were not updated because EOAT Inventory is missing."], 0

    ws = workbook["EOAT Inventory"]
    headers = worksheet_headers(ws)
    required = {"Audit ID", "Photos Taken?", "Photo Folder/Link"}
    missing = sorted(required - set(headers))
    if missing:
        return [], [f"Related audit rows were not updated because EOAT Inventory is missing: {', '.join(missing)}"], 0

    audit_id_col = headers.index("Audit ID") + 1
    photos_taken_col = headers.index("Photos Taken?") + 1
    photo_link_col = headers.index("Photo Folder/Link") + 1
    details: list[str] = []
    warnings: list[str] = []
    updated = 0
    for audit_id, references in grouped.items():
        target_row = None
        for row_number in range(2, ws.max_row + 1):
            if _text(ws.cell(row=row_number, column=audit_id_col).value).casefold() == audit_id.casefold():
                target_row = row_number
                break
        if target_row is None:
            warnings.append(
                "Photo Index was updated, but no matching EOAT Inventory row was found "
                f"for Related Audit ID: {audit_id}"
            )
            continue
        ws.cell(row=target_row, column=photos_taken_col).value = "Yes"
        link_cell = ws.cell(row=target_row, column=photo_link_col)
        existing_lines = [_text(line) for line in _text(link_cell.value).splitlines() if _text(line)]
        existing_folded = {line.casefold() for line in existing_lines}
        new_lines = [ref for ref in sorted(references) if ref.casefold() not in existing_folded]
        if new_lines:
            link_cell.value = "\n".join([*existing_lines, *new_lines])
        updated += 1
        details.append(f"Updated EOAT Inventory row {target_row} for {audit_id}: Photos Taken?=Yes.")
    return details, warnings, updated


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
