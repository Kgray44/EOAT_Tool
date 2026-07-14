from __future__ import annotations

import time
import os
from pathlib import Path
from typing import Any

from core.audit.uninstalled import is_uninstalled_eoat_audit
from core.audit_constants import AIR_CIRCUIT_ARCHITECTURE_FIELD, air_architecture_hides_robot_fields
from core.audit_entries import AuditSaveOptions, save_audit_entry
from core.logging import log_activity_event
from core.performance import log_performance_event
from core.result import ToolResult
from core.robot_info import ROBOT_INFO_AUDIT_FIELDS, ROBOT_NOTES_FIELD, load_robot_info_for_audit_entry

ROBOT_PNEUMATIC_FIELDS = [
    "Robot Vacuum Circuits",
    "Robot Pressure Circuits",
    "Robot Interchangeable Circuits",
]
ROBOT_INFO_FIELDS = list(ROBOT_INFO_AUDIT_FIELDS)


def save_audit_with_side_effects(
    config: Any,
    entry: dict[str, str],
    *,
    allow_update: bool,
    create_followup_action: bool,
    sync_linked_compatibility: bool | None = None,
):
    if os.getenv("EOAT_ATLAS_DATA_BACKEND", "legacy").strip().casefold() == "mysql_api":
        return _save_audit_via_api(config, entry, allow_update=allow_update)
    started = time.perf_counter()
    compatibility_preview_seconds = 0.0
    if sync_linked_compatibility is None:
        sync_linked_compatibility = False
    if is_uninstalled_eoat_audit(entry):
        sync_linked_compatibility = False

    save_started = time.perf_counter()
    result = save_audit_entry(
        config.project_root,
        entry,
        allow_update=allow_update,
        create_followup_action=create_followup_action,
        options=AuditSaveOptions(
            fast_interactive=True,
            backup_policy="session_or_daily",
            schema_policy="fail_if_stale",
            sync_linked_compatibility=False,
            defer_robot_info=True,
            defer_history=True,
            refresh_press_view=False,
            emit_refresh_mode="invalidate_only",
        ),
    )
    master_seconds = time.perf_counter() - save_started
    result.metrics["audit_save.master_workflow_seconds"] = round(master_seconds, 3)
    result.metrics["audit_save.compatibility_preview_seconds"] = round(compatibility_preview_seconds, 3)

    robot_info_seconds = 0.0
    robot_info_status = "skipped"
    if result.success:
        should_queue_robot, robot_skip_reason = should_queue_robot_info_update(config.project_root, entry)
        robot_result = ToolResult.ok(
            "robot_info_save",
            "Robot Info",
            (
                "Robot_Info.xlsx update queued after the audit save."
                if should_queue_robot
                else f"Robot Info skipped: {robot_skip_reason}."
            ),
            details=[
                (
                    "Queued follow-up job: robot_info_update_from_audit."
                    if should_queue_robot
                    else f"Robot_Info.xlsx was not opened for write because {robot_skip_reason}."
                )
            ],
            metrics={
                "robot_info_skipped": not should_queue_robot,
                "robot_info_update_queued": should_queue_robot,
                "robot_info_skip_reason": robot_skip_reason,
                "robot_notes": str(entry.get(ROBOT_NOTES_FIELD) or "").strip(),
            },
            duration_seconds=0.0,
        )
        robot_info_status = "queued" if should_queue_robot else f"skipped ({robot_skip_reason})"

        result.summary = ensure_audit_save_summary(result.summary)
        result.summary = insert_compatibility_summary(result.summary, bool(sync_linked_compatibility))
        result.summary = insert_robot_info_summary(result.summary, robot_result)
        result.details.extend(robot_result.details)
        result.details.append(
            "Queued follow-up jobs: "
            + ", ".join(
                item
                for item in [
                    "robot_info_update_from_audit" if should_queue_robot else "",
                    "linked_compatibility_update" if sync_linked_compatibility else "",
                ]
                if item
            )
            if (should_queue_robot or sync_linked_compatibility)
            else "Queued follow-up jobs: none."
        )
        result.metrics["robot_info_save_success"] = robot_result.success
        result.metrics["robot_info_save_skipped"] = bool(robot_result.metrics.get("robot_info_skipped"))
        result.metrics["robot_info_update_queued"] = should_queue_robot
        result.metrics["deferred_robot_info_queued"] = should_queue_robot
        result.metrics["deferred_compatibility_queued"] = bool(sync_linked_compatibility)
        result.metrics["deferred_followup_jobs"] = [
            item
            for item in [
                "robot_info_update_from_audit" if should_queue_robot else "",
                "linked_compatibility_update" if sync_linked_compatibility else "",
            ]
            if item
        ]
        result.metrics["robot_info_save_seconds"] = round(robot_info_seconds, 3)
        if robot_result.success:
            result.warnings.extend(robot_result.warnings)
        else:
            result.warnings.append("Robot_Info.xlsx was not updated. The EOAT audit save still completed.")
            log_activity_event(
                config.project_root,
                "robot_info_save_failed",
                {
                    "audit_id": entry.get("Audit ID", ""),
                    "errors": robot_result.errors,
                    "warnings": robot_result.warnings,
                },
            )

        result.details.append("Annotation color sync: deferred; audit save did not change tag assignments.")
        result.metrics["annotation_color_sync_deferred"] = True
        result.metrics["annotation_color_sync_seconds"] = 0.0
        result.metrics["annotation_color_sync_targets"] = 0
        result.metrics["annotation_color_sync_synced"] = 0
    else:
        result.metrics["robot_info_save_skipped"] = True
        result.metrics["robot_info_save_seconds"] = 0.0
        result.metrics["annotation_color_sync_deferred"] = True
        result.metrics["annotation_color_sync_seconds"] = 0.0

    total_seconds = time.perf_counter() - started
    compatibility_seconds = result.metrics.get("audit_save.compatibility_seconds", 0.0)
    compatibility_status = (
        "queued after fast save"
        if sync_linked_compatibility
        else "skipped (normal fast save updates only the physical audit row)"
    )
    timing = {
        "audit_save": round(master_seconds, 3),
        "robot_info_save": round(robot_info_seconds, 3),
        "compatibility_autorun": 0.0,
        "annotation_color_sync": 0.0,
        "validate_form_seconds": result.metrics.get("audit_save.validate_form_seconds", 0.0),
        "backup_seconds": result.metrics.get("audit_save.backup_seconds", 0.0),
        "schema_check_seconds": result.metrics.get("audit_save.schema_check_seconds", 0.0),
        "schema_repair_seconds": result.metrics.get("audit_save.schema_repair_seconds", 0.0),
        "workbook_open_load_seconds": result.metrics.get("audit_save.workbook_open_load_seconds", 0.0),
        "sheet_header_mapping_seconds": result.metrics.get("audit_save.sheet_header_mapping_seconds", 0.0),
        "audit_row_lookup_seconds": result.metrics.get("audit_save.audit_row_lookup_seconds", 0.0),
        "row_write_update_seconds": result.metrics.get("audit_save.row_write_update_seconds", 0.0),
        "workbook_save_seconds": result.metrics.get("audit_save.workbook_save_seconds", 0.0),
        "write_master_seconds": result.metrics.get("audit_save.write_master_seconds", round(master_seconds, 3)),
        "compatibility_seconds": compatibility_seconds if sync_linked_compatibility else 0.0,
        "compatibility_status": compatibility_status,
        "robot_info_seconds": round(robot_info_seconds, 3),
        "robot_info_status": robot_info_status,
        "annotation_sync_seconds": 0.0,
        "annotation_sync_status": "deferred",
        "history_seconds": result.metrics.get("audit_save.history_seconds", 0.0),
        "event_dispatch_seconds": result.metrics.get("audit_save.event_dispatch_seconds", 0.0),
        "total_seconds": round(total_seconds, 3),
    }
    result.metrics["audit_save_timing"] = timing
    result.metrics["compatibility_autorun_skipped"] = True
    result.metrics["compatibility_autorun_seconds"] = 0.0
    result.duration_seconds = total_seconds
    result.details.extend(
        [
            "Audit save timing:",
            f"Validation: {timing['validate_form_seconds']}s",
            f"Backup: {timing['backup_seconds']}s",
            f"Schema check: {timing['schema_check_seconds']}s",
            f"Schema repair: {timing['schema_repair_seconds']}s",
            f"Workbook open/load: {timing['workbook_open_load_seconds']}s",
            f"Sheet/header mapping: {timing['sheet_header_mapping_seconds']}s",
            f"Audit row lookup: {timing['audit_row_lookup_seconds']}s",
            f"Row write/update: {timing['row_write_update_seconds']}s",
            f"Workbook save: {timing['workbook_save_seconds']}s",
            f"Master workbook: {timing['write_master_seconds']}s",
            f"Fit Check: {timing['compatibility_status']}",
            f"Robot Info: {timing['robot_info_status']}",
            "Annotation sync: deferred",
            f"History: {timing['history_seconds']}s",
            f"Events/UI: {timing['event_dispatch_seconds']}s",
            f"Total: {timing['total_seconds']}s",
        ]
    )
    log_performance_event(
        config.project_root,
        "audit_save.deferred_robot_info",
        0.0,
        source="audit_save",
        page_tool="audit",
        details={
            "queued": bool(result.metrics.get("deferred_robot_info_queued")),
            "audit_id": entry.get("Audit ID", ""),
        },
        success=result.success,
    )
    log_performance_event(
        config.project_root,
        "audit_save.deferred_compatibility",
        0.0,
        source="audit_save",
        page_tool="audit",
        details={
            "queued": bool(result.metrics.get("deferred_compatibility_queued")),
            "audit_id": entry.get("Audit ID", ""),
        },
        success=result.success,
    )
    log_activity_event(config.project_root, "audit_save_timing", timing)
    log_performance_event(
        config.project_root,
        "audit_save.total",
        total_seconds,
        source="audit_save",
        page_tool="audit",
        details=timing,
        warning_count=len(result.warnings),
        error_count=len(result.errors),
        success=result.success,
    )
    return result


