from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from deployment.privileged.eoat_atlas_deploy_helper import Helper, Paths, Rejected, canonical_json, digest

COMMIT = "35dea122f0ee9fc0fd3a0ca6130de6a6f78d8811"
ARTIFACT = "eoat-atlas-server-0.17.3-35dea12.tar.gz"


def _paths(tmp_path: Path) -> Paths:
    root = tmp_path / "opt" / "eoat-atlas"
    paths = Paths(
        root=root,
        lock=tmp_path / "var" / "lock" / "eoat-atlas-deploy.lock",
        runtime_env=tmp_path / "etc" / "runtime.env",
    )
    for path in (paths.incoming, paths.releases, paths.shared, paths.transactions, paths.receipts, paths.backups):
        path.mkdir(parents=True, exist_ok=True)
    old = paths.releases / "eoat-atlas-server-0.17.1-b18de78"
    old.mkdir()
    (old / "venv").mkdir()
    return paths


def _manifest(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "application": "EOAT Atlas",
        "version": "0.17.3",
        "release_id": "eoat-atlas-0.17.3",
        "build_id": "eoat-atlas-0.17.3-35dea12-20260721T000000Z",
        "commit_sha": COMMIT,
        "branch": "development/mysql-api-consolidated",
        "created_at_utc": "2026-07-21T00:00:00Z",
        "payload_sha256": "a" * 64,
        "database": {"migration_system": "alembic", "target_revision": "20260717_0007"},
        "runtime": {"python": ">=3.13", "mysql": ">=8.4"},
        "services": ["eoat-atlas.service"],
        "health_checks": ["/api/v1/health"],
        "public_health_endpoint": {
            "scheme": "http",
            "hostname": "eoat-atlas.gwplastics.com",
            "port": 80,
            "paths": ["/api/v1/health"],
        },
        "api_contract_version": "1.4.0",
    }
    value.update(changes)
    return value


def _archive(
    path: Path, *, unsafe: bool = False, manifest: dict[str, object] | None = None, omit: str | None = None
) -> None:
    files = {
        "release_manifest.json": json.dumps(manifest or _manifest(), sort_keys=True).encode() + b"\n",
        "server/eoat_api/app.py": b"APP = 'EOAT'\n",
        "requirements.lock": b"example==1 --hash=sha256:" + b"a" * 64 + b"\n",
    }
    files.pop(omit, None)
    with tarfile.open(path, "w:gz") as bundle:
        for name, content in files.items():
            item = tarfile.TarInfo(name)
            item.size = len(content)
            bundle.addfile(item, io.BytesIO(content))
        if unsafe:
            item = tarfile.TarInfo("../escape")
            item.size = 1
            bundle.addfile(item, io.BytesIO(b"x"))


class Runner:
    def __init__(self, *, failures: tuple[str, ...] = (), health: dict[str, object] | None = None) -> None:
        self.failures, self.commands = list(failures), []
        self.health = health or {
            "api_reachable": True,
            "database_reachable": True,
            "compatible": True,
            "environment": "production",
            "writes_enabled": False,
            "current_schema_revision": "20260717_0007",
            "expected_schema_revision": "20260717_0007",
            "application_version": "0.17.3",
            "release_id": "eoat-atlas-0.17.3",
            "build_id": "eoat-atlas-0.17.3-35dea12-20260721T000000Z",
        }

    def __call__(self, command, **_kwargs):
        self.commands.append(command)
        if self.failures and self.failures[0] in " ".join(map(str, command)):
            self.failures.pop(0)
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="simulated failure")
        output = json.dumps(self.health) if "curl" in command[0] else "ok"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")


