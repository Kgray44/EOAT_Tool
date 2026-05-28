from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field as dataclass_field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .annotations.database import annotation_database_path
from .annotations.service import AnnotationService
from .audit_compatibility import machine_from_audit_row, normalize_entry_type, part_number_from_row, text_value
from .gripper_fields import CUP_COUNT_FIELD
from .open_items import list_open_items
from .paths import resolve_project_paths
from .reports import report_folders, read_report_preview
from .tool_fields import TOOL_FIELD
from .workbook_io import row_dicts


@dataclass(frozen=True)
class SearchFilters:
    result_types: tuple[str, ...] = ()
    audit_id: str = ""
    machine: str = ""
    tag: str = ""
    status: str = ""
    severity: str = ""
    date: str = ""
    due_date: str = ""


@dataclass(frozen=True)
class SearchResult:
    result_id: str
    result_type: str
    title: str
    subtitle: str = ""
    detail: str = ""
    audit_id: str = ""
    machine: str = ""
    field: str = ""
    target_id: str = ""
    path: str = ""
    action: str = ""
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def search_project(project_root: str | Path, query: str = "", filters: SearchFilters | None = None, *, limit: int = 100) -> list[SearchResult]:
    filters = filters or SearchFilters()
    query_text = query.strip()
    results: list[SearchResult] = []
    sources = [
        _audit_results,
        _machine_results,
        _note_results,
        _tag_results,
        _open_item_results,
        _validation_results,
        _report_results,
        _photo_results,
    ]
    for source in sources:
        if len(results) >= limit:
            break
        try:
            source_results = source(project_root, query_text, filters)
        except Exception:
            source_results = []
        for result in source_results:
            if _matches_filters(result, filters) and _matches_query(result, query_text):
                results.append(result)
                if len(results) >= limit:
                    break
    return results[:limit]


def sqlite_fts_status(project_root: str | Path) -> dict[str, Any]:
    db_path = annotation_database_path(project_root)
    if not db_path.exists():
        return {
            "available": False,
            "mode": "like_fallback",
            "reason": "Annotation database does not exist yet; search uses workbook/report sources and skips note/tag FTS.",
        }
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND lower(sql) LIKE '%virtual table%' AND lower(sql) LIKE '%fts%'"
            ).fetchall()
    except sqlite3.Error as exc:
        return {"available": False, "mode": "like_fallback", "reason": f"Could not inspect annotation FTS tables: {exc}"}
    tables = [str(row[0]) for row in rows]
    if tables:
        return {"available": True, "mode": "sqlite_fts", "tables": tables, "reason": "Annotation FTS tables are available."}
    return {
        "available": False,
        "mode": "like_fallback",
        "reason": "Annotation database exists, but no FTS virtual tables are installed; existing indexed LIKE searches are used.",
    }


def _audit_rows(project_root: str | Path) -> list[dict[str, Any]]:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return []
    return row_dicts(paths.master_workbook, "EOAT Inventory")


def _audit_results(project_root: str | Path, _query: str, _filters: SearchFilters) -> list[SearchResult]:
    results: list[SearchResult] = []
    for row in _audit_rows(project_root):
        audit_id = text_value(row.get("Audit ID"))
        if not audit_id:
            continue
        machine = machine_from_audit_row(row)
        status = text_value(row.get("Status"))
        entry_type = normalize_entry_type(row.get("Entry Type"))
        title = f"Audit {audit_id}"
        subtitle = " | ".join(piece for piece in [f"Press {machine}" if machine else "", f"Machine {machine}" if machine else "", text_value(row.get("EOAT Type")), status, entry_type] if piece)
        detail = " | ".join(
            piece
            for piece in [
                text_value(row.get(TOOL_FIELD)),
                text_value(row.get("Part Family")),
                text_value(row.get("Part Name/Description")),
                _field_value_summary(row, CUP_COUNT_FIELD),
                text_value(row.get("Known Issues")),
                text_value(row.get("Notes")),
            ]
            if piece
        )
        results.append(
            SearchResult(
                result_id=f"audit:{audit_id}",
                result_type="audit",
                title=title,
                subtitle=subtitle,
                detail=detail,
                audit_id=audit_id,
                machine=machine,
                action="open_audit",
                metadata={"status": status, "entry_type": entry_type, "date": _date_value(row.get("Audit Date"))},
            )
        )
    return results


def _machine_results(project_root: str | Path, _query: str, _filters: SearchFilters) -> list[SearchResult]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in _audit_rows(project_root):
        machine = machine_from_audit_row(row)
        if machine:
            grouped.setdefault(machine, []).append(row)
    results: list[SearchResult] = []
    for machine, rows in grouped.items():
        physical = sum(1 for row in rows if normalize_entry_type(row.get("Entry Type")) != "Compatible")
        compatible = len(rows) - physical
        tools = sorted({part_number_from_row(row) or text_value(row.get(TOOL_FIELD)) for row in rows if part_number_from_row(row) or text_value(row.get(TOOL_FIELD))})
        results.append(
            SearchResult(
                result_id=f"machine:{machine}",
                result_type="machine",
                title=f"Press {machine}",
                subtitle=f"{physical} physical / {compatible} compatible / {len(rows)} total audit row(s)",
                detail=", ".join(tools[:8]),
                machine=machine,
                action="open_press",
                metadata={"status": _combined_status(rows), "physical": physical, "compatible": compatible},
            )
        )
    return sorted(results, key=lambda item: item.title.casefold())


