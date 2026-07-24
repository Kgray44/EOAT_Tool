from __future__ import annotations

import json

import pytest

from release_tools_gui.models import DANGEROUS_PHASE_ONE_ACTIONS, GuiStatus, OperationResult, map_status
from release_tools_gui.receipts import ReceiptStore
from release_tools_gui.redaction import redact_text, sanitize
from release_tools_gui.services import ReleaseManagerAdapter, ServerUpdaterAdapter
from release_tools_gui.widgets import DetailTree
from release_tools_gui.workers import SafeWorker


def test_status_mapping_never_calls_skipped_or_unknown_a_pass():
    assert map_status("DRY_RUN_SUCCEEDED") is GuiStatus.PASS
    assert map_status("SKIPPED") is GuiStatus.NOT_RUN
    assert map_status("UNKNOWN") is GuiStatus.UNKNOWN
    assert map_status("READY", has_blockers=True) is GuiStatus.BLOCKED
    assert map_status("FAILED") is GuiStatus.FAILED


def test_redaction_removes_keyed_and_inline_values():
    assert sanitize({"token": "super-secret", "nested": {"password": "value"}}) == {
        "token": "***REDACTED***",
        "nested": {"password": "***REDACTED***"},
    }
    assert "super-secret" not in redact_text("token=super-secret")
    assert "ghp_abcdefghijklmnopqrstuvwx" not in redact_text("ghp_abcdefghijklmnopqrstuvwx")


def test_release_adapter_uses_existing_status_and_dry_run_only(monkeypatch, tmp_path):
    adapter = ReleaseManagerAdapter(tmp_path)
    monkeypatch.setattr(
        "release_tools_gui.services.release_manager.status_payload",
        lambda root: {"ready_to_package": True, "final_status": "READY"},
    )
    assert adapter.status().status is GuiStatus.PASS
    captured = {}

    def package(root, **kwargs):
        captured.update(kwargs)
        return {"final_status": "DRY_RUN_SUCCEEDED", "artifact": {"sha256": "abc"}}

    monkeypatch.setattr("release_tools_gui.services.release_manager.package", package)
    assert adapter.package_dry_run("1.2.3").status is GuiStatus.PASS
    assert captured == {
        "bump": None,
        "explicit_version": "1.2.3",
        "dry_run": True,
        "no_push": True,
        "no_publish": True,
        "allow_dirty": False,
        "approved_exception": None,
    }
    assert not any("publish" in name or "active" in name for name in dir(adapter))


def test_updater_accepts_only_non_secret_config_under_config_root(tmp_path):
    root = tmp_path
    config = root / "config"
    config.mkdir()
    approved = config / "server.json"
    approved.write_text(json.dumps({"server": {"hostname": "eoat.example.test"}}), encoding="utf-8")
    adapter = ServerUpdaterAdapter(root)
    result = adapter.load_config(approved)
    assert result.status is GuiStatus.PASS
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="approved"):
        adapter.load_config(outside)
    secret = config / "secret.json"
    secret.write_text(json.dumps({"server": {"hostname": "eoat.example.test", "token": "nope"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="secret"):
        adapter.load_config(secret)


def test_receipt_store_writes_only_sanitized_content(tmp_path):
    store = ReceiptStore(tmp_path)
    result = OperationResult(
        "updater", "preflight", GuiStatus.WARNING, "Safe", {"token": "secret", "detail": "token=secret"}
    )
    path = store.save(result)
    rendered = path.read_text(encoding="utf-8")
    assert "secret" not in rendered
    assert store.load(path)["details"]["token"] == "***REDACTED***"


def test_worker_can_only_cancel_before_the_engine_starts(qapp):
    calls: list[str] = []
    worker = SafeWorker("read-only", lambda: calls.append("called"))
    events: list[str] = []
    worker.signals.cancelled.connect(events.append)
    assert worker.token.cancel() is True
    worker.run()
    assert not calls
    assert events == ["Cancelled before the read-only engine operation started"]
    started = SafeWorker("read-only", lambda: None)
    started.token.started = True
    assert started.token.cancel() is False


def test_detail_tree_expands_sanitized_receipt_details(qapp):
    tree = DetailTree()
    tree.set_result(
        OperationResult(
            "packager", "validate", GuiStatus.WARNING, "Warnings", {"checks": [{"name": "one", "status": "WARNING"}]}
        )
    )
    assert tree.topLevelItemCount() == 1
    assert tree.topLevelItem(0).childCount() >= 1


def test_dangerous_actions_are_a_fixed_phase_one_disabled_set():
    assert {"upload", "activate", "migration", "token rotation"}.issubset(DANGEROUS_PHASE_ONE_ACTIONS)
