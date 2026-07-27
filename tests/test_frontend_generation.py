from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from deployment.frontend_generation import FrontendGenerationError, select_generation, validate_generation
from deployment.web_release import build_web_static

ROOT = Path(__file__).resolve().parents[1]
MIRRORLINE_DESCRIPTOR = ROOT / "web" / "public" / "frontend-release.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _release(root: Path, directory: str, descriptor: dict[str, object]) -> tuple[Path, str]:
    release = root / directory
    release.mkdir()
    (release / "index.html").write_text("<div id='root'></div>", encoding="utf-8")
    (release / "frontend-release.json").write_text(json.dumps(descriptor), encoding="utf-8")
    manifest = {
        item.name: _sha256(item)
        for item in release.iterdir()
        if item.is_file() and item.name != "web-static.manifest.json"
    }
    manifest_path = release / "web-static.manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return release, _sha256(manifest_path)


def _registry(path: Path, entries: dict[str, dict[str, str]]) -> Path:
    path.write_text(json.dumps({"schema": 1, "generations": entries}), encoding="utf-8")
    return path


def _entry(release: Path, manifest_sha: str, expected: str) -> dict[str, str]:
    return {
        "release_directory": release.name,
        "manifest_sha256": manifest_sha,
        "expected_ui_generation": expected,
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    releases = tmp_path / "releases"
    releases.mkdir(parents=True)
    mirrorline = json.loads(MIRRORLINE_DESCRIPTOR.read_text(encoding="utf-8"))
    atlas, atlas_manifest = _release(releases, "eoat-atlas-mirrorline", mirrorline)
    legacy, legacy_manifest = _release(releases, "eoat-atlas-legacy", {"ui_generation": "legacy"})
    registry = _registry(
        tmp_path / "frontend-generations.json",
        {
            "atlas": _entry(atlas, atlas_manifest, "mirrorline"),
            "legacy": _entry(legacy, legacy_manifest, "legacy"),
        },
    )
    return releases, registry, atlas, legacy


def test_actual_committed_mirrorline_descriptor_validates_as_atlas(tmp_path: Path) -> None:
    releases, registry, atlas, _ = _fixture(tmp_path)
    assert json.loads((atlas / "frontend-release.json").read_text(encoding="utf-8")) == json.loads(
        MIRRORLINE_DESCRIPTOR.read_text(encoding="utf-8")
    )
    result = validate_generation(releases, registry, "atlas")
    assert result["generation"] == "atlas"


def test_legacy_selection_validates_legacy_identity(tmp_path: Path) -> None:
    releases, registry, _, _ = _fixture(tmp_path)
    assert validate_generation(releases, registry, "legacy")["generation"] == "legacy"


@pytest.mark.parametrize(("selection", "replacement"), [("atlas", "legacy"), ("legacy", "mirrorline")])
def test_selection_rejects_mismatched_descriptor(tmp_path: Path, selection: str, replacement: str) -> None:
    releases, registry, atlas, legacy = _fixture(tmp_path)
    release = atlas if selection == "atlas" else legacy
    (release / "frontend-release.json").write_text(json.dumps({"ui_generation": replacement}), encoding="utf-8")
    with pytest.raises(FrontendGenerationError, match="identity"):
        validate_generation(releases, registry, selection)


def test_unknown_selection_and_missing_expected_identity_are_rejected(tmp_path: Path) -> None:
    releases, registry, atlas, _ = _fixture(tmp_path)
    with pytest.raises(FrontendGenerationError, match="not registered"):
        validate_generation(releases, registry, "preview")
    _registry(
        registry,
        {"atlas": {"release_directory": atlas.name, "manifest_sha256": "anything"}},
    )
    with pytest.raises(FrontendGenerationError, match="expected UI identity"):
        validate_generation(releases, registry, "atlas")


def test_modified_bundle_and_manifest_are_rejected(tmp_path: Path) -> None:
    releases, registry, atlas, _ = _fixture(tmp_path)
    (atlas / "index.html").write_text("modified", encoding="utf-8")
    with pytest.raises(FrontendGenerationError, match="hash manifest"):
        validate_generation(releases, registry, "atlas")
    releases, registry, atlas, _ = _fixture(tmp_path / "manifest")
    manifest = json.loads((atlas / "web-static.manifest.json").read_text(encoding="utf-8"))
    manifest["index.html"] = "0" * 64
    (atlas / "web-static.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FrontendGenerationError, match="manifest"):
        validate_generation(releases, registry, "atlas")


def test_dry_run_is_side_effect_free_and_activation_is_atomic_and_recoverable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    releases, registry, atlas, legacy = _fixture(tmp_path)
    current = releases / "current"
    current.write_text(legacy.name, encoding="utf-8")
    before = current.read_text(encoding="utf-8")
    links: list[tuple[str, str]] = []

    def fake_symlink(target: str, link_name: Path, *, target_is_directory: bool) -> None:
        assert target_is_directory is True
        links.append((target, str(link_name)))
        Path(link_name).write_text(target, encoding="utf-8")

    monkeypatch.setattr("deployment.frontend_generation.os.symlink", fake_symlink)
    result = select_generation(releases, registry, "atlas", dry_run=True)
    assert result["activated"] == "false"
    assert current.read_text(encoding="utf-8") == before
    result = select_generation(releases, registry, "atlas")
    assert result["activated"] == "true"
    assert current.read_text(encoding="utf-8") == atlas.name
    assert links and legacy.is_dir() and before == legacy.name
    select_generation(releases, registry, "legacy")
    assert current.read_text(encoding="utf-8") == legacy.name


def test_path_traversal_and_symlinked_release_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    releases, registry, atlas, _ = _fixture(tmp_path)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["generations"]["atlas"]["release_directory"] = "../outside"
    registry.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FrontendGenerationError, match="unsafe or missing"):
        validate_generation(releases, registry, "atlas")
    payload["generations"]["atlas"]["release_directory"] = "linked"
    linked = releases / "linked"
    linked.mkdir()
    monkeypatch.setattr(
        "deployment.frontend_generation._is_link_or_reparse",
        lambda path: path == linked.resolve(),
    )
    registry.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FrontendGenerationError, match="unsafe or missing"):
        validate_generation(releases, registry, "atlas")


