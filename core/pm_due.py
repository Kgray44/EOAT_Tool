from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .analysis_common import timestamp_for_report
from .audit_compatibility import normalize_machine_token
from .audit_field_rules import (
    cylinder_section_in_use,
    eoat_type_uses_gripper,
    eoat_type_uses_vacuum,
    is_meaningful_value,
    normalized_eoat_type,
)
from .paths import resolve_project_paths
from .photo_evidence import pm_bom_evidence_status
from .pm_checklists import generate_pm_checklists
from .result import ToolResult
from .safe_files import ensure_directory, safe_write_text
from .workbook_cache import row_dicts_cached as row_dicts

STATUS_NOT_STARTED = "not_started"
STATUS_DUE_SOON = "due_soon"
STATUS_DUE = "due"
STATUS_OVERDUE = "overdue"
STATUS_COMPLETE = "complete"
STATUS_BLOCKED = "blocked"
STATUS_NOT_APPLICABLE = "not_applicable"

PM_STATUSES = (
    STATUS_NOT_STARTED,
    STATUS_DUE_SOON,
    STATUS_DUE,
    STATUS_OVERDUE,
    STATUS_COMPLETE,
    STATUS_BLOCKED,
    STATUS_NOT_APPLICABLE,
)

RECENT_COMPLETION_DAYS = 14


@dataclass(frozen=True)
class PMItem:
    item_id: str
    label: str
    category: str
    default_interval_days: int = 30
    due_soon_days: int = 7
    applies_to: tuple[str, ...] = ("all",)
    help_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PMRecord:
    record_id: str
    item_id: str
    item_label: str
    audit_id: str
    machine: str
    eoat_type: str
    status: str = STATUS_NOT_STARTED
    due_date: str = ""
    last_completed: str = ""
    completed_at: str = ""
    notes: str = ""
    photo_evidence_link: str = ""
    blocked_reason: str = ""
    updated_at: str = ""
    source: str = "system"

    @property
    def due_state(self) -> str:
        return self.status

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PMRecord:
        status = _normalize_status(data.get("status"))
        return cls(
            record_id=_text(data.get("record_id")),
            item_id=_text(data.get("item_id")),
            item_label=_text(data.get("item_label")),
            audit_id=_text(data.get("audit_id")),
            machine=_text(data.get("machine")),
            eoat_type=_text(data.get("eoat_type")),
            status=status,
            due_date=_text(data.get("due_date")),
            last_completed=_text(data.get("last_completed")),
            completed_at=_text(data.get("completed_at")),
            notes=_text(data.get("notes")),
            photo_evidence_link=_text(data.get("photo_evidence_link")),
            blocked_reason=_text(data.get("blocked_reason")),
            updated_at=_text(data.get("updated_at")),
            source=_text(data.get("source")) or "system",
        )


@dataclass(frozen=True)
class PmDueItem:
    audit_id: str
    machine: str
    eoat_type: str
    priority: str
    maintenance_frequency: str
    due_state: str
    risk_score: int
    missing_evidence_count: int = 0
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PmDueSummary:
    items: list[PmDueItem] = field(default_factory=list)
    records: list[PMRecord] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "records": [record.to_dict() for record in self.records],
            "metrics": dict(self.metrics),
            "warnings": list(self.warnings),
        }


def default_pm_items() -> list[PMItem]:
    return [
        PMItem("inspect_vacuum_cups", "Inspect vacuum cups for wear/damage", "vacuum", applies_to=("vacuum", "hybrid"), default_interval_days=7),
        PMItem("inspect_pneumatic_tubing", "Inspect pneumatic tubing", "pneumatic", applies_to=("all",), default_interval_days=7),
        PMItem("verify_sensor_operation", "Verify sensor operation", "sensors", applies_to=("sensors",), default_interval_days=30),
        PMItem("inspect_mounting_hardware", "Inspect mounting hardware", "mechanical", applies_to=("all",), default_interval_days=30),
        PMItem("verify_eoat_alignment", "Verify EOAT alignment", "mechanical", applies_to=("all",), default_interval_days=30),
        PMItem("check_quick_disconnect_fittings", "Check quick disconnect fittings", "pneumatic", applies_to=("quick_disconnects",), default_interval_days=30),
        PMItem("verify_cable_management_condition", "Verify cable management condition", "electrical", applies_to=("all",), default_interval_days=30),
        PMItem("check_gripper_jaw_finger_wear", "Check gripper jaw/finger wear", "gripper", applies_to=("gripper", "hybrid"), default_interval_days=7),
        PMItem("check_cylinder_movement", "Check cylinder movement if cylinder fields exist", "cylinders", applies_to=("cylinders",), default_interval_days=30),
        PMItem("check_robot_side_pneumatic_labeling", "Check robot-side pneumatic circuit labeling", "pneumatic", applies_to=("robot_pneumatic",), default_interval_days=90),
        PMItem("check_eoat_side_pneumatic_labeling", "Check EOAT-side pneumatic circuit labeling", "pneumatic", applies_to=("eoat_pneumatic",), default_interval_days=90),
        PMItem("confirm_process_binder_documentation", "Confirm process binder documentation", "documentation", applies_to=("all",), default_interval_days=90),
    ]


