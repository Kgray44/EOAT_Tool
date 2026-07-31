from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from deployment.privileged.governed_data_operations import (
    DataOperationPaths,
    GovernedDataOperations,
    Rejected,
    canonical_json,
    digest,
)


class Runner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "COMPLETED", "receipt": "/private/receipt.json"}),
            stderr="",
        )


def _operation(tmp_path: Path, *, operation: str = "import-press-capacity") -> tuple[GovernedDataOperations, Runner, Path]:
    root = tmp_path / "opt" / "eoat-atlas"
    policy_root = tmp_path / "etc" / "data-operations"
    release = root / "releases" / "eoat-atlas-0.25.4"
    release.mkdir(parents=True)
    (release / "release_manifest.json").write_text("{}", encoding="utf-8")
    for name, content in {
        "shared/backups/backup.json": json.dumps({"database_identity": "eoat_atlas_prod", "verified": True}),
        "shared/candidates/candidate.json": "candidate",
        "shared/reference/press_capacity.xlsx": "workbook",
        "shared/reference/master_press.xlsx": "master",
    }.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    implementation = Path(__file__).parents[1] / "deployment" / "privileged" / "eoat_atlas_deploy_helper.py"
    payload: dict[str, object] = {
        "release_id": "eoat-atlas-0.25.4",
        "application_version": "0.25.4",
        "schema_revision": "20260729_0009",
        "database_identity": "eoat_atlas_prod",
        "backup_receipt": "shared/backups/backup.json",
        "backup_receipt_sha256": digest(root / "shared/backups/backup.json"),
        "candidate": "shared/candidates/candidate.json",
        "candidate_sha256": digest(root / "shared/candidates/candidate.json"),
        "rollback": "restore the verified backup and preserve this receipt",
        "dry_run_max_age_seconds": 3600,
    }
    if operation == "import-press-capacity":
        payload.update(
            workbook="shared/reference/press_capacity.xlsx",
            master_press_list="shared/reference/master_press.xlsx",
            plant_code="P4",
            excluded_machine_numbers=["6", "8", "24", "64", "70", "72"],
        )
    else:
        payload.update(source_roots=["/srv/eoat-approved-media"], target_root="/srv/eoat-browser-media")
    policy_root.mkdir(parents=True)
    policy = {
        "schema_version": 1,
        "operation": operation,
        "helper_sha256": digest(implementation),
        "payload": payload,
        "payload_sha256": hashlib.sha256(canonical_json(payload)).hexdigest(),
    }
    policy_path = policy_root / f"{operation}.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    runner = Runner()
    helper = GovernedDataOperations(
        DataOperationPaths(
            root=root,
            lock=tmp_path / "var" / "lock",
            policy_root=policy_root,
            receipts=root / "shared" / "data-operation-receipts",
            transactions=root / "shared" / "data-operation-transactions",
            release=release,
        ),
        runner,
        implementation=implementation,
        require_root_ownership=False,
    )
    return helper, runner, policy_path


def test_capacity_operation_requires_pinned_policy_backup_and_fresh_dry_run(tmp_path: Path) -> None:
    helper, runner, _policy = _operation(tmp_path)
    request = {"operation": "import-press-capacity", "request_id": "capacity-0001", "mode": "dry-run"}
    dry = helper.dispatch(request)
    assert dry["state"] == "COMPLETED"
    assert "--execute" not in runner.commands[0]

    completed = helper.dispatch({**request, "mode": "execute"})
    assert completed["state"] == "COMPLETED"
    assert "--execute" in runner.commands[1]
    assert completed["receipt"] == "receipt.json"
    assert helper.dispatch({**request, "mode": "execute"})["state"] == "ALREADY_COMPLETED"


@pytest.mark.parametrize(
    "data_operation_request,reason",
    [
        ({"operation": "import-press-capacity", "request_id": "capacity-0001", "mode": "dry-run", "sql": "DROP"}, "unknown"),
        ({"operation": "import-press-capacity", "request_id": "../../bad", "mode": "dry-run"}, "request_id"),
        ({"operation": "import-press-capacity", "request_id": "capacity-0001", "mode": "shell"}, "unsupported"),
        ({"operation": "migrate-profile-media", "request_id": "media-00001", "mode": "dry-run"}, "operation policy"),
    ],
)
def test_data_operation_rejects_arbitrary_caller_control(
    tmp_path: Path, data_operation_request: dict[str, str], reason: str
) -> None:
    helper, _runner, _policy = _operation(tmp_path)
    with pytest.raises(Rejected, match=reason):
        helper.dispatch(data_operation_request)


def test_policy_and_governed_inputs_fail_closed_on_drift_and_traversal(tmp_path: Path) -> None:
    helper, _runner, policy_path = _operation(tmp_path)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["payload"]["candidate"] = "../../outside"
    policy["payload_sha256"] = hashlib.sha256(canonical_json(policy["payload"])).hexdigest()
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(Rejected, match="candidate"):
        helper.dispatch({"operation": "import-press-capacity", "request_id": "capacity-0001", "mode": "dry-run"})

    helper, _runner, policy_path = _operation(tmp_path / "hash")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["payload"]["database_identity"] = "other_database"
    policy["payload_sha256"] = hashlib.sha256(canonical_json(policy["payload"])).hexdigest()
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(Rejected, match="database identity"):
        helper.dispatch({"operation": "import-press-capacity", "request_id": "capacity-0001", "mode": "dry-run"})


def test_media_operation_uses_only_policy_defined_roots_and_backup(tmp_path: Path) -> None:
    helper, runner, _policy = _operation(tmp_path, operation="migrate-profile-media")
    state = helper.dispatch({"operation": "migrate-profile-media", "request_id": "media-00001", "mode": "dry-run"})
    assert state["state"] == "COMPLETED"
    assert runner.commands[0].count("--source-root") == 1
    assert "/srv/eoat-approved-media" in runner.commands[0]
