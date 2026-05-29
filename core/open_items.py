from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from core.annotations.exports import unique_export_path
from core.annotations.migrations import utc_now
from core.annotations.service import AnnotationService
from core.annotations.tag_colors import is_neutral_context_tag
from core.paths import resolve_project_paths
from core.photo_evidence import evidence_coverage_for_project
from core.safe_files import ensure_directory, safe_write_text
from core.validation import validate_project_foundation
from core.validation_findings import findings_from_result
from core.workbook_cache import row_dicts_cached as row_dicts

STATUS_DISMISSED = "Dismissed / Overridden"
STATUS_FIXED_AT_SOURCE = "Fixed at Source"
OPEN_ITEMS_SUMMARY_CACHE_SCHEMA_VERSION = 1
OPEN_ITEM_STATUSES = ("Open", "In Progress", "Waiting on Info", "Blocked", STATUS_DISMISSED, STATUS_FIXED_AT_SOURCE)
UNRESOLVED_STATUSES = {"Open", "In Progress", "Waiting on Info", "Blocked"}
ACTION_OPEN_STATUSES = {"", "open", "not started", "needs follow-up", "in progress", "blocked", "new", "waiting on info"}
RESOLVED_SOURCE_STATUSES = {"resolved", "archived", "closed", "complete", "completed", "done", "dismissed"}


@dataclass(frozen=True)
class OpenItem:
    id: str
    source: str
    severity: str
    category: str
    title: str
    message: str
    audit_id: str = ""
    machine: str = ""
    field: str = ""
    target_id: str = ""
    target_type: str = ""
    due_date: str = ""
    status: str = "Open"
    recommended_action: str = ""
    created_at: str = ""
    updated_at: str = ""
    dismissed_reason: str = ""
    dismissed_at: str = ""
    fixed_at: str = ""

    @property
    def unresolved(self) -> bool:
        return self.status in UNRESOLVED_STATUSES

    def target_payload(self) -> dict[str, object]:
        if self.target_id:
            return {
                "id": self.target_id,
                "target_type": self.target_type or ("audit_field" if self.field else "audit"),
                "audit_id": self.audit_id,
                "machine_id": self.machine,
                "field_key": self.field,
                "field_label": self.field,
            }
        if self.target_type and self.target_type not in {"audit", "audit_field"}:
            return {
                "target_type": self.target_type,
                "target_label": self.title,
                "audit_id": self.audit_id,
                "machine_id": self.machine,
                "field_key": self.field,
                "field_label": self.field,
                "object_ref": self.message,
            }
        if self.audit_id and self.field:
            return {"target_type": "audit_field", "audit_id": self.audit_id, "machine_id": self.machine, "field_key": self.field, "field_label": self.field}
        if self.audit_id:
            return {"target_type": "audit", "audit_id": self.audit_id, "machine_id": self.machine}
        if self.machine:
            return {"target_type": "machine", "machine_id": self.machine, "target_label": f"Machine {self.machine}"}
        return {}

    def source_payload(self) -> dict[str, object]:
        if self.source in {"note", "note_followup"}:
            note_id = self.id.split(":", 2)[1] if ":" in self.id else ""
            return {"target_type": "note", "id": note_id, "object_ref": note_id, "target_label": self.title}
        if self.source == "tag":
            assignment_id = self.id.split(":", 1)[1] if ":" in self.id else ""
            return {"target_type": "tag_assignment", "id": assignment_id, "object_ref": assignment_id, "target_label": self.title}
        return self.target_payload()


def list_open_items(
    project_root: str | Path,
    *,
    include_resolved: bool = False,
    include_validation: bool = True,
    today: date | None = None,
) -> list[OpenItem]:
    root = Path(project_root)
    today = today or date.today()
    items = _generated_open_items(root, include_validation=include_validation)
    overrides = _override_map(root)
    _record_source_fixes(root, items, overrides, include_validation=include_validation)
    resolved = _apply_overrides(items, overrides)
    if include_resolved:
        return sorted([*resolved, *_fixed_history_items(root)], key=lambda item: _sort_key(item, today))
    return sorted([item for item in resolved if item.unresolved], key=lambda item: _sort_key(item, today))