def pm_records_path(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).project_admin / "pm_due" / "pm_records.json"


def load_pm_records(project_root: str | Path) -> list[PMRecord]:
    path = pm_records_path(project_root)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_records = payload.get("records", []) if isinstance(payload, dict) else payload if isinstance(payload, list) else []
    return [PMRecord.from_dict(record) for record in raw_records if isinstance(record, dict)]


def save_pm_records(project_root: str | Path, records: Iterable[PMRecord]) -> Path:
    path = pm_records_path(project_root)
    payload = {
        "schema_version": 1,
        "updated_at": _now(),
        "records": [record.to_dict() for record in sorted(records, key=lambda item: (item.machine, item.audit_id, item.item_label.casefold()))],
    }
    return safe_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n", overwrite=True)


def pm_items_for_audit(row: dict[str, Any]) -> list[PMItem]:
    return [item for item in default_pm_items() if pm_item_applies(item, row)]


def pm_item_applies(item: PMItem, row: dict[str, Any]) -> bool:
    scopes = set(item.applies_to)
    if "all" in scopes:
        return True
    if "vacuum" in scopes and eoat_type_uses_vacuum(row):
        return True
    if "gripper" in scopes and eoat_type_uses_gripper(row):
        return True
    if "hybrid" in scopes and normalized_eoat_type(row) == "Hybrid":
        return True
    if "cylinders" in scopes:
        return cylinder_section_in_use(row)
    if "sensors" in scopes:
        return _has_sensor_pm_scope(row)
    if "quick_disconnects" in scopes:
        return _has_quick_disconnect_pm_scope(row)
    if "robot_pneumatic" in scopes:
        return _has_any_meaningful(row, ("Robot Vacuum Circuits", "Robot Pressure Circuits", "Robot Interchangeable Circuits")) or _known_tooling_type(row)
    if "eoat_pneumatic" in scopes:
        return _has_any_meaningful(row, ("EOAT Vacuum Circuits", "EOAT Pressure Circuits", "EOAT Interchangeable Circuits")) or _known_tooling_type(row)
    return False


def build_pm_records_for_audit(project_root: str | Path, row: dict[str, Any], *, today: date | None = None) -> list[PMRecord]:
    today = today or date.today()
    audit_id = _text(row.get("Audit ID"))
    machine = normalize_machine_token(row.get("Press/Machine #")) or _text(row.get("Press/Machine #"))
    eoat_type = _text(row.get("EOAT Type"))
    records: list[PMRecord] = []
    for item in pm_items_for_audit(row):
        due_date = today + timedelta(days=_interval_days(row, item))
        status = _status_for_due_date(due_date, today)
        records.append(
            PMRecord(
                record_id=_record_id(audit_id, machine, item.item_id),
                item_id=item.item_id,
                item_label=item.label,
                audit_id=audit_id,
                machine=machine,
                eoat_type=eoat_type,
                status=status,
                due_date=due_date.isoformat(),
                updated_at=_now(),
            )
        )
    return records


