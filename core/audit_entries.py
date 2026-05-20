from __future__ import annotations

import time
from copy import copy
from datetime import date
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.worksheet.datavalidation import DataValidation

from .action_items import add_action_item
from .audit_by_press import refresh_audit_by_press_view
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import backup_file
from .tool_fields import LEGACY_TOOL_FIELD, TOOL_FIELD
from .workbook_io import find_row_by_value, next_empty_row, row_dicts, worksheet_headers, write_row_by_headers
from .workbook_schema import get_expected_headers

AUDIT_REQUIRED_FIELDS = [
    "Audit Date",
    "Auditor",
    "Plant/Area",
    "Press/Machine #",
    "Robot Type",
    "EOAT Type",
    "Status",
]

AUDIT_IMPORTANT_FIELDS = [
    "Part Family",
    "Tubing Condition",
    "Cable Management Condition",
    "Known Issues",
    "Photos Taken?",
    "Priority",
]

CONNECTION_TYPE_FIELD = "Connection Type"
GRIPPER_MODEL_FIELD = "Gripper Model"
GRIPPER_SIZE_FIELD = "Gripper Size"
NA_VALUE = "N/A"
CONNECTION_TYPE_VALUES = ["ATI", "DoveTail", "Direct Mount", "Lever Lock"]
EOAT_TYPE_DROPDOWN_VALUES = ["Vacuum", "Mechanical / Gripper", "Hybrid", "Unknown / Needs Review", "Miscellaneous"]
CLEANROOM_DROPDOWN_VALUES = ["Cleanroom", "Non-Cleanroom", "Whiteroom", "Unknown / Not Checked"]
CLEANROOM_DEFAULT = "Whiteroom"
CUP_TYPE_DEFAULT = "Silicone"
TOOLING_COLUMN_ORDER = [
    "EOAT Type",
    CONNECTION_TYPE_FIELD,
    "Cup Type/Material",
    "Cup Diameter/Size",
    GRIPPER_MODEL_FIELD,
    GRIPPER_SIZE_FIELD,
]
VACUUM_TOOLING_FIELDS = {
    "Number of Vacuum Cups",
    "Cup Type/Material",
    "Cup Diameter/Size",
    "Vacuum Generator Type",
    "Vacuum Zones",
}
GRIPPER_TOOLING_FIELDS = {"Gripper Type", GRIPPER_MODEL_FIELD, GRIPPER_SIZE_FIELD}

AUDIT_DROPDOWNS = {
    "Plant/Area": ["Plant 4", "Cleanroom"],
    "Cleanroom/Non-Cleanroom": CLEANROOM_DROPDOWN_VALUES,
    "EOAT Type": EOAT_TYPE_DROPDOWN_VALUES,
    CONNECTION_TYPE_FIELD: CONNECTION_TYPE_VALUES,
    "Robot Type": ["Wittmann R8", "Wittmann R9", "Engel Viper", "Other", "Unknown"],
    "YesNoUnknown": ["Yes", "No", "Unknown / Not Checked"],
    "YesNoUnknownNA": ["Yes", "No", "Unknown / Not Checked", "Not Applicable"],
    "YesNoPartialUnknown": ["Yes", "No", "Partial", "Unknown / Not Checked"],
    "Quick Disconnects Present?": ["Yes", "No", "Partial", "Unknown / Not Checked"],
    "Tubing Condition": ["OK", "Worn", "Damaged", "Poor Routing", "Needs Follow-Up", "Unknown / Not Checked"],
    "Cable Management Condition": ["OK", "Loose", "Damaged", "Poor Routing", "Needs Follow-Up", "Unknown / Not Checked"],
    "Mounting Hardware Condition": ["OK", "Loose", "Missing Hardware", "Damaged", "Needs Follow-Up", "Unknown / Not Checked"],
    "EOAT Alignment Condition": ["OK", "Slightly Off", "Misaligned", "Needs Follow-Up", "Unknown / Not Checked"],
    "Changeover Difficulty": ["Low", "Medium", "High", "Unknown / Not Checked"],
    "Photos Taken?": ["Yes", "No"],
    "Status": ["Not Started", "In Progress", "Complete", "Needs Follow-Up", "Blocked"],
    "Priority": ["Low", "Medium", "High", "Critical"],
    "Pilot Candidate?": ["Yes", "No", "Maybe"],
    "Follow-Up Needed": ["Yes", "No"],
}

