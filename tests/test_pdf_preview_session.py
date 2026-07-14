from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from core.reporting.pdf_preview_session import PdfPreviewSession, cleanup_abandoned_preview_files


def _session(path: Path, root: Path, **kwargs) -> PdfPreviewSession:
    return PdfPreviewSession(
        "setup_packet",
        "Tool 1 / Machine 2 / EOAT 3",
        path,
        root.parent / "exports" / path.name,
        temp_preview_dir=root,
        auto_save_close_seconds=0,
        **kwargs,
    )


def test_temporary_pdf_cleanup_immediate_success(tmp_path: Path) -> None:
    root = tmp_path / "eoat_atlas_setup_packet_previews"
    path = root / "preview.pdf"
    root.mkdir()
    path.write_bytes(b"pdf")
    session = _session(path, root)

    assert session.cleanup_temp_if_needed()
    assert not path.exists()


def test_temporary_pdf_cleanup_retries_transient_windows_lock(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "eoat_atlas_setup_packet_previews"
    path = root / "preview.pdf"
    root.mkdir()
    path.write_bytes(b"pdf")
    callbacks: list[object] = []
    original_unlink = Path.unlink
    attempts = 0

    def flaky_unlink(candidate: Path, *args, **kwargs):
        nonlocal attempts
        if candidate == path and attempts < 2:
            attempts += 1
            error = PermissionError(13, "file is in use", str(candidate))
            error.winerror = 32
            raise error
        return original_unlink(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    session = _session(path, root, cleanup_retry_delays=(0, 0), retry_scheduler=lambda _delay, callback: callbacks.append(callback))

    assert not session.cleanup_temp_if_needed()
    while callbacks:
        callbacks.pop(0)()

    assert attempts == 2
    assert not path.exists()


def test_persistent_pdf_lock_warns_once_and_later_maintenance_cleans(tmp_path: Path, monkeypatch, caplog) -> None:
    root = tmp_path / "eoat_atlas_setup_packet_previews"
    path = root / "preview.pdf"
    root.mkdir()
    path.write_bytes(b"pdf")
    callbacks: list[object] = []
    original_unlink = Path.unlink

    def locked_unlink(candidate: Path, *args, **kwargs):
        if candidate == path:
            error = PermissionError(13, "file is in use", str(candidate))
            error.winerror = 32
            raise error
        return original_unlink(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_unlink)
    session = _session(path, root, cleanup_retry_delays=(0, 0), retry_scheduler=lambda _delay, callback: callbacks.append(callback))
    caplog.set_level(logging.WARNING)
    session.close()
    while callbacks:
        callbacks.pop(0)()
    session.cleanup_temp_if_needed()

    warnings = [record for record in caplog.records if "cleanup deferred" in record.getMessage()]
    assert len(warnings) == 1
    assert str(path) in warnings[0].getMessage()
    assert path.exists()

    monkeypatch.setattr(Path, "unlink", original_unlink)
    old = time.time() - 7200
    os.utime(path, (old, old))
    assert cleanup_abandoned_preview_files(root, minimum_age_seconds=60) == (path,)
    assert not path.exists()


def test_pdf_cleanup_never_deletes_outside_registered_preview_root(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "eoat_atlas_setup_packet_previews"
    root.mkdir()
    exported = tmp_path / "exports" / "saved.pdf"
    exported.parent.mkdir()
    exported.write_bytes(b"saved")
    calls: list[Path] = []
    original_unlink = Path.unlink

    def recording_unlink(candidate: Path, *args, **kwargs):
        calls.append(candidate)
        return original_unlink(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", recording_unlink)
    session = _session(exported, root)

    assert not session.cleanup_temp_if_needed()
    assert exported.exists()
    assert calls == []


def test_maintenance_skips_active_preview_then_removes_it_after_close(tmp_path: Path) -> None:
    root = tmp_path / "eoat_atlas_setup_packet_previews"
    path = root / "active.pdf"
    root.mkdir()
    path.write_bytes(b"pdf")
    old = time.time() - 7200
    os.utime(path, (old, old))
    session = _session(path, root)

    assert cleanup_abandoned_preview_files(root, minimum_age_seconds=60) == ()
    assert path.exists()
    session.defer_cleanup()
    assert cleanup_abandoned_preview_files(root, minimum_age_seconds=60) == (path,)
