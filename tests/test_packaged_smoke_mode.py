from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.atlas import main as atlas_main
from scripts import build_package


class _SmokeApplication:
    """Minimal Qt stand-in proving smoke mode never enters the event loop."""

    event_loop_entered = False

    def __init__(self, _argv: list[str]) -> None:
        pass

    def setApplicationName(self, _value: str) -> None:  # noqa: N802 - Qt API
        pass

    def setApplicationDisplayName(self, _value: str) -> None:  # noqa: N802 - Qt API
        pass

    def setFont(self, _value: object) -> None:  # noqa: N802 - Qt API
        pass

    def setWindowIcon(self, _value: object) -> None:  # noqa: N802 - Qt API
        pass

    def exec(self) -> int:
        type(self).event_loop_entered = True
        raise AssertionError("packaged smoke must not enter the interactive Qt event loop")


def test_packaged_smoke_writes_receipt_and_exits_before_window_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt = tmp_path / "desktop-smoke.json"
    _SmokeApplication.event_loop_entered = False
    monkeypatch.setattr(atlas_main, "QApplication", _SmokeApplication)
    monkeypatch.setattr(atlas_main, "QFont", lambda *_args: object())
    monkeypatch.setattr(atlas_main, "QIcon", lambda *_args: object())
    monkeypatch.setattr(atlas_main, "configure_release_logging", lambda: None)
    monkeypatch.setattr(
        atlas_main,
        "get_version_info",
        lambda: SimpleNamespace(application_version="0.24.0", release_id="release-24", build_id="build-24"),
    )
    monkeypatch.setattr(atlas_main.sys, "argv", ["EOAT Atlas.exe", "--smoke-test", "--smoke-receipt", str(receipt)])
    monkeypatch.setenv("EOAT_ATLAS_DATA_BACKEND", "mysql_api")
    monkeypatch.setenv("EOAT_RELEASE_CANDIDATE_ID", "candidate-24")
    monkeypatch.setenv("EOAT_RELEASE_SOURCE_COMMIT", "a" * 40)
    monkeypatch.setenv("EOAT_RELEASE_SOURCE_TREE", "b" * 40)

    assert atlas_main.main() == 0
    assert _SmokeApplication.event_loop_entered is False
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["candidate_id"] == "candidate-24"
    assert payload["checks"] == ["qt-application-created", "release-identity-loaded", "clean-exit"]


def test_packaged_smoke_fails_before_qt_startup_for_invalid_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(atlas_main, "configure_release_logging", lambda: None)
    monkeypatch.setattr(atlas_main.sys, "argv", ["EOAT Atlas.exe", "--smoke-test"])
    monkeypatch.setenv("EOAT_ATLAS_DATA_BACKEND", "invalid")

    with pytest.raises(SystemExit, match="Invalid EOAT_ATLAS_DATA_BACKEND"):
        atlas_main.main()


def test_candidate_package_timestamp_is_explicit_and_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EOAT_RELEASE_BUILD_TIMESTAMP", "2026-07-27T19:28:32Z")
    assert build_package._candidate_build_timestamp().isoformat() == "2026-07-27T19:28:32+00:00"
    monkeypatch.setenv("EOAT_RELEASE_BUILD_TIMESTAMP", "not-a-timestamp")
    with pytest.raises(RuntimeError, match="EOAT_RELEASE_BUILD_TIMESTAMP"):
        build_package._candidate_build_timestamp()