EOAT_TYPE_VALUES = {"Vacuum", "Mechanical gripper", "Hybrid", "Custom/other", "Unknown"}


def repair_legacy_audit_lookup_shift(row: dict[str, Any]) -> dict[str, Any]:
    """Recover short positional rows written before lookup columns expanded.

    Some older tests and ad hoc workbook edits appended compact EOAT Inventory rows
    by column position. When lookup columns are inserted ahead of EOAT condition
    fields, those compact rows can land under lookup headers. This keeps readers
    tolerant without changing the saved workbook.
    """
    legacy_lookup_shift = _text(row.get("Press Brand")) in EOAT_TYPE_VALUES
    legacy_compact_shift = _text(row.get("Cleanroom/Non-Cleanroom")) in EOAT_TYPE_VALUES and not _text(row.get("EOAT Type"))
    if _text(row.get("EOAT Type")):
        return _repair_missing_connection_type_positional_shift(
            _repair_missing_gripper_fields_positional_shift(_repair_legacy_tail_compact_shift(row))
        )
    if not (legacy_lookup_shift or legacy_compact_shift):
        return row
    repaired = dict(row)
    if legacy_lookup_shift:
        fallback_map = {
            "EOAT Type": "Press Brand",
            "Number of Vacuum Cups": "Press Model",
            "Cup Type/Material": "Press Tonnage",
            "Cup Diameter/Size": "Press Year",
            "Known Issues": "# of TCU's",
            "Scrap/Quality Concern?": "Screw Size",
            "Status": "Bill-to / Customer",
            "Priority": "Cycle Time (S)",
            "Pilot Candidate?": "Cavitation",
        }
    else:
        fallback_map = {
            "EOAT Type": "Cleanroom/Non-Cleanroom",
            "Number of Vacuum Cups": "Vacuum Sensor",
            "Cup Type/Material": "Quick Disconnect",
            "Cup Diameter/Size": "PM Status",
            "Known Issues": "Cable Management Condition",
            "Scrap/Quality Concern?": "Estimated EOAT Weight",
            "Status": "Drawing/CAD Available?",
            "Priority": "BOM Available?",
            "Pilot Candidate?": "Process Binder Complete?",
        }
    for target, source in fallback_map.items():
        if not _text(repaired.get(target)) and _text(repaired.get(source)):
            repaired[target] = repaired.get(source)
    return repaired


def _repair_missing_connection_type_positional_shift(row: dict[str, Any]) -> dict[str, Any]:
    """Read compact rows written by position before Connection Type existed."""
    connection_value = _text(row.get(CONNECTION_TYPE_FIELD))
    if _looks_like_count(connection_value) and (_text(row.get("Cup Type/Material")) or _text(row.get("Cup Diameter/Size"))):
        repaired = dict(row)
        if not _text(repaired.get("Number of Vacuum Cups")):
            repaired["Number of Vacuum Cups"] = row.get(CONNECTION_TYPE_FIELD)
        repaired[CONNECTION_TYPE_FIELD] = ""
        return repaired
    shifted_after_connection = (
        _looks_like_count(connection_value)
        or (_text(row.get("Status")) in {"Low", "Medium", "High", "Critical"} and _text(row.get("Priority")) in {"Yes", "No", "Maybe"})
        or (_text(row.get("Estimated EOAT Weight")) and not _text(row.get("Known Issues")))
    )
    if not shifted_after_connection:
        return row
    headers = get_expected_headers("EOAT Inventory")
    if CONNECTION_TYPE_FIELD not in headers:
        return row
    repaired = dict(row)
    start = headers.index(CONNECTION_TYPE_FIELD)
    for index in range(len(headers) - 1, start, -1):
        repaired[headers[index]] = row.get(headers[index - 1])
    repaired[CONNECTION_TYPE_FIELD] = "" if connection_value not in CONNECTION_TYPE_VALUES else row.get(CONNECTION_TYPE_FIELD)
    return repaired


