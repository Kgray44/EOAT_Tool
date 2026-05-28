from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from .compatibility_health import validate_compatibility_health
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
from .gripper_fields import CUP_COUNT_FIELD, GRIPPER_COUNT_FIELD, GRIPPER_TYPE_FIELD, GRIPPER_TYPE_VALUES
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
    CYLINDER_COUNT_FIELD,
    CYLINDER_TYPE_FIELD,
    CYLINDER_TYPE_VALUES,
    ENTRY_TYPE_COMPATIBLE,
    ENTRY_TYPE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_FIELDS,
    SOURCE_AUDIT_ID_FIELD,
)
from .git_activity import is_git_repo
from .logging import log_tool_run
from .paths import resolve_project_paths
from .photo_evidence import validate_photo_evidence
from .result import ToolResult
from .robot_info import validate_robot_info_workbook
from .safe_files import ensure_directory, safe_write_text
from .schedule import available_schedule_weeks
from .validation_findings import (
    ValidationFinding,
    ValidationSeverity,
    attach_findings,
    make_finding,
    write_validation_json_report,
)
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
    CYLINDER_TYPE_FIELD: {*CYLINDER_TYPE_VALUES, NA_VALUE},
    GRIPPER_TYPE_FIELD: {*GRIPPER_TYPE_VALUES, NA_VALUE},
    "Cleanroom/Non-Cleanroom": {*CLEANROOM_DROPDOWN_VALUES, NA_VALUE},
    MANUAL_COMPLETION_OVERRIDE_FIELD: {"Yes", "No", NA_VALUE},
}
AUDIT_NUMERIC_FIELDS = {NUMBER_OF_PARTS_PICKED_FIELD, CYLINDER_COUNT_FIELD, CUP_COUNT_FIELD, GRIPPER_COUNT_FIELD}

BLANK_CELL_VALIDATION_IGNORED_FIELDS = AUTOFILLED_COMPATIBILITY_METADATA_FIELDS | frozenset(MANUAL_COMPLETION_OVERRIDE_FIELDS)
BLANK_CELL_VALIDATION_IGNORED_FIELD_LABEL = "Source Audit ID, Compatibility Source, and manual completion override metadata"