def build_pm_due_summary(
    project_root: str | Path,
    *,
    machine: str | None = None,
    eoat_type: str | None = None,
    today: date | None = None,
) -> PmDueSummary:
    workbook = resolve_project_paths(project_root).master_workbook
    warnings: list[str] = []
    today = today or date.today()
    if not workbook.exists():
        return PmDueSummary(metrics={"items": 0, "records": 0}, warnings=[f"Master workbook is missing: {workbook}"])
    try:
        rows = row_dicts(workbook, "EOAT Inventory")
    except Exception as exc:
        return PmDueSummary(metrics={"items": 0, "records": 0}, warnings=[f"Could not read EOAT Inventory: {exc}"])
    rows = [row for row in rows if _text(row.get("Audit ID"))]
    if machine:
        target = normalize_machine_token(machine)
        rows = [row for row in rows if normalize_machine_token(row.get("Press/Machine #")) == target]
    if eoat_type:
        target_type = eoat_type.strip().casefold()
        rows = [row for row in rows if target_type in _text(row.get("EOAT Type")).casefold()]

    generated_records = [record for row in rows for record in build_pm_records_for_audit(project_root, row, today=today)]
    stored = {record.record_id: record for record in load_pm_records(project_root)}
    records = [_merge_record(generated, stored.get(generated.record_id), today) for generated in generated_records]
    items = [build_pm_due_item(project_root, row) for row in rows]
    items.sort(key=lambda item: (-item.risk_score, item.machine, item.audit_id))
    records.sort(key=lambda record: (_status_sort(record.status), record.due_date, record.machine, record.item_label.casefold()))
    metrics = {
        "items": len(items),
        "records": len(records),
        "due_now": sum(1 for item in items if item.due_state == "Due Now"),
        "needs_frequency": sum(1 for item in items if item.due_state == "Needs Frequency"),
        "missing_evidence": sum(1 for item in items if item.missing_evidence_count),
        "highest_risk_score": items[0].risk_score if items else 0,
        "due_this_week": sum(1 for record in records if record.status in {STATUS_DUE, STATUS_DUE_SOON}),
        "overdue": sum(1 for record in records if record.status == STATUS_OVERDUE),
        "completed_recently": sum(1 for record in records if _completed_recently(record, today)),
        "blocked": sum(1 for record in records if record.status == STATUS_BLOCKED),
        "not_started": sum(1 for record in records if record.status == STATUS_NOT_STARTED),
    }
    return PmDueSummary(items=items, records=records, metrics=metrics, warnings=warnings)


def analyze_pm_due(project_root: str | Path) -> PmDueSummary:
    return build_pm_due_summary(project_root)


def build_pm_due_item(project_root: str | Path, row: dict[str, Any]) -> PmDueItem:
    audit_id = _text(row.get("Audit ID"))
    frequency = _text(row.get("Maintenance Frequency"))
    priority = _text(row.get("Priority"))
    known_issues = _text(row.get("Known Issues"))
    evidence = pm_bom_evidence_status(project_root, audit_id)
    missing_evidence = int(evidence.get("missing_required_count") or 0)
    reasons: list[str] = []
    score = 0
    due_state = _frequency_due_state(frequency)
    if due_state == "Needs Frequency":
        score += 20
        reasons.append("Maintenance frequency is missing or unknown.")
    elif due_state == "Due Now":
        score += 15
        reasons.append(f"Maintenance frequency is {frequency}.")
    if priority.casefold() in {"critical", "high"}:
        score += 20 if priority.casefold() == "critical" else 12
        reasons.append(f"Audit priority is {priority}.")
    if known_issues and known_issues.casefold() not in {"none", "no", "n/a", "unknown / not checked"}:
        score += 15
        reasons.append("Known issues are documented.")
    if missing_evidence:
        score += min(20, missing_evidence * 5)
        reasons.append("Required PM/photo evidence is missing.")
    if not reasons:
        reasons.append("No immediate PM risk signals detected.")
    return PmDueItem(
        audit_id=audit_id,
        machine=normalize_machine_token(row.get("Press/Machine #")) or _text(row.get("Press/Machine #")),
        eoat_type=_text(row.get("EOAT Type")),
        priority=priority,
        maintenance_frequency=frequency,
        due_state=due_state,
        risk_score=score,
        missing_evidence_count=missing_evidence,
        reasons=tuple(reasons),
    )


def mark_pm_item_complete(
    project_root: str | Path,
    record_id: str,
    *,
    notes: str = "",
    photo_evidence_link: str = "",
    completed_on: date | None = None,
) -> ToolResult:
    completed_on = completed_on or date.today()
    return update_pm_record(
        project_root,
        record_id,
        status=STATUS_COMPLETE,
        notes=notes,
        photo_evidence_link=photo_evidence_link,
        completed_at=completed_on.isoformat(),
    )