class HarnessHelper(Helper):
    """Filesystem harness for Windows, where the test account cannot create symlinks.

    Production executes Helper itself and therefore exercises its atomic Linux
    symlink replacement.  This small adapter isolates only the platform
    privilege limitation while allowing transactional state testing here.
    """

    def __init__(self, paths: Paths, runner: Runner) -> None:
        super().__init__(paths, runner)
        self.links = {"current": str(paths.releases / "eoat-atlas-server-0.17.1-b18de78")}

    def _current_target(self) -> str:
        return str(Path(self.links["current"]).resolve())

    def _replace_link(self, link: Path, target: Path, deployment_id: str) -> None:
        releases_root = self.paths.releases.resolve()
        if not target.is_dir() or target.resolve().parent != releases_root:
            raise Rejected("unsafe symlink target")
        self.links[link.name] = str(target.resolve())


def _request(paths: Paths, deployment_id: str = "deploy-0001") -> dict[str, str]:
    archive = paths.incoming / f".{deployment_id}.{ARTIFACT}"
    _archive(archive)
    _write_sidecars(paths, deployment_id, archive)
    return {
        "deployment_id": deployment_id,
        "version": "0.17.3",
        "commit_sha": COMMIT,
        "artifact_filename": ARTIFACT,
        "artifact_sha256": digest(archive),
        "external_manifest_sha256": digest(paths.incoming / f".{deployment_id}.release_manifest.json"),
        "migration_decision": "NOT_REQUIRED",
    }


def _write_sidecars(paths: Paths, deployment_id: str, archive: Path, manifest: dict[str, object] | None = None) -> None:
    core = manifest or _manifest()
    archive_sha = digest(archive)
    external = {
        "manifest_schema_version": 1,
        "manifest_core": core,
        "embedded_manifest_sha256": hashlib.sha256(canonical_json(core)).hexdigest(),
        "artifact": {
            "filename": ARTIFACT,
            "format": "tar.gz",
            "sha256": archive_sha,
            "size_bytes": archive.stat().st_size,
        },
    }
    external_path = paths.incoming / f".{deployment_id}.release_manifest.json"
    external_path.write_text(json.dumps(external, sort_keys=True), encoding="utf-8")
    (paths.incoming / f".{deployment_id}.{ARTIFACT}.sha256").write_text(
        f"{archive_sha}  {ARTIFACT}\n", encoding="utf-8"
    )


def _staged(tmp_path: Path, *, runner: Runner | None = None) -> tuple[Paths, HarnessHelper, dict[str, str], Runner]:
    paths, actual_runner = _paths(tmp_path), runner or Runner()
    helper, request = HarnessHelper(paths, actual_runner), _request(paths)
    helper.begin(request)
    helper.stage({"deployment_id": request["deployment_id"]})
    return paths, helper, request, actual_runner


def test_successful_transaction_creates_previous_current_and_receipt(tmp_path: Path) -> None:
    paths, helper, request, runner = _staged(tmp_path)
    completed = helper.activate({"deployment_id": request["deployment_id"]})
    assert completed["state"] == "COMPLETED"
    assert Path(helper.links["current"]).name == "eoat-atlas-server-0.17.3-35dea12"
    assert Path(helper.links["previous"]).name == "eoat-atlas-server-0.17.1-b18de78"
    assert not paths.lock.exists()
    assert json.loads((paths.receipts / "deploy-0001.json").read_text())["state"] == "COMPLETED"
    assert any(command[0] == "/usr/bin/chown" for command in runner.commands)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("deployment_id", "../../bad", "deployment_id"),
        ("version", "0.17", "version"),
        ("commit_sha", "ABC", "commit_sha"),
        ("artifact_filename", "../../evil.tar.gz", "artifact_filename"),
        ("artifact_sha256", "a" * 63, "artifact_sha256"),
        ("artifact_filename", "release.zip", "artifact identity"),
        ("migration_decision", "REQUIRED", "migration-bearing"),
    ],
)
def test_begin_and_migration_reject_invalid_transaction_inputs(
    tmp_path: Path, field: str, value: str, reason: str
) -> None:
    paths = _paths(tmp_path / "helper")
    helper = HarnessHelper(paths, Runner())
    request = _request(paths)
    request[field] = value
    if field == "migration_decision":
        helper.begin(request)
        with pytest.raises(Rejected, match=reason):
            helper.stage({"deployment_id": request["deployment_id"]})
    else:
        with pytest.raises(Rejected, match=reason):
            helper.begin(request)


