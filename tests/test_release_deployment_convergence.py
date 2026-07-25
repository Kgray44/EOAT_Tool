from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from deployment.common import sha256_file
from deployment.convergence.diagnostics import validate_diagnostic_envelope
from deployment.convergence.models import (
    CandidateState,
    DeploymentMode,
    DeploymentState,
    PublicationState,
    next_action_for,
    require_transition,
    validate_deployment_transition,
)
from deployment.convergence.receipts import ReceiptStore
from deployment.convergence.services import ProcessRunner, ReleaseDeploymentService
from deployment.server_updater import GitHubRelease, ReleaseAsset


def test_receipt_store_quarantines_corrupt_record(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path)
    path = store._path("candidate", "candidate-0.1.0-test")
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="quarantined"):
        store.read("candidate", "candidate-0.1.0-test")

    assert not path.exists()
    assert list((store.root / "quarantine").glob("candidate-candidate-0.1.0-test-*.json"))


def test_deployment_plan_is_truthful_for_unknown_required_and_no_migration(tmp_path: Path) -> None:
    service = ReleaseDeploymentService(tmp_path)

    unknown = service.deployment_plan(
        version="0.1.0", commit="a" * 40, source_schema=None, target_schema="20260721_0008"
    )
    no_migration = service.deployment_plan(
        version="0.1.0", commit="a" * 40, source_schema="20260721_0008", target_schema="20260721_0008"
    )
    blocked = service.deployment_plan(version="0.1.0", commit="a" * 40, source_schema="old", target_schema="new")
    ready = service.deployment_plan(
        version="0.1.0",
        commit="a" * 40,
        source_schema="old",
        target_schema="new",
        helper_capabilities={"backup-production", "verify-backup", "apply-migration", "verify-migration"},
    )

    assert unknown.mode is DeploymentMode.MIGRATION_STATE_UNKNOWN
    assert no_migration.mode is DeploymentMode.NO_MIGRATION_REQUIRED
    assert blocked.mode is DeploymentMode.MIGRATION_BLOCKED
    assert ready.mode is DeploymentMode.MIGRATION_REQUIRED


def test_publication_transition_rejects_skipped_remote_steps() -> None:
    require_transition(PublicationState.CANDIDATE_VALIDATED, PublicationState.RELEASE_COMMIT_CREATED)
    with pytest.raises(ValueError, match="invalid publication transition"):
        require_transition(PublicationState.CANDIDATE_VALIDATED, PublicationState.TAG_CREATED)


def test_next_action_never_describes_unknown_migration_as_safe() -> None:
    assert "inspection" in next_action_for(DeploymentMode.MIGRATION_STATE_UNKNOWN).lower()
    assert "roll back" in next_action_for(DeploymentMode.ROLLBACK_OR_RECOVERY_REQUIRED).lower()


def test_process_runner_redacts_structured_diagnostics(tmp_path: Path) -> None:
    outcome = ProcessRunner().run(
        "redaction",
        [
            sys.executable,
            "-c",
            "import sys; print('token=abcdefghijk'); print('mysql://user:password@example', file=sys.stderr)",
        ],
        cwd=tmp_path,
    )

    assert outcome.exit_code == 0
    assert "password" not in outcome.stderr
    assert "REDACTED" in outcome.stderr
    assert outcome.duration_seconds >= 0


def test_inventory_classifies_incomplete_release_without_selecting_latest() -> None:
    incomplete = GitHubRelease("v0.1.0", False, False, "2026-01-01T00:00:00Z", (ReleaseAsset("archive.tar.gz"),))
    complete = GitHubRelease(
        "v0.2.0",
        False,
        False,
        "2026-01-02T00:00:00Z",
        (ReleaseAsset("archive.tar.gz"), ReleaseAsset("archive.tar.gz.sha256"), ReleaseAsset("release_manifest.json")),
    )

    first = ReleaseDeploymentService._inventory_item(incomplete)
    second = ReleaseDeploymentService._inventory_item(complete)

    assert first["version"] == "0.1.0"
    assert not first["deployable"]
    assert second["version"] == "0.2.0"
    assert second["deployable"]


