from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .versioning import Version

REQUIRED_FIELDS = {
    "latest_version": str,
    "release_id": str,
    "build_id": str,
    "release_path": str,
    "minimum_supported_version": str,
    "sha256": str,
    "package_size": int,
    "published_at": str,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_manifest(payload: Any, *, require_package: bool = False) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Manifest must be a JSON object")
    for field, field_type in REQUIRED_FIELDS.items():
        if field not in payload or not isinstance(payload[field], field_type):
            raise ValueError(f"Manifest field {field!r} is missing or has the wrong type")
    Version.parse(payload["latest_version"])
    if payload["release_id"] != f"eoat-atlas-{payload['latest_version']}":
        raise ValueError("Manifest release_id does not match latest_version")
    if not payload["build_id"].strip():
        raise ValueError("Manifest build_id is required")
    Version.parse(payload["minimum_supported_version"])
    if len(payload["sha256"]) != 64 or any(c not in "0123456789abcdefABCDEF" for c in payload["sha256"]):
        raise ValueError("Manifest sha256 must contain 64 hexadecimal characters")
    if payload["package_size"] <= 0:
        raise ValueError("Manifest package_size must be positive")
    if not payload["release_path"].strip() or payload["release_path"].endswith((".partial", ".tmp")):
        raise ValueError("Manifest release_path is invalid")
    if require_package:
        package = Path(payload["release_path"])
        if not package.is_file():
            raise ValueError(f"Manifest package is unavailable: {package}")
        if package.stat().st_size != payload["package_size"]:
            raise ValueError("Manifest package size does not match")
        if sha256_file(package).lower() != payload["sha256"].lower():
            raise ValueError("Manifest package checksum does not match")
    return dict(payload)


def read_manifest(path: Path, *, require_package: bool = False) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read valid manifest {path}: {exc}") from exc
    return validate_manifest(payload, require_package=require_package)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    validate_manifest(payload)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temp_name).replace(path)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise
