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
from release_gui.state_rules import ToolState, activate_rule, publish_rule, stage_rule
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
    packager, updater = ReleasePackagerWindow(tmp_path), ServerUpdaterWindow(tmp_path)
    assert not packager._busy and not updater._busy
    assert not packager.publish_button.isEnabled()
    assert not updater.stage.isEnabled() and not updater.activate.isEnabled()


def test_version_change_invalidates_release_rehearsal(tmp_path: Path) -> None:
    app()
    updater = ServerUpdaterWindow(tmp_path)
    updater.release_dir = tmp_path / "release"
    updater.release_verified = updater.rehearsal_passed = updater.rehearsal_matches = True
    updater.version.setText("0.18.1")
    assert updater.release_dir is None
    assert not updater.release_verified and not updater.rehearsal_passed


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
    assert ServerUpdaterService(tmp_path).root == tmp_path.resolve()


def test_repository_status_keeps_computed_clean_property(tmp_path: Path, monkeypatch) -> None:
    from deployment.release_manager import GitState

    state = GitState(
        root=str(tmp_path),
        branch="codex/test",
        commit="a" * 40,
        upstream="origin/codex/test",
        ahead=0,
        behind=0,
        modified=[],
        staged=[],
        untracked=[],
        conflicts=[],
        latest_tag=None,
        version="0.18.0",
    )
    monkeypatch.setattr(
        "release_gui.services.release_manager.status_payload",
        lambda _root: {"repository": state, "ready_to_package": True},
    )
    status, result = ReleaseManagerService(tmp_path).inspect_status()
    assert status.clean and status.ready
    assert result.raw["repository"]["clean"] is True