@pytest.mark.skipif(
    os.name == "nt" or os.environ.get("EOAT_RUN_REAL_FRONTEND_GENERATION_ACTIVATION") != "1",
    reason="requires the isolated Linux generation-activation harness",
)
def test_linux_real_static_generations_activate_and_roll_back_safely(tmp_path: Path) -> None:
    """Exercise real Linux symlinks against built Mirrorline and legacy bundles only."""
    def commit(revision: str) -> str:
        result = subprocess.run(
            ["git", "rev-parse", f"{revision}^{{commit}}"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    releases = tmp_path / "releases"
    releases.mkdir()
    atlas = releases / "eoat-atlas-mirrorline"
    legacy = releases / "eoat-atlas-legacy"
    build_web_static(ROOT, commit("HEAD"), atlas)
    build_web_static(ROOT, commit("web-ui-legacy-0.22.12"), legacy)
    registry = _registry(
        tmp_path / "frontend-generations.json",
        {
            "atlas": _entry(atlas, _sha256(atlas / "web-static.manifest.json"), "mirrorline"),
            "legacy": _entry(legacy, _sha256(legacy / "web-static.manifest.json"), "legacy"),
        },
    )

    assert validate_generation(releases, registry, "atlas")["generation"] == "atlas"
    assert validate_generation(releases, registry, "legacy")["generation"] == "legacy"
    assert select_generation(releases, registry, "atlas")["activated"] == "true"
    current = releases / "current"
    assert current.is_symlink() and current.resolve() == atlas.resolve()
    assert select_generation(releases, registry, "legacy")["activated"] == "true"
    assert current.is_symlink() and current.resolve() == legacy.resolve()
    assert select_generation(releases, registry, "atlas")["activated"] == "true"
    assert current.is_symlink() and current.resolve() == atlas.resolve()

    (atlas / "index.html").write_text("tampered bundle", encoding="utf-8")
    with pytest.raises(FrontendGenerationError, match="hash manifest"):
        validate_generation(releases, registry, "atlas")
    manifest = json.loads((legacy / "web-static.manifest.json").read_text(encoding="utf-8"))
    manifest["index.html"] = "0" * 64
    (legacy / "web-static.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FrontendGenerationError, match="hash manifest"):
        validate_generation(releases, registry, "legacy")

    unsafe = json.loads(registry.read_text(encoding="utf-8"))
    unsafe["generations"]["atlas"]["release_directory"] = "../unsafe"
    registry.write_text(json.dumps(unsafe), encoding="utf-8")
    with pytest.raises(FrontendGenerationError, match="unsafe or missing"):
        validate_generation(releases, registry, "atlas")