def _note_results(project_root: str | Path, query: str, filters: SearchFilters) -> list[SearchResult]:
    db_path = annotation_database_path(project_root)
    if not db_path.exists():
        return []
    service = AnnotationService(project_root)
    notes = service.search_notes(
        query,
        status=filters.status or None,
        audit_id=filters.audit_id or None,
        machine_id=filters.machine or None,
        tag_name=filters.tag or None,
        follow_up_due_before=filters.due_date or None,
        include_archived=True,
    )
    results: list[SearchResult] = []
    for note in notes:
        targets = list(note.get("targets") or [])
        primary = targets[0] if targets else {}
        audit_id = str(primary.get("audit_id") or "")
        machine = str(primary.get("machine_id") or "")
        note_id = str(note.get("id") or "")
        results.append(
            SearchResult(
                result_id=f"note:{note_id}",
                result_type="note",
                title=str(note.get("subject") or "Note"),
                subtitle=" | ".join(piece for piece in [str(note.get("importance") or ""), str(note.get("status") or ""), audit_id, machine] if piece),
                detail=str(note.get("body_markdown") or ""),
                audit_id=audit_id,
                machine=machine,
                target_id=note_id,
                action="open_note",
                metadata={"status": note.get("status") or "", "due_date": note.get("follow_up_date") or "", "date": note.get("updated_at") or note.get("created_at") or ""},
            )
        )
    return results


def _tag_results(project_root: str | Path, query: str, filters: SearchFilters) -> list[SearchResult]:
    db_path = annotation_database_path(project_root)
    if not db_path.exists():
        return []
    service = AnnotationService(project_root)
    results: list[SearchResult] = []
    for tag in service.search_tags(query, include_archived=True):
        if filters.tag and filters.tag.casefold() not in tag.name.casefold():
            continue
        results.append(
            SearchResult(
                result_id=f"tag:{tag.id}",
                result_type="tag",
                title=f"Tag: {tag.name}",
                subtitle=tag.color_key,
                detail=tag.description or "",
                target_id=tag.id,
                action="open_tag",
                metadata={"tag": tag.name, "status": "Archived" if tag.is_archived else "Open", "date": tag.updated_at},
            )
        )
    for assignment in service.list_tag_assignments(query=query, audit_id=filters.audit_id or None, machine_id=filters.machine or None):
        tag_name = str(assignment.get("tag_name") or "")
        if filters.tag and filters.tag.casefold() not in tag_name.casefold():
            continue
        results.append(
            SearchResult(
                result_id=f"tag_assignment:{assignment.get('assignment_id')}",
                result_type="tag",
                title=f"{tag_name}: {assignment.get('target_label') or assignment.get('field_label') or assignment.get('object_ref') or 'target'}",
                subtitle=str(assignment.get("target_type") or ""),
                detail=str(assignment.get("comment") or ""),
                audit_id=str(assignment.get("audit_id") or ""),
                machine=str(assignment.get("machine_id") or ""),
                field=str(assignment.get("field_label") or assignment.get("field_key") or ""),
                target_id=str(assignment.get("assignment_id") or ""),
                action="open_tag",
                metadata={"tag": tag_name, "date": assignment.get("assignment_updated_at") or assignment.get("updated_at") or ""},
            )
        )
    return results


def _open_item_results(project_root: str | Path, _query: str, _filters: SearchFilters) -> list[SearchResult]:
    items = list_open_items(project_root, include_resolved=True, include_validation=False)
    return [
        SearchResult(
            result_id=f"open_item:{item.id}",
            result_type="open_item",
            title=item.title,
            subtitle=" | ".join(piece for piece in [item.source, item.severity, item.status] if piece),
            detail=item.message or item.recommended_action,
            audit_id=item.audit_id,
            machine=item.machine,
            field=item.field,
            target_id=item.id,
            action="open_open_item",
            metadata={"status": item.status, "severity": item.severity, "due_date": item.due_date, "date": item.updated_at or item.created_at},
        )
        for item in items
    ]


