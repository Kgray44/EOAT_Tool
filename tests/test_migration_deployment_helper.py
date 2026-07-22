"""Disposable end-to-end coverage for the restricted migration workflow."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from deployment.privileged.eoat_atlas_deploy_helper import (
    Helper,
    Paths,
    Rejected,
    canonical_json,
    digest,
)

COMMIT = "8f0788e5938dd6ec1056759b2594d05833407d41"
ARTIFACT = "eoat-atlas-server-0.18.0-8f0788e.tar.gz"
PREDECESSOR = "20260717_0007"
TARGET = "20260721_0008"


class Runner:
    def __init__(self, *, fail: str | None = None) -> None:
        self.commands: list[list[str]] = []
        self.mysql_defaults: list[str] = []
        self.fail = fail
        self.health = {
            "api_reachable": True,
            "database_reachable": True,
            "compatible": True,
            "environment": "production",
            "writes_enabled": False,
            "current_schema_revision": TARGET,
            "expected_schema_revision": TARGET,
            "database_schema_revision": TARGET,
            "application_version": "0.18.0",
            "release_id": "eoat-atlas-0.18.0",
            "build_id": "eoat-atlas-0.18.0-8f0788e-test",
        }

    def __call__(self, command, **kwargs):
        command = list(command)
        self.commands.append(command)
        for part in command:
            if str(part).startswith("--defaults-extra-file="):
                self.mysql_defaults.append(Path(str(part).split("=", 1)[1]).read_text(encoding="utf-8"))
        if self.fail and self.fail in " ".join(command):
            self.fail = None
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="failure with EOAT_DB_PASSWORD=redacted")
        for value in command:
            if str(value).startswith("--result-file="):
                Path(str(value).split("=", 1)[1]).write_text("-- MySQL dump\nCREATE TABLE example (id int);\n", encoding="utf-8")
        if command[:4] == ["/bin/systemctl", "show", "--property=MainPID", "--value"]:
            return subprocess.CompletedProcess(command, 0, stdout="4242\n", stderr="")
        if any("EOAT_STAGE_RUNTIME_VALIDATION" in str(value) for value in command):
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"health": self.health, "version": self.health}), stderr="")
        if "curl" in command[0]:
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(self.health), stderr="")
        if command[0] == "/usr/bin/mysql":
            if any("information_schema.ROUTINES" in str(part) for part in command):
                return subprocess.CompletedProcess(command, 0, stdout="0\t0\n", stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="1\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")


class DisposableHelper(Helper):
    def __init__(self, paths: Paths, runner: Runner) -> None:
        super().__init__(paths, runner)
        self.links = {"current": str(paths.releases / "eoat-atlas-server-0.17.3-35dea12")}
        self.revision = PREDECESSOR

    def _current_target(self) -> str:
        return str(Path(self.links["current"]).resolve())

    def _replace_link(self, link: Path, target: Path, deployment_id: str) -> None:
        self.links[link.name] = str(target.resolve())

    def _migration_command(self, state, action):
        if action == "current":
            return ["/fixed/alembic", "current"]
        if action == "upgrade":
            return ["/fixed/alembic", "upgrade", TARGET]
        if action == "downgrade":
            return ["/fixed/alembic", "downgrade", PREDECESSOR]
        raise Rejected("unsupported fixed migration action")

    def _alembic_revision(self, state) -> str:
        return self.revision

    def _run(self, command, **kwargs):
        result = super()._run(command, **kwargs)
        if command[-2:] == ["upgrade", TARGET]:
            self.revision = TARGET
        elif command[-2:] == ["downgrade", PREDECESSOR]:
            self.revision = PREDECESSOR
        return result


def paths(tmp_path: Path) -> Paths:
    value = Paths(
        root=tmp_path / "opt" / "eoat-atlas",
        lock=tmp_path / "var" / "lock" / "eoat-atlas-deploy.lock",
        runtime_env=tmp_path / "etc" / "runtime.env",
        migration_env=tmp_path / "etc" / "migration.env",
        proc=tmp_path / "proc",
    )
    for directory in (value.incoming, value.releases, value.transactions, value.receipts, value.backups):
        directory.mkdir(parents=True, exist_ok=True)
    (value.releases / "eoat-atlas-server-0.17.3-35dea12").mkdir()
    process = value.proc / "4242"
    process.mkdir(parents=True)
    (process / "environ").write_bytes(b"EOAT_API_ENVIRONMENT=production\0EOAT_API_WRITES_ENABLED=false\0")
    value.migration_env.parent.mkdir(parents=True, exist_ok=True)
    value.migration_env.write_text(
        "EOAT_API_ENVIRONMENT=production\n"
        "EOAT_API_WRITES_ENABLED=false\n"
        "EOAT_DB_HOST=127.0.0.1\n"
        "EOAT_DB_PORT=3306\n"
        "EOAT_DB_NAME=eoat_atlas_prod\n"
        "EOAT_MIGRATION_DB_USER=eoat_migrate\n"
        "EOAT_MIGRATION_DB_PASSWORD=disposable-only\n",
        encoding="utf-8",
    )
    return value


def core() -> dict[str, object]:
    return {
        "version": "0.18.0", "release_id": "eoat-atlas-0.18.0", "build_id": "eoat-atlas-0.18.0-8f0788e-test",
        "commit_sha": COMMIT, "payload_sha256": "a" * 64,
        "database": {"migration_system": "alembic", "target_revision": TARGET, "minimum_compatible_revision": PREDECESSOR},
    }


def request(value: Paths, deployment_id: str = "deploy-0001") -> dict[str, str]:
    archive = value.incoming / f".{deployment_id}.{ARTIFACT}"
    files = {
        "release_manifest.json": json.dumps(core()).encode(),
        "server/eoat_api/app.py": b"APP = 'EOAT'\n",
        "server/alembic.ini": b"[alembic]\n",
        "server/migrations/versions/20260721_0008_data_state_freshness.py": b"revision = '20260721_0008'\n",
        "requirements.lock": b"example==1 --hash=sha256:" + b"a" * 64,
    }
    with tarfile.open(archive, "w:gz") as bundle:
        for name, content in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            bundle.addfile(entry, io.BytesIO(content))
    external = {"manifest_core": core(), "embedded_manifest_sha256": hashlib.sha256(canonical_json(core())).hexdigest(), "artifact": {"filename": ARTIFACT, "sha256": digest(archive), "size_bytes": archive.stat().st_size}}
    (value.incoming / f".{deployment_id}.release_manifest.json").write_text(json.dumps(external), encoding="utf-8")
    (value.incoming / f".{deployment_id}.{ARTIFACT}.sha256").write_text(f"{digest(archive)}  {ARTIFACT}\n", encoding="utf-8")
    return {"deployment_id": deployment_id, "version": "0.18.0", "commit_sha": COMMIT, "artifact_filename": ARTIFACT, "artifact_sha256": digest(archive), "external_manifest_sha256": digest(value.incoming / f".{deployment_id}.release_manifest.json"), "migration_decision": "REQUIRED"}


def staged(tmp_path: Path, *, runner: Runner | None = None):
    value = paths(tmp_path)
    active_runner = runner or Runner()
    helper = DisposableHelper(value, active_runner)
    payload = request(value)
    helper.begin(payload)
    helper.backup_production({"deployment_id": payload["deployment_id"]})
    helper.verify_backup({"deployment_id": payload["deployment_id"]})
    helper.stage({"deployment_id": payload["deployment_id"]})
    return value, helper, payload, active_runner


def test_disposable_migration_deployment_end_to_end(tmp_path: Path) -> None:
    value, helper, payload, runner = staged(tmp_path)
    helper.migration_preflight({"deployment_id": payload["deployment_id"]})
    helper.apply_migration({"deployment_id": payload["deployment_id"]})
    helper.verify_migration({"deployment_id": payload["deployment_id"]})
    result = helper.activate({"deployment_id": payload["deployment_id"]})
    assert result["state"] == "COMPLETED" and not value.lock.exists()
    assert helper.revision == TARGET and Path(helper.links["current"]).name.endswith("8f0788e")
    assert json.loads((value.receipts / f"{payload['deployment_id']}.json").read_text())["state"] == "COMPLETED"
    backup_command = next(command for command in runner.commands if command[0] == "/usr/bin/mysqldump")
    assert any(part.startswith("--defaults-extra-file=") for part in backup_command)
    assert not any(part.startswith("--user=") or part.startswith("--login-path=") for part in backup_command)
    assert "--single-transaction" in backup_command
    assert "--no-tablespaces" in backup_command
    assert "--routines" not in backup_command and "--events" not in backup_command
    probe_commands = [command for command in runner.commands if command[0] == "/usr/bin/mysql"]
    connection_probe = next(command for command in probe_commands if command[-2] == "SELECT 1")
    metadata_probe = next(command for command in probe_commands if command[-2] == "SHOW TABLES; SHOW EVENTS; SHOW TRIGGERS")
    completeness_probe = next(command for command in probe_commands if "information_schema.ROUTINES" in command[-2])
    assert connection_probe[-1] == metadata_probe[-1] == completeness_probe[-1] == "eoat_atlas_prod"
    assert "--batch" in connection_probe and "--skip-column-names" in connection_probe
    expected_defaults = '[client]\nuser="eoat_migrate"\npassword="disposable-only"\nhost="127.0.0.1"\nport="3306"\n'
    assert runner.mysql_defaults and all(item == expected_defaults for item in runner.mysql_defaults)


def test_backup_corruption_wrong_schema_and_concurrency_block_migration(tmp_path: Path) -> None:
    value = paths(tmp_path)
    helper = DisposableHelper(value, Runner())
    payload = request(value)
    helper.begin(payload)
    with pytest.raises(Rejected, match="backup"):
        helper.stage({"deployment_id": payload["deployment_id"]})
    with pytest.raises(Rejected, match="lock is held"):
        helper.begin(request(value, "deploy-0002"))
    helper.backup_production({"deployment_id": payload["deployment_id"]})
    state = helper.status({"deployment_id": payload["deployment_id"]})
    Path(state["backup"]["path"]).write_bytes(b"corrupt")
    with pytest.raises(Rejected, match="verification"):
        helper.verify_backup({"deployment_id": payload["deployment_id"]})

    value2, helper2, payload2, _ = staged(tmp_path / "wrong-schema")
    helper2.revision = "20250101_0001"
    with pytest.raises(Rejected, match="predecessor"):
        helper2.migration_preflight({"deployment_id": payload2["deployment_id"]})


def test_backup_command_failure_is_recoverable_and_releases_no_partial_file(tmp_path: Path) -> None:
    value = paths(tmp_path)
    helper = DisposableHelper(value, Runner(fail="mysqldump"))
    payload = request(value)
    helper.begin(payload)

    with pytest.raises(Rejected, match="approved production backup \\(approved command exited nonzero"):
        helper.backup_production({"deployment_id": payload["deployment_id"]})

    state = helper.status({"deployment_id": payload["deployment_id"]})
    partial = value.backups / f"{payload['deployment_id']}-eoat_atlas_prod-pre-migration.sql.partial"
    assert state["state"] == "FAILED"
    assert state["failure"] == "approved command failed: approved production backup (approved command exited nonzero (exit status 1))"
    assert not partial.exists()
    assert Path(helper.links["current"]).name.endswith("35dea12")
    helper.cleanup_failed_deployment({"deployment_id": payload["deployment_id"]})
    assert not value.lock.exists()


def test_backup_query_privilege_failure_is_redacted_and_actionable(tmp_path: Path) -> None:
    class QueryDeniedRunner(Runner):
        def __call__(self, command, **kwargs):
            command = list(command)
            if command[0] == "/usr/bin/mysqldump":
                return subprocess.CompletedProcess(
                    command,
                    2,
                    stdout="",
                    stderr="mysqldump: Couldn't execute 'SHOW VIEW': SHOW VIEW command denied",
                )
            return super().__call__(command, **kwargs)

    value = paths(tmp_path)
    helper = DisposableHelper(value, QueryDeniedRunner())
    payload = request(value)
    helper.begin(payload)

    with pytest.raises(Rejected, match="required database read privilege unavailable"):
        helper.backup_production({"deployment_id": payload["deployment_id"]})

    state = helper.status({"deployment_id": payload["deployment_id"]})
    assert state["state"] == "FAILED"
    assert "SHOW VIEW" not in json.dumps(state)


def test_backup_refuses_stored_programs_without_full_backup_identity(tmp_path: Path) -> None:
    class StoredProgramRunner(Runner):
        def __call__(self, command, **kwargs):
            command = list(command)
            if command[0] == "/usr/bin/mysql" and any("information_schema.ROUTINES" in str(part) for part in command):
                return subprocess.CompletedProcess(command, 0, stdout="1\t0\n", stderr="")
            return super().__call__(command, **kwargs)

    value = paths(tmp_path)
    helper = DisposableHelper(value, StoredProgramRunner())
    payload = request(value)
    helper.begin(payload)

    with pytest.raises(Rejected, match="stored programs require an approved full-backup identity"):
        helper.backup_production({"deployment_id": payload["deployment_id"]})

    assert helper.status({"deployment_id": payload["deployment_id"]})["state"] == "FAILED"


def test_migration_failure_preserves_old_release_and_backup_restore_is_bounded(tmp_path: Path) -> None:
    value, helper, payload, runner = staged(tmp_path, runner=Runner(fail="upgrade"))
    helper.migration_preflight({"deployment_id": payload["deployment_id"]})
    with pytest.raises(Rejected, match="migration"):
        helper.apply_migration({"deployment_id": payload["deployment_id"]})
    assert helper.status({"deployment_id": payload["deployment_id"]})["state"] == "FAILED"
    assert Path(helper.links["current"]).name.endswith("35dea12") and value.lock.exists()
    helper.revision = PREDECESSOR
    restored = helper.restore_backup({"deployment_id": payload["deployment_id"]})
    assert restored["state"] == "ROLLED_BACK" and not value.lock.exists()


def test_post_activation_failure_rolls_back_the_application_but_retains_migrated_schema(tmp_path: Path) -> None:
    value, helper, payload, runner = staged(tmp_path)
    helper.migration_preflight({"deployment_id": payload["deployment_id"]})
    helper.apply_migration({"deployment_id": payload["deployment_id"]})
    helper.verify_migration({"deployment_id": payload["deployment_id"]})
    runner.fail = "curl"
    result = helper.activate({"deployment_id": payload["deployment_id"]})
    assert result["state"] == "ROLLED_BACK"
    assert Path(helper.links["current"]).name.endswith("35dea12")
    assert helper.revision == TARGET and not value.lock.exists()


def test_unknown_operations_arbitrary_fields_and_revisions_are_denied(tmp_path: Path) -> None:
    helper = DisposableHelper(paths(tmp_path), Runner())
    for payload in (
        {"operation": "shell"},
        {"operation": "apply-migration", "deployment_id": "deploy-0001", "revision": "base"},
        {"operation": "backup-production", "deployment_id": "deploy-0001", "database": "mysql"},
        {"operation": "restore-backup", "deployment_id": "deploy-0001", "path": "/tmp/a.sql"},
    ):
        with pytest.raises(Rejected):
            helper.dispatch(payload)


def test_production_migration_environment_uses_existing_root_only_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EOAT_DB_MIGRATION_PASSWORD", "caller-controlled-value")
    value = paths(tmp_path)
    value.migration_env.write_text(
        "EOAT_API_ENVIRONMENT=production\n"
        "EOAT_API_WRITES_ENABLED=false\n"
        "EOAT_DB_HOST=127.0.0.1\n"
        "EOAT_DB_PORT=3306\n"
        "EOAT_DB_NAME=eoat_atlas_prod\n"
        "EOAT_DB_MIGRATION_USER=eoat_migrate\n"
        "EOAT_DB_MIGRATION_PASSWORD='disposable only'\n"
        "EOAT_DB_DRIVER=pymysql\n",
        encoding="utf-8",
    )
    helper = DisposableHelper(value, Runner())

    environment = helper._migration_environment()

    assert environment["EOAT_MIGRATION_DB_USER"] == "eoat_migrate"
    assert environment["EOAT_DB_MIGRATION_PASSWORD"] == "disposable only"
    assert "MYSQL_PWD" not in environment


def test_migration_environment_rejects_a_nonproduction_database(tmp_path: Path) -> None:
    value = paths(tmp_path)
    value.migration_env.write_text(
        "EOAT_API_ENVIRONMENT=production\n"
        "EOAT_API_WRITES_ENABLED=false\n"
        "EOAT_DB_HOST=127.0.0.1\n"
        "EOAT_DB_PORT=3306\n"
        "EOAT_DB_NAME=not_eoat_atlas_prod\n"
        "EOAT_DB_MIGRATION_USER=eoat_migrate\n",
        encoding="utf-8",
    )

    with pytest.raises(Rejected, match="fixed production database"):
        DisposableHelper(value, Runner())._migration_environment()


def test_migration_environment_rejects_a_nonlocal_mysql_endpoint(tmp_path: Path) -> None:
    value = paths(tmp_path)
    value.migration_env.write_text(
        "EOAT_API_ENVIRONMENT=production\n"
        "EOAT_API_WRITES_ENABLED=false\n"
        "EOAT_DB_HOST=database.example.test\n"
        "EOAT_DB_PORT=3306\n"
        "EOAT_DB_NAME=eoat_atlas_prod\n"
        "EOAT_DB_MIGRATION_USER=eoat_migrate\n",
        encoding="utf-8",
    )

    with pytest.raises(Rejected, match="fixed local MySQL endpoint"):
        DisposableHelper(value, Runner())._migration_environment()
