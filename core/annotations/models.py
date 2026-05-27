from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Note:
    id: str
    subject: str
    body_markdown: str
    importance: str
    status: str | None
    collection: str | None
    note_type: str | None
    follow_up_date: str | None
    created_at: str
    updated_at: str
    archived_at: str | None = None


@dataclass(frozen=True)
class Tag:
    id: str
    name: str
    color_key: str
    description: str | None
    is_default: bool
    is_archived: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AnnotationTarget:
    id: str
    target_type: str
    target_label: str | None
    audit_id: str | None
    machine_id: str | None
    field_key: str | None
    field_label: str | None
    sheet_name: str | None
    header_name: str | None
    workbook_path: str | None
    cached_cell_ref: str | None
    object_ref: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TagAssignment:
    id: str
    tag_id: str
    target_id: str
    comment: str | None
    created_at: str
    updated_at: str
    archived_at: str | None = None


@dataclass(frozen=True)
class Attachment:
    id: str
    note_id: str | None
    target_id: str | None
    file_path: str
    display_name: str | None
    description: str | None
    created_at: str
