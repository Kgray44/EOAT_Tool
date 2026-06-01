from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from core.paths import resolve_project_paths
from core.safe_files import ensure_directory, safe_write_text


def annotation_export_dir(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).annotation_exports


def unique_export_path(project_root: str | Path, base_name: str, extension: str) -> Path:
    folder = ensure_directory(annotation_export_dir(project_root))
    suffix = extension if extension.startswith(".") else f".{extension}"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = folder / f"{base_name}_{stamp}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = folder / f"{base_name}_{stamp}_{counter}{suffix}"
        counter += 1
    return candidate


def export_notes_markdown(project_root: str | Path, notes: Iterable[dict[str, object]]) -> Path:
    lines = ["# EOAT Notes Export", ""]
    for note in notes:
        lines.extend(
            [
                f"## {note.get('subject') or 'Untitled Note'}",
                "",
                f"- Importance: {note.get('importance') or 'Neutral'}",
                f"- Status: {note.get('status') or ''}",
                f"- Collection: {note.get('collection') or ''}",
                f"- Note Type: {note.get('note_type') or ''}",
                f"- Follow-Up Date: {note.get('follow_up_date') or ''}",
                f"- Created: {note.get('created_at') or ''}",
                f"- Updated: {note.get('updated_at') or ''}",
                "",
                str(note.get("body_markdown") or ""),
                "",
            ]
        )
        tags = note.get("tags") or []
        if tags:
            lines.extend(
                ["Related tags: " + ", ".join(str(tag.get("name") or "") for tag in tags if isinstance(tag, dict)), ""]
            )
        targets = note.get("targets") or []
        if targets:
            lines.extend(["Linked targets:"])
            for target in targets:
                if isinstance(target, dict):
                    lines.append(
                        f"- {target.get('target_type')}: {target.get('target_label') or target.get('object_ref') or target.get('audit_id') or ''}"
                    )
            lines.append("")
    path = unique_export_path(project_root, "notes_export", ".md")
    return safe_write_text(path, "\n".join(lines).rstrip() + "\n", overwrite=False)


def export_notes_excel(project_root: str | Path, notes: Iterable[dict[str, object]]) -> Path:
    path = unique_export_path(project_root, "notes_export", ".xlsx")
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Notes"
    headers = [
        "ID",
        "Subject",
        "Importance",
        "Status",
        "Collection",
        "Note Type",
        "Follow-Up Date",
        "Created",
        "Updated",
        "Tags",
        "Targets",
        "Body Markdown",
    ]
    ws.append(headers)
    for note in notes:
        tags = ", ".join(str(tag.get("name") or "") for tag in note.get("tags") or [] if isinstance(tag, dict))
        targets = ", ".join(
            str(target.get("target_label") or target.get("object_ref") or "")
            for target in note.get("targets") or []
            if isinstance(target, dict)
        )
        ws.append(
            [
                note.get("id"),
                note.get("subject"),
                note.get("importance"),
                note.get("status"),
                note.get("collection"),
                note.get("note_type"),
                note.get("follow_up_date"),
                note.get("created_at"),
                note.get("updated_at"),
                tags,
                targets,
                note.get("body_markdown"),
            ]
        )
    workbook.save(path)
    workbook.close()
    return path


def export_tags_markdown(project_root: str | Path, assignments: Iterable[dict[str, object]]) -> Path:
    lines = ["# EOAT Tags Export", ""]
    for assignment in assignments:
        lines.extend(
            [
                f"## {assignment.get('tag_name') or assignment.get('name') or 'Tag'}",
                "",
                f"- Color: {assignment.get('color_key') or ''}",
                f"- Target Type: {assignment.get('target_type') or ''}",
                f"- Target: {assignment.get('target_label') or assignment.get('object_ref') or ''}",
                f"- Audit ID: {assignment.get('audit_id') or ''}",
                f"- Machine: {assignment.get('machine_id') or ''}",
                f"- Field: {assignment.get('field_label') or assignment.get('field_key') or ''}",
                f"- Comment: {assignment.get('comment') or ''}",
                f"- Updated: {assignment.get('updated_at') or ''}",
                "",
            ]
        )
    path = unique_export_path(project_root, "tags_export", ".md")
    return safe_write_text(path, "\n".join(lines).rstrip() + "\n", overwrite=False)


def export_tags_excel(project_root: str | Path, assignments: Iterable[dict[str, object]]) -> Path:
    path = unique_export_path(project_root, "tags_export", ".xlsx")
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Tags"
    ws.append(
        [
            "Assignment ID",
            "Tag ID",
            "Tag Name",
            "Color",
            "Target ID",
            "Target Type",
            "Target Label",
            "Audit ID",
            "Machine",
            "Field Key",
            "Field Label",
            "Comment",
            "Created",
            "Updated",
        ]
    )
    for assignment in assignments:
        ws.append(
            [
                assignment.get("assignment_id") or assignment.get("id"),
                assignment.get("tag_id"),
                assignment.get("tag_name") or assignment.get("name"),
                assignment.get("color_key"),
                assignment.get("target_id"),
                assignment.get("target_type"),
                assignment.get("target_label"),
                assignment.get("audit_id"),
                assignment.get("machine_id"),
                assignment.get("field_key"),
                assignment.get("field_label"),
                assignment.get("comment"),
                assignment.get("created_at"),
                assignment.get("updated_at"),
            ]
        )
    workbook.save(path)
    workbook.close()
    return path
