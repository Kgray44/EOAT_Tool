from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from pathlib import Path
from typing import Any

from .annotations.database import annotation_database_path
from .annotations.service import AnnotationService
from .audit.history import read_audit_history
from .logging import read_recent_activity
from .open_items import list_open_items
from .paths import resolve_project_paths
from .reports import report_folders
from .workbook_io import row_dicts


@dataclass(frozen=True)
class TimelineEvent:
    timestamp: str
    event_type: str
    title: str
    source: str
    audit_id: str = ""
    machine: str = ""
    field: str = ""
    detail: str = ""
    path: str = ""
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_timeline(project_root: str | Path, *, limit: int = 200) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    events.extend(_audit_history_events(project_root))
    events.extend(_activity_events(project_root))
    events.extend(_annotation_events(project_root))
    events.extend(_open_item_events(project_root))
    events.extend(_validation_events(project_root))
    events.extend(_photo_events(project_root))
    events.extend(_report_file_events(project_root))
    events.sort(key=lambda event: event.timestamp or "", reverse=True)
    return events[: max(1, int(limit))]


def timeline_event_counts(project_root: str | Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in build_timeline(project_root, limit=10000):
        counts[event.event_type] = counts.get(event.event_type, 0) + 1
    return counts


def _audit_history_events(project_root: str | Path) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for record in read_audit_history(project_root):
        event_type = str(record.get("event_type") or "")
        changed_fields = [str(field) for field in record.get("changed_fields") or []]
        audit_id = str(record.get("audit_id") or "")
        timestamp = str(record.get("timestamp") or "")
        if event_type == "created":
            events.append(
                TimelineEvent(
                    timestamp,
                    "audit_created",
                    f"Audit created: {audit_id}",
                    "audit_history",
                    audit_id=audit_id,
                    metadata=record,
                )
            )
        elif event_type in {"updated", "audit_updated"}:
            events.append(
                TimelineEvent(
                    timestamp,
                    "audit_updated",
                    f"Audit updated: {audit_id}",
                    "audit_history",
                    audit_id=audit_id,
                    detail=", ".join(changed_fields),
                    metadata=record,
                )
            )
        elif event_type == "compatibility_sync":
            events.append(
                TimelineEvent(
                    timestamp,
                    "compatibility_rows_updated",
                    f"Compatibility rows updated for {audit_id}",
                    "audit_history",
                    audit_id=audit_id,
                    detail=", ".join(changed_fields),
                    metadata=record,
                )
            )
        elif event_type in {"validation_auto_fix", "workbook_repair"}:
            events.append(
                TimelineEvent(
                    timestamp,
                    "field_changed",
                    f"Workbook fields changed for {audit_id}",
                    "audit_history",
                    audit_id=audit_id,
                    detail=", ".join(changed_fields),
                    metadata=record,
                )
            )
        else:
            events.append(
                TimelineEvent(
                    timestamp,
                    event_type or "audit_updated",
                    f"Audit history event: {audit_id}",
                    "audit_history",
                    audit_id=audit_id,
                    detail=", ".join(changed_fields),
                    metadata=record,
                )
            )
        for field in changed_fields:
            old_value = (record.get("old_values") or {}).get(field, "")
            new_value = (record.get("new_values") or {}).get(field, "")
            field_type = (
                "manual_override_applied"
                if field == "Manual Completion Override" and str(new_value).casefold() == "yes"
                else "field_changed"
            )
            events.append(
                TimelineEvent(
                    timestamp,
                    field_type,
                    f"{field} changed on {audit_id}",
                    "audit_history",
                    audit_id=audit_id,
                    field=field,
                    detail=f"{old_value} -> {new_value}",
                    metadata=record,
                )
            )
            if field.startswith("Robot") or field in {
                "EOAT Vacuum Circuits",
                "EOAT Pressure Circuits",
                "EOAT Interchangeable Circuits",
            }:
                events.append(
                    TimelineEvent(
                        timestamp,
                        "robot_info_updated",
                        f"Robot info related field changed on {audit_id}",
                        "audit_history",
                        audit_id=audit_id,
                        field=field,
                        detail=f"{old_value} -> {new_value}",
                        metadata=record,
                    )
                )
    return events


def _activity_events(project_root: str | Path) -> list[TimelineEvent]:
    entries, _warning = read_recent_activity(project_root, limit=1000)
    events: list[TimelineEvent] = []
    for entry in entries:
        tool_id = str(entry.get("tool_id") or entry.get("event_name") or "")
        tool_name = str(entry.get("tool_name") or tool_id or "Activity")
        timestamp = str(entry.get("timestamp") or "")
        files_created = [str(path) for path in entry.get("files_created") or []]
        event_type = (
            "report_generated"
            if any(_is_report_file(path) for path in files_created) or "report" in tool_id
            else "activity"
        )
        if "pm_checklist" in tool_id:
            event_type = "pm_checklist_generated"
        if "photo" in tool_id:
            event_type = "photo_evidence_added"
        events.append(
            TimelineEvent(
                timestamp,
                event_type,
                tool_name,
                "activity_log",
                detail=str(entry.get("summary") or ""),
                path=files_created[0] if files_created else "",
                metadata=entry,
            )
        )
    return events


def _annotation_events(project_root: str | Path) -> list[TimelineEvent]:
    if not annotation_database_path(project_root).exists():
        return []
    try:
        service = AnnotationService(project_root)
        notes = service.search_notes(include_archived=True)
        tags = service.list_tag_assignments(include_archived=True)
    except Exception:
        return []
    events: list[TimelineEvent] = []
    for note in notes:
        target = (note.get("targets") or [{}])[0] if isinstance(note.get("targets"), list) else {}
        events.append(
            TimelineEvent(
                str(note.get("created_at") or note.get("updated_at") or ""),
                "note_added",
                str(note.get("subject") or "Note added"),
                "annotations",
                audit_id=str(target.get("audit_id") or ""),
                machine=str(target.get("machine_id") or ""),
                detail=str(note.get("body_markdown") or ""),
                metadata=dict(note),
            )
        )
    for assignment in tags:
        events.append(
            TimelineEvent(
                str(assignment.get("assignment_created_at") or assignment.get("created_at") or ""),
                "tag_added",
                f"Tag added: {assignment.get('tag_name') or ''}",
                "annotations",
                audit_id=str(assignment.get("audit_id") or ""),
                machine=str(assignment.get("machine_id") or ""),
                field=str(assignment.get("field_label") or assignment.get("field_key") or ""),
                detail=str(assignment.get("comment") or ""),
                metadata=dict(assignment),
            )
        )
    return events


def _open_item_events(project_root: str | Path) -> list[TimelineEvent]:
    try:
        items = list_open_items(project_root, include_resolved=True)
    except Exception:
        return []
    return [
        TimelineEvent(
            item.created_at or item.updated_at or "",
            "follow_up_created",
            item.title,
            "open_items",
            audit_id=item.audit_id,
            machine=item.machine,
            field=item.field,
            detail=item.message or item.recommended_action,
            metadata=asdict(item) if hasattr(item, "__dataclass_fields__") else dict(getattr(item, "__dict__", {})),
        )
        for item in items
    ]


def _validation_events(project_root: str | Path) -> list[TimelineEvent]:
    folder = resolve_project_paths(project_root).validation_reports
    if not folder.exists():
        return []
    events: list[TimelineEvent] = []
    for path in sorted(folder.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:5]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for finding in payload.get("findings", []) if isinstance(payload, dict) else []:
            if not isinstance(finding, dict):
                continue
            events.append(
                TimelineEvent(
                    str(finding.get("created_at") or finding.get("timestamp") or _file_timestamp(path)),
                    "validation_finding_created",
                    str(finding.get("message") or "Validation finding"),
                    "validation_report",
                    audit_id=str(finding.get("audit_id") or ""),
                    machine=str(finding.get("machine_number") or ""),
                    field=str(finding.get("column_name") or ""),
                    path=str(path),
                    metadata=finding,
                )
            )
    return events


def _photo_events(project_root: str | Path) -> list[TimelineEvent]:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return []
    try:
        rows = row_dicts(paths.master_workbook, "Photo Index")
    except Exception:
        return []
    events: list[TimelineEvent] = []
    for row in rows:
        title = str(row.get("Photo Filename") or row.get("Photo ID") or "Photo evidence added")
        events.append(
            TimelineEvent(
                str(row.get("Date Taken") or ""),
                "photo_evidence_added",
                title,
                "photo_index",
                audit_id=str(row.get("Related Audit ID") or ""),
                machine=str(row.get("Press/Machine #") or ""),
                detail=str(row.get("Description") or row.get("Notes") or ""),
                path=str(Path(str(row.get("Folder Path") or "")) / title) if row.get("Folder Path") else title,
                metadata=dict(row),
            )
        )
    return events


def _report_file_events(project_root: str | Path) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for folder in report_folders(project_root, limit=20):
        for path in folder.recent_files:
            events.append(
                TimelineEvent(
                    _file_timestamp(path),
                    "report_generated",
                    path.name,
                    folder.label,
                    path=str(path),
                    metadata={"folder": folder.label},
                )
            )
    return events


def _file_timestamp(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return ""


def _is_report_file(path: str) -> bool:
    return Path(path).suffix.lower() in {".md", ".txt", ".json", ".csv", ".pdf", ".docx", ".pptx", ".png", ".svg"}


__all__ = ["TimelineEvent", "build_timeline", "timeline_event_counts"]
