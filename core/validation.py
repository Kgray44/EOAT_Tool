from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from .audit_by_press import AUDIT_BY_PRESS_SHEET, audit_by_press_last_refreshed
from .constants import TOOLKIT_ROOT
from .audit_entries import (
    AUDIT_IMPORTANT_FIELDS,
    AUDIT_REQUIRED_FIELDS,
    CLEANROOM_DROPDOWN_VALUES,
    CONNECTION_TYPE_FIELD,
    CONNECTION_TYPE_VALUES,
    EOAT_MOVES_FIELD,
    EOAT_MOVES_VALUES,
    EOAT_TYPE_DROPDOWN_VALUES,
    LEGACY_VACUUM_CUPS_FIELD,
    NA_VALUE,
    NUMBER_OF_PARTS_PICKED_FIELD,
    apply_part_present_sensor_defaults,
    audit_field_applies,
    is_na_value,
)
from .gripper_fields import GRIPPER_COUNT_FIELD, GRIPPER_TYPE_FIELD, GRIPPER_TYPE_VALUES
from .audit_field_rules import (
    ELECTRICAL_DETAIL_FIELDS,
    ELECTRICAL_WIRING_PRESENT_FIELD,
    entry_type_requirements,
    field_applies,
    hybrid_completeness_warnings,
    is_meaningful_value,
    semantic_consistency_warnings,
)
from .audit_constants import (
    AUTOFILLED_COMPATIBILITY_METADATA_FIELDS,
    ENTRY_TYPE_COMPATIBLE,
    ENTRY_TYPE_FIELD,
    SOURCE_AUDIT_ID_FIELD,
)
from .git_activity import is_git_repo
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .robot_info import validate_robot_info_workbook
from .safe_files import ensure_directory, safe_write_text
from .schedule import available_schedule_weeks
from .workbook_schema import get_expected_headers, get_expected_sheets, get_key_inventory_headers

MAJOR_AUDIT_COLUMNS = {
    "Audit ID",
    "Audit Date",
    "Auditor",
    "Plant/Area",
    "Press/Machine #",
    "Tool #",
    "EOAT Type",
    CONNECTION_TYPE_FIELD,
    "Cleanroom/Non-Cleanroom",
    "Status",
    "Priority",
    "Known Issues",
    *AUDIT_REQUIRED_FIELDS,
    *AUDIT_IMPORTANT_FIELDS,
} - {EOAT_MOVES_FIELD}

AUDIT_DROPDOWN_ALLOWED_VALUES = {
    "EOAT Type": {*EOAT_TYPE_DROPDOWN_VALUES, NA_VALUE},
    EOAT_MOVES_FIELD: set(EOAT_MOVES_VALUES),
    CONNECTION_TYPE_FIELD: {*CONNECTION_TYPE_VALUES, NA_VALUE},
    GRIPPER_TYPE_FIELD: {*GRIPPER_TYPE_VALUES, NA_VALUE},
    "Cleanroom/Non-Cleanroom": {*CLEANROOM_DROPDOWN_VALUES, NA_VALUE},
}
AUDIT_NUMERIC_FIELDS = {NUMBER_OF_PARTS_PICKED_FIELD, GRIPPER_COUNT_FIELD}

BLANK_CELL_VALIDATION_IGNORED_FIELDS = AUTOFILLED_COMPATIBILITY_METADATA_FIELDS
BLANK_CELL_VALIDATION_IGNORED_FIELD_LABEL = "Source Audit ID and Compatibility Source"