def update_pm_record(
    project_root: str | Path,
    record_id: str,
    *,
    status: str | None = None,
    notes: str | None = None,
    photo_evidence_link: str | None = None,
    blocked_reason: str | None = None,
    completed_at: str | None = None,
) -> ToolResult:
    start = time.perf_counter()
    record = _record_by_id(project_root, record_id)
    if record is None:
        return ToolResult.fail("pm_due_update", "PM Due Tracking", f"PM record not found: {record_id}")
    path = pm_records_path(project_root)
    existed_before = path.exists()
    next_status = _normalize_status(status or record.status)
    updated = replace(
        record,
        status=next_status,
        notes=record.notes if notes is None else notes.strip(),
        photo_evidence_link=record.photo_evidence_link if photo_evidence_link is None else photo_evidence_link.strip(),
        blocked_reason=record.blocked_reason if blocked_reason is None else blocked_reason.strip(),
        completed_at=completed_at if completed_at is not None else record.completed_at,
        last_completed=completed_at if completed_at is not None else record.last_completed,
        updated_at=_now(),
        source="user",
    )
    records = {item.record_id: item for item in _records_with_generated(project_root)}
    records[updated.record_id] = updated
    path = save_pm_records(project_root, records.values())
    return ToolResult.ok(
        "pm_due_update",
        "PM Due Tracking",
        f"Updated PM record {record_id}.",
        details=[f"Status: {updated.status}", f"Record file: {path}"],
        files_created=[] if existed_before else [str(path)],
        files_modified=[str(path)] if existed_before else [],
        metrics={"record_count": len(records), "status": updated.status},
        duration_seconds=time.perf_counter() - start,
    )


def export_pm_pack(
    project_root: str | Path,
    *,
    machine: str | None = None,
    eoat_type: str | None = None,
    today: date | None = None,
) -> ToolResult:
    start = time.perf_counter()
    summary = build_pm_due_summary(project_root, machine=machine, eoat_type=eoat_type, today=today)
    checklist = generate_pm_checklists(project_root, press=machine, generic=False, formats=["markdown"]) if machine else None
    paths = resolve_project_paths(project_root)
    output_dir = ensure_directory(paths.pm_generated_checklists)
    stamp = timestamp_for_report()
    name = _slug("_".join(part for part in ["PM_Due_Pack", machine or "", eoat_type or ""] if part))
    report_path = safe_write_text(output_dir / f"{name}_{stamp}.md", _pm_pack_markdown(summary, machine=machine, eoat_type=eoat_type), overwrite=False)
    files_created = [str(report_path)]
    warnings = list(summary.warnings)
    if checklist is not None:
        files_created.extend(checklist.files_created)
        warnings.extend(checklist.warnings)
    return ToolResult.ok(
        "pm_due_export",
        "PM Due Tracking",
        f"Exported PM pack with {len(summary.records)} tracking item(s).",
        details=[f"PM due pack: {report_path}", f"Records included: {len(summary.records)}"],
        warnings=warnings,
        files_created=files_created,
        output_reports=files_created,
        metrics=dict(summary.metrics),
        duration_seconds=time.perf_counter() - start,
    )


def _records_with_generated(project_root: str | Path, *, today: date | None = None) -> list[PMRecord]:
    return build_pm_due_summary(project_root, today=today).records


def _record_by_id(project_root: str | Path, record_id: str) -> PMRecord | None:
    target = _text(record_id)
    if not target:
        return None
    return next((record for record in _records_with_generated(project_root) if record.record_id == target), None)


def _merge_record(generated: PMRecord, stored: PMRecord | None, today: date) -> PMRecord:
    if stored is None:
        return generated
    status = stored.status
    if status not in {STATUS_COMPLETE, STATUS_BLOCKED, STATUS_NOT_APPLICABLE}:
        status = _status_for_due_date(_parse_date(stored.due_date) or _parse_date(generated.due_date) or today, today)
    return replace(
        generated,
        status=status,
        due_date=stored.due_date or generated.due_date,
        last_completed=stored.last_completed,
        completed_at=stored.completed_at,
        notes=stored.notes,
        photo_evidence_link=stored.photo_evidence_link,
        blocked_reason=stored.blocked_reason,
        updated_at=stored.updated_at or generated.updated_at,
        source=stored.source or generated.source,
    )


