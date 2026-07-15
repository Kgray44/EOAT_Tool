from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory
from server.eoat_api.release_provenance import ensure_application_release


@dataclass
class AnnotationImportReport:
    dry_run: bool
    source_path: str
    source_checksum_before: str
    source_checksum_after: str
    source_unchanged: bool
    batch_uuid: str | None
    source_counts: dict[str, int]
    imported_counts: dict[str, int]
    duplicates: dict[str, int]
    orphans: dict[str, int]
    warnings: list[str]
    status: str


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _load_source(path: Path) -> dict[str, list[dict]]:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        tables = (
            "tags",
            "annotation_targets",
            "tag_assignments",
            "notes",
            "note_targets",
            "note_tags",
            "attachments",
        )
        return {table: [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')] for table in tables}
    finally:
        connection.close()


def _quality(source: dict[str, list[dict]]) -> tuple[dict[str, int], dict[str, int]]:
    tag_ids = {row["id"] for row in source["tags"]}
    target_ids = {row["id"] for row in source["annotation_targets"]}
    note_ids = {row["id"] for row in source["notes"]}
    duplicate_tag_names = len(source["tags"]) - len({row["name"].casefold() for row in source["tags"]})
    active_assignment_keys = [
        (row["tag_id"], row["target_id"]) for row in source["tag_assignments"] if not row.get("archived_at")
    ]
    duplicates = {
        "tag_names": duplicate_tag_names,
        "active_tag_assignments": len(active_assignment_keys) - len(set(active_assignment_keys)),
    }
    orphans = {
        "tag_assignments": sum(
            row["tag_id"] not in tag_ids or row["target_id"] not in target_ids for row in source["tag_assignments"]
        ),
        "note_targets": sum(
            row["note_id"] not in note_ids or row["target_id"] not in target_ids for row in source["note_targets"]
        ),
        "note_tags": sum(row["note_id"] not in note_ids or row["tag_id"] not in tag_ids for row in source["note_tags"]),
    }
    return duplicates, orphans


def _empty_counts(source: dict[str, list[dict]]) -> dict[str, int]:
    return {name: 0 for name in source}


def _import(session: Session, source: dict[str, list[dict]], path: Path, checksum: str) -> tuple[str, dict[str, int]]:
    prior = session.scalar(
        select(db.ImportBatch).where(
            db.ImportBatch.source_type == "LEGACY_ANNOTATION_SQLITE",
            db.ImportBatch.source_file_checksum == checksum,
            db.ImportBatch.status == "COMPLETED",
            db.ImportBatch.dry_run.is_(False),
        )
    )
    if prior:
        raise RuntimeError(f"DUPLICATE_IMPORT:{prior.batch_uuid}")
    batch = db.ImportBatch(
        batch_uuid=str(uuid4()),
        batch_name="Legacy annotation/tag migration",
        source_type="LEGACY_ANNOTATION_SQLITE",
        source_file_name=path.name,
        source_file_checksum=checksum,
        started_at=datetime.now(timezone.utc),
        status="RUNNING",
        dry_run=False,
        application_release_id=ensure_application_release(session).id,
        records_discovered=sum(len(rows) for rows in source.values()),
    )
    session.add(batch)
    session.flush()
    counts = _empty_counts(source)
    tags: dict[str, db.Tag] = {}
    targets: dict[str, db.AnnotationTarget] = {}
    notes: dict[str, db.Annotation] = {}
    for row in source["tags"]:
        record = session.scalar(select(db.Tag).where(db.Tag.source_record_identifier == row["id"]))
        if record is None:
            record = db.Tag(
                tag_code=f"legacy_{row['id']}"[:96],
                display_name=row["name"],
                description=row.get("description"),
                color_key=row["color_key"],
                is_default=bool(row.get("is_default")),
                is_active=not bool(row.get("is_archived")),
                archived_at=_timestamp(row.get("updated_at")) if row.get("is_archived") else None,
                source_system="legacy_annotation_sqlite",
                source_record_identifier=row["id"],
                source_import_batch_id=batch.id,
                created_at=_timestamp(row.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_timestamp(row.get("updated_at")) or datetime.now(timezone.utc),
            )
            session.add(record)
            session.flush()
            counts["tags"] += 1
        tags[row["id"]] = record
    for row in source["annotation_targets"]:
        record = session.scalar(
            select(db.AnnotationTarget).where(db.AnnotationTarget.source_record_identifier == row["id"])
        )
        if record is None:
            record = db.AnnotationTarget(
                target_uuid=row["id"],
                target_type=row["target_type"],
                target_label=row.get("target_label"),
                audit_identifier=row.get("audit_id"),
                machine_identifier=row.get("machine_id"),
                field_key=row.get("field_key"),
                field_label=row.get("field_label"),
                sheet_name=row.get("sheet_name"),
                header_name=row.get("header_name"),
                workbook_path=row.get("workbook_path"),
                cached_cell_ref=row.get("cached_cell_ref"),
                object_ref=row.get("object_ref"),
                source_record_identifier=row["id"],
                source_system="legacy_annotation_sqlite",
                source_import_batch_id=batch.id,
                created_at=_timestamp(row.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_timestamp(row.get("updated_at")) or datetime.now(timezone.utc),
            )
            session.add(record)
            session.flush()
            counts["annotation_targets"] += 1
        targets[row["id"]] = record
    for row in source["notes"]:
        record = session.scalar(select(db.Annotation).where(db.Annotation.source_record_identifier == row["id"]))
        links = [link for link in source["note_targets"] if link["note_id"] == row["id"]]
        first_target = targets.get(links[0]["target_id"]) if links else None
        if record is None:
            record = db.Annotation(
                annotation_uuid=row["id"],
                entity_type="annotation_target" if first_target else None,
                entity_id=first_target.id if first_target else None,
                annotation_target_id=first_target.id if first_target else None,
                annotation_type=row.get("note_type") or "note",
                subject=row["subject"],
                body=row.get("body_markdown") or "",
                importance=row.get("importance") or "Neutral",
                status=row.get("status"),
                collection=row.get("collection"),
                follow_up_date=_date(row.get("follow_up_date")),
                is_active=not bool(row.get("archived_at")),
                archived_at=_timestamp(row.get("archived_at")),
                source_record_identifier=row["id"],
                source_system="legacy_annotation_sqlite",
                source_import_batch_id=batch.id,
                created_at=_timestamp(row.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_timestamp(row.get("updated_at")) or datetime.now(timezone.utc),
            )
            session.add(record)
            session.flush()
            counts["notes"] += 1
        notes[row["id"]] = record
    for row in source["note_targets"]:
        annotation, target = notes.get(row["note_id"]), targets.get(row["target_id"])
        if not annotation or not target:
            continue
        exists = session.scalar(
            select(db.AnnotationTargetLink.id).where(
                db.AnnotationTargetLink.annotation_id == annotation.id,
                db.AnnotationTargetLink.annotation_target_id == target.id,
            )
        )
        if not exists:
            session.add(
                db.AnnotationTargetLink(
                    annotation_id=annotation.id,
                    annotation_target_id=target.id,
                    created_at=_timestamp(row.get("created_at")) or datetime.now(timezone.utc),
                )
            )
            counts["note_targets"] += 1
    for row in source["tag_assignments"]:
        tag, target = tags.get(row["tag_id"]), targets.get(row["target_id"])
        if not tag or not target:
            continue
        record = session.scalar(select(db.EntityTag).where(db.EntityTag.source_record_identifier == row["id"]))
        if record is None:
            session.add(
                db.EntityTag(
                    tag_id=tag.id,
                    entity_type="annotation_target",
                    entity_id=target.id,
                    annotation_target_id=target.id,
                    comment=row.get("comment"),
                    assigned_at=_timestamp(row.get("created_at")) or datetime.now(timezone.utc),
                    removed_at=_timestamp(row.get("archived_at")),
                    source_record_identifier=row["id"],
                    source_import_batch_id=batch.id,
                )
            )
            counts["tag_assignments"] += 1
    for row in source["note_tags"]:
        tag, annotation = tags.get(row["tag_id"]), notes.get(row["note_id"])
        if not tag or not annotation:
            continue
        source_id = f"legacy_note_tag:{row['id']}"
        record = session.scalar(select(db.EntityTag).where(db.EntityTag.source_record_identifier == source_id))
        if record is None:
            session.add(
                db.EntityTag(
                    tag_id=tag.id,
                    entity_type="annotation",
                    entity_id=annotation.id,
                    assigned_at=_timestamp(row.get("created_at")) or datetime.now(timezone.utc),
                    source_record_identifier=source_id,
                    source_import_batch_id=batch.id,
                )
            )
            counts["note_tags"] += 1
    if source["attachments"]:
        raise RuntimeError("Legacy annotation attachments require an approved document mapping before import.")
    batch.records_imported = sum(counts.values())
    batch.records_rejected = 0
    batch.warnings_count = 0
    batch.status = "COMPLETED"
    batch.completed_at = datetime.now(timezone.utc)
    return batch.batch_uuid, counts


def migrate_annotations(source_path: str | Path, *, dry_run: bool = True) -> AnnotationImportReport:
    path = Path(source_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    checksum_before = _checksum(path)
    source = _load_source(path)
    duplicates, orphans = _quality(source)
    warnings = []
    if any(duplicates.values()):
        warnings.append("Duplicate source records require review.")
    if any(orphans.values()):
        warnings.append("Orphaned source records require review.")
    counts = _empty_counts(source)
    batch_uuid = None
    status = "DRY_RUN_COMPLETE"
    if not dry_run:
        factory = create_session_factory(migration=True)
        try:
            with factory() as session, session.begin():
                batch_uuid, counts = _import(session, source, path, checksum_before)
            status = "COMPLETED"
        except RuntimeError as exc:
            if str(exc).startswith("DUPLICATE_IMPORT:"):
                batch_uuid = str(exc).split(":", 1)[1]
                status = "DUPLICATE_IMPORT_STOPPED"
            else:
                raise
    checksum_after = _checksum(path)
    return AnnotationImportReport(
        dry_run=dry_run,
        source_path=str(path),
        source_checksum_before=checksum_before,
        source_checksum_after=checksum_after,
        source_unchanged=checksum_before == checksum_after,
        batch_uuid=batch_uuid,
        source_counts={name: len(rows) for name, rows in source.items()},
        imported_counts=counts,
        duplicates=duplicates,
        orphans=orphans,
        warnings=warnings,
        status=status,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate the permanent legacy annotation/tag SQLite source to MySQL.")
    parser.add_argument("source")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--report-json")
    args = parser.parse_args()
    report = migrate_annotations(args.source, dry_run=not args.execute)
    payload = asdict(report)
    if args.report_json:
        Path(args.report_json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if report.source_unchanged and not any(report.orphans.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