def validate_project_foundation(project_root: str | Path) -> ToolResult:
    started = time.perf_counter()
    paths = resolve_project_paths(project_root)
    details: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []
    metrics: dict[str, int | bool] = {}

    if not paths.project_root.exists():
        return ToolResult.fail(
            "workbook_validator",
            "EOAT Project Foundation Validation",
            "Project root does not exist.",
            errors=[f"Missing project root: {paths.project_root}"],
            duration_seconds=time.perf_counter() - started,
        )

    details.append(f"Project root exists: {paths.project_root}")

    for folder in paths.expected_numbered_folders():
        if folder.exists():
            details.append(f"Found folder: {folder.name}")
        else:
            warnings.append(f"Missing expected folder: {folder.name}")

    for folder_name, folder in {
        "daily reports": paths.daily_reports,
        "weekly reports": paths.weekly_reports,
        "activity logs": paths.activity_logs,
    }.items():
        if folder.exists():
            details.append(f"Found {folder_name} folder: {folder}")
        else:
            warnings.append(f"Missing {folder_name} folder: {folder}")

    workbook_path = paths.master_workbook
    if not workbook_path.exists():
        errors.append(f"Missing master workbook: {workbook_path}")
        return ToolResult.fail(
            "workbook_validator",
            "EOAT Project Foundation Validation",
            "Master workbook is missing.",
            details=details,
            warnings=warnings,
            errors=errors,
            metrics=metrics,
            duration_seconds=time.perf_counter() - started,
        )

    details.append(f"Found master workbook: {workbook_path}")
    try:
        workbook = load_workbook(workbook_path, read_only=True, data_only=False)
    except Exception as exc:
        errors.append(f"Could not open workbook with openpyxl: {exc}")
        return ToolResult.fail(
            "workbook_validator",
            "EOAT Project Foundation Validation",
            "Master workbook exists but could not be opened.",
            details=details,
            warnings=warnings,
            errors=errors,
            metrics=metrics,
            duration_seconds=time.perf_counter() - started,
        )

    expected_sheets = get_expected_sheets()
    missing_sheets = [sheet for sheet in expected_sheets if sheet not in workbook.sheetnames]
    metrics["expected_sheet_count"] = len(expected_sheets)
    metrics["actual_sheet_count"] = len(workbook.sheetnames)
    if missing_sheets:
        errors.extend(f"Missing expected sheet: {sheet}" for sheet in missing_sheets)
    else:
        details.append("All expected workbook sheets are present.")
    if AUDIT_BY_PRESS_SHEET not in workbook.sheetnames:
        warnings.append("Audit by Press view missing or stale; refresh generated view.")
    elif audit_by_press_last_refreshed(workbook) is None:
        warnings.append("Audit by Press view missing or stale; refresh generated view.")
    else:
        details.append("Audit by Press generated view is present.")

    if "EOAT Inventory" in workbook.sheetnames:
        ws = workbook["EOAT Inventory"]
        header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        headers = [str(value) for value in header_row if value is not None]
        required_headers = get_expected_headers("EOAT Inventory")
        missing_full_headers = [header for header in required_headers if header not in headers]
        missing_key_headers = [header for header in get_key_inventory_headers() if header not in headers]
        missing_major_headers = [header for header in MAJOR_AUDIT_COLUMNS if header in required_headers and header not in headers]
        schema_upgrade_headers = []
        if ELECTRICAL_WIRING_PRESENT_FIELD in missing_full_headers:
            schema_upgrade_headers.append(ELECTRICAL_WIRING_PRESENT_FIELD)
        missing_detail_headers = [
            header
            for header in missing_full_headers
            if header not in missing_major_headers and header not in schema_upgrade_headers
        ]
        unexpected_headers = [
            header
            for header in headers
            if header and header not in required_headers and header != LEGACY_VACUUM_CUPS_FIELD
        ]
        duplicate_headers = sorted({header for header in headers if header and headers.count(header) > 1})
        legacy_vacuum_header_present = LEGACY_VACUUM_CUPS_FIELD in headers
        has_parts_picked_header = NUMBER_OF_PARTS_PICKED_FIELD in headers
        metrics["eoat_inventory_header_count"] = len(headers)
        metrics["missing_full_inventory_header_count"] = len(missing_full_headers)
        metrics["missing_key_inventory_header_count"] = len(missing_key_headers)
        metrics["missing_major_inventory_header_count"] = len(missing_major_headers)
        metrics["unexpected_inventory_header_count"] = len(unexpected_headers)
        metrics["duplicate_inventory_header_count"] = len(duplicate_headers)
        metrics["legacy_vacuum_cups_header_present"] = int(legacy_vacuum_header_present)
        if missing_major_headers:
            errors.extend(f"Missing major EOAT Inventory header: {header}" for header in missing_major_headers)
        elif missing_key_headers:
            warnings.extend(f"Missing key EOAT Inventory header: {header}" for header in missing_key_headers)
        else:
            details.append("Key EOAT Inventory headers are present.")
        if missing_detail_headers:
            warnings.extend(f"Missing detail EOAT Inventory header: {header}" for header in missing_detail_headers)
        if ELECTRICAL_WIRING_PRESENT_FIELD in schema_upgrade_headers:
            warnings.append(
                "Workbook is missing Electrical/Wiring Present?. Run Repair Workbook Schema to upgrade old workbooks."
            )
        if legacy_vacuum_header_present and has_parts_picked_header:
            warnings.append(
                "EOAT Inventory has both Number of Vacuum Cups and Number of Parts Picked. "
                "Run Repair Workbook Schema to merge values into Number of Parts Picked and remove the legacy header."
            )
        elif legacy_vacuum_header_present:
            warnings.append(
                "EOAT Inventory still uses legacy header Number of Vacuum Cups. "
                "Run Repair Workbook Schema to rename it to Number of Parts Picked."
            )
        if unexpected_headers:
            warnings.extend(f"Unexpected EOAT Inventory header: {header}" for header in unexpected_headers)
        if duplicate_headers:
            warnings.extend(f"Duplicate EOAT Inventory header: {header}" for header in duplicate_headers)
        if any(header in headers for header in BLANK_CELL_VALIDATION_IGNORED_FIELDS):
            details.append(
                f"Blank {BLANK_CELL_VALIDATION_IGNORED_FIELD_LABEL} cells are intentionally ignored during "
                "blank-cell validation because they are autofilled/system-managed compatibility metadata; "
                "the columns still remain part of the workbook schema."
            )
        inventory_warnings, inventory_metrics = _validate_inventory_rows(ws, headers)
        warnings.extend(inventory_warnings)
        metrics.update(inventory_metrics)
    else:
        errors.append("EOAT Inventory sheet is missing, so headers could not be checked.")

    workbook.close()

    robot_warnings, robot_errors, robot_metrics = validate_robot_info_workbook(paths.project_root)
    warnings.extend(robot_warnings)
    errors.extend(robot_errors)
    metrics.update(robot_metrics)
    if not robot_warnings and not robot_errors:
        details.append("Robot Info workbook is present and valid.")

    weeks = available_schedule_weeks(paths.project_root)
    metrics["schedule_week_count"] = len(weeks)
    if weeks:
        details.append(f"Found schedule/task progress week files for week(s): {', '.join(str(week) for week in weeks)}")
    else:
        warnings.append("No project schedule or task progress week files found.")

    readme_path = paths.project_root / "README.md"
    if readme_path.exists():
        details.append(f"Found project README: {readme_path}")
    else:
        warnings.append(f"Missing project README: {readme_path}")

    usage_path = TOOLKIT_ROOT / "USAGE.md"
    if usage_path.exists():
        details.append(f"Found toolkit usage guide: {usage_path}")
    else:
        warnings.append(f"Missing toolkit usage guide: {usage_path}")

    git_repo, git_warning = is_git_repo(paths.project_root)
    metrics["git_repo_detected"] = git_repo
    if git_repo:
        details.append("Git repository detected.")
    elif git_warning:
        warnings.append(f"Git repository not detected or Git unavailable: {git_warning}")

    summary = "Project foundation validation completed."
    if warnings and not errors:
        summary = "Project foundation validation completed with warnings."
    if errors:
        summary = "Project foundation validation failed."
    return ToolResult(
        tool_id="workbook_validator",
        tool_name="EOAT Project Foundation Validation",
        success=not errors,
        summary=summary,
        details=details,
        warnings=warnings,
        errors=errors,
        metrics=metrics,
        duration_seconds=time.perf_counter() - started,
    )