@pytest.mark.parametrize(
    "operation,payload,reason",
    [
        ("shell", {}, "unsupported"),
        ("begin", {"path": "/etc/passwd"}, "unknown request fields"),
        ("status", {"deployment_id": "missing-0001"}, "unknown"),
        ("activate", {"deployment_id": "missing-0001"}, "unknown"),
        ("retention-status", {"command": "id"}, "unknown request fields"),
    ],
)
def test_dispatch_rejects_unapproved_privileged_surface(
    tmp_path: Path, operation: str, payload: dict[str, str], reason: str
) -> None:
    helper = HarnessHelper(_paths(tmp_path), Runner())
    with pytest.raises(Rejected, match=reason):
        helper.dispatch({"operation": operation, **payload})


def test_corrupt_upload_unsafe_archive_missing_runtime_and_existing_target_are_rejected(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "hash")
    helper = HarnessHelper(paths, Runner())
    request = _request(paths)
    helper.begin(request)
    (paths.incoming / f".{request['deployment_id']}.{ARTIFACT}").write_bytes(b"bad")
    with pytest.raises(Rejected, match="hash"):
        helper.stage({"deployment_id": request["deployment_id"]})

    paths2 = _paths(tmp_path / "unsafe")
    helper2 = HarnessHelper(paths2, Runner())
    request2 = _request(paths2)
    archive = paths2.incoming / f".{request2['deployment_id']}.{ARTIFACT}"
    _archive(archive, unsafe=True)
    request2["artifact_sha256"] = digest(archive)
    _write_sidecars(paths2, request2["deployment_id"], archive)
    request2["external_manifest_sha256"] = digest(
        paths2.incoming / f".{request2['deployment_id']}.release_manifest.json"
    )
    helper2.begin(request2)
    with pytest.raises(Rejected, match="unsafe archive"):
        helper2.stage({"deployment_id": request2["deployment_id"]})

    paths3 = _paths(tmp_path / "missing")
    helper3 = HarnessHelper(paths3, Runner())
    request3 = _request(paths3)
    archive = paths3.incoming / f".{request3['deployment_id']}.{ARTIFACT}"
    _archive(archive, omit="requirements.lock")
    request3["artifact_sha256"] = digest(archive)
    _write_sidecars(paths3, request3["deployment_id"], archive)
    request3["external_manifest_sha256"] = digest(
        paths3.incoming / f".{request3['deployment_id']}.release_manifest.json"
    )
    helper3.begin(request3)
    with pytest.raises(Rejected, match="misses required"):
        helper3.stage({"deployment_id": request3["deployment_id"]})

    paths4 = _paths(tmp_path / "existing")
    helper4 = HarnessHelper(paths4, Runner())
    request4 = _request(paths4)
    helper4.begin(request4)
    (paths4.releases / "eoat-atlas-server-0.17.3-35dea12").mkdir()
    with pytest.raises(Rejected, match="already exists"):
        helper4.stage({"deployment_id": request4["deployment_id"]})


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"version": "0.17.4"}, "identity"),
        ({"commit_sha": "a" * 40}, "identity"),
        ({"release_id": ""}, "release/build"),
        ({"build_id": ""}, "release/build"),
    ],
)
def test_staging_binds_embedded_manifest_identity(tmp_path: Path, change: dict[str, object], reason: str) -> None:
    paths = _paths(tmp_path / "manifest")
    helper = HarnessHelper(paths, Runner())
    request = _request(paths)
    archive = paths.incoming / f".{request['deployment_id']}.{ARTIFACT}"
    _archive(archive, manifest=_manifest(**change))
    request["artifact_sha256"] = digest(archive)
    _write_sidecars(paths, request["deployment_id"], archive, _manifest(**change))
    request["external_manifest_sha256"] = digest(paths.incoming / f".{request['deployment_id']}.release_manifest.json")
    helper.begin(request)
    with pytest.raises(Rejected, match=reason):
        helper.stage({"deployment_id": request["deployment_id"]})