def _generated_open_items(project_root: Path, *, include_validation: bool = True) -> list[OpenItem]:
    items: list[OpenItem] = []
    service = AnnotationService(project_root)
    items.extend(_note_items(service))
    items.extend(_tag_items(service))
    items.extend(_action_items(project_root))
    items.extend(_missing_evidence_items(project_root))
    items.extend(_documentation_gap_items(project_root))
    if include_validation:
        items.extend(_validation_items(project_root))
    return items


def open_items_summary(project_root: str | Path, *, today: date | None = None) -> dict[str, int]:
    today = today or date.today()
    items = list_open_items(project_root, include_resolved=True, today=today)
    return summarize_open_items(items, today=today)


def open_items_summary_cache_path(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).cache / "open_items_summary.json"


def load_cached_open_items_summary(project_root: str | Path) -> tuple[dict[str, int] | None, str | None]:
    path = open_items_summary_cache_path(project_root)
    if not path.exists():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    if payload.get("schema") != OPEN_ITEMS_SUMMARY_CACHE_SCHEMA_VERSION:
        return None, None
    raw_summary = payload.get("summary")
    if not isinstance(raw_summary, dict):
        return None, None
    summary: dict[str, int] = {}
    for key, value in raw_summary.items():
        try:
            summary[str(key)] = int(value or 0)
        except (TypeError, ValueError):
            summary[str(key)] = 0
    generated_at = str(payload.get("generated_at") or "") or None
    return summary, generated_at


