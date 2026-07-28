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
    identity = {
        "product_version": "0.24.0",
        "release_id": "eoat-atlas-0.24.0",
        "build_id": "build-1",
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "release_set_digest": "c" * 64,
    }
    with zipfile.ZipFile(server, "w") as archive:
        archive.writestr("release_identity.json", __import__("json").dumps(identity))
        archive.writestr("app.py", "# immutable API entry point\n")
    index = b"<html><body>EOAT Atlas</body></html>"
    with zipfile.ZipFile(web, "w") as archive:
        archive.writestr("index.html", index)
        archive.writestr("release_identity.json", __import__("json").dumps(identity))
        archive.writestr("web-static.manifest.json", __import__("json").dumps({"index.html": hashlib.sha256(index).hexdigest()}))

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


def test_staging_rejects_mutated_embedded_identity_and_unsafe_web_content(tmp_path: Path) -> None:
    item = _input(tmp_path)
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(tampered, "w") as archive:
        archive.writestr("release_identity.json", '{"release_id":"wrong"}')
        archive.writestr("app.py", "# no")
    bad = VerifiedDeploymentInput(**{**item.__dict__, "server_archive": tampered, "server_sha256": hashlib.sha256(tampered.read_bytes()).hexdigest()})
    try:
        DisposableCoordinatedDeployment(tmp_path / "root").stage(bad, active_schema="schema-1")
    except Exception as error:
        assert "identity" in str(error)
    else:
        raise AssertionError("mutated embedded server identity was accepted")


def test_drift_scanner_reports_match_mismatch_and_recovery_truth(tmp_path: Path) -> None:
    item = _input(tmp_path)
    deployment = DisposableCoordinatedDeployment(tmp_path / "runtime")
    staged = deployment.stage(item, active_schema="schema-1")
    assert deployment.activate(staged["transaction_id"])["state"] == "ACTIVE_CONFIRMED"
    assert deployment.drift(staged["transaction_id"])["classification"] == "MATCH"
    assert deployment.drift(staged["transaction_id"], desktop_identity={"release_id": "other"})["classification"] == "MISMATCH"
    failed = DisposableCoordinatedDeployment(tmp_path / "failed", health=lambda *_: False)
    rejected = failed.stage(item, active_schema="schema-1")
    assert failed.activate(rejected["transaction_id"])["state"] == "ROLLED_BACK"
    assert failed.drift(rejected["transaction_id"])["classification"] == "RECOVERY_REQUIRED"
