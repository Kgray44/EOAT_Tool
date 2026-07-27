from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from deployment.frontend_generation import FrontendGenerationError, select_generation


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _release(root: Path, generation: str) -> tuple[Path, str]:
    release = root / f"eoat-atlas-web-{generation}"
    release.mkdir()
    (release / "index.html").write_text("<div id='root'></div>", encoding="utf-8")
    (release / "frontend-release.json").write_text(json.dumps({"ui_generation": generation}), encoding="utf-8")
    manifest = {item.name: _sha256(item) for item in release.iterdir() if item.is_file() and item.name != "web-static.manifest.json"}
    manifest_path = release / "web-static.manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return release, _sha256(manifest_path)


def test_select_generation_validates_hashes_before_dry_run(tmp_path: Path) -> None:
    releases = tmp_path / "releases"
    releases.mkdir()
    atlas, atlas_manifest = _release(releases, "atlas")
    legacy, legacy_manifest = _release(releases, "legacy")
    registry = tmp_path / "frontend-generations.json"
    registry.write_text(json.dumps({"schema": 1, "generations": {"atlas": {"release_directory": atlas.name, "manifest_sha256": atlas_manifest}, "legacy": {"release_directory": legacy.name, "manifest_sha256": legacy_manifest}}}), encoding="utf-8")
    result = select_generation(releases, registry, "legacy", dry_run=True)
    assert result["generation"] == "legacy"
    assert result["activated"] == "false"


def test_select_generation_rejects_modified_release(tmp_path: Path) -> None:
    releases = tmp_path / "releases"
    releases.mkdir()
    atlas, atlas_manifest = _release(releases, "atlas")
    registry = tmp_path / "frontend-generations.json"
    registry.write_text(json.dumps({"schema": 1, "generations": {"atlas": {"release_directory": atlas.name, "manifest_sha256": atlas_manifest}}}), encoding="utf-8")
    (atlas / "index.html").write_text("modified", encoding="utf-8")
    with pytest.raises(FrontendGenerationError, match="manifest"):
        select_generation(releases, registry, "atlas", dry_run=True)
