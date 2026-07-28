from __future__ import annotations

import json
from pathlib import Path

import pytest

from deployment.common import DeploymentError
from deployment.convergence.cli import parse_args
from deployment.convergence.phase3a import DisposableCoordinatedDeployment
from deployment.convergence.receipts import ReceiptStore
from tests.test_phase_3a_coordinated_deployment import _input


def test_schema2_transaction_is_durable_and_terminal_receipt_is_immutable(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path / "repository")
    item = _input(tmp_path)
    deployment = DisposableCoordinatedDeployment(tmp_path / "runtime", store=store)
    staged = deployment.stage(item, active_schema="schema-1")
    active = deployment.activate(staged["transaction_id"])
    persisted = store.read("transaction", staged["transaction_id"])
    assert active["state"] == "ACTIVE_CONFIRMED"
    assert persisted["schema_version"] == 2
    assert [entry["state"] for entry in persisted["state_history"]][-1] == "ACTIVE_CONFIRMED"
    changed = dict(persisted)
    changed["next_safe_action"] = "unsafe rewrite"
    with pytest.raises(DeploymentError, match="immutable"):
        store.write("transaction", staged["transaction_id"], changed)


def test_unknown_future_transaction_receipt_is_rejected_and_corrupt_receipt_quarantined(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path / "repository")
    directory = store.root / "transaction"
    directory.mkdir(parents=True)
    (directory / "future.json").write_text(json.dumps({"receipt_kind": "transaction", "receipt_id": "future", "schema_version": 99}), encoding="utf-8")
    with pytest.raises(DeploymentError, match="unsupported future"):
        store.read("transaction", "future")
    (directory / "broken.json").write_text("{", encoding="utf-8")
    with pytest.raises(DeploymentError, match="quarantined"):
        store.read("transaction", "broken")
    assert store.quarantine()


def test_phase3a_cli_requires_disposable_root_and_exact_confirmation(tmp_path: Path) -> None:
    parsed = parse_args([
        "coordinated-deploy", "stage", "--input", str(tmp_path / "input.json"), "--disposable-root", str(tmp_path / "runtime"),
        "--active-schema", "schema-1", "--confirm", "STAGE release-1",
    ])
    assert parsed.phase3a_command == "stage"
    assert parsed.confirm == "STAGE release-1"