def _pm_pack_markdown(summary: PmDueSummary, *, machine: str | None, eoat_type: str | None) -> str:
    lines = [
        "# PM Due Pack",
        "",
        f"- Machine filter: {machine or 'All'}",
        f"- EOAT type filter: {eoat_type or 'All'}",
        f"- Due this week: {summary.metrics.get('due_this_week', 0)}",
        f"- Overdue: {summary.metrics.get('overdue', 0)}",
        f"- Completed recently: {summary.metrics.get('completed_recently', 0)}",
        f"- Blocked: {summary.metrics.get('blocked', 0)}",
        "",
        "## PM Items",
        "| Status | Due Date | Machine | Audit ID | EOAT Type | Item | Notes | Evidence |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in summary.records:
        lines.append(
            "| "
            + " | ".join(
                _table_cell(value)
                for value in [
                    record.status,
                    record.due_date,
                    record.machine,
                    record.audit_id,
                    record.eoat_type,
                    record.item_label,
                    record.notes,
                    record.photo_evidence_link,
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _interval_days(row: dict[str, Any], item: PMItem) -> int:
    frequency = _text(row.get("Maintenance Frequency")).casefold()
    if any(token in frequency for token in ("daily", "per shift", "each shift")):
        return 0
    if "weekly" in frequency:
        return 7
    if "monthly" in frequency:
        return 30
    if "quarter" in frequency:
        return 90
    if "annual" in frequency or "yearly" in frequency:
        return 365
    return min(item.default_interval_days, 7)


def _status_for_due_date(due_date: date, today: date) -> str:
    if due_date < today:
        return STATUS_OVERDUE
    if due_date == today:
        return STATUS_DUE
    if due_date <= today + timedelta(days=7):
        return STATUS_DUE_SOON
    return STATUS_NOT_STARTED


def _frequency_due_state(value: str) -> str:
    text = value.strip().casefold()
    if not text or text in {"unknown", "unknown / not checked", "n/a", "na"}:
        return "Needs Frequency"
    if any(token in text for token in ("daily", "weekly", "per shift", "each shift")):
        return "Due Now"
    if any(token in text for token in ("monthly", "quarterly", "annual", "yearly")):
        return "Scheduled"
    return "Review"


def _has_sensor_pm_scope(row: dict[str, Any]) -> bool:
    if _text(row.get("Sensors Present?")).casefold() == "no":
        return _has_any_meaningful(row, ("Sensor Type", "Sensor Brand/Model", "Vacuum Confirmation Present?", "Part-Present Detection Present?"))
    return True


def _has_quick_disconnect_pm_scope(row: dict[str, Any]) -> bool:
    if _text(row.get("Quick Disconnects Present?")).casefold() == "no":
        return _has_any_meaningful(row, ("Pneumatic Quick Disconnect Type", "Electrical Quick Disconnect Type"))
    return True


def _has_any_meaningful(row: dict[str, Any], fields: Iterable[str]) -> bool:
    return any(is_meaningful_value(row.get(field)) for field in fields)


def _known_tooling_type(row: dict[str, Any]) -> bool:
    return eoat_type_uses_vacuum(row) or eoat_type_uses_gripper(row)


def _completed_recently(record: PMRecord, today: date) -> bool:
    completed = _parse_date(record.completed_at or record.last_completed)
    return bool(completed and record.status == STATUS_COMPLETE and completed >= today - timedelta(days=RECENT_COMPLETION_DAYS))


def _parse_date(value: str) -> date | None:
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _normalize_status(value: Any) -> str:
    text = _text(value).casefold()
    return text if text in PM_STATUSES else STATUS_NOT_STARTED


def _record_id(audit_id: str, machine: str, item_id: str) -> str:
    parts = [_slug(audit_id or "unassigned"), _slug(machine or "machine"), _slug(item_id)]
    return "pm_" + "_".join(part for part in parts if part)


def _status_sort(status: str) -> int:
    order = {
        STATUS_OVERDUE: 0,
        STATUS_DUE: 1,
        STATUS_DUE_SOON: 2,
        STATUS_BLOCKED: 3,
        STATUS_NOT_STARTED: 4,
        STATUS_COMPLETE: 5,
        STATUS_NOT_APPLICABLE: 6,
    }
    return order.get(status, 99)


def _slug(text: str, fallback: str = "pm") -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in _text(text))
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or fallback


def _table_cell(value: Any) -> str:
    return _text(value).replace("|", "/")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


__all__ = [
    "PMItem",
    "PMRecord",
    "PM_STATUSES",
    "PmDueItem",
    "PmDueSummary",
    "STATUS_BLOCKED",
    "STATUS_COMPLETE",
    "STATUS_DUE",
    "STATUS_DUE_SOON",
    "STATUS_NOT_APPLICABLE",
    "STATUS_NOT_STARTED",
    "STATUS_OVERDUE",
    "analyze_pm_due",
    "build_pm_due_item",
    "build_pm_due_summary",
    "build_pm_records_for_audit",
    "default_pm_items",
    "export_pm_pack",
    "load_pm_records",
    "mark_pm_item_complete",
    "pm_item_applies",
    "pm_items_for_audit",
    "pm_records_path",
    "save_pm_records",
    "update_pm_record",
]
