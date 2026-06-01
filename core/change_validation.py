from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .analysis_common import timestamp_for_report
from .audit_entries import repair_legacy_audit_lookup_shift
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory, safe_write_text
from .workbook_io import row_dicts

TOOL_ID = "eoat_change_validation"
TOOL_NAME = "EOAT Change Validation"

CHANGE_VALIDATION_ITEMS: tuple[tuple[str, str], ...] = (
    ("eoat_mounted_securely", "EOAT mounted securely"),
    ("vacuum_gripper_function_verified", "Vacuum/gripper function verified"),
    ("sensor_operation_verified", "Sensor operation verified"),
    ("quick_disconnects_verified", "Quick disconnects verified"),
    ("tubing_cable_routing_verified", "Tubing/cable routing verified"),
    ("dry_cycle_completed", "Dry cycle completed"),
    ("first_part_pickup_checked", "First-part pickup checked"),
    ("drop_mispick_checked", "Drop/mis-pick checked"),
    ("cycle_time_captured", "Cycle time captured"),
    ("scrap_quality_concerns_checked", "Scrap/quality concerns checked"),
    ("photos_captured", "Photos captured"),
    ("signoff_completed", "Signoff completed"),
)


@dataclass(frozen=True)
class ChangeValidationItem:
    item_id: str
    label: str
    status: str
    evidence_source: str
    notes: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChangeValidationChecklist:
    change_id: str
    audit_id: str
    machine: str
    eoat_type: str
    generated_at: str
    items: tuple[ChangeValidationItem, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "audit_id": self.audit_id,
            "machine": self.machine,
            "eoat_type": self.eoat_type,
            "generated_at": self.generated_at,
            "warnings": list(self.warnings),
            "items": [item.to_dict() for item in self.items],
        }

    def to_markdown(self) -> str:
        lines = [
            "# EOAT Change Validation Checklist",
            "",
            f"- Change ID: {self.change_id}",
            f"- Audit ID: {self.audit_id}",
            f"- Press/Machine #: {self.machine}",
            f"- EOAT Type: {self.eoat_type}",
            f"- Generated: {self.generated_at}",
            "",
            "## Checklist",
            "| Item | Status | Evidence Source | Notes | Signoff Initials |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in self.items:
            lines.append(f"| {item.label} | {item.status} | {item.evidence_source} | {item.notes} |  |")
        if self.warnings:
            lines.extend(["", "## Missing Evidence Warnings"])
            lines.extend(f"- {warning}" for warning in self.warnings)
        lines.extend(
            [
                "",
                "## Signoff",
                "- Operator / Setup:",
                "- Technician / Maintenance:",
                "- Quality / Process:",
                "- Timestamp:",
                "",
                "## Guardrails",
                "- This checklist is a validation aid generated from audit data.",
                "- Pending or blocked items must be physically verified before release.",
                "- Missing photos, cycle-time data, CAD, BOM, or binder evidence must remain clearly marked.",
            ]
        )
        return "\n".join(lines) + "\n"


def build_change_validation_checklist(
    project_root: str | Path, *, audit_id: str = "", machine: str = "", change_id: str = ""
) -> ChangeValidationChecklist | None:
    row = _select_audit_row(project_root, audit_id=audit_id, machine=machine)
    if row is None:
        return None
    row = repair_legacy_audit_lookup_shift(row)
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    audit = _clean(row.get("Audit ID"))
    press = _clean(row.get("Press/Machine #"))
    checklist = ChangeValidationChecklist(
        change_id=change_id or f"CHG-{audit or _slug(press) or timestamp_for_report()}",
        audit_id=audit or "N/A",
        machine=press or "N/A",
        eoat_type=_clean(row.get("EOAT Type")) or "Unknown",
        generated_at=generated_at,
        items=tuple(_item_for(row, item_id, label) for item_id, label in CHANGE_VALIDATION_ITEMS),
        warnings=tuple(_warnings_for(row)),
    )
    return checklist


def generate_change_validation_checklist(
    project_root: str | Path,
    *,
    audit_id: str = "",
    machine: str = "",
    change_id: str = "",
    log_activity: bool = True,
) -> ToolResult:
    start = time.perf_counter()
    checklist = build_change_validation_checklist(project_root, audit_id=audit_id, machine=machine, change_id=change_id)
    if checklist is None:
        return ToolResult.fail(
            TOOL_ID, TOOL_NAME, "No matching EOAT Inventory audit row found; change validation was not generated."
        )
    output_dir = ensure_directory(resolve_project_paths(project_root).change_validation / _slug(checklist.change_id))
    stamp = timestamp_for_report()
    files_created: list[str] = []
    try:
        markdown_path = safe_write_text(
            output_dir / f"Change_Validation_{_slug(checklist.change_id)}_{stamp}.md",
            checklist.to_markdown(),
            overwrite=False,
        )
        json_path = safe_write_text(
            output_dir / f"Change_Validation_{_slug(checklist.change_id)}_{stamp}.json",
            json.dumps(checklist.to_dict(), indent=2, sort_keys=True) + "\n",
            overwrite=False,
        )
        files_created.extend([str(markdown_path), str(json_path)])
    except Exception as exc:
        return ToolResult.fail(TOOL_ID, TOOL_NAME, "Could not write change validation checklist.", errors=[str(exc)])
    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Generated EOAT change validation checklist.",
        details=[
            f"Change ID: {checklist.change_id}",
            f"Audit ID: {checklist.audit_id}",
            f"Output folder: {output_dir}",
        ],
        warnings=list(checklist.warnings),
        files_created=files_created,
        output_reports=files_created,
        structured_data=checklist.to_dict(),
        metrics={"checklist_items": len(checklist.items), "warning_count": len(checklist.warnings)},
        duration_seconds=time.perf_counter() - start,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result


def _item_for(row: dict[str, Any], item_id: str, label: str) -> ChangeValidationItem:
    status = "pending physical verification"
    evidence_source = "Audit data and post-change validation"
    notes = "Verify after EOAT change before production release."
    if item_id == "eoat_mounted_securely":
        evidence_source = "Mounting Hardware Condition"
        notes = f"Audit condition: {_display(row.get('Mounting Hardware Condition'))}."
    elif item_id == "vacuum_gripper_function_verified":
        evidence_source = "EOAT Type, vacuum/gripper fields"
        notes = _function_notes(row)
    elif item_id == "sensor_operation_verified":
        evidence_source = "Sensors Present?, Sensor Type, Sensor Brand/Model"
        if _no(row.get("Sensors Present?")) and _no(row.get("Part-Present Detection Present?")):
            status = "not applicable per audit"
            notes = "Sensors are documented as not present; verify this remains true after the change."
        else:
            notes = f"Sensor type: {_display(row.get('Sensor Type'))}; brand/model: {_display(row.get('Sensor Brand/Model'))}."
    elif item_id == "quick_disconnects_verified":
        evidence_source = "Quick Disconnects Present? and quick disconnect type fields"
        notes = f"Pneumatic: {_display(row.get('Pneumatic Quick Disconnect Type'))}; Electrical: {_display(row.get('Electrical Quick Disconnect Type'))}."
    elif item_id == "tubing_cable_routing_verified":
        evidence_source = "Tubing Condition, Tubing Routing Notes, Cable Management Condition"
        notes = f"Tubing: {_display(row.get('Tubing Condition'))}; cable management: {_display(row.get('Cable Management Condition'))}."
    elif item_id == "dry_cycle_completed" or item_id == "first_part_pickup_checked":
        evidence_source = "Post-change validation"
    elif item_id == "drop_mispick_checked":
        evidence_source = "Drop/Mis-Pick History"
        notes = f"Known history: {_display(row.get('Drop/Mis-Pick History'))}."
    elif item_id == "cycle_time_captured":
        evidence_source = "KPI/change validation record"
        if _yes(row.get("Cycle Time Concern?")):
            notes = "Cycle time concern is flagged in the audit; capture baseline and post-change value."
    elif item_id == "scrap_quality_concerns_checked":
        evidence_source = "Scrap/Quality Concern?"
        notes = f"Audit value: {_display(row.get('Scrap/Quality Concern?'))}."
    elif item_id == "photos_captured":
        evidence_source = "Photos Taken? and Photo Folder/Link"
        if not _yes(row.get("Photos Taken?")) or not _clean(row.get("Photo Folder/Link")):
            status = "blocked - missing evidence"
            notes = "Capture or link post-change photos before signoff."
        else:
            notes = f"Photo folder/link: {_display(row.get('Photo Folder/Link'))}."
    elif item_id == "signoff_completed":
        evidence_source = "Manual signoff"
    return ChangeValidationItem(
        item_id=item_id, label=label, status=status, evidence_source=evidence_source, notes=notes
    )


def _function_notes(row: dict[str, Any]) -> str:
    eoat_type = _clean(row.get("EOAT Type")).casefold()
    parts: list[str] = []
    if "vacuum" in eoat_type or "hybrid" in eoat_type:
        parts.append(
            f"vacuum cups {_display(row.get('# of Cups'))}, circuits {_display(row.get('EOAT Vacuum Circuits'))}"
        )
    if "gripper" in eoat_type or "mechanical" in eoat_type or "hybrid" in eoat_type:
        parts.append(f"grippers {_display(row.get('# of Grippers'))}, model {_display(row.get('Gripper Model'))}")
    if not parts:
        parts.append("EOAT function not fully documented")
    return "Verify " + "; ".join(parts) + "."


def _warnings_for(row: dict[str, Any]) -> list[str]:
    machine = _clean(row.get("Press/Machine #")) or _clean(row.get("Audit ID")) or "selected EOAT"
    warnings: list[str] = []
    if not _yes(row.get("Photos Taken?")) or not _clean(row.get("Photo Folder/Link")):
        warnings.append(f"{machine}: photos are missing or not linked.")
    for label, field in [
        ("CAD/drawing", "Drawing/CAD Available?"),
        ("BOM", "BOM Available?"),
        ("process binder", "Process Binder Complete?"),
    ]:
        if not _yes(row.get(field)):
            warnings.append(f"{machine}: {label} not documented as available.")
    return warnings


def _select_audit_row(project_root: str | Path, *, audit_id: str = "", machine: str = "") -> dict[str, Any] | None:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return None
    try:
        rows = row_dicts(paths.master_workbook, "EOAT Inventory")
    except Exception:
        return None
    audit_key = audit_id.strip().casefold()
    machine_key = machine.strip().casefold()
    for row in rows:
        if audit_key and _clean(row.get("Audit ID")).casefold() == audit_key:
            return row
    for row in rows:
        if machine_key and _clean(row.get("Press/Machine #")).casefold() == machine_key:
            return row
    return rows[0] if rows and not audit_key and not machine_key else None


def _display(value: Any) -> str:
    return _clean(value) or "Not documented"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _yes(value: Any) -> bool:
    return _clean(value).casefold() in {"yes", "y", "true", "1", "available", "complete"}


def _no(value: Any) -> bool:
    return _clean(value).casefold() in {"no", "n", "false", "0", "not applicable", "n/a"}


def _slug(text: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in text.strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "EOAT"


__all__ = [
    "CHANGE_VALIDATION_ITEMS",
    "ChangeValidationChecklist",
    "ChangeValidationItem",
    "build_change_validation_checklist",
    "generate_change_validation_checklist",
]