def _validate_inventory_rows(ws, headers: list[str]) -> tuple[list[str], dict[str, int]]:
    warnings: list[str] = []
    metrics = {
        "duplicate_audit_id_count": 0,
        "blank_saved_audit_cell_count": 0,
        "major_na_cell_count": 0,
        "missing_applicable_major_cell_count": 0,
        "non_applicable_na_cell_count": 0,
        "stale_hidden_value_count": 0,
        "hybrid_warning_count": 0,
        "semantic_warning_count": 0,
        "physical_audit_row_count": 0,
        "compatible_row_count": 0,
        "invalid_dropdown_value_count": 0,
        "invalid_numeric_value_count": 0,
        "audit_row_count": 0,
    }
    if not headers:
        return warnings, metrics

    header_positions = {header: index for index, header in enumerate(headers)}
    missing_electrical_wiring_control = ELECTRICAL_WIRING_PRESENT_FIELD not in header_positions
    audit_ids: dict[str, int] = {}
    duplicate_ids: set[str] = set()
    blank_cells = 0
    major_na_examples: set[str] = set()
    non_applicable_na_examples: list[str] = []
    stale_hidden_value_examples: list[str] = []
    hybrid_warning_examples: list[str] = []
    semantic_warning_examples: list[str] = []
    invalid_dropdown_examples: list[str] = []
    invalid_numeric_examples: list[str] = []
    missing_eoat_moves_examples: list[str] = []
    source_eoat_moves_by_audit_id: dict[str, str] = {}

    if EOAT_MOVES_FIELD in header_positions:
        for row in ws.iter_rows(min_row=2, values_only=True):
            row_data = {header: row[index] for header, index in header_positions.items() if index < len(row)}
            audit_id = _cell_text(row_data.get("Audit ID"))
            if audit_id:
                source_eoat_moves_by_audit_id[audit_id] = _cell_text(row_data.get(EOAT_MOVES_FIELD))

    for row_number, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        row_data = {header: row[index] for header, index in header_positions.items() if index < len(row)}
        if not _is_audit_data_row(row_data):
            continue
        row_data = apply_part_present_sensor_defaults(row_data)
        metrics["audit_row_count"] += 1
        entry_type = _cell_text(row_data.get(ENTRY_TYPE_FIELD)).lower()
        if entry_type == ENTRY_TYPE_COMPATIBLE.lower():
            metrics["compatible_row_count"] += 1
        else:
            metrics["physical_audit_row_count"] += 1
        audit_id = _cell_text(row_data.get("Audit ID"))
        if audit_id and not is_na_value(audit_id):
            if audit_id in audit_ids:
                duplicate_ids.add(audit_id)
            else:
                audit_ids[audit_id] = row_number
        elif "Audit ID" in headers:
            major_na_examples.add(f"row {row_number} Audit ID")

        requirements = entry_type_requirements(row_data)
        for required_field in requirements["required"]:
            if required_field in BLANK_CELL_VALIDATION_IGNORED_FIELDS:
                continue
            if required_field in header_positions and field_applies(row_data, required_field) and _is_missing_audit_value(row_data.get(required_field)):
                major_na_examples.add(f"row {row_number} {required_field}")

        for header in get_expected_headers("EOAT Inventory"):
            if header not in header_positions:
                continue
            if header in BLANK_CELL_VALIDATION_IGNORED_FIELDS:
                continue
            value = row_data.get(header)
            if _cell_text(value) == "":
                blank_cells += 1
            applies = audit_field_applies(row_data, header)
            if missing_electrical_wiring_control and header in ELECTRICAL_DETAIL_FIELDS and not is_meaningful_value(value):
                applies = False
            if (
                header in MAJOR_AUDIT_COLUMNS
                and _is_missing_audit_value(value)
                and applies
            ):
                major_na_examples.add(f"row {row_number} {header}")
            if not applies and is_na_value(value):
                non_applicable_na_examples.append(f"row {row_number} {header}")
            if not applies and is_meaningful_value(value):
                stale_hidden_value_examples.append(f"row {row_number} {header}")
            if (
                header in AUDIT_DROPDOWN_ALLOWED_VALUES
                and _cell_text(value)
                and (header == EOAT_MOVES_FIELD or not is_na_value(value))
                and _cell_text(value) not in AUDIT_DROPDOWN_ALLOWED_VALUES[header]
            ):
                invalid_dropdown_examples.append(f"row {row_number} {header}={_cell_text(value)}")
            if (
                header in AUDIT_NUMERIC_FIELDS
                and applies
                and _cell_text(value)
                and not is_na_value(value)
                and not _is_non_negative_whole_number(value)
            ):
                invalid_numeric_examples.append(f"row {row_number} {header}={_cell_text(value)}")
        if EOAT_MOVES_FIELD in header_positions and _is_missing_eoat_moves(row_data.get(EOAT_MOVES_FIELD)):
            entry_type = _cell_text(row_data.get("Entry Type")).lower()
            source_id = _cell_text(row_data.get(SOURCE_AUDIT_ID_FIELD))
            source_missing = source_id and _is_missing_eoat_moves(source_eoat_moves_by_audit_id.get(source_id))
            if entry_type == "compatible" and source_missing:
                missing_eoat_moves_examples.append(f"row {row_number} Missing important audit field: {EOAT_MOVES_FIELD} inherited from source audit {source_id}")
            else:
                missing_eoat_moves_examples.append(f"row {row_number} Missing important audit field: {EOAT_MOVES_FIELD}")
        for warning in hybrid_completeness_warnings(row_data):
            hybrid_warning_examples.append(f"row {row_number}: {warning}")
        for warning in semantic_consistency_warnings(row_data):
            semantic_warning_examples.append(f"row {row_number}: {warning}")

    metrics["duplicate_audit_id_count"] = len(duplicate_ids)
    metrics["blank_saved_audit_cell_count"] = blank_cells
    major_na_list = sorted(major_na_examples)
    metrics["major_na_cell_count"] = len(major_na_list)
    metrics["missing_applicable_major_cell_count"] = len(major_na_list)
    metrics["non_applicable_na_cell_count"] = len(non_applicable_na_examples)
    metrics["stale_hidden_value_count"] = len(stale_hidden_value_examples)
    metrics["hybrid_warning_count"] = len(hybrid_warning_examples)
    metrics["semantic_warning_count"] = len(semantic_warning_examples)
    metrics["invalid_dropdown_value_count"] = len(invalid_dropdown_examples)
    metrics["invalid_numeric_value_count"] = len(invalid_numeric_examples)
    metrics["missing_eoat_moves_count"] = len(missing_eoat_moves_examples)

    if duplicate_ids:
        warnings.append(f"Duplicate Audit ID value(s): {', '.join(sorted(duplicate_ids))}")
    if major_na_list:
        warnings.append(f"{len(major_na_list)} applicable major EOAT Inventory cell(s) are blank or contain {NA_VALUE}: {', '.join(major_na_list[:10])}")
    if stale_hidden_value_examples:
        warnings.append(f"{len(stale_hidden_value_examples)} non-applicable EOAT Inventory cell(s) contain stale values: {', '.join(stale_hidden_value_examples[:10])}")
    if hybrid_warning_examples:
        warnings.append(f"{len(hybrid_warning_examples)} Hybrid EOAT completeness warning(s): {', '.join(hybrid_warning_examples[:5])}")
    if semantic_warning_examples:
        warnings.append(f"{len(semantic_warning_examples)} semantic EOAT warning(s): {', '.join(semantic_warning_examples[:5])}")
    if invalid_dropdown_examples:
        warnings.append(f"{len(invalid_dropdown_examples)} invalid EOAT Inventory dropdown value(s): {', '.join(invalid_dropdown_examples[:5])}")
    if invalid_numeric_examples:
        warnings.append(f"{len(invalid_numeric_examples)} invalid EOAT Inventory whole-number value(s): {', '.join(invalid_numeric_examples[:5])}")
    if missing_eoat_moves_examples:
        warnings.append(f"{len(missing_eoat_moves_examples)} EOAT Inventory row(s) are missing EOAT Moves: {', '.join(missing_eoat_moves_examples[:5])}")
    if blank_cells:
        warnings.append(
            f"{blank_cells} saved EOAT Inventory cell(s) are blank; new saves should write {NA_VALUE} "
            "for unanswered user-entered audit fields. Autofilled/system-managed compatibility metadata fields "
            "are intentionally ignored."
        )
    return warnings, metrics


