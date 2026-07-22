from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .dialogs import TypedConfirmationDialog
from .models import OperationResult, readiness_from_payload
from .services import ServerUpdaterService
from .state_rules import ToolState, abort_rule, activate_rule, recover_rule, rollback_rule, stage_rule
from .widgets import KeyValuePanel, OperationLog, StatusCard, WarningPanel
from .window_base import ToolWindow, ensure_application


class ServerUpdaterWindow(ToolWindow):
    def __init__(self, root: Path | None = None) -> None:
        super().__init__("EOAT Atlas Server Updater")
        self.service = ServerUpdaterService(root or Path.cwd())
        self.config_path: Path | None = None
        self.release_dir: Path | None = None
        self.helper_available = False
        self.server_ok = self.release_verified = self.rehearsal_passed = self.rehearsal_matches = self.host_key = False
        self.migration = "UNKNOWN"
        self.deployment_state = "UNKNOWN"
        self.last_result: OperationResult | None = None
        self.status_card = StatusCard("Deployment readiness")
        self.details = KeyValuePanel("Selected deployment")
        self.warnings = WarningPanel()
        self.log = OperationLog()
        self.config = QLineEdit()
        self.config.setReadOnly(True)
        self.version = QLineEdit()
        self.version.setPlaceholderText("Latest eligible release, or exact version")
        self.deployment_id = QLineEdit()
        self.deployment_id.setPlaceholderText("deploy-YYYYMMDDtHHMMSSz-abcdef0")
        (
            self.choose,
            self.status,
            self.inspect_server,
            self.list_releases,
            self.inspect_release,
            self.rehearse,
            self.stage,
            self.activate,
            self.abort,
            self.recover,
            self.rollback,
            self.receipt,
        ) = (
            QPushButton("Choose configuration"),
            QPushButton("Refresh status"),
            QPushButton("Inspect server"),
            QPushButton("Check available releases"),
            QPushButton("Inspect selected release"),
            QPushButton("Run deployment rehearsal"),
            QPushButton("Stage selected release"),
            QPushButton("Activate staged release"),
            QPushButton("Abort"),
            QPushButton("Recover"),
            QPushButton("Rollback"),
            QPushButton("Open latest receipt"),
        )
        self.receipt.setEnabled(False)
        form = QFormLayout()
        config_row = QHBoxLayout()
        config_row.addWidget(self.config)
        config_row.addWidget(self.choose)
        form.addRow("Non-secret server config", config_row)
        form.addRow("Release version", self.version)
        form.addRow("Deployment ID", self.deployment_id)
        actions = QHBoxLayout()
        for button in (
            self.status,
            self.inspect_server,
            self.list_releases,
            self.inspect_release,
            self.rehearse,
            self.stage,
            self.activate,
            self.abort,
            self.recover,
            self.rollback,
            self.receipt,
        ):
            actions.addWidget(button)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(
            QLabel(
                "<h1>EOAT Atlas Server Updater</h1><p>All server actions use the established strict-host-key deployment backend. Staging never activates a release; migration-required releases remain blocked.</p>"
            )
        )
        layout.addWidget(self.status_card)
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(self.details)
        layout.addWidget(self.warnings)
        splitter = QSplitter()
        splitter.addWidget(self.log)
        layout.addWidget(splitter)
        self.setCentralWidget(content)
        self.choose.clicked.connect(self.choose_config)
        self.status.clicked.connect(self.refresh_status)
        self.inspect_server.clicked.connect(self.inspect)
        self.list_releases.clicked.connect(self.list)
        self.inspect_release.clicked.connect(self.inspect_selected)
        self.rehearse.clicked.connect(self.run_rehearsal)
        self.stage.clicked.connect(self.stage_selected)
        self.activate.clicked.connect(lambda: self.confirm_operation("Activate staged release", "ACTIVATE", "activate"))
        self.abort.clicked.connect(lambda: self.confirm_operation("Abort deployment", "ABORT", "abort"))
        self.recover.clicked.connect(lambda: self.operation("recover"))
        self.rollback.clicked.connect(lambda: self.confirm_operation("Rollback deployment", "ROLLBACK", "rollback"))
        self.receipt.clicked.connect(lambda: self.last_result and self.show_receipt(self.last_result.raw))
        self.version.textChanged.connect(self._invalidate_release_selection)
        self.refresh_actions()

    def state(self) -> ToolState:
        return ToolState(
            busy=self._busy,
            config_loaded=self.config_path is not None,
            server_inspected=self.server_ok,
            release_verified=self.release_verified,
            rehearsal_passed=self.rehearsal_passed,
            rehearsal_matches_selection=self.rehearsal_matches,
            migration_status=self.migration,
            host_key_trusted=self.host_key,
            helper_available=self.helper_available,
            blockers=not self.host_key,
            deployment_state=self.deployment_state,
        )

    def refresh_actions(self) -> None:
        state = self.state()
        stage = stage_rule(state)
        activate = activate_rule(state)
        abort = abort_rule(state)
        recover = recover_rule(state)
        rollback = rollback_rule(state)
        self.inspect_server.setEnabled(not self._busy and self.config_path is not None)
        self.inspect_release.setEnabled(not self._busy)
        self.rehearse.setEnabled(not self._busy and self.config_path is not None and self.release_dir is not None)
        self.stage.setEnabled(stage.enabled)
        self.activate.setEnabled(activate.enabled)
        self.abort.setEnabled(abort.enabled)
        self.recover.setEnabled(recover.enabled)
        self.rollback.setEnabled(rollback.enabled)
        for button, rule in (
            (self.stage, stage),
            (self.activate, activate),
            (self.abort, abort),
            (self.recover, recover),
            (self.rollback, rollback),
        ):
            button.setToolTip(rule.reason)

    def choose_config(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Choose non-secret server configuration", str(Path.home()), "JSON files (*.json)"
        )
        if not filename:
            return
        path = Path(filename)

        def done(result: OperationResult) -> None:
            self.config_path = path
            self.config.setText(str(path))
            self.server_ok = self.host_key = self.helper_available = False
            self.rehearsal_passed = self.rehearsal_matches = False
            self.last_result = result
            self.show_result(result)
            self.refresh_actions()

        self.run_operation("Configuration validation", lambda: self.service.load_config(path), done)

    def refresh_status(self) -> None:
        self.run_operation("Updater status", lambda: self.service.inspect_status(self.config_path), self._record)

    def inspect(self) -> None:
        assert self.config_path

        def done(result: OperationResult) -> None:
            self.server_ok = result.status.startswith("READY")
            details = result.raw
            key = details.get("ssh_host_key", {}) if isinstance(details, dict) else {}
            self.host_key = bool(key.get("known"))
            helper = details.get("privileged_helper", {}) if isinstance(details, dict) else {}
            self.helper_available = bool(helper.get("available"))
            self._record(result)

        self.run_operation("Server inspection", lambda: self.service.inspect_server(self.config_path), done)

    def list(self) -> None:
        self.run_operation("Release listing", self.service.list_releases, self._record)

    def inspect_selected(self) -> None:
        version = self.version.text().strip() or None

        def done(result: OperationResult) -> None:
            self.release_dir = Path(str(result.raw["release_dir"]))
            self.release_verified = result.status == "VERIFIED"
            self._record(result)

        self.run_operation("Release inspection", lambda: self.service.inspect_release(version), done)

    def run_rehearsal(self) -> None:
        assert self.config_path and self.release_dir

        def done(result: OperationResult) -> None:
            readiness = readiness_from_payload(result.raw)
            self.migration = readiness.migration_status
            self.host_key = readiness.host_key_trusted
            self.rehearsal_passed = readiness.readiness.startswith("READY")
            self.rehearsal_matches = self.rehearsal_passed
            self._record(result)

        self.run_operation(
            "Deployment rehearsal", lambda: self.service.rehearse_deployment(self.config_path, self.release_dir), done
        )

    def stage_selected(self) -> None:
        assert self.config_path and self.release_dir
        version = self.version.text().strip() or "selected release"
        dialog = TypedConfirmationDialog(
            "Stage selected release",
            "STAGING DOES NOT ACTIVATE THE RELEASE. The backend will reject blocked or migration-required releases.",
            f"STAGE {version}",
            self,
        )
        if not dialog.exec():
            return

        def done(result: OperationResult) -> None:
            self.deployment_id.setText(str(result.raw.get("deployment_id", "")))
            self.deployment_state = result.status
            self._record(result)

        self.run_operation(
            "Release staging", lambda: self.service.stage_release(self.config_path, self.release_dir), done
        )

    def confirm_operation(self, title: str, verb: str, operation: str) -> None:
        identifier = self.deployment_id.text().strip()
        dialog = TypedConfirmationDialog(
            title,
            "This request is sent to the existing backend state machine and is not assumed successful until status and health are returned.",
            f"{verb} {identifier}",
            self,
        )
        if dialog.exec():
            self.operation(operation)

    def operation(self, operation: str) -> None:
        if not self.config_path:
            return
        identifier = self.deployment_id.text().strip()

        def done(result: OperationResult) -> None:
            self.deployment_state = result.status
            self._record(result)

        self.run_operation(
            f"Deployment {operation}",
            lambda: self.service.deployment_operation(self.config_path, identifier, operation),
            done,
        )

    def _record(self, result: OperationResult) -> None:
        self.last_result = result
        self.show_result(result)
        self.details.set_values(
            {
                "Configuration": self.config_path or "None",
                "Release cache": self.release_dir or "None",
                "Deployment ID": self.deployment_id.text() or "None",
                "Deployment state": self.deployment_state,
                "Migration": self.migration,
                "Privileged helper": self.helper_available,
            }
        )
        self.receipt.setEnabled(True)
        self.refresh_actions()

    def _invalidate_release_selection(self) -> None:
        self.release_dir = None
        self.release_verified = False
        self.rehearsal_passed = False
        self.rehearsal_matches = False
        self.refresh_actions()


def main() -> int:
    app = ensure_application()
    window = ServerUpdaterWindow()
    window.show()
    return app.exec()
