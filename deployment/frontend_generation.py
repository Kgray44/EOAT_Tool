"""Validate and select an immutable EOAT Atlas frontend generation.

This is an operator-only building block for the existing transactional web
host. It deliberately accepts a reviewed registry instead of a browser flag;
the caller must run it in the privileged host transaction.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any


class FrontendGenerationError(RuntimeError):
    pass


SELECTIONS = frozenset({"atlas", "legacy"})
UI_GENERATIONS = frozenset({"mirrorline", "legacy"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_registry(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrontendGenerationError("frontend generation registry is unreadable") from exc
    if not isinstance(value, dict) or value.get("schema") != 1 or not isinstance(value.get("generations"), dict):
        raise FrontendGenerationError("frontend generation registry is invalid")
    return value


def _release_path(releases_root: Path, configured: str) -> Path:
    candidate = (releases_root / configured).resolve()
    if not candidate.is_relative_to(releases_root.resolve()) or not candidate.is_dir() or _is_link_or_reparse(candidate):
        raise FrontendGenerationError("registered frontend release is unsafe or missing")
    return candidate


def _is_link_or_reparse(path: Path) -> bool:
    """Reject Unix links and Windows reparse points, including directory junctions."""
    if path.is_symlink():
        return True
    attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def validate_generation(releases_root: Path, registry_path: Path, generation: str) -> dict[str, str]:
    registry = _read_registry(registry_path)
    entry = registry["generations"].get(generation)
    if generation not in SELECTIONS or not isinstance(entry, dict):
        raise FrontendGenerationError("requested frontend generation is not registered")
    expected_identity = entry.get("expected_ui_generation")
    if not isinstance(expected_identity, str) or expected_identity not in UI_GENERATIONS:
        raise FrontendGenerationError("registered frontend generation has no valid expected UI identity")
    release = _release_path(releases_root, str(entry.get("release_directory") or ""))
    descriptor_path = release / "frontend-release.json"
    manifest_path = release / "web-static.manifest.json"
    try:
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrontendGenerationError("registered frontend release has invalid metadata") from exc
    descriptor_identity = descriptor.get("ui_generation")
    if descriptor_identity not in UI_GENERATIONS or descriptor_identity != expected_identity or not isinstance(manifest, dict):
        raise FrontendGenerationError("registered frontend generation identity is invalid")
    actual = {
        item.relative_to(release).as_posix(): _sha256(item)
        for item in sorted(release.rglob("*"))
        if item.is_file() and item != manifest_path
    }
    if manifest != actual:
        raise FrontendGenerationError("registered frontend release hash manifest does not match")
    manifest_sha = _sha256(manifest_path)
    expected = str(entry.get("manifest_sha256") or "")
    if expected and expected != manifest_sha:
        raise FrontendGenerationError("registered frontend manifest digest does not match")
    return {"generation": generation, "release": str(release), "manifest_sha256": manifest_sha}


def select_generation(releases_root: Path, registry_path: Path, generation: str, *, dry_run: bool = False) -> dict[str, str]:
    verified = validate_generation(releases_root, registry_path, generation)
    if dry_run:
        return {**verified, "activated": "false"}
    current = releases_root / "current"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".current-", dir=releases_root)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.unlink()
        relative = os.path.relpath(verified["release"], releases_root)
        os.symlink(relative, temporary, target_is_directory=True)
        os.replace(temporary, current)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
    return {**verified, "activated": "true"}
