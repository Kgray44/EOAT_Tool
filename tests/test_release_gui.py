from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget

from release_gui.dialogs import TypedConfirmationDialog
from release_gui.models import result_from_payload
from release_gui.packager_window import ReleasePackagerWindow
from release_gui.receipt_viewer import ReceiptViewer
from release_gui.services import ReleaseManagerService, ServerUpdaterService
from release_gui.settings import GuiSettings
from release_gui.state_rules import ToolState, activate_rule, package_rule, publish_rule, stage_rule, update_server_rule
from release_gui.updater_window import ServerUpdaterWindow


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_state_rules_keep_sensitive_actions_disabled_by_default() -> None:
    assert not publish_rule(ToolState()).enabled
    assert not stage_rule(ToolState()).enabled
    assert not activate_rule(ToolState()).enabled


def test_stage_requires_matching_rehearsal_and_no_migration() -> None:
    state = ToolState(
        config_loaded=True,
        server_inspected=True,
        release_verified=True,
        rehearsal_passed=True,
        rehearsal_matches_selection=True,
        migration_status="NOT_REQUIRED",
        host_key_trusted=True,
        helper_available=True,
        blockers=False,
    )
    assert stage_rule(state).enabled
    assert not stage_rule(state.__class__(**{**state.__dict__, "migration_status": "REQUIRED"})).enabled


def test_confirmation_requires_exact_case_sensitive_text() -> None:
    app()
    dialog = TypedConfirmationDialog("Stage", "Safe test", "STAGE 0.18.1")
    assert not dialog.accept_button.isEnabled()
    dialog.entry.setText("stage 0.18.1")
    assert not dialog.accept_button.isEnabled()
    dialog.entry.setText("STAGE 0.18.1")
    assert dialog.accept_button.isEnabled()


def test_result_preserves_raw_receipt() -> None:
    result = result_from_payload("test", {"overall_readiness": "READY", "warnings": ["watch"]})
    assert result.status == "READY"
    assert result.raw["warnings"] == ["watch"]


def test_windows_construct_without_starting_operations(tmp_path: Path) -> None:
    app()
    packager, updater = (
        ReleasePackagerWindow(tmp_path, auto_refresh=False),
        ServerUpdaterWindow(tmp_path, auto_refresh=False),
    )
    assert not packager._busy and not updater._busy
    assert packager.package_button.text() == "Package Software"
    assert not packager.package_button.isEnabled()
    assert updater.update_button.text() == "Update Server"
    assert not updater.update_button.isEnabled()


def test_update_server_requires_source_and_configuration() -> None:
    assert not update_server_rule(ToolState()).enabled
    assert update_server_rule(ToolState(config_loaded=True, source_selected=True)).enabled


def test_update_server_refuses_artifact_for_a_different_commit(tmp_path: Path, monkeypatch) -> None:
    service = ServerUpdaterService(tmp_path)
    monkeypatch.setattr(
        service,
        "inspect_release",
        lambda _version: result_from_payload(
            "release inspection",
            {"release": {"commit_sha": "b" * 40}, "release_dir": str(tmp_path), "manifest": {}},
        ),
    )
    attempted = False

    def stage(*_args, **_kwargs) -> None:
        nonlocal attempted
        attempted = True

    monkeypatch.setattr("release_gui.services.active_deployment.stage_release", stage)
    try:
        service.update_server(tmp_path / "server.json", "0.18.2", "a" * 40)
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("a mismatched release must never reach staging")
    assert not attempted


def test_receipt_viewer_keeps_raw_json_visible() -> None:
    app()
    viewer = ReceiptViewer({"state": "STAGED_VALIDATED", "warnings": ["observe"], "custom": {"key": "value"}})
    tabs = viewer.findChild(QTabWidget)
    assert tabs is not None
    assert tabs.tabText(tabs.count() - 1) == "Raw JSON"


def test_settings_reject_sensitive_values(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    settings = GuiSettings("test")
    settings.set("last_server_config", "C:/safe/config.json")
    assert settings.get("last_server_config").endswith("config.json")
    try:
        settings.set("api_token", "never-save")
    except ValueError:
        pass
    else:
        raise AssertionError("sensitive GUI settings must be rejected")


def test_services_are_importable_without_cli_execution(tmp_path: Path) -> None:
    assert ReleaseManagerService(tmp_path).root == tmp_path.resolve()
    updater = ServerUpdaterService(tmp_path)
    assert updater.root == tmp_path.resolve()
    assert updater.default_config_path == tmp_path / "config" / "deployment_server.local.json"


def test_repository_status_keeps_computed_clean_property(tmp_path: Path, monkeypatch) -> None:
    class FakeGit:
        def __init__(self, _root: Path) -> None:
            pass

        def output(self, *args: str) -> str:
            values = {
                ("branch", "--show-current"): "codex/test",
                ("rev-parse", "HEAD"): "a" * 40,
                ("status", "--porcelain=v1"): "",
                ("show", f"{'a' * 40}:app/atlas/version.json"): '{"version": "0.18.0"}',
            }
            return values[args]

    monkeypatch.setattr("release_gui.services.release_manager.Git", FakeGit)
    status, result = ReleaseManagerService(tmp_path).inspect_status()
    assert status.clean and status.ready
    assert result.raw["repository"]["clean"] is True


def test_package_requires_selected_clean_checkout() -> None:
    enabled = ToolState(repository_ready=True, selected_reference_current=True, blockers=False)
    assert package_rule(enabled).enabled
    assert not package_rule(enabled.__class__(**{**enabled.__dict__, "selected_reference_current": False})).enabled