class FakePublisher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _record(self, name: str) -> None:
        self.calls.append(name)

    def promote(self, candidate: dict[str, object]) -> None:
        self._record("promote")

    def ensure_tag(self, candidate: dict[str, object]) -> None:
        self._record("tag")

    def push_branch(self, candidate: dict[str, object]) -> None:
        self._record("branch")

    def push_tag(self, candidate: dict[str, object]) -> None:
        self._record("tag-push")

    def ensure_release(self, candidate: dict[str, object]) -> None:
        self._record("release")

    def upload_assets(self, candidate: dict[str, object]) -> None:
        self._record("assets")

    def attach_receipt(self, candidate: dict[str, object], receipt: Path) -> None:
        assert receipt.is_file()
        self._record("receipt")

    def verify_step(self, candidate: dict[str, object], step: PublicationState, receipt: dict[str, object]) -> bool:
        return True


def test_publication_uses_all_durable_steps_once(tmp_path: Path) -> None:
    service = ReleaseDeploymentService(tmp_path)
    candidate_dir = service.store.root / "candidates" / "candidate-0.2.0-unit"
    candidate_dir.mkdir(parents=True)
    artifact = candidate_dir / "archive.tar.gz"
    artifact.write_bytes(b"artifact")
    manifest = candidate_dir / "release_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    bundle = candidate_dir / "candidate.bundle"
    bundle.write_bytes(b"bundle")
    service.store.write(
        "candidate",
        "candidate-0.2.0-unit",
        {
            "schema_version": 1,
            "candidate_id": "candidate-0.2.0-unit",
            "state": CandidateState.CANDIDATE_VALIDATED.value,
            "version": "0.2.0",
            "tag": "v0.2.0",
            "base_commit": "a" * 40,
            "candidate_commit": "b" * 40,
            "candidate_tree": "c" * 40,
            "artifact_sha256": sha256_file(artifact),
            "manifest_sha256": sha256_file(manifest),
            "artifact_path": str(artifact),
            "bundle_path": str(bundle),
        },
    )

    publisher = FakePublisher()
    result = service.publish("candidate-0.2.0-unit", "0.2.0", publisher=publisher)

    assert result.status.value == "PASS"
    assert publisher.calls == ["promote", "tag", "branch", "tag-push", "release", "assets", "receipt"]
    record = service.store.read("publication", "publication-candidate-0.2.0-unit")
    assert record["state"] == PublicationState.PUBLICATION_COMPLETE.value


def test_console_starts_in_truthful_not_run_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from release_tools_console.app import ReleaseDeploymentConsole

    app = QApplication.instance() or QApplication([])
    window = ReleaseDeploymentConsole(tmp_path)
    try:
        assert "NOT RUN" in window.overview.toPlainText()
        assert window.refresh.isEnabled()
        assert window.prepare.accessibleName() == "Prepare immutable release candidate"
    finally:
        window.close()
        app.processEvents()


def test_structured_diagnostic_requires_versioned_complete_facts() -> None:
    facts = {
        name: {}
        for name in (
            "target",
            "active_release",
            "schema_revision",
            "services",
            "health",
            "web",
            "deployment_lock",
            "disk",
            "helper",
            "writes_enabled",
            "transactions",
        )
    }
    envelope = validate_diagnostic_envelope(
        {"schema_version": 1, "operation": "diagnose", "facts": facts, "unavailable": [], "permission_denied": []}
    )
    assert envelope.method == "structured_helper"
    with pytest.raises(RuntimeError, match="missing facts"):
        validate_diagnostic_envelope(
            {"schema_version": 1, "operation": "diagnose", "facts": {}, "unavailable": [], "permission_denied": []}
        )


def test_transaction_model_rejects_activation_before_staging() -> None:
    with pytest.raises(ValueError, match="invalid deployment transition"):
        validate_deployment_transition(
            DeploymentState.NOT_STARTED, DeploymentState.ACTIVATION_STARTED, DeploymentMode.NO_MIGRATION_REQUIRED
        )


def test_receipt_export_refuses_overwrite(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path)
    store.write("plan", "plan-unit", {"state": "READY", "next_safe_action": "continue"})
    output = tmp_path / "receipt.txt"
    assert store.export_text("plan-unit", output) == output
    with pytest.raises(RuntimeError, match="overwrite"):
        store.export_text("plan-unit", output)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)
    return result.stdout.strip()