def save_cached_open_items_summary(project_root: str | Path, summary: dict[str, int]) -> Path:
    path = open_items_summary_cache_path(project_root)
    ensure_directory(path.parent)
    payload = {
        "schema": OPEN_ITEMS_SUMMARY_CACHE_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {str(key): int(value or 0) for key, value in summary.items()},
        "source": {
            "project_root": _safe_project_root_label(project_root),
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    return path


def summarize_open_items(items: Iterable[OpenItem], *, today: date | None = None) -> dict[str, int]:
    today = today or date.today()
    rows = list(items)
    unresolved = [item for item in rows if item.unresolved]
    week_start = today - timedelta(days=today.weekday())
    fixed_this_week = sum(
        1
        for item in rows
        if item.status == STATUS_FIXED_AT_SOURCE
        and _date_or_none(item.fixed_at or item.updated_at)
        and (_date_or_none(item.fixed_at or item.updated_at) or today) >= week_start
    )
    return {
        "total_open_items": len(unresolved),
        "critical_open_items": sum(1 for item in unresolved if item.severity.casefold() == "critical"),
        "overdue_followups": sum(1 for item in unresolved if item.due_date and (_date_or_none(item.due_date) or today) < today),
        "missing_evidence_count": sum(1 for item in unresolved if item.category == "missing_evidence"),
        "data_conflict_count": sum(1 for item in unresolved if item.category == "data_conflict"),
        "dismissed_overridden_count": sum(1 for item in rows if item.status == STATUS_DISMISSED),
        "items_fixed_at_source_this_week": fixed_this_week,
        "blocked_items": sum(1 for item in unresolved if item.status == "Blocked"),
    }


def set_open_item_status(project_root: str | Path, item_id: str, status: str, *, reason: str = "") -> OpenItem | None:
    normalized_status = _normalize_status(status)
    if normalized_status == STATUS_DISMISSED:
        return dismiss_open_item(project_root, item_id, reason=reason)
    raise ValueError(
        "Generated open items cannot be manually marked resolved. Fix the underlying source data, "
        "or dismiss/override the item with a reason."
    )


def dismiss_open_item(project_root: str | Path, item_id: str, *, reason: str) -> OpenItem | None:
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("Dismissal reason is required.")
    root = Path(project_root)
    current_items = _generated_open_items(root, include_validation=True)
    item = next((candidate for candidate in current_items if candidate.id == item_id), None)
    if item is None:
        item = next((candidate for candidate in list_open_items(root, include_resolved=True) if candidate.id == item_id), None)
    if item is None:
        raise KeyError(item_id)
    now = utc_now()
    record = {
        **_item_record(item),
        "status": STATUS_DISMISSED,
        "dismissed_at": now,
        "updated_at": now,
        "resolution_type": "manual_override",
        "reason": reason,
    }
    _append_jsonl(_override_path(root), record)
    _append_jsonl(_state_ledger_path(root), record)
    return next((candidate for candidate in list_open_items(root, include_resolved=True) if candidate.id == item_id), None)


def export_open_items_report(project_root: str | Path, items: Iterable[OpenItem] | None = None) -> Path:
    rows = list(items) if items is not None else list_open_items(project_root)
    lines = ["# Open Items Report", ""]
    if not rows:
        lines.append("No open items.")
    for item in rows:
        lines.extend(
            [
                f"## {item.title}",
                f"- ID: {item.id}",
                f"- Source: {item.source}",
                f"- Severity: {item.severity}",
                f"- Category: {item.category}",
                f"- Status: {item.status}",
                f"- Audit ID: {item.audit_id}",
                f"- Machine: {item.machine}",
                f"- Field: {item.field}",
                f"- Due Date: {item.due_date}",
                f"- Message: {item.message}",
                f"- Recommended Action: {item.recommended_action}",
                "",
            ]
        )
    path = unique_export_path(project_root, "open_items_report", ".md")
    return safe_write_text(path, "\n".join(lines).rstrip() + "\n", overwrite=False)


def load_cached_open_items(
    project_root: str | Path,
    *,
    include_resolved: bool = False,
    today: date | None = None,
) -> tuple[list[OpenItem], str | None, str | None]:
    snapshot = _snapshot_path(project_root)
    records = _read_snapshot(snapshot)
    if not records:
        return [], None, "No cached open-items snapshot found."
    items = [_item_from_record(record) for record in records]
    items = _apply_overrides(items, _override_map(project_root))
    if include_resolved:
        items = [*items, *_fixed_history_items(project_root)]
    else:
        items = [item for item in items if item.unresolved]
    generated_at = None
    try:
        generated_at = datetime.fromtimestamp(snapshot.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        pass
    return sorted(items, key=lambda item: _sort_key(item, today or date.today())), generated_at, None


def _note_items(service: AnnotationService) -> list[OpenItem]:
    items: list[OpenItem] = []
    for note in service.search_notes(sort_by="follow_up_date"):
        source_status = _status_from_source(note.get("status"))
        if source_status not in UNRESOLVED_STATUSES:
            continue
        targets = list(note.get("targets") or [])
        primary_target = targets[0] if targets else {}
        severity = _note_severity(note.get("importance"))
        note_id = str(note.get("id") or "")
        item = OpenItem(
            id=f"note:{note_id}",
            source="note",
            severity=severity,
            category="note",
            title=str(note.get("subject") or "Open note"),
            message=str(note.get("body_markdown") or ""),
            audit_id=str(primary_target.get("audit_id") or ""),
            machine=str(primary_target.get("machine_id") or ""),
            field=str(primary_target.get("field_label") or primary_target.get("field_key") or ""),
            target_id=str(primary_target.get("id") or ""),
            target_type=str(primary_target.get("target_type") or ""),
            due_date=str(note.get("follow_up_date") or ""),
            status=source_status,
            recommended_action="Review or resolve the note.",
            created_at=str(note.get("created_at") or ""),
            updated_at=str(note.get("updated_at") or ""),
        )
        items.append(item)
        if item.due_date:
            items.append(
                replace(
                    item,
                    id=f"note_followup:{note_id}:{item.due_date}",
                    source="note_followup",
                    category="follow_up",
                    title=f"Follow up: {item.title}",
                    recommended_action="Complete the note follow-up or update the due date.",
                )
            )
    return items


def _tag_items(service: AnnotationService) -> list[OpenItem]:
    items: list[OpenItem] = []
    for assignment in service.list_tag_assignments(sort_by="updated"):
        tag_name = str(assignment.get("tag_name") or assignment.get("name") or "Tag")
        if is_neutral_context_tag(tag_name):
            continue
        category = _category_for_tag(tag_name)
        items.append(
            OpenItem(
                id=f"tag_assignment:{assignment.get('assignment_id')}",
                source="tag",
                severity=_severity_for_tag(tag_name),
                category=category,
                title=f"{tag_name}: {assignment.get('target_label') or assignment.get('field_label') or assignment.get('field_key') or 'target'}",
                message=str(assignment.get("comment") or ""),
                audit_id=str(assignment.get("audit_id") or ""),
                machine=str(assignment.get("machine_id") or ""),
                field=str(assignment.get("field_label") or assignment.get("field_key") or ""),
                target_id=str(assignment.get("target_id") or ""),
                target_type=str(assignment.get("target_type") or ""),
                status="Open",
                recommended_action=_action_for_tag(tag_name),
                created_at=str(assignment.get("created_at") or ""),
                updated_at=str(assignment.get("assignment_updated_at") or assignment.get("updated_at") or ""),
            )
        )
    return items


def _action_items(project_root: Path) -> list[OpenItem]:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return []
    try:
        rows = row_dicts(paths.master_workbook, "Action Items")
    except Exception:
        return []
    items: list[OpenItem] = []
    for index, row in enumerate(rows, start=2):
        status = _status_from_source(row.get("Status"))
        if str(row.get("Status") or "").strip().casefold() not in ACTION_OPEN_STATUSES and status not in UNRESOLVED_STATUSES:
            continue
        action_id = str(row.get("Action ID") or "").strip() or _short_hash("action", index, row.get("Action Item"), row.get("Related Cell/Press"))
        title = str(row.get("Action Item") or "Open action item").strip()
        items.append(
            OpenItem(
                id=f"action_item:{action_id}",
                source="action_item",
                severity=_severity_for_priority(row.get("Priority"), status),
                category="action_item",
                title=title,
                message=str(row.get("Notes") or ""),
                machine=str(row.get("Related Cell/Press") or ""),
                due_date=str(row.get("Due Date") or ""),
                status=status if status in UNRESOLVED_STATUSES else "Open",
                recommended_action="Update or complete the workbook Action Items row.",
                created_at=str(row.get("Date Added") or ""),
                updated_at=str(row.get("Date Added") or ""),
            )
        )
    return items


def _validation_items(project_root: Path) -> list[OpenItem]:
    result = validate_project_foundation(project_root)
    items: list[OpenItem] = []
    findings = findings_from_result(result)
    if findings:
        for finding in findings:
            items.append(
                OpenItem(
                    id=f"validation:{finding.finding_id}",
                    source="validation",
                    severity=finding.severity,
                    category=finding.category or "validation",
                    title=f"Workbook validation: {finding.category or finding.severity}",
                    message=finding.message,
                    audit_id=finding.audit_id,
                    machine=finding.machine_number,
                    field=finding.column_name,
                    target_type="audit_field" if finding.audit_id and finding.column_name else "workbook_warning",
                    status="Open",
                    recommended_action=finding.recommended_action or "Open Workbook Health and review this finding.",
                )
            )
        return items
    for severity, messages in [("Error", result.errors), ("Warning", result.warnings)]:
        for message in messages:
            items.append(
                OpenItem(
                    id=f"validation:{severity.casefold()}:{_short_hash(message)}",
                    source="validation",
                    severity=severity,
                    category="validation",
                    title=f"Workbook validation {severity.lower()}",
                    message=str(message),
                    status="Open",
                    recommended_action="Open Workbook Health and review this finding.",
                )
            )
    return items


def _missing_evidence_items(project_root: Path) -> list[OpenItem]:
    rows = _inventory_rows(project_root)
    items: list[OpenItem] = []
    for coverage in evidence_coverage_for_project(project_root):
        for status in coverage.statuses:
            if not status.required or status.present:
                continue
            items.append(
                OpenItem(
                    id=f"missing_evidence:{coverage.audit_id}:{status.category}",
                    source="missing_evidence",
                    severity="Warning",
                    category="missing_evidence",
                    title=f"Missing evidence: {status.label}",
                    message=status.warning or f"Required photo evidence missing for {status.label}.",
                    audit_id=coverage.audit_id,
                    machine=coverage.machine,
                    field="Photos Taken?",
                    target_type="photo",
                    status="Open",
                    recommended_action="Capture or intake local photos for this evidence category.",
                )
            )
    for row in rows:
        audit_id = str(row.get("Audit ID") or "").strip()
        if not audit_id:
            continue
        priority = str(row.get("Priority") or "").strip().casefold()
        photos = str(row.get("Photos Taken?") or "").strip().casefold()
        link = str(row.get("Photo Folder/Link") or "").strip()
        if photos == "no" and priority in {"high", "critical"}:
            items.append(
                OpenItem(
                    id=f"missing_evidence:{audit_id}:Photos Taken",
                    source="missing_evidence",
                    severity="Warning",
                    category="missing_evidence",
                    title="Missing photo evidence",
                    message="High-priority audit is marked Photos Taken? = No.",
                    audit_id=audit_id,
                    machine=str(row.get("Press/Machine #") or ""),
                    field="Photos Taken?",
                    target_type="photo",
                    status="Open",
                    recommended_action="Capture photos or mark why evidence is unavailable.",
                )
            )
        if photos == "yes" and not link:
            items.append(
                OpenItem(
                    id=f"missing_evidence:{audit_id}:Photo Folder Link",
                    source="missing_evidence",
                    severity="Info",
                    category="missing_evidence",
                    title="Photo folder/link missing",
                    message="Photos are marked taken but no local folder or link is recorded.",
                    audit_id=audit_id,
                    machine=str(row.get("Press/Machine #") or ""),
                    field="Photo Folder/Link",
                    target_type="photo",
                    status="Open",
                    recommended_action="Record the local photo folder or evidence reference.",
                )
            )
    return items


def _documentation_gap_items(project_root: Path) -> list[OpenItem]:
    rows = _inventory_rows(project_root)
    fields = ["Drawing/CAD Available?", "BOM Available?", "Process Binder Complete?", "Spare Parts Identified?"]
    items: list[OpenItem] = []
    for row in rows:
        audit_id = str(row.get("Audit ID") or "").strip()
        if not audit_id:
            continue
        for field in fields:
            value = str(row.get(field) or "").strip().casefold()
            if value in {"no", "", "unknown / not checked"}:
                items.append(
                        OpenItem(
                        id=f"documentation_gap:{audit_id}:{field}",
                        source="documentation_gap",
                        severity="Info",
                        category="documentation_gap",
                        title=f"Documentation gap: {field}",
                        message=f"{field} is {row.get(field) or 'blank'}.",
                        audit_id=audit_id,
                        machine=str(row.get("Press/Machine #") or ""),
                        field=field,
                        target_type="audit_field",
                        status="Open",
                        recommended_action="Find the documentation or mark the gap intentionally.",
                    )
                )
    return items


def _inventory_rows(project_root: Path) -> list[dict[str, object]]:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return []
    try:
        return row_dicts(paths.master_workbook, "EOAT Inventory")
    except Exception:
        return []


def _open_items_dir(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).project_admin / "open_items"


def _override_path(project_root: str | Path) -> Path:
    return _open_items_dir(project_root) / "open_item_overrides.jsonl"


def _state_ledger_path(project_root: str | Path) -> Path:
    return _open_items_dir(project_root) / "open_item_state.jsonl"


def _snapshot_path(project_root: str | Path, *, include_validation: bool = True) -> Path:
    suffix = "" if include_validation else "_without_validation"
    return _open_items_dir(project_root) / f"open_item_snapshot{suffix}.json"


def _append_jsonl(path: Path, record: dict[str, object]) -> None:
    ensure_directory(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


def _override_map(project_root: str | Path) -> dict[str, dict[str, object]]:
    overrides: dict[str, dict[str, object]] = {}
    for record in _read_jsonl(_override_path(project_root)):
        item_id = str(record.get("item_id") or "")
        if item_id:
            overrides[item_id] = record
    return overrides


def _apply_overrides(items: list[OpenItem], overrides: dict[str, dict[str, object]]) -> list[OpenItem]:
    resolved: list[OpenItem] = []
    for item in items:
        override = overrides.get(item.id)
        if override:
            resolved.append(
                replace(
                    item,
                    status=STATUS_DISMISSED,
                    dismissed_reason=str(override.get("reason") or ""),
                    dismissed_at=str(override.get("dismissed_at") or ""),
                    updated_at=str(override.get("updated_at") or override.get("dismissed_at") or item.updated_at),
                )
            )
        else:
            resolved.append(item)
    return resolved


def _record_source_fixes(project_root: str | Path, current_items: list[OpenItem], overrides: dict[str, dict[str, object]], *, include_validation: bool = True) -> None:
    snapshot_path = _snapshot_path(project_root, include_validation=include_validation)
    previous = _read_snapshot(snapshot_path)
    current_records = [_item_record(item) for item in current_items]
    _write_snapshot(snapshot_path, current_records)
    if not previous:
        return
    current_ids = {str(record.get("item_id") or "") for record in current_records}
    current_identities = {_source_identity(record) for record in current_records}
    existing_fixed = {
        str(record.get("item_id") or "")
        for record in _read_jsonl(_state_ledger_path(project_root))
        if str(record.get("status") or "") == STATUS_FIXED_AT_SOURCE
    }
    for record in previous:
        item_id = str(record.get("item_id") or "")
        if not item_id or item_id in current_ids or item_id in overrides or item_id in existing_fixed:
            continue
        if _source_identity(record) in current_identities:
            continue
        now = utc_now()
        fixed_record = {
            **record,
            "status": STATUS_FIXED_AT_SOURCE,
            "resolved_at": now,
            "fixed_at": now,
            "updated_at": now,
            "resolution_type": "source_diff",
            "reason": "Previously generated item no longer appears after source refresh.",
        }
        _append_jsonl(_state_ledger_path(project_root), fixed_record)


def _fixed_history_items(project_root: str | Path) -> list[OpenItem]:
    latest: dict[str, dict[str, object]] = {}
    for record in _read_jsonl(_state_ledger_path(project_root)):
        if str(record.get("status") or "") != STATUS_FIXED_AT_SOURCE:
            continue
        item_id = str(record.get("item_id") or "")
        if item_id:
            latest[item_id] = record
    return [_item_from_record(record) for record in latest.values()]


def _read_snapshot(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [record for record in data if isinstance(record, dict)]


def _write_snapshot(path: Path, records: list[dict[str, object]]) -> None:
    ensure_directory(path.parent)
    project_root = _project_root_from_snapshot_path(path)
    safe_records = [_sanitize_snapshot_value(record, project_root) for record in records]
    path.write_text(json.dumps(safe_records, indent=2, sort_keys=True), encoding="utf-8")


def _project_root_from_snapshot_path(path: Path) -> Path:
    # Snapshot files live under <project>/00_Project_Admin/open_items.
    try:
        return path.resolve().parents[2]
    except IndexError:
        return path.resolve().parent


def _safe_project_root_label(project_root: str | Path) -> str:
    root = Path(project_root)
    parts = tuple(part.casefold() for part in root.parts)
    if "examples" in parts and "demo_project" in parts:
        return "examples/demo_project"
    return "<project_root>"


def _sanitize_snapshot_value(value: object, project_root: Path) -> object:
    if isinstance(value, dict):
        return {str(key): _sanitize_snapshot_value(item, project_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_snapshot_value(item, project_root) for item in value]
    if isinstance(value, str):
        label = _safe_project_root_label(project_root)
        candidates = {str(project_root), str(project_root.resolve()), project_root.as_posix()}
        sanitized = value
        for candidate in sorted(candidates, key=len, reverse=True):
            if candidate:
                sanitized = sanitized.replace(candidate, label)
        return sanitized
    return value


def _item_record(item: OpenItem) -> dict[str, object]:
    return {
        "item_id": item.id,
        "source": item.source,
        "severity": item.severity,
        "category": item.category,
        "title": item.title,
        "message": item.message,
        "audit_id": item.audit_id,
        "machine": item.machine,
        "field": item.field,
        "target_id": item.target_id,
        "target_type": item.target_type,
        "due_date": item.due_date,
        "status": item.status,
        "recommended_action": item.recommended_action,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _item_from_record(record: dict[str, object]) -> OpenItem:
    return OpenItem(
        id=str(record.get("item_id") or ""),
        source=str(record.get("source") or ""),
        severity=str(record.get("severity") or "Info"),
        category=str(record.get("category") or ""),
        title=str(record.get("title") or "Fixed at source"),
        message=str(record.get("message") or ""),
        audit_id=str(record.get("audit_id") or ""),
        machine=str(record.get("machine") or ""),
        field=str(record.get("field") or ""),
        target_id=str(record.get("target_id") or ""),
        target_type=str(record.get("target_type") or ""),
        due_date=str(record.get("due_date") or ""),
        status=str(record.get("status") or STATUS_FIXED_AT_SOURCE),
        recommended_action=str(record.get("recommended_action") or ""),
        created_at=str(record.get("created_at") or ""),
        updated_at=str(record.get("updated_at") or record.get("fixed_at") or record.get("resolved_at") or ""),
        dismissed_reason=str(record.get("reason") or ""),
        dismissed_at=str(record.get("dismissed_at") or ""),
        fixed_at=str(record.get("fixed_at") or record.get("resolved_at") or ""),
    )


def _source_identity(record: dict[str, object]) -> tuple[str, str, str, str, str, str]:
    return (
        str(record.get("source") or ""),
        str(record.get("category") or ""),
        str(record.get("audit_id") or ""),
        str(record.get("machine") or ""),
        str(record.get("field") or ""),
        str(record.get("target_type") or ""),
    )


def _normalize_status(value: Any) -> str:
    text = str(value or "").strip().casefold()
    mapping = {
        "": "Open",
        "new": "Open",
        "not started": "Open",
        "open": "Open",
        "needs follow-up": "Open",
        "needs follow up": "Open",
        "in progress": "In Progress",
        "waiting": "Waiting on Info",
        "waiting on info": "Waiting on Info",
        "blocked": "Blocked",
        "resolved": STATUS_FIXED_AT_SOURCE,
        "fixed": STATUS_FIXED_AT_SOURCE,
        "fixed at source": STATUS_FIXED_AT_SOURCE,
        "complete": STATUS_FIXED_AT_SOURCE,
        "completed": STATUS_FIXED_AT_SOURCE,
        "closed": STATUS_FIXED_AT_SOURCE,
        "done": STATUS_FIXED_AT_SOURCE,
        "archived": STATUS_DISMISSED,
        "dismissed": STATUS_DISMISSED,
        "dismissed / overridden": STATUS_DISMISSED,
        "overridden": STATUS_DISMISSED,
    }
    return mapping.get(text, str(value or "Open").strip() or "Open")


def _status_from_source(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text in RESOLVED_SOURCE_STATUSES:
        return STATUS_FIXED_AT_SOURCE if text not in {"archived", "dismissed"} else STATUS_DISMISSED
    return _normalize_status(value)


def _note_severity(importance: Any) -> str:
    text = str(importance or "").strip().casefold()
    if text == "critical":
        return "Critical"
    if text == "important":
        return "Warning"
    return "Info"


def _severity_for_tag(tag_name: str) -> str:
    folded = tag_name.casefold()
    if "data conflict" in folded or "safety" in folded:
        return "Critical"
    if "missing evidence" in folded or "compatibility" in folded or "needs review" in folded:
        return "Warning"
    return "Info"


def _category_for_tag(tag_name: str) -> str:
    folded = tag_name.casefold()
    if "data conflict" in folded:
        return "data_conflict"
    if "missing evidence" in folded:
        return "missing_evidence"
    if "documentation" in folded:
        return "documentation_gap"
    if "compatibility" in folded:
        return "compatibility_concern"
    if "follow" in folded:
        return "follow_up"
    return "tag"


def _action_for_tag(tag_name: str) -> str:
    category = _category_for_tag(tag_name)
    actions = {
        "data_conflict": "Resolve the conflicting audit data or document the exception.",
        "missing_evidence": "Add evidence or explain why evidence is unavailable.",
        "documentation_gap": "Find or create the missing documentation.",
        "compatibility_concern": "Review the compatible-row relationship.",
        "follow_up": "Complete the follow-up action.",
    }
    return actions.get(category, "Review the tagged target.")


def _severity_for_priority(priority: Any, status: str) -> str:
    if status == "Blocked":
        return "Critical"
    text = str(priority or "").strip().casefold()
    if text == "critical":
        return "Critical"
    if text == "high":
        return "Warning"
    return "Info"


def _sort_key(item: OpenItem, today: date) -> tuple[int, int, str, str]:
    severity_rank = {"critical": 0, "error": 1, "warning": 2, "info": 3}.get(item.severity.casefold(), 4)
    due = _date_or_none(item.due_date)
    due_rank = 0 if due and due < today else 1 if due else 2
    return severity_rank, due_rank, item.source, item.title.casefold()


def _date_or_none(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _short_hash(*parts: Any) -> str:
    text = "\u241f".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "OPEN_ITEM_STATUSES",
    "OpenItem",
    "dismiss_open_item",
    "export_open_items_report",
    "load_cached_open_items",
    "load_cached_open_items_summary",
    "list_open_items",
    "open_items_summary",
    "open_items_summary_cache_path",
    "save_cached_open_items_summary",
    "set_open_item_status",
    "summarize_open_items",
]
