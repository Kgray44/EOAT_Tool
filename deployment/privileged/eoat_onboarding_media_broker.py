#!/usr/bin/env python3
"""Fixed-operation local broker for onboarding media publication.

This root-owned process is intentionally the *only* writer for the published
EOAT media tree.  The API can ask it, over a local group-restricted socket, to
promote bytes from the configured temporary onboarding root.  It cannot choose
the media root, execute a command, read arbitrary files, or modify existing
published media.  A pending journal makes filesystem compensation explicit
when the MySQL transaction subsequently rolls back.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from PIL import Image, ImageOps

try:
    import pillow_heif
except ImportError:  # Production packaging validates this before enabling HEIF uploads.
    pillow_heif = None


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_REQUEST_BYTES = 1024 * 1024
_IMAGE_EXTENSIONS = {".heic", ".heif", ".jpg", ".jpeg", ".png", ".webp", ".gif"}
_PRESERVED_EXIF_TAGS = {306, 36867, 36868}


class BrokerError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrokerConfig:
    staging_root: Path
    media_root: Path
    pending_root: Path
    socket_path: Path

    @classmethod
    def from_file(cls, path: Path) -> BrokerConfig:
        try:
            values = {
                key: value
                for key, value in (
                    line.strip().split("=", 1)
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith("#") and "=" in line
                )
            }
            staging = Path(values["EOAT_ONBOARDING_STAGING_ROOT"])
            media = Path(values["EOAT_CANONICAL_MEDIA_ROOT"])
            socket_path = Path(values["EOAT_ONBOARDING_MEDIA_SOCKET"])
        except (OSError, KeyError, ValueError) as exc:
            raise BrokerError("The root-owned onboarding media configuration is invalid.") from exc
        for candidate in (staging, media, socket_path):
            if not candidate.is_absolute() or ".." in candidate.parts:
                raise BrokerError("The root-owned onboarding media configuration is unsafe.")
        return cls(staging.resolve(), media.resolve(), (media / "pending").resolve(), socket_path)


def _safe_name(value: str) -> str:
    name = _SAFE_NAME.sub("-", Path(value).name).strip(".-")
    if not name:
        raise BrokerError("The file name is invalid.")
    return name


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _source(path_value: object, root: Path) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise BrokerError("The staged source is invalid.")
    try:
        raw = Path(path_value)
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise BrokerError("The staged source is unavailable.") from exc
    if raw.is_symlink() or not raw.is_absolute() or not _under(resolved, root) or not stat.S_ISREG(resolved.stat().st_mode):
        raise BrokerError("The staged source is not an approved regular file.")
    return resolved


def _atomic_copy(source: Path, target: Path) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if _hash(target) != _hash(source):
            raise BrokerError("A canonical media collision was detected.")
        return False
    with tempfile.NamedTemporaryFile(delete=False, dir=target.parent, prefix=f".{target.name}.") as handle:
        temporary = Path(handle.name)
    try:
        shutil.copyfile(source, temporary)
        if _hash(temporary) != _hash(source):
            raise BrokerError("Canonical media hash verification failed.")
        os.chmod(temporary, 0o640)
        os.replace(temporary, target)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, prefix=f".{path.name}.") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    try:
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _manifest(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload["entries"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise BrokerError("The canonical media manifest is invalid.") from exc
    if payload.get("version") != 1 or not isinstance(entries, list):
        raise BrokerError("The canonical media manifest is invalid.")
    if any(not isinstance(entry, dict) or not isinstance(entry.get("document_uuid"), str) for entry in entries):
        raise BrokerError("The canonical media manifest is invalid.")
    return entries


def _jpeg(source: Path, target: Path) -> tuple[str, dict[str, int]]:
    if source.suffix.casefold() in {".heic", ".heif"}:
        if pillow_heif is None:
            raise BrokerError("HEIF media cannot be promoted on this host.")
        pillow_heif.register_heif_opener()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(source) as image:
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
                image.save(temporary, format="JPEG", quality=94, subsampling=0, optimize=True, progressive=True, exif=safe_exif.tobytes())
                os.chmod(temporary, 0o640)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
    except (OSError, ValueError) as exc:
        raise BrokerError("The staged photo cannot be converted safely.") from exc
    return _hash(target), {"width": width, "height": height}


def _read_promotion_id(value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise BrokerError("The promotion identifier is invalid.") from exc


class Broker:
    def __init__(self, config: BrokerConfig) -> None:
        self.config = config

    def promote(self, request: dict[str, Any]) -> dict[str, Any]:
        raw_items = request.get("items")
        identifier = request.get("eoat_identifier")
        if not isinstance(raw_items, list) or not raw_items or not isinstance(identifier, str) or not identifier.strip():
            raise BrokerError("The promotion request is invalid.")
        if len(raw_items) > 64:
            raise BrokerError("The promotion request contains too many files.")
        manifest_path = self.config.media_root / "manifest" / "media-manifest.json"
        manifest_existed = manifest_path.exists()
        existing = {entry["document_uuid"]: entry for entry in _manifest(manifest_path)}
        pending_id = str(uuid4())
        journal_items: list[dict[str, Any]] = []
        response_items: list[dict[str, Any]] = []
        created_paths: list[Path] = []
        new_entries: dict[str, dict[str, Any]] = {}
        manifest_written = False
        try:
            seen: set[int] = set()
            for raw in raw_items:
                if not isinstance(raw, dict):
                    raise BrokerError("The promotion request is invalid.")
                media_id = raw.get("media_id")
                if not isinstance(media_id, int) or media_id < 1 or media_id in seen:
                    raise BrokerError("The promotion request has invalid media identities.")
                seen.add(media_id)
                document_uuid = str(UUID(str(raw.get("document_uuid"))))
                if document_uuid in existing or document_uuid in new_entries:
                    raise BrokerError("The requested canonical document identity already exists.")
                source = _source(raw.get("source_path"), self.config.staging_root)
                file_name = _safe_name(str(raw.get("file_name") or ""))
                if source.name != file_name:
                    raise BrokerError("The staged source name does not match its approved metadata.")
                is_photo = raw.get("is_photo") is True
                if is_photo and source.suffix.casefold() not in _IMAGE_EXTENSIONS:
                    raise BrokerError("The staged photo format is not supported.")
                source_hash = _hash(source)
                original_relative = Path("originals") / document_uuid / file_name
                original = self.config.media_root / original_relative
                if _atomic_copy(source, original):
                    created_paths.append(original)
                if _hash(original) != source_hash:
                    raise BrokerError("The durable media copy failed verification.")
                derivative_relative: Path | None = None
                derivative_hash: str | None = None
                dimensions: dict[str, int] | None = None
                if is_photo:
                    derivative_relative = Path("web") / f"{document_uuid}.jpg"
                    derivative = self.config.media_root / derivative_relative
                    derivative_hash, dimensions = _jpeg(original, derivative)
                    created_paths.append(derivative)
                entry = {
                    "document_uuid": document_uuid,
                    "managed_media": True,
                    "source_path": str(original),
                    "eoat_links": [identifier.strip()],
                    "source_format": source.suffix.casefold().lstrip("."),
                    "source_size_bytes": source.stat().st_size,
                    "source_sha256": source_hash,
                    "original_relative_path": original_relative.as_posix(),
                    "web_relative_path": derivative_relative.as_posix() if derivative_relative else None,
                    "derivative_sha256": derivative_hash,
                    "derivative_dimensions": dimensions,
                    "derivative_mime_type": "image/jpeg" if is_photo else None,
                    "conversion": {
                        "tool": "Pillow with pillow-heif",
                        "orientation": "EXIF transposed",
                        "color_mode": "RGB",
                        "jpeg_quality": 94,
                        "jpeg_subsampling": 0,
                        "metadata": "capture timestamps only; device and location metadata removed",
                    } if is_photo else None,
                    "synchronized_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                }
                if is_photo:
                    new_entries[document_uuid] = entry
                journal_items.append({"document_uuid": document_uuid, "original": str(original), "derivative": str(self.config.media_root / derivative_relative) if derivative_relative else None, "source": str(source)})
                response_items.append({"media_id": media_id, "document_uuid": document_uuid, "storage_path": str(original), "checksum_sha256": source_hash, "file_size_bytes": source.stat().st_size})
            if new_entries:
                merged = [entry for key, entry in existing.items() if key not in new_entries] + list(new_entries.values())
                _atomic_json(manifest_path, {"version": 1, "entries": sorted(merged, key=lambda entry: entry["document_uuid"])})
                manifest_written = True
            _atomic_json(self.config.pending_root / f"{pending_id}.json", {"promotion_id": pending_id, "items": journal_items, "manifest_document_uuids": sorted(new_entries)})
            return {"ok": True, "promotion_id": pending_id, "items": response_items}
        except Exception:
            if manifest_written:
                if manifest_existed:
                    _atomic_json(manifest_path, {"version": 1, "entries": sorted(existing.values(), key=lambda entry: entry["document_uuid"])})
                else:
                    manifest_path.unlink(missing_ok=True)
            for path in reversed(created_paths):
                path.unlink(missing_ok=True)
                try:
                    path.parent.rmdir()
                except OSError:
                    pass
            raise

    def _journal(self, promotion_id: str) -> tuple[Path, dict[str, Any]]:
        path = self.config.pending_root / f"{promotion_id}.json"
        try:
            journal = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrokerError("The promotion journal is unavailable.") from exc
        if journal.get("promotion_id") != promotion_id or not isinstance(journal.get("items"), list):
            raise BrokerError("The promotion journal is invalid.")
        return path, journal

    def confirm(self, promotion_id: str) -> dict[str, Any]:
        path, journal = self._journal(promotion_id)
        for raw in journal["items"]:
            source = _source(raw.get("source"), self.config.staging_root)
            source.unlink()
            try:
                source.parent.rmdir()
            except OSError:
                pass
        path.unlink()
        return {"ok": True}

    def compensate(self, promotion_id: str) -> dict[str, Any]:
        path, journal = self._journal(promotion_id)
        manifest_path = self.config.media_root / "manifest" / "media-manifest.json"
        entries = _manifest(manifest_path)
        removal = set(journal.get("manifest_document_uuids") or [])
        _atomic_json(manifest_path, {"version": 1, "entries": [entry for entry in entries if entry["document_uuid"] not in removal]})
        for raw in journal["items"]:
            for key in ("derivative", "original"):
                value = raw.get(key)
                if isinstance(value, str):
                    candidate = Path(value)
                    if _under(candidate, self.config.media_root):
                        candidate.unlink(missing_ok=True)
                        try:
                            candidate.parent.rmdir()
                        except OSError:
                            pass
        path.unlink()
        return {"ok": True}

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        operation = request.get("operation")
        if operation == "promote":
            return self.promote(request)
        if operation == "confirm":
            return self.confirm(_read_promotion_id(request.get("promotion_id")))
        if operation == "compensate":
            return self.compensate(_read_promotion_id(request.get("promotion_id")))
        raise BrokerError("The requested promotion operation is invalid.")


def serve(config: BrokerConfig) -> None:
    config.socket_path.parent.mkdir(parents=True, exist_ok=True)
    config.socket_path.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(config.socket_path))
        try:
            import grp

            os.chown(config.socket_path, 0, grp.getgrnam("eoat-atlas").gr_gid)
        except (ImportError, KeyError) as exc:
            raise BrokerError("The EOAT Atlas service group is unavailable.") from exc
        os.chmod(config.socket_path, 0o660)
        listener.listen(16)
        broker = Broker(config)
        while True:
            connection, _address = listener.accept()
            with connection:
                raw = connection.recv(_MAX_REQUEST_BYTES + 1)
                try:
                    if len(raw) > _MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
                        raise BrokerError("The promotion request is invalid.")
                    request = json.loads(raw.decode("utf-8"))
                    if not isinstance(request, dict):
                        raise BrokerError("The promotion request is invalid.")
                    response = broker.handle(request)
                except (BrokerError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                    response = {"ok": False, "message": str(exc)}
                except OSError:
                    # Do not disclose root-owned filesystem paths or platform
                    # diagnostics to the unprivileged API process.
                    response = {"ok": False, "message": "Canonical media promotion failed."}
                connection.sendall(json.dumps(response, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/etc/eoat-atlas/onboarding-media.env"))
    args = parser.parse_args()
    try:
        serve(BrokerConfig.from_file(args.config))
    except BrokerError as exc:
        print(f"onboarding media broker: {exc}", file=os.sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