class LocalBarePublisher:
    """Disposable Git remote plus a local fake release backend for black-box publication."""

    def __init__(self, root: Path, remote: Path) -> None:
        self.root, self.remote = root, remote
        self.release_created = False
        self.assets_uploaded = False
        self.receipt_attached = False

    def promote(self, candidate: dict[str, object]) -> None:
        _git(self.root, "fetch", str(candidate["bundle_path"]), str(candidate["candidate_commit"]))
        _git(self.root, "merge", "--ff-only", "FETCH_HEAD")

    def ensure_tag(self, candidate: dict[str, object]) -> None:
        tag = str(candidate["tag"])
        _git(self.root, "tag", "-a", tag, str(candidate["candidate_commit"]), "-m", tag)

    def push_branch(self, _candidate: dict[str, object]) -> None:
        _git(self.root, "push", "origin", "main")

    def push_tag(self, candidate: dict[str, object]) -> None:
        _git(self.root, "push", "origin", str(candidate["tag"]))

    def ensure_release(self, _candidate: dict[str, object]) -> None:
        self.release_created = True

    def upload_assets(self, _candidate: dict[str, object]) -> None:
        assert self.release_created
        self.assets_uploaded = True

    def attach_receipt(self, _candidate: dict[str, object], receipt: Path) -> None:
        assert self.assets_uploaded and receipt.is_file()
        self.receipt_attached = True

    def verify_step(self, candidate: dict[str, object], step: PublicationState, _receipt: dict[str, object]) -> bool:
        commit = str(candidate["candidate_commit"])
        if step is PublicationState.RELEASE_COMMIT_CREATED:
            return _git(self.root, "rev-parse", "HEAD") == commit
        if step is PublicationState.TAG_CREATED:
            return _git(self.root, "rev-list", "-n", "1", str(candidate["tag"])) == commit
        if step is PublicationState.BRANCH_PUSHED:
            return commit in _git(self.root, "ls-remote", str(self.remote), "refs/heads/main")
        if step is PublicationState.TAG_PUSHED:
            return commit in _git(self.root, "ls-remote", str(self.remote), f"refs/tags/{candidate['tag']}^{{}}")
        if step is PublicationState.GITHUB_RELEASE_CREATED:
            return self.release_created
        if step is PublicationState.PRIMARY_ASSETS_UPLOADED:
            return self.assets_uploaded
        return self.receipt_attached


