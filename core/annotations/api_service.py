from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from core.data_gateway.gateway import AtlasDataGateway

from .models import AnnotationTarget, Note, Tag, TagAssignment
from .tag_colors import normalize_color_key
from .targets import normalize_target_type, target_id_for


class ApiAnnotationService:
    """Annotation compatibility facade whose authority is the API/MySQL stack."""

    def __init__(self, project_root: str | Path, db_path=None, *, initialize: bool = True):
        self.project_root = Path(project_root)
        self.db_path = None
        self.gateway = AtlasDataGateway()
        self._versions: dict[tuple[str, str], int] = {}
        self._initialized = True

    @property
    def initialized(self) -> bool:
        return True

    def mark_initialized(self) -> None:
        return None

    def ensure_initialized(self) -> None:
        return None

    def connection(self):
        raise RuntimeError("Legacy annotation SQLite access is forbidden in mysql_api mode.")

    def _get(self, path: str, **params):
        return self.gateway.client._request("GET", path, params=params)

    def _write(self, method: str, path: str, payload: dict | None = None):
        return self.gateway._server_first_write(method, path, payload or {})

    def _tag(self, value: dict) -> Tag:
        key = str(value["id"])
        self._versions[("tag", key)] = int(value.get("row_version", 1))
        return Tag(
            id=key,
            name=str(value["display_name"]),
            color_key=str(value["color_key"]),
            description=value.get("description"),
            is_default=bool(value.get("is_default")),
            is_archived=not bool(value.get("is_active", True)),
            created_at=str(value.get("created_at") or ""),
            updated_at=str(value.get("updated_at") or ""),
        )

    def _note(self, value: dict) -> Note:
        key = str(value["id"])
        self._versions[("annotation", key)] = int(value.get("row_version", 1))
        return Note(
            id=key,
            subject=str(value["subject"]),
            body_markdown=str(value.get("body") or ""),
            importance=str(value.get("importance") or "Neutral"),
            status=value.get("status"),
            collection=value.get("collection"),
            note_type=value.get("annotation_type"),
            follow_up_date=value.get("follow_up_date"),
            created_at=str(value.get("created_at") or ""),
            updated_at=str(value.get("updated_at") or ""),
            archived_at=value.get("archived_at"),
        )

    def _target(self, value: dict) -> AnnotationTarget:
        key = str(value["target_uuid"])
        self._versions[("annotation_target", key)] = int(value.get("row_version", 1))
        return AnnotationTarget(
            id=key,
            target_type=str(value["target_type"]),
            target_label=value.get("target_label"),
            audit_id=value.get("audit_identifier"),
            machine_id=value.get("machine_identifier"),
            field_key=value.get("field_key"),
            field_label=value.get("field_label"),
            sheet_name=value.get("sheet_name"),
            header_name=value.get("header_name"),
            workbook_path=value.get("workbook_path"),
            cached_cell_ref=value.get("cached_cell_ref"),
            object_ref=value.get("object_ref"),
            created_at=str(value.get("created_at") or ""),
            updated_at=str(value.get("updated_at") or ""),
        )

    def _assignment(self, value: dict) -> TagAssignment:
        key = str(value["id"])
        self._versions[("entity_tag", key)] = int(value.get("row_version", 1))
        return TagAssignment(
            id=key,
            tag_id=str(value["tag_id"]),
            target_id=str(value.get("target_id") or value.get("entity_id")),
            comment=value.get("comment"),
            created_at=str(value.get("assigned_at") or ""),
            updated_at=str(value.get("assigned_at") or ""),
            archived_at=value.get("removed_at"),
        )

    def create_note(
        self,
        subject: str,
        body_markdown: str = "",
        importance: str = "Neutral",
        *,
        status: str | None = None,
        collection: str | None = None,
        note_type: str | None = None,
        follow_up_date: str | None = None,
        target_ids: Iterable[str] | None = None,
        tag_ids: Iterable[str] | None = None,
        attachment_paths: Iterable[str | Path] | None = None,
    ) -> Note:
        payload = {
            "subject": subject,
            "body": body_markdown or "",
            "importance": importance,
            "status": status,
            "collection": collection,
            "annotation_type": note_type or "note",
            "follow_up_date": follow_up_date,
        }
        targets = [str(value) for value in target_ids or []]
        path = f"/api/v1/entities/annotation_target/{targets[0]}/annotations" if targets else "/api/v1/annotations"
        result = self._write("POST", path, payload)
        self._note(result)
        for target_id in targets:
            result = self.gateway.link_annotation_target(
                int(result["id"]),
                target_id,
                self._versions[("annotation", str(result["id"]))],
            )
            self._note(result)
        for tag_id in tag_ids or []:
            self.gateway.assign_tag("annotation", result["id"], int(tag_id))
        for attachment in attachment_paths or []:
            self.gateway.add_document(
                {
                    "document_type": "document",
                    "title": Path(attachment).name,
                    "storage_path": str(Path(attachment)),
                    "entity_type": "annotation",
                    "entity_id": result["id"],
                }
            )
        return self._note(result)

    def get_note(self, note_id: str) -> Note:
        return self._note(self._get(f"/api/v1/annotations/{note_id}"))

    def update_note(self, note_id: str, **updates: Any) -> Note:
        mapping = {"body_markdown": "body", "note_type": "annotation_type"}
        payload = {mapping.get(key, key): value for key, value in updates.items()}
        expected = self._versions.get(("annotation", str(note_id)))
        if expected is None:
            self.get_note(note_id)
            expected = self._versions[("annotation", str(note_id))]
        return self._note(self.gateway.update_annotation(int(note_id), payload, expected))

    def archive_note(self, note_id: str) -> Note:
        if ("annotation", str(note_id)) not in self._versions:
            self.get_note(note_id)
        return self._note(self.gateway.archive_annotation(int(note_id), self._versions[("annotation", str(note_id))]))

    def search_notes(self, query: str = "", **filters) -> list[dict[str, object]]:
        values = self._get("/api/v1/annotations", query=query, include_archived=filters.get("include_archived", False))
        results = []
        for value in values:
            note = self._note(value)
            if filters.get("importance") not in (None, "All", note.importance):
                continue
            if filters.get("status") not in (None, "All", note.status):
                continue
            results.append(
                {
                    **note.__dict__,
                    "body_markdown": note.body_markdown,
                    "note_type": note.note_type,
                    "targets": [],
                    "tags": [],
                    "attachments": [],
                }
            )
        return results

    def create_tag(
        self, name: str, color_key: str = "yellow", *, description: str | None = None, is_default: bool = False
    ) -> Tag:
        code = "custom_" + "_".join(name.casefold().split())
        return self._tag(
            self.gateway.create_tag(
                {
                    "tag_code": code[:96],
                    "display_name": name,
                    "color_key": normalize_color_key(color_key),
                    "description": description,
                }
            )
        )

    def list_tags(self, *, include_archived: bool = False, sort_by: str = "name") -> list[Tag]:
        return [self._tag(value) for value in self._get("/api/v1/tags", include_archived=include_archived)]

    def search_tags(
        self, query: str = "", *, color_key: str | None = None, include_archived: bool = False, sort_by: str = "name"
    ) -> list[Tag]:
        values = self.list_tags(include_archived=include_archived, sort_by=sort_by)
        folded = query.casefold()
        return [
            tag
            for tag in values
            if (not folded or folded in tag.name.casefold() or folded in (tag.description or "").casefold())
            and (color_key in (None, "All") or tag.color_key == color_key)
        ]

    def get_tag(self, tag_id: str) -> Tag:
        for tag in self.list_tags(include_archived=True):
            if tag.id == str(tag_id):
                return tag
        raise KeyError(tag_id)

    def get_tag_by_name(self, name: str) -> Tag | None:
        folded = name.casefold()
        return next((tag for tag in self.list_tags() if tag.name.casefold() == folded), None)

    def update_tag(self, tag_id: str, **updates: Any) -> Tag:
        tag = self.get_tag(tag_id)
        payload = {"display_name" if key == "name" else key: value for key, value in updates.items()}
        result = self.gateway.update_tag(tag_id, payload, self._versions[("tag", tag.id)])
        return self._tag(result)

    def archive_tag(self, tag_id: str) -> Tag:
        tag = self.get_tag(tag_id)
        return self._tag(self.gateway.archive_tag(tag_id, self._versions[("tag", tag.id)]))

    def create_or_get_target(self, target_type: str, **values) -> AnnotationTarget:
        normalized = normalize_target_type(target_type)
        target_uuid = target_id_for(
            target_type=normalized,
            audit_id=values.get("audit_id", ""),
            machine_id=values.get("machine_id", ""),
            field_key=values.get("field_key", ""),
            object_ref=values.get("object_ref", ""),
        )
        payload = {
            "target_uuid": target_uuid,
            "target_type": normalized,
            "target_label": values.get("target_label"),
            "audit_identifier": values.get("audit_id"),
            "machine_identifier": values.get("machine_id"),
            "field_key": values.get("field_key"),
            "field_label": values.get("field_label"),
            "sheet_name": values.get("sheet_name"),
            "header_name": values.get("header_name"),
            "workbook_path": str(values.get("workbook_path") or "") or None,
            "cached_cell_ref": values.get("cached_cell_ref"),
            "object_ref": values.get("object_ref"),
        }
        return self._target(self._write("POST", "/api/v1/annotation-targets", payload))

    def get_target(self, target_id: str) -> AnnotationTarget:
        return self._target(self._get(f"/api/v1/annotation-targets/{target_id}"))

    def find_audit_field_target(self, audit_id: str, field_key: str) -> AnnotationTarget | None:
        values = self._get("/api/v1/annotation-targets", audit_identifier=audit_id, field_key=field_key)
        return self._target(values[0]) if values else None

    def assign_tag_to_target(
        self, tag_id: str, target_id: str, comment: str | None = None, *, sync_workbook: bool = True
    ) -> TagAssignment:
        return self._assignment(self.gateway.assign_tag("annotation_target", target_id, int(tag_id), comment))

    def get_tag_assignment(self, assignment_id: str) -> TagAssignment:
        values = self._get("/api/v1/tag-assignments", include_archived=True)
        value = next((item for item in values if str(item["id"]) == str(assignment_id)), None)
        if value is None:
            raise KeyError(assignment_id)
        return self._assignment(value)

    def remove_tag_from_target(self, tag_id: str, target_id: str, *, sync_workbook: bool = True) -> None:
        values = self.get_tags_for_target(target_id)
        assignment = next((item for item in values if str(item["tag_id"]) == str(tag_id)), None)
        self.gateway.remove_tag(
            "annotation_target", target_id, int(tag_id), int(assignment["row_version"]) if assignment else None
        )

    def get_tags_for_target(self, target_id: str) -> list[dict[str, object]]:
        assignments = self._get(f"/api/v1/entities/annotation_target/{target_id}/tags")
        tags = {tag.id: tag for tag in self.list_tags(include_archived=True)}
        return [
            {
                **value,
                "id": str(value["tag_id"]),
                "name": tags.get(str(value["tag_id"]), Tag("", "", "gray", None, False, False, "", "")).name,
                "color_key": tags.get(str(value["tag_id"]), Tag("", "", "gray", None, False, False, "", "")).color_key,
                "assignment_id": str(value["id"]),
            }
            for value in assignments
        ]

    def archive_assignments(
        self,
        assignment_ids: Iterable[str],
        *,
        sync_workbook: bool = True,
    ) -> int:
        identifiers = [str(value) for value in assignment_ids if value]
        if not identifiers:
            return 0
        result = self.gateway.archive_tag_assignments(identifiers)
        return int(result["archived_count"])

    def get_targets_for_tag(self, tag_id: str) -> list[dict[str, object]]:
        return [
            value for value in self.list_tag_assignments(include_archived=False) if str(value["tag_id"]) == str(tag_id)
        ]

    def get_notes_for_target(self, target_id: str) -> list[dict[str, object]]:
        return [
            {
                **self._note(value).__dict__,
                "body_markdown": value.get("body", ""),
                "note_type": value.get("annotation_type"),
            }
            for value in self._get(f"/api/v1/entities/annotation_target/{target_id}/annotations")
        ]

    def list_tag_assignments(self, query: str = "", **filters) -> list[dict[str, object]]:
        values = self._get("/api/v1/tag-assignments", include_archived=filters.get("include_archived", False))
        folded = query.casefold()
        return [value for value in values if not folded or folded in str(value).casefold()]

    def link_note_to_target(self, note_id: str, target_id: str) -> None:
        if ("annotation", str(note_id)) not in self._versions:
            self.get_note(note_id)
        result = self.gateway.link_annotation_target(
            int(note_id),
            target_id,
            self._versions[("annotation", str(note_id))],
        )
        self._note(result)

    def unlink_note_from_target(self, note_id: str, target_id: str) -> None:
        if ("annotation", str(note_id)) not in self._versions:
            self.get_note(note_id)
        result = self.gateway.unlink_annotation_target(
            int(note_id),
            target_id,
            self._versions[("annotation", str(note_id))],
        )
        self._note(result)

    def link_note_to_tag(self, note_id: str, tag_id: str) -> None:
        self.gateway.assign_tag("annotation", int(note_id), int(tag_id))

    def unlink_note_from_tag(self, note_id: str, tag_id: str) -> None:
        assignments = self._get(f"/api/v1/entities/annotation/{note_id}/tags")
        assignment = next(
            (item for item in assignments if str(item["tag_id"]) == str(tag_id)),
            None,
        )
        self.gateway.remove_tag(
            "annotation",
            int(note_id),
            int(tag_id),
            int(assignment["row_version"]) if assignment else None,
        )

    def attach_file(
        self,
        *,
        note_id: str | None = None,
        target_id: str | None = None,
        file_path: str | Path,
        display_name: str | None = None,
        description: str | None = None,
    ) -> str:
        path = Path(file_path)
        if note_id is None and target_id is None:
            raise ValueError("A note_id or target_id is required.")
        entity_type = "annotation" if note_id is not None else "annotation_target"
        if note_id is not None:
            entity_id = int(note_id)
        else:
            target_record = self._get(f"/api/v1/annotation-targets/{target_id}")
            entity_id = int(target_record["id"])
        result = self.gateway.add_document(
            {
                "document_type": "document",
                "title": display_name or path.name,
                "description": description,
                "storage_path": str(path),
                "entity_type": entity_type,
                "entity_id": entity_id,
                "relationship_type": "attachment",
            }
        )
        return str(result["id"])

    def sync_target_colors_to_workbook(self, target_id: str) -> dict[str, object]:
        return {"status": "skipped", "reason": "Excel writes are forbidden in mysql_api mode."}

    def sync_target_colors_to_workbook_batch(self, target_ids: Iterable[str]) -> dict[str, object]:
        return {
            "status": "skipped",
            "reason": "Excel writes are forbidden in mysql_api mode.",
            "targets": len(list(target_ids)),
        }

    def sync_all_tag_colors_to_workbook(self) -> dict[str, object]:
        return {"status": "skipped", "reason": "Excel writes are forbidden in mysql_api mode."}

    def export_notes_markdown(self, notes=None):
        from .exports import export_notes_markdown

        return export_notes_markdown(self.project_root, notes or self.search_notes(include_archived=True))

    def export_notes_excel(self, notes=None):
        from .exports import export_notes_excel

        return export_notes_excel(self.project_root, notes or self.search_notes(include_archived=True))

    def export_tags_markdown(self, assignments=None):
        from .exports import export_tags_markdown

        return export_tags_markdown(self.project_root, assignments or self.list_tag_assignments(include_archived=True))

    def export_tags_excel(self, assignments=None):
        from .exports import export_tags_excel

        return export_tags_excel(self.project_root, assignments or self.list_tag_assignments(include_archived=True))
