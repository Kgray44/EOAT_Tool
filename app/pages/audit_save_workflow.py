from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from core.audit_entries import AuditSaveOptions, save_audit_entry
from core.logging import log_activity_event
from core.performance import log_performance_event
from core.result import ToolResult
from core.robot_info import load_robot_info_for_audit_entry

ROBOT_PNEUMATIC_FIELDS = [
    "Robot Vacuum Circuits",
    "Robot Pressure Circuits",
    "Robot Interchangeable Circuits",
]


def save_audit_with_side_effects(
    config: Any,
    entry: dict[str, str],
    *,
    allow_update: bool,
    create_followup_action: bool,
    sync_linked_compatibility: bool | None = None,
):
    started = time.perf_counter()
    compatibility_preview_seconds = 0.0
    if sync_linked_compatibility is None:
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
        should_queue_robot, robot_skip_reason = should_queue_robot_info_update(entry)
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
                {"audit_id": entry.get("Audit ID", ""), "errors": robot_result.errors, "warnings": robot_result.warnings},
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
            f"Compatibility: {timing['compatibility_status']}",
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
        details={"queued": bool(result.metrics.get("deferred_robot_info_queued")), "audit_id": entry.get("Audit ID", "")},
        success=result.success,
    )
    log_performance_event(
        config.project_root,
        "audit_save.deferred_compatibility",
        0.0,
        source="audit_save",
        page_tool="audit",
        details={"queued": bool(result.metrics.get("deferred_compatibility_queued")), "audit_id": entry.get("Audit ID", "")},
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


def should_update_robot_info(project_root: str | Path, entry: dict[str, Any]) -> tuple[bool, str]:
    machine_number = str(entry.get("Press/Machine #") or "").strip()
    if not machine_number:
        return False, "machine number is blank"
    if not any(_robot_circuit_value_is_meaningful(field, entry.get(field)) for field in ROBOT_PNEUMATIC_FIELDS):
        return False, "no robot circuit values were entered beyond defaults"
    try:
        existing = load_robot_info_for_audit_entry(project_root, entry)
    except Exception:
        return True, "existing Robot_Info.xlsx values could not be checked"
    if existing is None:
        return True, "robot circuit values were entered"
    for field in ROBOT_PNEUMATIC_FIELDS:
        desired = _robot_circuit_compare_value(field, entry.get(field))
        current = _robot_circuit_compare_value(field, existing.get(field))
        if desired != current:
            return True, "robot circuit values changed"
    return False, "robot circuit values are unchanged"


def should_queue_robot_info_update(entry: dict[str, Any]) -> tuple[bool, str]:
    machine_number = str(entry.get("Press/Machine #") or "").strip()
    if not machine_number:
        return False, "machine number is blank"
    if not any(_robot_circuit_value_is_meaningful(field, entry.get(field)) for field in ROBOT_PNEUMATIC_FIELDS):
        return False, "no robot circuit values were entered beyond defaults"
    return True, "robot circuit values will be reconciled in the background"


def insert_compatibility_summary(summary: str, sync_linked_compatibility: bool) -> str:
    if "Compatibility Entry Summary" in summary:
        return summary
    status = (
        "Linked compatibility rows update queued after the fast audit save."
        if sync_linked_compatibility
        else "Normal audit save updated only the physical audit row. Use the Compatibility Entry tab or explicit linked-row action when compatible rows need review."
    )
    return summary.rstrip() + "\n\nCompatibility Entry Summary\n---------------------------\n" + status


def ensure_audit_save_summary(summary: str) -> str:
    if "Audit Save Summary" in summary:
        return summary
    return "Audit Save Summary\n------------------\n" + summary.strip()


def insert_robot_info_summary(summary: str, robot_result) -> str:
    robot_lines = [
        "Robot Info Summary",
        "------------------",
        robot_result.summary if robot_result.success else "Robot_Info.xlsx was not updated. The EOAT audit save still completed.",
    ]
    if robot_result.success:
        for field in ROBOT_PNEUMATIC_FIELDS:
            value = robot_result.metrics.get(field.lower().replace(" ", "_"))
            if value is not None:
                robot_lines.append(f"{field}: {value}")
    elif robot_result.warnings:
        robot_lines.append("; ".join(robot_result.warnings))

    compatibility_header = "Compatibility Entry Summary"
    if compatibility_header in summary:
        before, after = summary.split(compatibility_header, 1)
        return before.rstrip() + "\n\n" + "\n".join(robot_lines) + "\n\n" + compatibility_header + after
    return summary.rstrip() + "\n\n" + "\n".join(robot_lines)


def _robot_circuit_value_is_meaningful(field: str, value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if field == "Robot Interchangeable Circuits":
        return _robot_circuit_compare_value(field, value) not in {"", 0}
    return True


def _robot_circuit_compare_value(field: str, value: Any) -> int | str:
    text = str(value or "").strip()
    if not text and field != "Robot Interchangeable Circuits":
        return ""
    if not text:
        return 0
    numeric_text = text[:-2] if text.endswith(".0") else text
    try:
        return int(numeric_text)
    except ValueError:
        return text
