"""Bounded, candidate-local cleanup of disposable Windows web build trees."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from deployment import web_release
from deployment.common import DeploymentError


def _staging(parent: Path, name: str = "eoat-web-release-test") -> Path:
    directory = parent / name
    directory.mkdir(parents=True)
    (directory / "payload.txt").write_text("disposable", encoding="utf-8")
    return directory


def test_normal_cleanup_removes_only_governed_staging(tmp_path: Path) -> None:
    parent = tmp_path / "w"
    staging = _staging(parent)
    destination = tmp_path / "release"
    destination.mkdir()
    (destination / "index.html").write_text("complete", encoding="utf-8")

    result = web_release._cleanup_web_staging_with_retry(parent, staging, sleep=lambda _delay: None)

    assert result["status"] == "REMOVED"
    assert not staging.exists()
    assert (destination / "index.html").read_text(encoding="utf-8") == "complete"


def test_transient_windows_lock_retries_then_removes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parent = tmp_path / "w"
    staging = _staging(parent)
    real_rmtree = shutil.rmtree
    calls = 0

    def transient_once(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(145, "directory not empty")
        real_rmtree(path)

    monkeypatch.setattr(web_release.shutil, "rmtree", transient_once)
    result = web_release._cleanup_web_staging_with_retry(parent, staging, sleep=lambda _delay: None)

    assert result == {"status": "REMOVED", "attempts": 2}
    assert not staging.exists()


def test_persistent_lock_retains_one_redacted_governed_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parent = tmp_path / "w"
    staging = _staging(parent)

    def locked(_path: Path) -> None:
        raise OSError(145, "directory not empty")

    monkeypatch.setattr(web_release.shutil, "rmtree", locked)
    result = web_release._cleanup_web_staging_with_retry(parent, staging, sleep=lambda _delay: None)

    assert result["status"] == "RETAINED"
    assert result["category"] == "TRANSIENT_LOCK_EXHAUSTED"
    assert "payload.txt" not in str(result)
    assert str(staging) not in str(result)
    assert staging.is_dir()


def test_reconciliation_removes_stale_but_not_active_or_unrelated(tmp_path: Path) -> None:
    parent = tmp_path / "w"
    stale = _staging(parent, "eoat-web-release-stale")
    active = _staging(parent, "eoat-web-release-active")
    unrelated = _staging(parent, "not-owned-by-web-builder")

    web_release._reconcile_stale_web_staging(parent, active=active)

    assert not stale.exists()
    assert active.is_dir()
    assert unrelated.is_dir()


def test_reconciliation_blocks_when_retention_limit_cannot_be_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "w"
    for index in range(web_release._WEB_STAGING_MAX_RETAINED_DIRECTORIES):
        _staging(parent, f"eoat-web-release-locked-{index}")

    def locked(_path: Path) -> None:
        raise OSError(145, "directory not empty")

    monkeypatch.setattr(web_release.shutil, "rmtree", locked)
    with pytest.raises(DeploymentError, match="retention limit"):
        web_release._reconcile_stale_web_staging(parent)


def test_cleanup_refuses_traversal_or_non_owned_path(tmp_path: Path) -> None:
    parent = tmp_path / "w"
    parent.mkdir()
    unrelated = tmp_path / "outside"
    unrelated.mkdir()

    with pytest.raises(DeploymentError, match="unsafe web staging"):
        web_release._cleanup_web_staging_with_retry(parent, unrelated, sleep=lambda _delay: None)
    assert unrelated.is_dir()
