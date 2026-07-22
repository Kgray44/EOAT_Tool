from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
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
from .models import OperationResult, RepositoryStatus
from .services import ReleaseManagerService, ServerUpdaterService
from .state_rules import ToolState, update_server_rule
from .widgets import KeyValuePanel, OperationLog, StatusCard, WarningPanel
from .window_base import ToolWindow, ensure_application


class ServerUpdaterWindow(ToolWindow):
    """A simple source-first updater that still delegates every gate to deployment."""

    def __init__(self, root: Path | None = None, *, auto_refresh: bool = True) -> None:
        super().__init__("EOAT Atlas Server Updater")
        source_root = root or Path.cwd()
        self.source_service = ReleaseManagerService(source_root)
        self.service = ServerUpdaterService(source_root)
        self.config_path: Path | None = None
        self.repository: RepositoryStatus | None = None
        self.last_result: OperationResult | None = None
        self._loading_choices = False

        self.status_card = StatusCard("Server update readiness")
        self.status_card.set_status("CHECKING", "Loading source branches, commits, and app version")
        self.details = KeyValuePanel("Selected update source")
        self.warnings = WarningPanel()
        self.log = OperationLog()
        self.branch = QComboBox()
        self.commit = QComboBox()
        self.config = QLineEdit()
        self.config.setReadOnly(True)
        self.refresh_button = QPushButton("Refresh source")
        self.choose_config_button = QPushButton("Choose server configuration")
        self.update_button = QPushButton("Update Server")
        self.receipt_button = QPushButton("Inspect latest receipt")
        self.receipt_button.setEnabled(False)

        form = QFormLayout()
        form.addRow("Branch", self.branch)
        form.addRow("Commit", self.commit)
        form.addRow("App version", QLabel("Shown below for the selected branch and commit."))
        config_row = QHBoxLayout()
        config_row.addWidget(self.config)
        config_row.addWidget(self.choose_config_button)
        form.addRow("Server configuration", config_row)
        actions = QHBoxLayout()
        for button in (self.refresh_button, self.update_button, self.receipt_button):
            actions.addWidget(button)
        form.addRow(actions)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(
            QLabel(
                "<h1>EOAT Atlas Server Updater</h1>"
                "<p>Select the exact source branch and commit, then update the server. "
                "The existing backend verifies the published artifact, SSH trust, server readiness, migration gate, "
                "and transaction state before any production change.</p>"
            )
        )
        layout.addWidget(self.status_card)
        layout.addLayout(form)
        layout.addWidget(self.details)
        layout.addWidget(self.warnings)
        splitter = QSplitter()
        splitter.addWidget(self.log)
        layout.addWidget(splitter)
        self.setCentralWidget(content)

        self.refresh_button.clicked.connect(self.refresh_source)
        self.branch.currentTextChanged.connect(self._branch_changed)
        self.commit.currentIndexChanged.connect(self._commit_changed)
        self.choose_config_button.clicked.connect(self.choose_config)
        self.update_button.clicked.connect(self.update_server)
        self.receipt_button.clicked.connect(lambda: self.last_result and self.show_receipt(self.last_result.raw))
        self.refresh_actions()
        if auto_refresh:
            QTimer.singleShot(0, self.refresh_source)

    def refresh_actions(self) -> None:
        source_selected = bool(self.repository and self.repository.version and self.commit.currentData())
        rule = update_server_rule(
            ToolState(busy=self._busy, config_loaded=self.config_path is not None, source_selected=source_selected)
        )
        self.update_button.setEnabled(rule.enabled)
        self.update_button.setToolTip(rule.reason)
        self.refresh_button.setEnabled(not self._busy)
        self.branch.setEnabled(not self._busy)
        self.commit.setEnabled(not self._busy)
        self.choose_config_button.setEnabled(not self._busy)

    def refresh_source(self) -> None:
        self.status_card.set_status("CHECKING", "Reading branches, commits, and current source state")

        def done(value: tuple[RepositoryStatus, OperationResult, list[str]]) -> None:
            status, result, branches = value
            self._loading_choices = True
            self.branch.clear()
            self.branch.addItems(branches)
            self.branch.setCurrentText(status.branch)
            self._loading_choices = False
            self._show_source((status, result))
            QTimer.singleShot(0, lambda: self._load_commits(status.branch, status.commit))

        self.run_operation("Source refresh", self.source_service.repository_view, done)

    def _set_commits(self, commits: list[tuple[str, str]], selected: str | None = None) -> None:
        self.commit.clear()
        for sha, subject in commits:
            self.commit.addItem(f"{sha[:12]}  {subject}", sha)
        if selected:
            index = self.commit.findData(selected)
            if index >= 0:
                self.commit.setCurrentIndex(index)

    def _branch_changed(self, branch: str) -> None:
        if not self._loading_choices and branch:
            self._load_commits(branch)

    def _load_commits(self, branch: str, selected: str | None = None) -> None:
        def done(commits: list[tuple[str, str]]) -> None:
            self._loading_choices = True
            self._set_commits(commits, selected)
            self._loading_choices = False
            self._inspect_selected_source()

        self.run_operation("Branch inspection", lambda: self.source_service.commits_for_branch(branch), done)

    def _commit_changed(self, _index: int) -> None:
        if not self._loading_choices:
            self._inspect_selected_source()

    def _inspect_selected_source(self) -> None:
        branch = self.branch.currentText()
        commit = self.commit.currentData()
        if branch and isinstance(commit, str):
            self.run_operation(
                "Source inspection", lambda: self.source_service.inspect_reference(branch, commit), self._show_source
            )

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
            self.last_result = result
            self._show_source((self.repository, result) if self.repository else None)

        self.run_operation("Configuration validation", lambda: self.service.load_config(path), done)

    def update_server(self) -> None:
        if not self.repository or not self.config_path:
            return
        version = self.repository.version
        commit = self.repository.commit
        if not version:
            return
        dialog = TypedConfirmationDialog(
            "Update Server",
            f"This verifies the published EOAT Atlas {version} artifact matches {commit[:12]}, then asks the existing "
            "backend to stage and activate it. A migration requirement, untrusted host key, health failure, or transaction "
            "gate stops the update before activation.",
            f"UPDATE SERVER {version}",
            self,
        )
        if not dialog.exec():
            return

        def done(result: OperationResult) -> None:
            self.last_result = result
            self.show_result(result)
            self.receipt_button.setEnabled(True)
            self.details.set_values(
                {
                    "Branch": self.repository.branch,
                    "Commit": self.repository.commit,
                    "App version": self.repository.version,
                    "Server configuration": self.config_path,
                    "Deployment ID": result.raw.get("deployment_id", "Unavailable"),
                    "Backend state": result.status,
                }
            )
            self.refresh_actions()

        self.run_operation("Update server", lambda: self.service.update_server(self.config_path, version, commit), done)

    def _show_source(self, value: tuple[RepositoryStatus, OperationResult] | None) -> None:
        if value is None:
            return
        self.repository, result = value
        self.last_result = result
        self.details.set_values(
            {
                "Branch": self.repository.branch,
                "Commit": self.repository.commit,
                "App version": self.repository.version or "Unavailable in this commit",
                "Server configuration": self.config_path or "Choose a configuration to enable Update Server",
                "Artifact requirement": "A published artifact must match this exact commit",
            }
        )
        self.show_result(result)
        self.receipt_button.setEnabled(True)
        self.refresh_actions()


def main() -> int:
    app = ensure_application()
    window = ServerUpdaterWindow()
    window.show()
    return app.exec()