def _save_audit_via_api(config: Any, entry: dict[str, str], *, allow_update: bool) -> ToolResult:
    """Persist a development audit server-first without touching Excel or legacy queues."""
    from core.data_gateway.exceptions import DataGatewayError
    from core.data_gateway.gateway import AtlasDataGateway

    started = time.perf_counter()
    audit_identifier = str(entry.get("Audit ID") or "").strip()
    if not audit_identifier:
        return ToolResult.fail("audit_save", "Audit Save", "Audit ID is required.", errors=["Audit ID is required."])
    gateway = AtlasDataGateway()
    try:
        try:
            existing = gateway.client._request("GET", f"/api/v1/audits/by-identifier/{audit_identifier}")
        except DataGatewayError:
            existing = None
        if existing:
            if not allow_update:
                return ToolResult.fail(
                    "audit_save",
                    "Audit Save",
                    f"Audit {audit_identifier} already exists.",
                    errors=["Enable update mode to revise the authoritative audit."],
                )
            authoritative = gateway.update_audit(
                existing["id"],
                {"details": dict(entry), "notes": str(entry.get("Notes") or "") or None},
                existing["row_version"],
            )
            action = "updated"
        else:
            request: dict[str, Any] = {
                "audit_identifier": audit_identifier,
                "details": dict(entry),
                "notes": str(entry.get("Notes") or "") or None,
            }
            candidates = (
                ("eoat_identifier", str(entry.get("EOAT Assembly ID") or "").strip(), gateway.client.get_eoat),
                ("machine_number", str(entry.get("Press/Machine #") or "").strip(), gateway.client.get_machine),
                ("tool_identifier", str(entry.get("Tool #") or "").strip(), gateway.client.get_tool),
            )
            for field_name, identifier, lookup in candidates:
                if not identifier:
                    continue
                try:
                    lookup(identifier)
                except DataGatewayError:
                    continue
                request[field_name] = identifier
            authoritative = gateway.create_audit(request)
            action = "created"
        duration = time.perf_counter() - started
        return ToolResult.ok(
            "audit_save",
            "Audit Save",
            f"Audit {audit_identifier} {action} in authoritative MySQL.",
            details=[
                "Server commit completed before local cache refresh.",
                "Excel, Robot_Info.xlsx, legacy annotation SQLite, and legacy write queues were not modified.",
            ],
            metrics={
                "backend": "mysql_api",
                "server_first": True,
                "row_version": authoritative.get("row_version"),
                "cache_refresh_required": bool(authoritative.get("cache_refresh_required")),
            },
            structured_data=authoritative,
            duration_seconds=duration,
        )
    except Exception as exc:
        return ToolResult.fail(
            "audit_save",
            "Audit Save",
            "The server did not confirm the audit save.",
            errors=[str(exc)],
            metrics={"backend": "mysql_api", "server_first": True},
            duration_seconds=time.perf_counter() - started,
        )
    finally:
        gateway.close()