def _repair_missing_gripper_fields_positional_shift(row: dict[str, Any]) -> dict[str, Any]:
    """Read rows written by position before Gripper Model/Size existed."""
    shifted_after_gripper_fields = (
        _looks_like_count(row.get(GRIPPER_MODEL_FIELD))
        or (_text(row.get("Status")) in {"Low", "Medium", "High", "Critical"} and _text(row.get("Priority")) in {"Yes", "No", "Maybe"})
        or (_text(row.get("Estimated EOAT Weight")) and not _text(row.get("Known Issues")))
    )
    if not shifted_after_gripper_fields:
        return row
    headers = get_expected_headers("EOAT Inventory")
    if GRIPPER_MODEL_FIELD not in headers or GRIPPER_SIZE_FIELD not in headers:
        return row
    repaired = dict(row)
    start = headers.index(GRIPPER_MODEL_FIELD)
    for index in range(len(headers) - 1, start + 1, -1):
        repaired[headers[index]] = row.get(headers[index - 2])
    repaired[GRIPPER_MODEL_FIELD] = ""
    repaired[GRIPPER_SIZE_FIELD] = ""
    return repaired


def _repair_legacy_tail_compact_shift(row: dict[str, Any]) -> dict[str, Any]:
    """Recover very compact rows written before the current tail columns settled."""
    status_candidate = _text(row.get("Process Binder Complete?"))
    priority_candidate = _text(row.get("Photos Taken?"))
    pilot_candidate = _text(row.get("Photo Folder/Link"))
    if not (
        status_candidate
        and priority_candidate in {"Low", "Medium", "High", "Critical"}
        and pilot_candidate in {"Yes", "No", "Maybe"}
        and not _text(row.get("Status"))
    ):
        return row
    repaired = dict(row)
    repaired["Status"] = status_candidate
    repaired["Priority"] = priority_candidate
    repaired["Pilot Candidate?"] = pilot_candidate
    if not _text(repaired.get("Known Issues")) and _text(row.get("EOAT Alignment Condition")):
        repaired["Known Issues"] = row.get("EOAT Alignment Condition")
    return repaired


def _looks_like_count(value: Any) -> bool:
    text = _text(value)
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def _text(value: Any) -> str:
    return str(value or "").strip()


def generate_audit_id(project_root: str | Path, audit_date: str | None = None) -> str:
    audit_date = audit_date or date.today().isoformat()
    compact = audit_date.replace("-", "")
    workbook_path = resolve_project_paths(project_root).master_workbook
    rows = row_dicts(workbook_path, "EOAT Inventory") if workbook_path.exists() else []
    prefix = f"AUD-{compact}-"
    max_number = 0
    for row in rows:
        value = str(row.get("Audit ID") or "")
        if value.startswith(prefix):
            try:
                max_number = max(max_number, int(value.rsplit("-", 1)[1]))
            except ValueError:
                continue
    return f"{prefix}{max_number + 1:03d}"


def normalize_audit_entry(project_root: str | Path, entry: dict[str, Any]) -> dict[str, Any]:
    headers = get_expected_headers("EOAT Inventory")
    if TOOL_FIELD not in entry and LEGACY_TOOL_FIELD in entry:
        entry = {**entry, TOOL_FIELD: entry.get(LEGACY_TOOL_FIELD, "")}
    normalized = {header: entry.get(header, "") for header in headers}
    if not normalized.get("Audit Date"):
        normalized["Audit Date"] = date.today().isoformat()
    if not normalized.get("Audit ID"):
        normalized["Audit ID"] = generate_audit_id(project_root, str(normalized["Audit Date"]))
    if not normalized.get("Cleanroom/Non-Cleanroom"):
        normalized["Cleanroom/Non-Cleanroom"] = CLEANROOM_DEFAULT
    eoat_type = normalized.get("EOAT Type")
    if not _text(normalized.get("Cup Type/Material")) and cup_type_default_applies(eoat_type):
        normalized["Cup Type/Material"] = CUP_TYPE_DEFAULT
    if not tooling_field_applies(eoat_type, "Cup Type/Material") and _text(normalized.get("Cup Type/Material")) == CUP_TYPE_DEFAULT:
        normalized["Cup Type/Material"] = ""
    for header in headers:
        if not _text(normalized.get(header)):
            normalized[header] = NA_VALUE
    return normalized


