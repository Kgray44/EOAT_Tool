"""Governed copy-and-repoint migration for browser-served EOAT photos.

The migration is intentionally source-root allowlisted, dry-run first, and
does not modify document links, assignments, or compatibility records.  A
production invocation must provide an existing database-backup receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import shutil
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.eoat_api.data_state import record_import_completion
from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory
from server.eoat_api.release_provenance import ensure_application_release

_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_PHOTO_ENTITY_TYPES = {"eoat", "machine", "tool"}


@dataclass(frozen=True)
class MediaSource:
    document_id: int
    document_uuid: str
    file_name: str
    storage_path: str
    mime_type: str | None


@dataclass(frozen=True)
class MediaPlanItem:
    document_id: int
    document_uuid: str
    file_name: str
    target_relative_path: str | None
    checksum_sha256: str | None
    file_size_bytes: int | None
    mime_type: str | None
    status: str
    reason: str | None = None


@dataclass
class MediaMigrationReport:
    source_count: int
    eligible_count: int
    copied_count: int = 0
    repointed_count: int = 0
    already_governed_count: int = 0
    missing_count: int = 0
    unsafe_count: int = 0
    conflict_count: int = 0
    thumbnail_ready_count: int = 0
    items: list[MediaPlanItem] = field(default_factory=list)
    status: str = "DRY_RUN_COMPLETE"
    batch_uuid: str | None = None
    manifest_sha256: str = ""

    @property
    def safe_to_execute(self) -> bool:
        return not (self.missing_count or self.unsafe_count or self.conflict_count)

    def redacted_dict(self) -> dict:
        payload = asdict(self)
        # Storage roots and legacy source paths never belong in a durable
        # receipt; UUID, basename, checksums, and relative target are enough.
        return payload


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_source(path_value: str, roots: Iterable[Path]) -> Path | None:
    """Resolve only existing regular files within an explicit source root."""
    if not path_value or ".." in path_value.replace("\\", "/").split("/"):
        return None
    try:
        candidate = Path(path_value).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not candidate.is_file() or not any(candidate.is_relative_to(root) for root in roots):
        return None
    return candidate


def _target_relative(document_uuid: str, file_name: str) -> Path:
    suffix = Path(file_name).suffix.casefold()
    return Path(document_uuid[:2], f"{document_uuid}{suffix}")


def _thumbnail_ready(path: Path, mime_type: str | None) -> bool:
    if (mime_type or mimetypes.guess_type(path.name)[0] or "").casefold() not in _IMAGE_MIME_TYPES:
        return False
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.thumbnail((640, 640))
            return True
    except (OSError, ValueError):
        return False


def plan_media_migration(
    sources: Iterable[MediaSource],
    *,
    source_roots: Iterable[str | Path],
    target_root: str | Path,
) -> MediaMigrationReport:
    """Inventory photos and calculate safe UUID-addressed destination paths."""
    roots = tuple(Path(root).resolve(strict=True) for root in source_roots)
    if not roots or any(not root.is_dir() for root in roots):
        raise ValueError("At least one existing directory must be an approved source root.")
    target = Path(target_root).resolve(strict=False)
    if not target.is_absolute():
        raise ValueError("The governed target root must be absolute.")
    records = list(sources)
    report = MediaMigrationReport(source_count=len(records), eligible_count=0)
    canonical_manifest: list[dict[str, str | int | None]] = []
    for source in sorted(records, key=lambda item: item.document_uuid):
        path = _safe_source(source.storage_path, roots)
        if path is None:
            exists = False
            try:
                exists = Path(source.storage_path).exists()
            except OSError:
                pass
            report.items.append(
                MediaPlanItem(source.document_id, source.document_uuid, source.file_name, None, None, None, source.mime_type,
                              "UNSAFE_SOURCE" if exists else "MISSING_SOURCE", "Source is not in an approved migration root."))
            if exists:
                report.unsafe_count += 1
            else:
                report.missing_count += 1
            continue
        report.eligible_count += 1
        relative = _target_relative(source.document_uuid, source.file_name)
        destination = target / relative
        digest = _digest(path)
        size = path.stat().st_size
        mime_type = (source.mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream").casefold()
        status, reason = "COPY", None
        if destination.exists():
            if not destination.is_file() or _digest(destination) != digest:
                status, reason = "TARGET_CONFLICT", "UUID target already contains different content."
                report.conflict_count += 1
            else:
                status = "ALREADY_GOVERNED"
                report.already_governed_count += 1
        thumbnail_ready = _thumbnail_ready(path, mime_type)
        if thumbnail_ready:
            report.thumbnail_ready_count += 1
        report.items.append(
            MediaPlanItem(
                source.document_id,
                source.document_uuid,
                source.file_name,
                relative.as_posix(),
                digest,
                size,
                mime_type,
                status,
                reason,
            )
        )
        canonical_manifest.append({"uuid": source.document_uuid, "target": str(relative).replace("\\", "/"), "sha256": digest, "size": size})
    report.manifest_sha256 = hashlib.sha256(json.dumps(canonical_manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return report


def photo_sources(session: Session) -> list[MediaSource]:
    """Return only photos linked to browser-visible EOAT, Machine, or Tool records."""
    rows = session.execute(
        select(db.Document)
        .join(db.Photo, db.Photo.document_id == db.Document.id)
        .join(db.DocumentLink, db.DocumentLink.document_id == db.Document.id)
        .where(db.DocumentLink.entity_type.in_(_PHOTO_ENTITY_TYPES))
        .distinct()
    ).scalars()
    return [MediaSource(row.id, row.document_uuid, row.file_name, row.storage_path, row.mime_type) for row in rows]


def run_media_migration(
    *,
    source_roots: Iterable[str | Path],
    target_root: str | Path,
    execute: bool = False,
    database_backup_receipt: str | Path | None = None,
) -> MediaMigrationReport:
    """Copy verified files atomically and repoint document metadata in one DB transaction."""
    target = Path(target_root).resolve(strict=False)
    factory = create_session_factory(migration=True)
    with factory() as session:
        report = plan_media_migration(photo_sources(session), source_roots=source_roots, target_root=target)
        if not execute:
            return report
        backup = Path(database_backup_receipt) if database_backup_receipt else None
        if backup is None or not backup.is_file() or backup.stat().st_size == 0:
            report.status = "SAFE_STOP_BACKUP_RECEIPT_REQUIRED"
            return report
        if not report.safe_to_execute:
            report.status = "SAFE_STOP_REVIEW_REQUIRED"
            return report
        prior = session.scalar(
            select(db.ImportBatch).where(
                db.ImportBatch.source_type == "governed_media",
                db.ImportBatch.source_file_checksum == report.manifest_sha256,
                db.ImportBatch.status == "COMPLETED",
                db.ImportBatch.dry_run.is_(False),
            )
        )
        if prior:
            report.status = "SAFE_STOP_ALREADY_IMPORTED"
            report.batch_uuid = prior.batch_uuid
            return report
        session.rollback()
        target.mkdir(parents=True, exist_ok=True)
        with session.begin():
            batch = db.ImportBatch(
                batch_uuid=str(uuid4()), batch_name="Governed browser media migration", source_type="governed_media",
                source_file_name="redacted-media-manifest.json", source_file_checksum=report.manifest_sha256,
                started_at=datetime.now(timezone.utc), status="RUNNING", dry_run=False,
                application_release_id=ensure_application_release(session).id, records_discovered=report.source_count,
                notes="Approved-photo copy and document repoint only; links and operational relationships unchanged.",
            )
            session.add(batch)
            session.flush()
            source_map = {source.document_id: source for source in photo_sources(session)}
            copied = 0
            repointed = 0
            for row_number, item in enumerate(report.items, start=1):
                if item.status not in {"COPY", "ALREADY_GOVERNED"}:
                    continue
                document = session.get(db.Document, item.document_id)
                if document is None or item.target_relative_path is None or item.checksum_sha256 is None:
                    raise RuntimeError(f"Document changed during media migration: {item.document_uuid}")
                destination = target / item.target_relative_path
                if item.status == "COPY":
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source = _safe_source(source_map[item.document_id].storage_path, tuple(Path(root).resolve(strict=True) for root in source_roots))
                    if source is None or _digest(source) != item.checksum_sha256:
                        raise RuntimeError(f"Source changed during media migration: {item.document_uuid}")
                    temporary = destination.with_name(destination.name + f".{uuid4().hex}.partial")
                    shutil.copyfile(source, temporary)
                    if _digest(temporary) != item.checksum_sha256:
                        temporary.unlink(missing_ok=True)
                        raise RuntimeError(f"Checksum verification failed: {item.document_uuid}")
                    os.replace(temporary, destination)
                    copied += 1
                if (
                    document.storage_path != str(destination)
                    or document.storage_provider != "governed_server_media"
                    or document.checksum_sha256 != item.checksum_sha256
                    or document.file_size_bytes != item.file_size_bytes
                    or document.mime_type != item.mime_type
                ):
                    repointed += 1
                document.storage_path = str(destination)
                document.storage_provider = "governed_server_media"
                document.checksum_sha256 = item.checksum_sha256
                document.file_size_bytes = item.file_size_bytes
                document.mime_type = item.mime_type
                session.add(db.ImportRow(import_batch_id=batch.id, source_sheet="governed_media", source_row_number=row_number,
                                          source_identifier=item.document_uuid, target_entity_type="document", target_entity_id=document.id,
                                          status="IMPORTED" if item.status == "COPY" else "UNCHANGED",
                                          normalized_values_json={"sha256": item.checksum_sha256, "target": item.target_relative_path}))
            batch.records_imported = repointed
            batch.status = "COMPLETED"
            batch.completed_at = datetime.now(timezone.utc)
            record_import_completion(session, source=f"governed_media:{report.manifest_sha256[:12]}", changed_data=bool(repointed))
            report.copied_count = copied
            report.repointed_count = repointed
            report.batch_uuid = batch.batch_uuid
            report.status = "COMPLETED"
    return report


def write_immutable_receipt(report: MediaMigrationReport, directory: str | Path) -> Path:
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"media-migration-{report.manifest_sha256[:16]}.json"
    with target.open("x", encoding="utf-8") as stream:
        json.dump(report.redacted_dict(), stream, indent=2, sort_keys=True)
        stream.write("\n")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run-first governed photo migration.")
    parser.add_argument("--source-root", action="append", required=True)
    parser.add_argument("--target-root", required=True)
    parser.add_argument("--receipt-directory", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--database-backup-receipt")
    args = parser.parse_args()
    report = run_media_migration(source_roots=args.source_root, target_root=args.target_root, execute=args.execute,
                                 database_backup_receipt=args.database_backup_receipt)
    receipt = write_immutable_receipt(report, args.receipt_directory)
    print(json.dumps({**report.redacted_dict(), "receipt": str(receipt)}, indent=2))
    return 0 if report.status in {"DRY_RUN_COMPLETE", "COMPLETED", "SAFE_STOP_ALREADY_IMPORTED"} and report.safe_to_execute else 2


if __name__ == "__main__":
    raise SystemExit(main())