def validate_project_foundation(project_root: str | Path) -> ToolResult:
    started = time.perf_counter()
    paths = resolve_project_paths(project_root)
    details: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []
    metrics: dict[str, object] = {}
    findings: list[ValidationFinding] = []

    if not paths.project_root.exists():
        findings.append(
            make_finding(
                ValidationSeverity.BLOCKER,
                "project_foundation",
                f"Missing project root: {paths.project_root}",
                expected_behavior="The selected project root should exist before validation runs.",
                recommended_action="Select an existing EOAT project root in Settings.",
                source_validator="foundation",
            )
        )
        return attach_findings(ToolResult.fail(
            "workbook_validator",
            "EOAT Project Foundation Validation",
            "Project root does not exist.",
            errors=[f"Missing project root: {paths.project_root}"],
            duration_seconds=time.perf_counter() - started,
        ), findings)

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
        message = f"Missing master workbook: {workbook_path}"
        errors.append(message)
        findings.append(
            make_finding(
                ValidationSeverity.BLOCKER,
                "workbook_schema",
                message,
                expected_behavior="The master tracker workbook should exist at the project workbook path.",
                recommended_action="Restore the workbook from backup or select the correct project root.",
                source_validator="foundation",
            )
        )
        return attach_findings(ToolResult.fail(
            "workbook_validator",
            "EOAT Project Foundation Validation",
            "Master workbook is missing.",
            details=details,
            warnings=warnings,
            errors=errors,
            metrics=metrics,
            duration_seconds=time.perf_counter() - started,
        ), findings)

    details.append(f"Found master workbook: {workbook_path}")
    try:
        workbook = load_workbook(workbook_path, read_only=True, data_only=False)
    except Exception as exc:
        message = f"Could not open workbook with openpyxl: {exc}"
        errors.append(message)
        findings.append(
            make_finding(
                ValidationSeverity.BLOCKER,
                "workbook_lock",
                message,
                expected_behavior="Validation needs read access to the master workbook.",
                recommended_action="Close the workbook in Excel or check file permissions, then retry validation.",
                source_validator="foundation",
            )
        )
        return attach_findings(ToolResult.fail(
            "workbook_validator",
            "EOAT Project Foundation Validation",
            "Master workbook exists but could not be opened.",
            details=details,
            warnings=warnings,
            errors=errors,
            metrics=metrics,
            duration_seconds=time.perf_counter() - started,
        ), findings)

    expected_sheets = get_expected_sheets()
    missing_sheets = [sheet for sheet in expected_sheets if sheet not in workbook.sheetnames]
    metrics["expected_sheet_count"] = len(expected_sheets)
    metrics["actual_sheet_count"] = len(workbook.sheetnames)
    if missing_sheets:
        for sheet in missing_sheets:
            message = f"Missing expected sheet: {sheet}"
            errors.append(message)
            findings.append(
                make_finding(
                    ValidationSeverity.ERROR,
                    "workbook_schema",
                    message,
                    sheet_name=sheet,
                    expected_behavior="All expected workbook sheets should be present.",
                    recommended_action="Restore the missing sheet from the template or a trusted backup.",
                    source_validator="foundation",
                )
            )
    else:
        details.append("All expected workbook sheets are present.")
    if AUDIT_BY_PRESS_SHEET not in workbook.sheetnames:
        message = "Audit by Press view missing or stale; refresh generated view."
        warnings.append(message)
        findings.append(
            make_finding(
                ValidationSeverity.AUTO_FIXABLE,
                "generated_view",
                message,
                sheet_name=AUDIT_BY_PRESS_SHEET,
                expected_behavior="Generated Audit by Press view should be present and carry a refresh timestamp.",
                recommended_action="Preview and apply the Refresh Generated Views safe fix.",
                fix_available=True,
                fix_id="refresh_generated_views",
                source_validator="foundation",
            )
        )
    elif audit_by_press_last_refreshed(workbook) is None:
        message = "Audit by Press view missing or stale; refresh generated view."
        warnings.append(message)
        findings.append(
            make_finding(
                ValidationSeverity.AUTO_FIXABLE,
                "generated_view",
                message,
                sheet_name=AUDIT_BY_PRESS_SHEET,
                expected_behavior="Generated Audit by Press view should carry a refresh timestamp.",
                recommended_action="Preview and apply the Refresh Generated Views safe fix.",
                fix_available=True,
                fix_id="refresh_generated_views",
                source_validator="foundation",
            )
        )
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
            for header in missing_major_headers:
                message = f"Missing major EOAT Inventory header: {header}"
                errors.append(message)
                findings.append(
                    make_finding(
                        ValidationSeverity.ERROR,
                        "workbook_schema",
                        message,
                        sheet_name="EOAT Inventory",
                        row_number=1,
                        column_name=header,
                        expected_behavior="Major EOAT Inventory headers must be present for audit save/load workflows.",
                        recommended_action="Preview and apply the Repair Legacy Headers safe fix or restore the header from the workbook template.",
                        fix_available=True,
                        fix_id="repair_legacy_headers",
                        source_validator="foundation",
                    )
                )
        elif missing_key_headers:
            for header in missing_key_headers:
                message = f"Missing key EOAT Inventory header: {header}"
                warnings.append(message)
                findings.append(
                    make_finding(
                        ValidationSeverity.AUTO_FIXABLE,
                        "workbook_schema",
                        message,
                        sheet_name="EOAT Inventory",
                        row_number=1,
                        column_name=header,
                        expected_behavior="Key EOAT Inventory headers should be present.",
                        recommended_action="Preview and apply the Repair Legacy Headers safe fix.",
                        fix_available=True,
                        fix_id="repair_legacy_headers",
                        source_validator="foundation",
                    )
                )
        else:
            details.append("Key EOAT Inventory headers are present.")
        if missing_detail_headers:
            for header in missing_detail_headers:
                message = f"Missing detail EOAT Inventory header: {header}"
                warnings.append(message)
                findings.append(
                    make_finding(
                        ValidationSeverity.AUTO_FIXABLE,
                        "workbook_schema",
                        message,
                        sheet_name="EOAT Inventory",
                        row_number=1,
                        column_name=header,
                        expected_behavior="Detail EOAT Inventory headers should match the current workbook schema.",
                        recommended_action="Preview and apply the Repair Legacy Headers safe fix.",
                        fix_available=True,
                        fix_id="repair_legacy_headers",
                        source_validator="foundation",
                    )
                )
        if ELECTRICAL_WIRING_PRESENT_FIELD in schema_upgrade_headers:
            message = "Workbook is missing Electrical/Wiring Present?. Run Repair Workbook Schema to upgrade old workbooks."
            warnings.append(message)
            findings.append(
                make_finding(
                    ValidationSeverity.AUTO_FIXABLE,
                    "workbook_schema",
                    message,
                    sheet_name="EOAT Inventory",
                    row_number=1,
                    column_name=ELECTRICAL_WIRING_PRESENT_FIELD,
                    expected_behavior="Current workbooks include Electrical/Wiring Present? to control electrical field applicability.",
                    recommended_action="Preview and apply the Repair Legacy Headers safe fix.",
                    fix_available=True,
                    fix_id="repair_legacy_headers",
                    source_validator="foundation",
                )
            )
        if legacy_vacuum_header_present and has_parts_picked_header:
            message = (
                "EOAT Inventory has both Number of Vacuum Cups and Number of Parts Picked. "
                "Run Repair Workbook Schema to merge values into Number of Parts Picked and remove the legacy header."
            )
            warnings.append(message)
            findings.append(
                make_finding(
                    ValidationSeverity.AUTO_FIXABLE,
                    "workbook_schema",
                    message,
                    sheet_name="EOAT Inventory",
                    row_number=1,
                    column_name=LEGACY_VACUUM_CUPS_FIELD,
                    expected_behavior="Legacy vacuum-cup header should be migrated to Number of Parts Picked.",
                    recommended_action="Preview and apply the Repair Legacy Headers safe fix.",
                    fix_available=True,
                    fix_id="repair_legacy_headers",
                    source_validator="foundation",
                )
            )
        elif legacy_vacuum_header_present:
            message = (
                "EOAT Inventory still uses legacy header Number of Vacuum Cups. "
                "Run Repair Workbook Schema to rename it to Number of Parts Picked."
            )
            warnings.append(message)
            findings.append(
                make_finding(
                    ValidationSeverity.AUTO_FIXABLE,
                    "workbook_schema",
                    message,
                    sheet_name="EOAT Inventory",
                    row_number=1,
                    column_name=LEGACY_VACUUM_CUPS_FIELD,
                    expected_behavior="Legacy vacuum-cup header should be renamed to Number of Parts Picked.",
                    recommended_action="Preview and apply the Repair Legacy Headers safe fix.",
                    fix_available=True,
                    fix_id="repair_legacy_headers",
                    source_validator="foundation",
                )
            )
        if unexpected_headers:
            for header in unexpected_headers:
                message = f"Unexpected EOAT Inventory header: {header}"
                warnings.append(message)
                findings.append(
                    make_finding(
                        ValidationSeverity.WARNING,
                        "workbook_schema",
                        message,
                        sheet_name="EOAT Inventory",
                        row_number=1,
                        column_name=header,
                        expected_behavior="Workbook headers should match the expected local schema.",
                        recommended_action="Review whether this is a local-only note column or an accidental workbook edit.",
                        source_validator="foundation",
                    )
                )
        if duplicate_headers:
            for header in duplicate_headers:
                message = f"Duplicate EOAT Inventory header: {header}"
                warnings.append(message)
                findings.append(
                    make_finding(
                        ValidationSeverity.ERROR,
                        "workbook_schema",
                        message,
                        sheet_name="EOAT Inventory",
                        row_number=1,
                        column_name=header,
                        expected_behavior="Each EOAT Inventory header should appear once.",
                        recommended_action="Review the duplicate header manually before saving more audit rows.",
                        source_validator="foundation",
                    )
                )
        if any(header in headers for header in BLANK_CELL_VALIDATION_IGNORED_FIELDS):
            details.append(
                f"Blank {BLANK_CELL_VALIDATION_IGNORED_FIELD_LABEL} cells are intentionally ignored during "
                "blank-cell validation because they are autofilled or system-managed metadata; "
                "the columns still remain part of the workbook schema."
            )
        inventory_warnings, inventory_metrics, inventory_findings = _validate_inventory_rows(ws, headers)
        warnings.extend(inventory_warnings)
        metrics.update(inventory_metrics)
        findings.extend(inventory_findings)
    else:
        message = "EOAT Inventory sheet is missing, so headers could not be checked."
        errors.append(message)
        findings.append(
            make_finding(
                ValidationSeverity.ERROR,
                "workbook_schema",
                message,
                sheet_name="EOAT Inventory",
                expected_behavior="EOAT Inventory sheet must exist for audit save/load workflows.",
                recommended_action="Restore EOAT Inventory from the template or a trusted backup.",
                source_validator="foundation",
            )
        )

    workbook.close()
    compatibility_findings = validate_compatibility_health(workbook_path)
    findings.extend(compatibility_findings)
    metrics["compatibility_health_finding_count"] = len(compatibility_findings)

    evidence_warnings, evidence_metrics, evidence_findings = validate_photo_evidence(paths.project_root)
    warnings.extend(evidence_warnings)
    metrics.update(evidence_metrics)
    findings.extend(evidence_findings)
    if evidence_metrics.get("photo_evidence_audit_count", 0):
        details.append("Photo evidence coverage checked.")

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
    return attach_findings(ToolResult(
        tool_id="workbook_validator",
        tool_name="EOAT Project Foundation Validation",
        success=not errors,
        summary=summary,
        details=details,
        warnings=warnings,
        errors=errors,
        metrics=metrics,
        duration_seconds=time.perf_counter() - started,
    ), findings)


