"""Stage and synchronize EOAT photo originals plus browser-safe JPEG derivatives.

This tool deliberately separates the Windows UNC read from the Debian media
write.  ``stage`` runs on the authorized Windows workstation.  The resulting
package is transferred with an approved SSH/SFTP command, then ``sync`` runs
on Debian against that transferred package.  Neither operation changes the
corporate source files or the EOAT database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from PIL import Image, ImageOps

try:
    import pillow_heif
except ImportError:  # The check in _open_image gives the operator a useful failure.
    pillow_heif = None


MANIFEST_VERSION = 1
JPEG_QUALITY = 94
JPEG_SUBSAMPLING = 0
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_IMAGE_EXTENSIONS = {".heic", ".heif", ".jpg", ".jpeg"}
_PRESERVED_EXIF_TAGS = {306, 36867, 36868}  # DateTime, DateTimeOriginal, DateTimeDigitized


class MediaSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class InventoryEntry:
    document_uuid: str
    source_path: str
    file_name: str
    eoat_links: tuple[str, ...]
    source_sha256: str | None = None
    source_size_bytes: int | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> InventoryEntry:
        try:
            document_uuid = str(UUID(str(raw["document_uuid"])))
            source_path = str(raw["source_path"]).strip()
            file_name = str(raw["file_name"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise MediaSyncError("Inventory contains an invalid document identity.") from exc
        if not source_path or not file_name:
            raise MediaSyncError(f"Inventory entry {document_uuid} is missing its source path or filename.")
        extension = Path(file_name).suffix.casefold()
        if extension not in _IMAGE_EXTENSIONS:
            raise MediaSyncError(f"Inventory entry {document_uuid} has unsupported image extension {extension or '<none>'}.")
        source_hash = raw.get("source_sha256")
        if source_hash is not None and (not isinstance(source_hash, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", source_hash)):
            raise MediaSyncError(f"Inventory entry {document_uuid} has an invalid source hash.")
        source_size = raw.get("source_size_bytes")
        if source_size is not None and (not isinstance(source_size, int) or source_size < 0):
            raise MediaSyncError(f"Inventory entry {document_uuid} has an invalid source size.")
        links = raw.get("eoat_links", [])
        if not isinstance(links, list) or any(not isinstance(value, str) or not value.strip() for value in links):
            raise MediaSyncError(f"Inventory entry {document_uuid} has invalid EOAT links.")
        return cls(document_uuid, source_path, file_name, tuple(sorted(set(links))), source_hash.casefold() if source_hash else None, source_size)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_name(value: str) -> str:
    name = _SAFE_NAME.sub("-", Path(value).name).strip(".-")
    if not name:
        raise MediaSyncError("A filename becomes empty after safety normalization.")
    return name


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=target.parent, prefix=f".{target.name}.") as handle:
        temporary = Path(handle.name)
    try:
        shutil.copy2(source, temporary)
        os.chmod(temporary, 0o640)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, prefix=f".{path.name}.", encoding="utf-8") as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    try:
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_inventory(path: Path, *, require_source_hash: bool) -> list[InventoryEntry]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_entries = payload["entries"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise MediaSyncError("Inventory JSON is unreadable or invalid.") from exc
    if payload.get("version") != MANIFEST_VERSION or not isinstance(raw_entries, list):
        raise MediaSyncError("Inventory JSON has an unsupported version or entries shape.")
    entries = [InventoryEntry.from_dict(entry) for entry in raw_entries if isinstance(entry, dict)]
    if len(entries) != len(raw_entries) or not entries:
        raise MediaSyncError("Inventory contains no usable photo entries.")
    if len({entry.document_uuid for entry in entries}) != len(entries):
        raise MediaSyncError("Inventory contains duplicate document UUIDs.")
    if require_source_hash and any(entry.source_sha256 is None or entry.source_size_bytes is None for entry in entries):
        raise MediaSyncError("The Debian sync requires the Windows-staged source hashes and sizes.")
    return sorted(entries, key=lambda entry: entry.document_uuid)


def _under_source_prefix(source_path: str, source_prefix: str) -> bool:
    normalized_source = source_path.replace("/", "\\").rstrip("\\").casefold()
    normalized_prefix = source_prefix.replace("/", "\\").rstrip("\\").casefold()
    return normalized_source == normalized_prefix or normalized_source.startswith(normalized_prefix + "\\")


def stage(inventory: Path, source_prefix: str, staging_root: Path) -> dict[str, Any]:
    entries = _read_inventory(inventory, require_source_hash=False)
    staged_entries: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for entry in entries:
        if not _under_source_prefix(entry.source_path, source_prefix):
            failures.append({"document_uuid": entry.document_uuid, "reason": "SOURCE_OUTSIDE_APPROVED_PREFIX"})
            continue
        source = Path(entry.source_path)
        if not source.is_file():
            failures.append({"document_uuid": entry.document_uuid, "reason": "SOURCE_NOT_FOUND"})
            continue
        source_hash = _hash_file(source)
        source_size = source.stat().st_size
        if entry.source_sha256 and entry.source_sha256 != source_hash:
            failures.append({"document_uuid": entry.document_uuid, "reason": "INVENTORY_SOURCE_HASH_CHANGED"})
            continue
        if entry.source_size_bytes is not None and entry.source_size_bytes != source_size:
            failures.append({"document_uuid": entry.document_uuid, "reason": "INVENTORY_SOURCE_SIZE_CHANGED"})
            continue
        target = staging_root / "originals" / entry.document_uuid / _safe_name(entry.file_name)
        if target.exists():
            if _hash_file(target) != source_hash:
                failures.append({"document_uuid": entry.document_uuid, "reason": "STAGING_TARGET_CONFLICT"})
                continue
        else:
            _atomic_copy(source, target)
        if _hash_file(target) != source_hash:
            raise MediaSyncError(f"Staged file hash verification failed for {entry.document_uuid}.")
        staged_entries.append(
            {
                "document_uuid": entry.document_uuid,
                "source_path": entry.source_path,
                "file_name": entry.file_name,
                "eoat_links": list(entry.eoat_links),
                "source_sha256": source_hash,
                "source_size_bytes": source_size,
            }
        )
    payload = {"version": MANIFEST_VERSION, "entries": staged_entries}
    # A failed re-stage must not erase the last complete transfer inventory.
    # Operators can investigate the explicit report and retry without making a
    # previously verified package ambiguous.
    if not failures:
        _atomic_json(staging_root / "manifest" / "staged-inventory.json", payload)
    report = {
        "source_linked_photo_count": len(entries),
        "staged_count": len(staged_entries),
        "missing_or_unresolved": failures,
        "inventory_path": str(inventory),
        "staged_inventory_path": str(staging_root / "manifest" / "staged-inventory.json"),
    }
    _atomic_json(staging_root / "manifest" / "stage-report.json", report)
    return report


def _read_existing_manifest(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload["entries"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise MediaSyncError("Existing production media manifest is unreadable; refusing to replace it.") from exc
    if payload.get("version") != MANIFEST_VERSION or not isinstance(entries, list):
        raise MediaSyncError("Existing production media manifest has an unsupported format.")
    return {entry["document_uuid"]: entry for entry in entries if isinstance(entry, dict) and isinstance(entry.get("document_uuid"), str)}


def _open_image(source: Path) -> Image.Image:
    if source.suffix.casefold() in {".heic", ".heif"}:
        if pillow_heif is None:
            raise MediaSyncError("pillow-heif is required for HEIC/HEIF derivative conversion.")
        pillow_heif.register_heif_opener()
    return Image.open(source)


def _jpeg_derivative(source: Path, target: Path) -> tuple[str, int, int]:
    target.parent.mkdir(parents=True, exist_ok=True)
    with _open_image(source) as image:
        image = ImageOps.exif_transpose(image)
        source_exif = image.getexif()
        safe_exif = Image.Exif()
        for tag in _PRESERVED_EXIF_TAGS:
            if tag in source_exif:
                safe_exif[tag] = source_exif[tag]
        if image.mode != "RGB":
            image = image.convert("RGB")
        width, height = image.size
        with tempfile.NamedTemporaryFile(delete=False, dir=target.parent, prefix=f".{target.name}.", suffix=".jpg") as handle:
            temporary = Path(handle.name)
        try:
            image.save(
                temporary,
                format="JPEG",
                quality=JPEG_QUALITY,
                subsampling=JPEG_SUBSAMPLING,
                optimize=True,
                progressive=True,
                exif=safe_exif.tobytes(),
            )
            os.chmod(temporary, 0o640)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return _hash_file(target), width, height


def sync(staged_inventory: Path, staging_root: Path, media_root: Path) -> dict[str, Any]:
    entries = _read_inventory(staged_inventory, require_source_hash=True)
    manifest_path = media_root / "manifest" / "media-manifest.json"
    previous = _read_existing_manifest(manifest_path)
    conflicts: list[dict[str, str]] = []
    staged_sources: dict[str, Path] = {}
    for entry in entries:
        source = staging_root / "originals" / entry.document_uuid / _safe_name(entry.file_name)
        if not source.is_file():
            conflicts.append({"document_uuid": entry.document_uuid, "reason": "TRANSFERRED_SOURCE_NOT_FOUND"})
            continue
        if source.stat().st_size != entry.source_size_bytes or _hash_file(source) != entry.source_sha256:
            conflicts.append({"document_uuid": entry.document_uuid, "reason": "TRANSFERRED_SOURCE_HASH_MISMATCH"})
            continue
        original = media_root / "originals" / entry.document_uuid / _safe_name(entry.file_name)
        old = previous.get(entry.document_uuid)
        if original.exists() and _hash_file(original) != entry.source_sha256:
            conflicts.append({"document_uuid": entry.document_uuid, "reason": "SOURCE_CHANGED"})
            continue
        if old and old.get("source_sha256") != entry.source_sha256:
            conflicts.append({"document_uuid": entry.document_uuid, "reason": "SOURCE_CHANGED"})
            continue
        staged_sources[entry.document_uuid] = source
    if conflicts:
        return {
            "source_linked_photo_count": len(entries),
            "mirrored_count": 0,
            "missing_or_unresolved": conflicts,
            "manifest_updated": False,
        }

    manifest_entries: list[dict[str, Any]] = []
    copied = 0
    converted = 0
    for entry in entries:
        source = staged_sources[entry.document_uuid]
        original_relative = Path("originals") / entry.document_uuid / _safe_name(entry.file_name)
        original = media_root / original_relative
        if not original.exists():
            _atomic_copy(source, original)
            copied += 1
        if _hash_file(original) != entry.source_sha256:
            raise MediaSyncError(f"Original mirror hash verification failed for {entry.document_uuid}.")
        os.chmod(original, 0o640)
        web_relative = Path("web") / f"{entry.document_uuid}.jpg"
        derivative = media_root / web_relative
        old = previous.get(entry.document_uuid)
        derivative_hash = old.get("derivative_sha256") if old else None
        dimensions = old.get("derivative_dimensions") if old else None
        if not derivative.is_file() or not isinstance(derivative_hash, str) or _hash_file(derivative) != derivative_hash:
            derivative_hash, width, height = _jpeg_derivative(original, derivative)
            dimensions = {"width": width, "height": height}
            converted += 1
        if not isinstance(dimensions, dict) or not isinstance(dimensions.get("width"), int) or not isinstance(dimensions.get("height"), int):
            with Image.open(derivative) as image:
                dimensions = {"width": image.width, "height": image.height}
        os.chmod(derivative, 0o640)
        manifest_entries.append(
            {
                "document_uuid": entry.document_uuid,
                "source_path": entry.source_path,
                "eoat_links": list(entry.eoat_links),
                "source_format": Path(entry.file_name).suffix.casefold().lstrip("."),
                "source_size_bytes": entry.source_size_bytes,
                "source_sha256": entry.source_sha256,
                "original_relative_path": original_relative.as_posix(),
                "web_relative_path": web_relative.as_posix(),
                "derivative_sha256": derivative_hash,
                "derivative_dimensions": dimensions,
                "derivative_mime_type": "image/jpeg",
                "conversion": {
                    "tool": "Pillow with pillow-heif",
                    "orientation": "EXIF transposed",
                    "color_mode": "RGB",
                    "jpeg_quality": JPEG_QUALITY,
                    "jpeg_subsampling": JPEG_SUBSAMPLING,
                    "metadata": "capture timestamps only; device and location metadata removed",
                },
                "synchronized_at": old.get("synchronized_at") if old and old.get("source_sha256") == entry.source_sha256 else _utc_now(),
            }
        )
    payload = {"version": MANIFEST_VERSION, "entries": manifest_entries}
    _atomic_json(manifest_path, payload)
    expected_originals = {entry["original_relative_path"] for entry in manifest_entries}
    orphaned_originals = sorted(
        str(path.relative_to(media_root).as_posix())
        for path in (media_root / "originals").rglob("*")
        if path.is_file() and path.relative_to(media_root).as_posix() not in expected_originals
    ) if (media_root / "originals").exists() else []
    report = {
        "source_linked_photo_count": len(entries),
        "mirrored_count": len(entries),
        "copied_originals": copied,
        "generated_or_repaired_derivatives": converted,
        "missing_or_unresolved": [],
        "manifest_updated": True,
        "manifest_path": str(manifest_path),
        "orphaned_originals_not_deleted": orphaned_originals,
    }
    _atomic_json(media_root / "manifest" / "last-sync-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    stage_parser = commands.add_parser("stage", help="Read authoritative UNC originals and create a transfer package.")
    stage_parser.add_argument("--inventory", type=Path, required=True)
    stage_parser.add_argument("--source-prefix", required=True)
    stage_parser.add_argument("--staging-root", type=Path, required=True)
    sync_parser = commands.add_parser("sync", help="Verify transferred originals and create the managed Debian mirror.")
    sync_parser.add_argument("--staged-inventory", type=Path, required=True)
    sync_parser.add_argument("--staging-root", type=Path, required=True)
    sync_parser.add_argument("--media-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = (
            stage(args.inventory, args.source_prefix, args.staging_root)
            if args.command == "stage"
            else sync(args.staged_inventory, args.staging_root, args.media_root)
        )
    except MediaSyncError as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if not report["missing_or_unresolved"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