def test_lock_contention_abort_and_recovery_boundaries(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "lock")
    helper = HarnessHelper(paths, Runner())
    request = _request(paths)
    helper.begin(request)
    with pytest.raises(Rejected, match="lock is held"):
        helper.begin(_request(paths, "deploy-0002"))
    recovery = helper.recover({"deployment_id": request["deployment_id"]})
    assert recovery["recovery"]["required_action"] == "abort"
    state = helper.abort({"deployment_id": request["deployment_id"]})
    assert state["state"] == "FAILED" and not paths.lock.exists()
    with pytest.raises(Rejected, match="absent"):
        helper.abort({"deployment_id": request["deployment_id"]})


def test_health_failure_rolls_back_without_database_action(tmp_path: Path) -> None:
    paths, helper, request, _ = _staged(tmp_path, runner=Runner(failures=("curl",)))
    result = helper.activate({"deployment_id": request["deployment_id"]})
    assert result["state"] == "ROLLED_BACK"
    assert Path(helper.links["current"]).name == "eoat-atlas-server-0.17.1-b18de78"
    assert result["backup"]["database"] == "NOT_REQUIRED" and not paths.lock.exists()


def test_identity_health_mismatch_rolls_back(tmp_path: Path) -> None:
    bad_health = {
        "api_reachable": True,
        "database_reachable": True,
        "compatible": True,
        "environment": "production",
        "writes_enabled": False,
        "current_schema_revision": "20260717_0007",
        "expected_schema_revision": "20260717_0007",
        "application_version": "0.17.2",
        "release_id": "eoat-atlas-0.17.3",
        "build_id": "eoat-atlas-0.17.3-35dea12-20260721T000000Z",
    }
    paths, helper, request, _ = _staged(tmp_path, runner=Runner(health=bad_health))
    result = helper.activate({"deployment_id": request["deployment_id"]})
    assert result["state"] == "ROLLED_BACK"
    assert Path(helper.links["current"]).name == "eoat-atlas-server-0.17.1-b18de78"


def test_failed_rollback_preserves_lock_and_requires_manual_intervention(tmp_path: Path) -> None:
    paths, helper, request, _ = _staged(tmp_path, runner=Runner(failures=("curl", "curl")))
    with pytest.raises(Rejected, match="manual intervention"):
        helper.activate({"deployment_id": request["deployment_id"]})
    assert helper.status({"deployment_id": request["deployment_id"]})["state"] == "MANUAL_INTERVENTION_REQUIRED"
    assert paths.lock.exists()


def test_current_change_after_staging_is_rejected_and_explicit_rollback_is_bounded(tmp_path: Path) -> None:
    paths, helper, request, _ = _staged(tmp_path)
    other = paths.releases / "eoat-atlas-server-0.17.2-aaaaaaa"
    other.mkdir()
    helper.links["current"] = str(other)
    with pytest.raises(Rejected, match="changed since staging"):
        helper.activate({"deployment_id": request["deployment_id"]})
    with pytest.raises(Rejected, match="not eligible"):
        helper.rollback({"deployment_id": request["deployment_id"]})


def test_retention_status_is_machine_readable_without_a_previous_release(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    helper = HarnessHelper(paths, Runner())
    payload = helper.retention_status({})
    assert payload["previous"] == []
    assert json.loads(json.dumps(payload))["current"].endswith("eoat-atlas-server-0.17.1-b18de78")