def _is_audit_data_row(row_data: dict[str, object]) -> bool:
    values = [_cell_text(value) for value in row_data.values()]
    if not any(values):
        return False
    if len([value for value in values if value]) == 1 and values[-1].startswith("Last Updated:"):
        return False
    return True


def _cell_text(value: object) -> str:
    return str(value or "").strip()


def _is_missing_eoat_moves(value: object) -> bool:
    text = _cell_text(value)
    return not text or text.upper() == NA_VALUE


def _is_missing_audit_value(value: object) -> bool:
    text = _cell_text(value)
    return not text or is_na_value(text)


def _is_non_negative_whole_number(value: object) -> bool:
    text = _cell_text(value)
    if not text:
        return False
    try:
        parsed = int(text)
    except ValueError:
        return False
    return parsed >= 0 and str(parsed) == text


def write_validation_report(project_root: str | Path, result: ToolResult) -> Path:
    paths = resolve_project_paths(project_root)
    ensure_directory(paths.validation_reports)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    report_path = paths.validation_reports / f"Foundation_Validation_{stamp}.md"
    return safe_write_text(report_path, result.to_markdown(), overwrite=False)


def run_foundation_validation(
    project_root: str | Path,
    write_report: bool = True,
    log_activity: bool = True,
) -> ToolResult:
    result = validate_project_foundation(project_root)
    if write_report and Path(project_root).exists():
        try:
            report_path = write_validation_report(project_root, result)
            result.output_reports.append(str(report_path))
            result.files_created.append(str(report_path))
        except FileExistsError:
            # Minute-level names can collide during rapid tests; retry with seconds.
            paths = resolve_project_paths(project_root)
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            report_path = safe_write_text(
                paths.validation_reports / f"Foundation_Validation_{stamp}.md",
                result.to_markdown(),
                overwrite=False,
            )
            result.output_reports.append(str(report_path))
            result.files_created.append(str(report_path))
        except Exception as exc:
            result.warnings.append(f"Could not write validation report: {exc}")
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result