def _validate_inventory_rows(ws, headers: list[str]) -> tuple[list[str], dict[str, int], list[ValidationFinding]]:
    warnings: list[str] = []
    findings: list[ValidationFinding] = []
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
        return warnings, metrics, findings

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
    major_na_seen: set[tuple[int, str]] = set()

    def add_major_na(row_number: int, field_name: str, row_data: dict[str, object]) -> None:
        if (row_number, field_name) in major_na_seen:
            return
        major_na_seen.add((row_number, field_name))
        major_na_examples.add(f"row {row_number} {field_name}")
        findings.append(
            make_finding(
                ValidationSeverity.WARNING,
                "audit_data",
                f"Applicable major EOAT Inventory cell is blank or contains {NA_VALUE}: row {row_number} {field_name}",
                sheet_name="EOAT Inventory",
                row_number=row_number,
                column_name=field_name,
                audit_id=_cell_text(row_data.get("Audit ID")),
                machine_number=_cell_text(row_data.get("Press/Machine #")),
                current_value=row_data.get(field_name),
                expected_behavior="Applicable major audit fields should contain a verified value or Unknown / Not Checked when appropriate.",
                recommended_action="Open the audit row and complete the field; do not treat N/A as complete when the field applies.",
                source_validator="inventory_rows",
            )
        )

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
                findings.append(
                    make_finding(
                        ValidationSeverity.ERROR,
                        "audit_data",
                        f"Duplicate Audit ID value: {audit_id}",
                        sheet_name="EOAT Inventory",
                        row_number=row_number,
                        column_name="Audit ID",
                        audit_id=audit_id,
                        machine_number=_cell_text(row_data.get("Press/Machine #")),
                        current_value=audit_id,
                        expected_behavior="Audit IDs must be unique across EOAT Inventory rows.",
                        recommended_action=f"Compare this row with row {audit_ids[audit_id]} and assign a unique Audit ID before saving updates.",
                        source_validator="inventory_rows",
                    )
                )
            else:
                audit_ids[audit_id] = row_number
        elif "Audit ID" in headers:
            add_major_na(row_number, "Audit ID", row_data)

        requirements = entry_type_requirements(row_data)
        for required_field in requirements["required"]:
            if required_field in BLANK_CELL_VALIDATION_IGNORED_FIELDS:
                continue
            if required_field in header_positions and field_applies(row_data, required_field) and _is_missing_audit_value(row_data.get(required_field)):
                add_major_na(row_number, required_field, row_data)

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
                and (header != CUP_COUNT_FIELD or header in requirements["important"])
                and _is_missing_audit_value(value)
                and applies
            ):
                add_major_na(row_number, header, row_data)
            if not applies and is_na_value(value):
                non_applicable_na_examples.append(f"row {row_number} {header}")
            if not applies and is_meaningful_value(value):
                stale_hidden_value_examples.append(f"row {row_number} {header}")
                findings.append(
                    make_finding(
                        ValidationSeverity.AUTO_FIXABLE,
                        "audit_data",
                        f"Non-applicable EOAT Inventory cell contains a stale value: row {row_number} {header}",
                        sheet_name="EOAT Inventory",
                        row_number=row_number,
                        column_name=header,
                        audit_id=audit_id,
                        machine_number=_cell_text(row_data.get("Press/Machine #")),
                        current_value=value,
                        expected_behavior=f"Non-applicable fields should be saved as {NA_VALUE}.",
                        recommended_action="Preview and apply the Clear Stale Hidden Values safe fix.",
                        fix_available=True,
                        fix_id="clear_stale_hidden_na",
                        source_validator="inventory_rows",
                    )
                )
            if (
                header in AUDIT_DROPDOWN_ALLOWED_VALUES
                and _cell_text(value)
                and (header == EOAT_MOVES_FIELD or not is_na_value(value))
                and _cell_text(value) not in AUDIT_DROPDOWN_ALLOWED_VALUES[header]
            ):
                invalid_dropdown_examples.append(f"row {row_number} {header}={_cell_text(value)}")
                findings.append(
                    make_finding(
                        ValidationSeverity.WARNING,
                        "audit_data",
                        f"Invalid EOAT Inventory dropdown value: row {row_number} {header}={_cell_text(value)}",
                        sheet_name="EOAT Inventory",
                        row_number=row_number,
                        column_name=header,
                        audit_id=audit_id,
                        machine_number=_cell_text(row_data.get("Press/Machine #")),
                        current_value=value,
                        expected_behavior=f"Value should be one of: {', '.join(sorted(AUDIT_DROPDOWN_ALLOWED_VALUES[header]))}.",
                        recommended_action="Open the audit field and choose a valid dropdown value; rebuild dropdown validation if Excel validation is missing.",
                        source_validator="inventory_rows",
                    )
                )
            if (
                header in AUDIT_NUMERIC_FIELDS
                and applies
                and _cell_text(value)
                and not is_na_value(value)
                and not _is_non_negative_whole_number(value)
            ):
                invalid_numeric_examples.append(f"row {row_number} {header}={_cell_text(value)}")
                findings.append(
                    make_finding(
                        ValidationSeverity.ERROR,
                        "audit_data",
                        f"Invalid EOAT Inventory whole-number value: row {row_number} {header}={_cell_text(value)}",
                        sheet_name="EOAT Inventory",
                        row_number=row_number,
                        column_name=header,
                        audit_id=audit_id,
                        machine_number=_cell_text(row_data.get("Press/Machine #")),
                        current_value=value,
                        expected_behavior="Applicable count fields must be non-negative whole numbers.",
                        recommended_action="Open the audit field and correct the count; do not guess the engineering value.",
                        source_validator="inventory_rows",
                    )
                )
        if EOAT_MOVES_FIELD in header_positions and _is_missing_eoat_moves(row_data.get(EOAT_MOVES_FIELD)):
            entry_type = _cell_text(row_data.get("Entry Type")).lower()
            source_id = _cell_text(row_data.get(SOURCE_AUDIT_ID_FIELD))
            source_missing = source_id and _is_missing_eoat_moves(source_eoat_moves_by_audit_id.get(source_id))
            if entry_type == "compatible" and source_missing:
                message = f"row {row_number} Missing important audit field: {EOAT_MOVES_FIELD} inherited from source audit {source_id}"
                missing_eoat_moves_examples.append(message)
            else:
                message = f"row {row_number} Missing important audit field: {EOAT_MOVES_FIELD}"
                missing_eoat_moves_examples.append(message)
            findings.append(
                make_finding(
                    ValidationSeverity.WARNING,
                    "audit_data",
                    message,
                    sheet_name="EOAT Inventory",
                    row_number=row_number,
                    column_name=EOAT_MOVES_FIELD,
                    audit_id=audit_id,
                    machine_number=_cell_text(row_data.get("Press/Machine #")),
                    current_value=row_data.get(EOAT_MOVES_FIELD),
                    expected_behavior="EOAT Moves should be known for source audits and inherited compatibility rows.",
                    recommended_action="Open the audit row and verify whether the EOAT moves parts, sprues, or both.",
                    source_validator="inventory_rows",
                )
            )
        for warning in hybrid_completeness_warnings(row_data):
            hybrid_warning_examples.append(f"row {row_number}: {warning}")
            findings.append(
                make_finding(
                    ValidationSeverity.WARNING,
                    "audit_data",
                    f"row {row_number}: {warning}",
                    sheet_name="EOAT Inventory",
                    row_number=row_number,
                    audit_id=audit_id,
                    machine_number=_cell_text(row_data.get("Press/Machine #")),
                    expected_behavior="Hybrid audits should capture both vacuum-side and gripper/mechanical-side details.",
                    recommended_action="Open the audit row and complete the missing hybrid section.",
                    source_validator="inventory_rows",
                )
            )
        for warning in semantic_consistency_warnings(row_data):
            semantic_warning_examples.append(f"row {row_number}: {warning}")
            findings.append(
                make_finding(
                    ValidationSeverity.WARNING,
                    "audit_data",
                    f"row {row_number}: {warning}",
                    sheet_name="EOAT Inventory",
                    row_number=row_number,
                    audit_id=audit_id,
                    machine_number=_cell_text(row_data.get("Press/Machine #")),
                    expected_behavior="Audit field values should be internally consistent with field applicability rules.",
                    recommended_action="Open the audit row and resolve the conflicting field values.",
                    source_validator="inventory_rows",
                )
            )

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
    return warnings, metrics, findings


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
            json_report_path = write_validation_json_report(project_root, result)
            result.output_reports.append(str(json_report_path))
            result.files_created.append(str(json_report_path))
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
            json_report_path = write_validation_json_report(project_root, result)
            result.output_reports.append(str(json_report_path))
            result.files_created.append(str(json_report_path))
        except Exception as exc:
            result.warnings.append(f"Could not write validation report: {exc}")
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result