def should_update_robot_info(project_root: str | Path, entry: dict[str, Any]) -> tuple[bool, str]:
    if air_architecture_hides_robot_fields(entry.get(AIR_CIRCUIT_ARCHITECTURE_FIELD)):
        return False, "air architecture is External Peripheral Only"
    machine_number = str(entry.get("Press/Machine #") or "").strip()
    if not machine_number:
        return False, "machine number is blank"
    submitted_fields = [field for field in ROBOT_INFO_FIELDS if field in entry]
    if not submitted_fields:
        return False, "no robot info fields were submitted"
    if not any(_robot_info_value_is_meaningful(field, entry.get(field)) for field in submitted_fields):
        try:
            existing = load_robot_info_for_audit_entry(project_root, entry)
        except Exception:
            existing = None
        if not existing or not any(str(existing.get(field) or "").strip() for field in submitted_fields):
            return False, "no robot info values were entered beyond defaults"
    else:
        existing = None
    try:
        existing = existing if existing is not None else load_robot_info_for_audit_entry(project_root, entry)
    except Exception:
        return True, "existing Robot_Info.xlsx values could not be checked"
    if existing is None:
        return True, "robot info values were entered"
    for field in submitted_fields:
        desired = _robot_info_compare_value(field, entry.get(field))
        current = _robot_info_compare_value(field, existing.get(field))
        if desired != current:
            return True, "robot info values changed"
    return False, "robot info values are unchanged"