def validate_audit_entry(entry: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for field in AUDIT_REQUIRED_FIELDS:
        if not str(entry.get(field) or "").strip():
            errors.append(f"Missing required field: {field}")
    for field in AUDIT_IMPORTANT_FIELDS:
        if not str(entry.get(field) or "").strip():
            warnings.append(f"Missing important audit field: {field}")
    return errors, warnings


def is_na_value(value: Any) -> bool:
    return _text(value).upper() == NA_VALUE


def tooling_field_applies(eoat_type: Any, field: str) -> bool:
    text = _text(eoat_type).lower()
    if not text or text.startswith("unknown") or text == "miscellaneous":
        return True
    if text == "vacuum":
        return field not in GRIPPER_TOOLING_FIELDS
    if text == "hybrid":
        return True
    if "mechanical" in text and "gripper" in text:
        return field not in VACUUM_TOOLING_FIELDS
    return True


def cup_type_default_applies(eoat_type: Any) -> bool:
    text = _text(eoat_type).lower()
    return not text or text == "vacuum" or text == "hybrid" or text.startswith("unknown")


def load_audit_entry(project_root: str | Path, audit_id: str) -> dict[str, Any] | None:
    workbook_path = resolve_project_paths(project_root).master_workbook
    for row in row_dicts(workbook_path, "EOAT Inventory"):
        if str(row.get("Audit ID") or "") == str(audit_id):
            if TOOL_FIELD not in row and LEGACY_TOOL_FIELD in row:
                row = {**row, TOOL_FIELD: row.get(LEGACY_TOOL_FIELD, "")}
            return {key: ("" if value is None else value) for key, value in row.items()}
    return None


def _ensure_inventory_headers(ws, required_headers: list[str]) -> list[str]:
    _migrate_legacy_tool_header(ws)
    existing = worksheet_headers(ws)
    missing = [header for header in required_headers if header not in existing]
    for header in missing:
        if header == TOOL_FIELD and "Press/Machine #" in existing:
            ws.insert_cols(existing.index("Press/Machine #") + 2)
            ws.cell(row=1, column=existing.index("Press/Machine #") + 2).value = header
        elif header in TOOLING_COLUMN_ORDER and _tooling_insert_index(existing, header):
            target_idx = _tooling_insert_index(existing, header)
            ws.insert_cols(target_idx)
            ws.cell(row=1, column=target_idx).value = header
        else:
            ws.cell(row=1, column=ws.max_column + 1).value = header
        existing = worksheet_headers(ws)
    _move_tool_after_press(ws)
    _order_tooling_columns(ws)
    _style_inventory_tooling_columns(ws)
    _refresh_inventory_ranges(ws)
    _apply_inventory_validations(ws)
    return missing


def _migrate_workbook_tool_headers(workbook) -> None:
    for ws in workbook.worksheets:
        _migrate_legacy_tool_header(ws)
    if "EOAT Inventory" in workbook.sheetnames:
        _move_tool_after_press(workbook["EOAT Inventory"])
        _order_tooling_columns(workbook["EOAT Inventory"])


def _migrate_legacy_tool_header(ws) -> None:
    headers = worksheet_headers(ws)
    while LEGACY_TOOL_FIELD in headers:
        legacy_idx = headers.index(LEGACY_TOOL_FIELD) + 1
        if TOOL_FIELD in headers:
            tool_idx = headers.index(TOOL_FIELD) + 1
            for row_number in range(2, ws.max_row + 1):
                tool_cell = ws.cell(row=row_number, column=tool_idx)
                legacy_cell = ws.cell(row=row_number, column=legacy_idx)
                if tool_cell.value in (None, "") and legacy_cell.value not in (None, ""):
                    tool_cell.value = legacy_cell.value
            ws.delete_cols(legacy_idx)
        else:
            ws.cell(row=1, column=legacy_idx).value = TOOL_FIELD
        headers = worksheet_headers(ws)


def _move_tool_after_press(ws) -> None:
    headers = worksheet_headers(ws)
    if "Press/Machine #" not in headers or TOOL_FIELD not in headers:
        return
    source_idx = headers.index(TOOL_FIELD) + 1
    target_idx = headers.index("Press/Machine #") + 2
    if source_idx == target_idx:
        return
    _move_column(ws, source_idx, target_idx)


def _tooling_insert_index(headers: list[str], header: str) -> int | None:
    if header not in TOOLING_COLUMN_ORDER:
        return None
    header_order_index = TOOLING_COLUMN_ORDER.index(header)
    for previous in reversed(TOOLING_COLUMN_ORDER[:header_order_index]):
        if previous in headers:
            return headers.index(previous) + 2
    for following in TOOLING_COLUMN_ORDER[header_order_index + 1 :]:
        if following in headers:
            return headers.index(following) + 1
    return None


def _order_tooling_columns(ws) -> None:
    if "EOAT Type" not in worksheet_headers(ws):
        return
    for offset, header in enumerate(TOOLING_COLUMN_ORDER):
        headers = worksheet_headers(ws)
        if header not in headers:
            continue
        target_idx = headers.index("EOAT Type") + 1 + offset
        source_idx = headers.index(header) + 1
        if source_idx != target_idx:
            _move_column(ws, source_idx, target_idx)


def _style_inventory_tooling_columns(ws) -> None:
    headers = worksheet_headers(ws)
    style_pairs = {
        CONNECTION_TYPE_FIELD: "EOAT Type",
        GRIPPER_MODEL_FIELD: "Cup Type/Material",
        GRIPPER_SIZE_FIELD: "Cup Diameter/Size",
    }
    for target_header, source_header in style_pairs.items():
        if target_header not in headers or source_header not in headers:
            continue
        target_col = headers.index(target_header) + 1
        source_col = headers.index(source_header) + 1
        _copy_column_style(ws, source_col, target_col, max_row=max(ws.max_row, 2))


def _copy_column_style(ws, source_col: int, target_col: int, *, max_row: int) -> None:
    source_letter = get_column_letter(source_col)
    target_letter = get_column_letter(target_col)
    ws.column_dimensions[target_letter].width = ws.column_dimensions[source_letter].width
    for row_number in range(1, max_row + 1):
        source = ws.cell(row=row_number, column=source_col)
        target = ws.cell(row=row_number, column=target_col)
        target._style = copy(source._style)
        target.number_format = source.number_format
        target.alignment = copy(source.alignment)
        target.fill = copy(source.fill)
        target.font = copy(source.font)
        target.border = copy(source.border)
        target.protection = copy(source.protection)


def _refresh_inventory_ranges(ws) -> None:
    headers = worksheet_headers(ws)
    if not headers:
        return
    last_column = get_column_letter(len(headers))
    ws.auto_filter.ref = f"A1:{last_column}1"
    for table in ws.tables.values():
        try:
            min_col, min_row, _max_col, max_row = range_boundaries(table.ref)
        except ValueError:
            continue
        if min_row == 1:
            table.ref = f"{get_column_letter(min_col)}{min_row}:{last_column}{max_row}"


def _move_connection_after_eoat_type(ws) -> None:
    headers = worksheet_headers(ws)
    if "EOAT Type" not in headers or CONNECTION_TYPE_FIELD not in headers:
        return
    source_idx = headers.index(CONNECTION_TYPE_FIELD) + 1
    target_idx = headers.index("EOAT Type") + 2
    if source_idx == target_idx:
        return
    _move_column(ws, source_idx, target_idx)


def _dropdown_formula(values: list[str]) -> str:
    return '"' + ",".join(value.replace('"', '""') for value in values) + '"'


def _remove_column_validations(ws, column_numbers: set[int]) -> None:
    kept = []
    for validation in ws.data_validations.dataValidation:
        ranges = getattr(validation.sqref, "ranges", [])
        if any(
            cell_range.min_col in column_numbers
            and cell_range.max_col in column_numbers
            and cell_range.min_row <= 2
            and cell_range.max_row >= 1000
            for cell_range in ranges
        ):
            continue
        kept.append(validation)
    ws.data_validations.dataValidation = kept


def _add_column_validation(ws, column_number: int, values: list[str]) -> None:
    column_letter = get_column_letter(column_number)
    validation = DataValidation(type="list", formula1=_dropdown_formula(values), allow_blank=True)
    validation.error = "Choose a value from the dropdown list."
    validation.errorTitle = "Invalid value"
    validation.prompt = "Choose a standard value, or leave blank if not known yet."
    validation.promptTitle = "Dropdown"
    ws.add_data_validation(validation)
    validation.add(f"{column_letter}2:{column_letter}1000")


def _apply_inventory_validations(ws) -> None:
    headers = worksheet_headers(ws)
    desired = {
        "EOAT Type": [*EOAT_TYPE_DROPDOWN_VALUES, NA_VALUE],
        CONNECTION_TYPE_FIELD: [*CONNECTION_TYPE_VALUES, NA_VALUE],
        "Cleanroom/Non-Cleanroom": [*CLEANROOM_DROPDOWN_VALUES, NA_VALUE],
    }
    columns = {headers.index(header) + 1 for header in desired if header in headers}
    if not columns:
        return
    _remove_column_validations(ws, columns)
    for header, values in desired.items():
        if header in headers:
            _add_column_validation(ws, headers.index(header) + 1, values)


def _move_column(ws, source_idx: int, target_idx: int) -> None:
    width = ws.column_dimensions[get_column_letter(source_idx)].width
    cells = []
    for row_number in range(1, ws.max_row + 1):
        source = ws.cell(row=row_number, column=source_idx)
        cells.append(
            {
                "value": source.value,
                "style": copy(source._style),
                "number_format": source.number_format,
                "alignment": copy(source.alignment),
                "fill": copy(source.fill),
                "font": copy(source.font),
                "border": copy(source.border),
                "protection": copy(source.protection),
            }
        )
    ws.delete_cols(source_idx)
    if source_idx < target_idx:
        target_idx -= 1
    ws.insert_cols(target_idx)
    ws.column_dimensions[get_column_letter(target_idx)].width = width
    for row_number, snapshot in enumerate(cells, start=1):
        target = ws.cell(row=row_number, column=target_idx)
        target.value = snapshot["value"]
        target._style = snapshot["style"]
        target.number_format = snapshot["number_format"]
        target.alignment = snapshot["alignment"]
        target.fill = snapshot["fill"]
        target.font = snapshot["font"]
        target.border = snapshot["border"]
        target.protection = snapshot["protection"]


def save_audit_entry(
    project_root: str | Path,
    entry: dict[str, Any],
    allow_update: bool = False,
    create_followup_action: bool = False,
    log_activity: bool = True,
) -> ToolResult:
    started = time.perf_counter()
    paths = resolve_project_paths(project_root)
    workbook_path = paths.master_workbook
    if not workbook_path.exists():
        return ToolResult.fail("eoat_audit_form", "EOAT Audit Form Tool", "Master workbook is missing.", errors=[str(workbook_path)])

    validation_entry = dict(entry)
    if TOOL_FIELD not in validation_entry and LEGACY_TOOL_FIELD in validation_entry:
        validation_entry[TOOL_FIELD] = validation_entry.get(LEGACY_TOOL_FIELD, "")
    if not validation_entry.get("Audit Date"):
        validation_entry["Audit Date"] = date.today().isoformat()
    if not validation_entry.get("Cleanroom/Non-Cleanroom"):
        validation_entry["Cleanroom/Non-Cleanroom"] = CLEANROOM_DEFAULT
    errors, warnings = validate_audit_entry(validation_entry)
    if errors:
        return ToolResult.fail(
            "eoat_audit_form",
            "EOAT Audit Form Tool",
            "Audit entry failed validation.",
            errors=errors,
            warnings=warnings,
            duration_seconds=time.perf_counter() - started,
        )
    data = normalize_audit_entry(project_root, entry)

    workbook = None
    try:
        backup = backup_file(workbook_path, workbook_path.parent / "_backups")
        workbook = load_workbook(workbook_path)
        if "EOAT Inventory" not in workbook.sheetnames:
            raise ValueError("EOAT Inventory sheet is missing.")
        _migrate_workbook_tool_headers(workbook)
        ws = workbook["EOAT Inventory"]
        added_headers = _ensure_inventory_headers(ws, get_expected_headers("EOAT Inventory"))
        existing_row = find_row_by_value(ws, "Audit ID", str(data["Audit ID"]))
        if existing_row and not allow_update:
            workbook.close()
            return ToolResult.fail(
                "eoat_audit_form",
                "EOAT Audit Form Tool",
                "Audit ID already exists. Re-run with update enabled to modify it.",
                errors=[str(data["Audit ID"])],
                files_created=[str(backup)],
                duration_seconds=time.perf_counter() - started,
            )
        if existing_row:
            supplied_fields = set(entry)
            if LEGACY_TOOL_FIELD in supplied_fields:
                supplied_fields.add(TOOL_FIELD)
            headers = worksheet_headers(ws)
            for column, header in enumerate(headers, start=1):
                existing_value = ws.cell(row=existing_row, column=column).value
                if header in data and header not in supplied_fields and _text(existing_value):
                    data[header] = existing_value
        row_number = existing_row or next_empty_row(ws)
        write_row_by_headers(ws, row_number, data)
        refresh_audit_by_press_view(workbook)
        workbook.save(workbook_path)
        workbook.close()
    except Exception as exc:
        if workbook is not None:
            try:
                workbook.close()
            except Exception:
                pass
        return ToolResult.fail(
            "eoat_audit_form",
            "EOAT Audit Form Tool",
            "Could not save audit entry.",
            errors=[str(exc)],
            warnings=warnings,
            duration_seconds=time.perf_counter() - started,
        )

    details = [
        f"Audit ID: {data['Audit ID']}",
        f"Workbook row: {row_number}",
        f"Mode: {'updated existing row' if existing_row else 'added new row'}",
        f"Workbook backup: {backup}",
    ]
    if added_headers:
        details.append(f"Added missing EOAT Inventory headers: {', '.join(added_headers)}")
    files_modified = [str(workbook_path)]
    action_result = None
    if create_followup_action or str(data.get("Follow-Up Needed") or "").lower() == "yes":
        action_result = add_action_item(
            project_root,
            action_item=f"Follow up on EOAT audit {data['Audit ID']}: {data.get('Known Issues') or data.get('Notes') or 'Review audit entry.'}",
            related_cell_press=str(data.get("Press/Machine #") or ""),
            priority=str(data.get("Priority") or "Medium"),
            notes=f"Generated from audit entry {data['Audit ID']}.",
            log_activity=False,
        )
        details.append(action_result.summary)
        warnings.extend(action_result.warnings)
        if action_result.errors:
            warnings.extend(action_result.errors)
        files_modified.extend(action_result.files_modified)

    result = ToolResult.ok(
        "eoat_audit_form",
        "EOAT Audit Form Tool",
        f"Saved audit entry {data['Audit ID']}.",
        details=details,
        warnings=warnings,
        files_created=[str(backup), *(action_result.files_created if action_result else [])],
        files_modified=sorted(set(files_modified)),
        metrics={"audit_id": data["Audit ID"], "row": row_number, "updated": bool(existing_row)},
        duration_seconds=time.perf_counter() - started,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result