def test_disposable_black_box_publication_and_recovery_transaction(tmp_path: Path) -> None:
    """Exercise retained state against a temp repo/bare remote/fake release backend only."""
    remote = tmp_path / "remote.git"
    source = tmp_path / "source"
    subprocess.run(["git", "init", "--bare", str(remote)], text=True, check=True, capture_output=True)
    _git(tmp_path, "init", "--initial-branch=main", str(source))
    _git(source, "config", "user.email", "test@example.invalid")
    _git(source, "config", "user.name", "EOAT disposable test")
    (source / "README.md").write_text("base\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "base")
    base = _git(source, "rev-parse", "HEAD")
    _git(source, "remote", "add", "origin", str(remote))
    _git(source, "push", "-u", "origin", "main")
    subprocess.run(
        ["git", "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"],
        text=True,
        check=True,
        capture_output=True,
    )

    candidate_clone = tmp_path / "candidate"
    _git(tmp_path, "clone", str(source), str(candidate_clone))
    _git(candidate_clone, "config", "user.email", "test@example.invalid")
    _git(candidate_clone, "config", "user.name", "EOAT disposable test")
    (candidate_clone / "README.md").write_text("candidate\n", encoding="utf-8")
    _git(candidate_clone, "add", "README.md")
    _git(candidate_clone, "commit", "-m", "candidate")
    candidate_commit = _git(candidate_clone, "rev-parse", "HEAD")
    candidate_tree = _git(candidate_clone, "rev-parse", "HEAD^{tree}")

    service = ReleaseDeploymentService(source)
    candidate_id = "candidate-0.23.0-black-box"
    candidate_dir = service.store.root / "candidates" / candidate_id
    candidate_dir.mkdir(parents=True)
    artifact = candidate_dir / "eoat-atlas-server.tar.gz"
    artifact.write_bytes(b"disposable artifact")
    manifest = candidate_dir / "release_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    bundle = candidate_dir / "candidate.bundle"
    _git(candidate_clone, "bundle", "create", str(bundle), "HEAD", f"^{base}")
    service.store.write(
        "candidate",
        candidate_id,
        {
            "schema_version": 1,
            "candidate_id": candidate_id,
            "state": CandidateState.CANDIDATE_VALIDATED.value,
            "version": "0.23.0",
            "tag": "v0.23.0-black-box",
            "base_commit": base,
            "candidate_commit": candidate_commit,
            "candidate_tree": candidate_tree,
            "artifact_sha256": sha256_file(artifact),
            "manifest_sha256": sha256_file(manifest),
            "artifact_path": str(artifact),
            "bundle_path": str(bundle),
        },
    )
    publisher = LocalBarePublisher(source, remote)
    result = service.publish_start(candidate_id, "0.23.0", publisher=publisher)
    assert result.status.value == "PASS"
    assert publisher.receipt_attached
    assert _git(source, "rev-parse", "HEAD") == candidate_commit

    release = {
        "state": "RELEASE_VERIFIED",
        "release": {"commit_sha": candidate_commit, "release_id": "fake-release", "build_id": "fake-build"},
        "schema_target": "schema-1",
        "next_safe_action": "inspect",
    }
    service.store.write("inspection", "release-0.23.0", release)
    service.store.write(
        "inspection",
        "inspection-disposable",
        {
            "state": "TARGET_INSPECTED",
            "target_name": "disposable-target.invalid",
            "facts": {"schema_revision": "schema-1", "helper": {"operations": []}, "transactions": []},
            "blocking_failures": [],
            "warnings": [],
            "next_safe_action": "plan",
        },
    )
    plan = service.create_plan("0.23.0", "inspection-disposable").data["plan"]
    transaction = service.begin_transaction(plan.plan_id, "0.23.0").data["transaction"]
    transaction_id = transaction.transaction_id
    for state in (
        DeploymentState.PREFLIGHT_COMPLETE,
        DeploymentState.RELEASE_VERIFIED,
        DeploymentState.LOCK_ACQUIRED,
        DeploymentState.BACKUP_CREATED,
        DeploymentState.ARTIFACT_TRANSFERRED,
        DeploymentState.ARTIFACT_VERIFIED,
        DeploymentState.RELEASE_EXTRACTED,
        DeploymentState.RUNTIME_READY,
        DeploymentState.STAGED_VALIDATED,
        DeploymentState.ACTIVATION_READY,
    ):
        transaction = service.transition_transaction(transaction_id, state).data["transaction"]
    transaction = service.transition_transaction(
        transaction_id, DeploymentState.ACTIVATION_STARTED, transaction_id
    ).data["transaction"]
    transaction = service.transition_transaction(transaction_id, DeploymentState.FAILED_RECOVERABLE).data["transaction"]
    transaction = service.transition_transaction(transaction_id, DeploymentState.ROLLBACK_STARTED, transaction_id).data[
        "transaction"
    ]
    transaction = service.transition_transaction(transaction_id, DeploymentState.APPLICATION_ROLLED_BACK).data[
        "transaction"
    ]
    assert transaction["state"] == DeploymentState.APPLICATION_ROLLED_BACK.value


def test_disposable_mysql84_failure_rolls_back() -> None:
    """CI-only disposable MySQL 8.4 rollback proof; never points at a configured target."""
    if os.environ.get("EOAT_DISPOSABLE_MYSQL") != "1":
        pytest.skip("requires the disposable MySQL 8.4 CI service")
    import pymysql

    connection = pymysql.connect(
        host=os.environ["EOAT_MYSQL_HOST"],
        port=int(os.environ["EOAT_MYSQL_PORT"]),
        user=os.environ["EOAT_MYSQL_USER"],
        password=os.environ["EOAT_MYSQL_PASSWORD"],
        database="eoat_disposable",
        autocommit=False,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            assert cursor.fetchone()[0].startswith("8.4.")
            cursor.execute("CREATE TABLE IF NOT EXISTS convergence_rollback (id INT PRIMARY KEY, detail VARCHAR(64))")
            connection.commit()
            with pytest.raises(pymysql.err.IntegrityError):
                cursor.execute("INSERT INTO convergence_rollback VALUES (1, 'first')")
                cursor.execute("INSERT INTO convergence_rollback VALUES (1, 'duplicate')")
            connection.rollback()
            cursor.execute("SELECT COUNT(*) FROM convergence_rollback")
            assert cursor.fetchone()[0] == 0
    finally:
        connection.close()
