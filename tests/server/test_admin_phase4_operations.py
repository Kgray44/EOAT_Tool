from __future__ import annotations

import hashlib
import os
from pathlib import Path

from server.eoat_api.admin.operations import _recovery_point_state
from server.eoat_api.services import EXPECTED_SCHEMA_REVISION


def _configure_recovery(monkeypatch, path: Path) -> None:
    monkeypatch.setenv("EOAT_PHASE4_TEST_RECOVERY_POINT", str(path))
    monkeypatch.setenv("EOAT_PHASE4_TEST_RECOVERY_POINT_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setenv("EOAT_PHASE4_TEST_RECOVERY_POINT_REVISION", EXPECTED_SCHEMA_REVISION)


def test_phase4_recovery_point_requires_hash_revision_and_freshness(tmp_path, monkeypatch):
    artifact = tmp_path / "test-recovery.sql"
    artifact.write_bytes(b"test-only recovery artifact")
    _configure_recovery(monkeypatch, artifact)
    assert _recovery_point_state()[0] == "PASS"

    monkeypatch.delenv("EOAT_PHASE4_TEST_RECOVERY_POINT_SHA256")
    assert _recovery_point_state()[0] == "FAIL"

    _configure_recovery(monkeypatch, artifact)
    monkeypatch.setenv("EOAT_PHASE4_TEST_RECOVERY_POINT_REVISION", "20260811_0007")
    assert _recovery_point_state()[0] == "FAIL"

    _configure_recovery(monkeypatch, artifact)
    artifact.write_bytes(b"modified after manifest")
    assert _recovery_point_state()[0] == "FAIL"

    _configure_recovery(monkeypatch, artifact)
    stale = os.path.getmtime(artifact) - (5 * 60 * 60)
    os.utime(artifact, (stale, stale))
    assert _recovery_point_state()[0] == "FAIL"