def should_queue_robot_info_update(project_root: str | Path, entry: dict[str, Any]) -> tuple[bool, str]:
    should_update, reason = should_update_robot_info(project_root, entry)
    if should_update:
        return True, "robot info values will be reconciled in the background"
    return False, reason


def insert_compatibility_summary(summary: str, sync_linked_compatibility: bool) -> str:
    if "Fit Check Entry Summary" in summary:
        return summary
    status = (
        "Linked Fit Check rows update queued after the fast audit save."
        if sync_linked_compatibility
        else "Normal audit save updated only the physical audit row. Use the Fit Check Entry tab or explicit linked-row action when compatible rows need review."
    )
    return summary.rstrip() + "\n\nFit Check Entry Summary\n-----------------------\n" + status


def ensure_audit_save_summary(summary: str) -> str:
    if "Audit Save Summary" in summary:
        return summary
    return "Audit Save Summary\n------------------\n" + summary.strip()


def insert_robot_info_summary(summary: str, robot_result) -> str:
    robot_lines = [
        "Robot Info Summary",
        "------------------",
        robot_result.summary
        if robot_result.success
        else "Robot_Info.xlsx was not updated. The EOAT audit save still completed.",
    ]
    if robot_result.success:
        for field in ROBOT_INFO_FIELDS:
            value = robot_result.metrics.get(field.lower().replace(" ", "_"))
            if value not in (None, ""):
                robot_lines.append(f"{field}: {value}")
    elif robot_result.warnings:
        robot_lines.append("; ".join(robot_result.warnings))

    compatibility_header = "Fit Check Entry Summary"
    if compatibility_header in summary:
        before, after = summary.split(compatibility_header, 1)
        return before.rstrip() + "\n\n" + "\n".join(robot_lines) + "\n\n" + compatibility_header + after
    return summary.rstrip() + "\n\n" + "\n".join(robot_lines)


def _robot_circuit_value_is_meaningful(field: str, value: Any) -> bool:
    text = str(value or "").strip()
    if not text or text.upper() in {"N/A", "NA", "NOT APPLICABLE"}:
        return False
    if field == "Robot Interchangeable Circuits":
        return _robot_circuit_compare_value(field, value) not in {"", 0}
    return True


def _robot_circuit_compare_value(field: str, value: Any) -> int | str:
    text = str(value or "").strip()
    if text.upper() in {"N/A", "NA", "NOT APPLICABLE"}:
        return ""
    if not text and field != "Robot Interchangeable Circuits":
        return ""
    if not text:
        return 0
    numeric_text = text[:-2] if text.endswith(".0") else text
    try:
        return int(numeric_text)
    except ValueError:
        return text


def _robot_info_value_is_meaningful(field: str, value: Any) -> bool:
    if field == ROBOT_NOTES_FIELD:
        return bool(str(value or "").strip())
    return _robot_circuit_value_is_meaningful(field, value)


def _robot_info_compare_value(field: str, value: Any) -> int | str:
    if field == ROBOT_NOTES_FIELD:
        return str(value or "").strip()
    return _robot_circuit_compare_value(field, value)
