from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from deployment.convergence.phase3a import DisposableCoordinatedDeployment, VerifiedDeploymentInput


def _zip(path: Path, name: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, "ok")


def _input(tmp_path: Path) -> VerifiedDeploymentInput:
    server, web = tmp_path / "server.zip", tmp_path / "web.zip"
    _zip(server, "server.txt")
    _zip(web, "index.html")

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return VerifiedDeploymentInput(
        "0.24.0",
        "eoat-atlas-0.24.0",
        "build-1",
        "a" * 40,
        "b" * 40,
        "c" * 64,
        "test-key",
        "1.4.0",
        "schema-1",
        "NO_MIGRATION_REQUIRED",
        server,
        digest(server),
        web,
        digest(web),
    )


def test_disposable_stage_activate_parity_and_rollback(tmp_path: Path) -> None:
    item = _input(tmp_path)
    deployment = DisposableCoordinatedDeployment(tmp_path / "root")
    staged = deployment.stage(item, active_schema="schema-1")
    active = deployment.activate(staged["transaction_id"])
    assert active["state"] == "ACTIVE_CONFIRMED"
    assert deployment.drift(staged["transaction_id"])["classification"] == "MATCH"
    failing = DisposableCoordinatedDeployment(tmp_path / "failed", health=lambda *_: False)
    staged = failing.stage(item, active_schema="schema-1")
    assert failing.activate(staged["transaction_id"])["state"] == "ROLLED_BACK"
    assert failing.drift(staged["transaction_id"])["classification"] == "RECOVERY_REQUIRED"


def test_unknown_or_migration_required_modes_block_before_staging(tmp_path: Path) -> None:
    item = _input(tmp_path)
    deployment = DisposableCoordinatedDeployment(tmp_path / "root")
    for mode in ("MIGRATION_REQUIRED", "MIGRATION_STATE_UNKNOWN"):
        try:
            deployment.stage(
                VerifiedDeploymentInput(**{**item.__dict__, "migration_mode": mode}), active_schema="schema-1"
            )
        except Exception as error:
            assert "migration" in str(error)
        else:
            raise AssertionError("unsafe migration mode staged")