def _validation_results(project_root: str | Path, _query: str, _filters: SearchFilters) -> list[SearchResult]:
    payload = _latest_validation_payload(project_root)
    findings = list(payload.get("findings") or []) if payload else []
    results: list[SearchResult] = []
    for finding in findings:
        finding_id = str(finding.get("finding_id") or "")
        results.append(
            SearchResult(
                result_id=f"validation:{finding_id}",
                result_type="validation",
                title=str(finding.get("message") or "Validation finding"),
                subtitle=" | ".join(piece for piece in [str(finding.get("severity") or ""), str(finding.get("category") or ""), str(finding.get("sheet_name") or "")] if piece),
                detail=str(finding.get("recommended_action") or finding.get("expected_behavior") or ""),
                audit_id=str(finding.get("audit_id") or ""),
                machine=str(finding.get("machine_number") or ""),
                field=str(finding.get("column_name") or ""),
                target_id=finding_id,
                action="open_validation",
                metadata={"severity": finding.get("severity") or "", "category": finding.get("category") or "", "path": payload.get("_path", "")},
            )
        )
    return results


def _report_results(project_root: str | Path, query: str, _filters: SearchFilters) -> list[SearchResult]:
    results: list[SearchResult] = []
    for folder in report_folders(project_root, limit=20):
        for path in folder.recent_files:
            detail = ""
            if query and query.casefold() not in path.name.casefold() and path.suffix.lower() in {".md", ".txt", ".json", ".csv", ".log", ".jsonl"}:
                preview, _warning = read_report_preview(path, max_chars=1500)
                detail = preview[:500]
            results.append(
                SearchResult(
                    result_id=f"report:{path}",
                    result_type="report",
                    title=path.name,
                    subtitle=folder.label,
                    detail=detail,
                    path=str(path),
                    action="open_report",
                    metadata={"date": _file_date(path), "status": "Exists"},
                )
            )
    return results


def _photo_results(project_root: str | Path, _query: str, _filters: SearchFilters) -> list[SearchResult]:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return []
    try:
        rows = row_dicts(paths.master_workbook, "Photo Index")
    except Exception:
        return []
    results: list[SearchResult] = []
    for row in rows:
        photo_id = text_value(row.get("Photo ID"))
        filename = text_value(row.get("Photo Filename"))
        if not photo_id and not filename:
            continue
        folder = text_value(row.get("Folder Path"))
        path = str(Path(folder) / filename) if folder and filename else folder
        results.append(
            SearchResult(
                result_id=f"photo:{photo_id or filename}",
                result_type="photo",
                title=filename or photo_id,
                subtitle=" | ".join(piece for piece in [text_value(row.get("EOAT Area Shown")), text_value(row.get("Date Taken"))] if piece),
                detail=" | ".join(piece for piece in [text_value(row.get("Description")), text_value(row.get("Notes"))] if piece),
                audit_id=text_value(row.get("Related Audit ID")),
                machine=text_value(row.get("Press/Machine #")),
                path=path,
                action="open_photo",
                metadata={"date": text_value(row.get("Date Taken")), "status": "Indexed"},
            )
        )
    return results


def _latest_validation_payload(project_root: str | Path) -> dict[str, Any]:
    folder = resolve_project_paths(project_root).validation_reports
    if not folder.exists():
        return {}
    for path in sorted(folder.glob("Foundation_Validation_*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload["_path"] = str(path)
        return payload
    return {}


def _matches_query(result: SearchResult, query: str) -> bool:
    if not query:
        return True
    needle = query.casefold()
    haystack = " ".join(
        [
            result.result_type,
            result.title,
            result.subtitle,
            result.detail,
            result.audit_id,
            result.machine,
            result.field,
            result.target_id,
            result.path,
            " ".join(str(value) for value in result.metadata.values()),
        ]
    ).casefold()
    return needle in haystack


def _field_value_summary(row: dict[str, Any], field: str) -> str:
    value = text_value(row.get(field))
    if not value or value.upper() in {"N/A", "NA", "NOT APPLICABLE"}:
        return ""
    return f"{field}: {value}"


def _matches_filters(result: SearchResult, filters: SearchFilters) -> bool:
    if filters.result_types and result.result_type not in filters.result_types:
        return False
    comparisons = [
        (filters.audit_id, result.audit_id),
        (filters.machine, result.machine),
        (filters.status, str(result.metadata.get("status") or "")),
        (filters.severity, str(result.metadata.get("severity") or "")),
        (filters.date, str(result.metadata.get("date") or "")),
        (filters.due_date, str(result.metadata.get("due_date") or "")),
    ]
    for expected, actual in comparisons:
        if expected and expected.casefold() not in actual.casefold():
            return False
    if filters.tag:
        tag_text = " ".join([str(result.metadata.get("tag") or ""), result.title, result.subtitle, result.detail]).casefold()
        if filters.tag.casefold() not in tag_text:
            return False
    return True


def _combined_status(rows: Iterable[dict[str, Any]]) -> str:
    statuses = [text_value(row.get("Status")) for row in rows if text_value(row.get("Status"))]
    if not statuses:
        return ""
    unique = list(dict.fromkeys(statuses))
    return ", ".join(unique[:3])


def _date_value(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return text_value(value)


def _file_date(path: Path) -> str:
    try:
        return date.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return ""
