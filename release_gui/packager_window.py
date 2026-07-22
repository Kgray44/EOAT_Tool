from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter, QVBoxLayout, QWidget

from .dialogs import TypedConfirmationDialog
from .models import OperationResult, RepositoryStatus
from .services import ReleaseManagerService
from .state_rules import ToolState, publish_rule
from .widgets import KeyValuePanel, OperationLog, StatusCard, WarningPanel
from .window_base import ToolWindow, ensure_application


class ReleasePackagerWindow(ToolWindow):
    def __init__(self, root: Path | None = None) -> None:
        super().__init__("EOAT Atlas Release Packager")
        self.service = ReleaseManagerService(root or Path.cwd())
        self.repository: RepositoryStatus | None = None
        self.validation_passed = False
        self.last_result: OperationResult | None = None
        self.status_card = StatusCard("Release readiness")
        self.details = KeyValuePanel("Repository")
        self.warnings = WarningPanel()
        self.log = OperationLog()
        self.version = QLineEdit()
        self.version.setPlaceholderText("Next release version, e.g. 0.18.1")
        self.refresh_button, self.validate_button, self.rehearse_button, self.publish_button, self.receipt_button = (
            QPushButton("Refresh status"),
            QPushButton("Run validation"),
            QPushButton("Run deployment rehearsal"),
            QPushButton("Publish active release"),
            QPushButton("Inspect latest receipt"),
        )
        self.receipt_button.setEnabled(False)
        controls = QFormLayout()
        controls.addRow("Proposed version", self.version)
        row = QHBoxLayout()
        for button in (
            self.refresh_button,
            self.validate_button,
            self.rehearse_button,
            self.publish_button,
            self.receipt_button,
        ):
            row.addWidget(button)
        controls.addRow(row)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(
            QLabel(
                "<h1>EOAT Atlas Release Packager</h1><p>Prepare releases through the established release-manager backend. Publishing is gated and always requires an exact typed confirmation.</p>"
            )
        )
        layout.addWidget(self.status_card)
        layout.addLayout(controls)
        layout.addWidget(self.details)
        layout.addWidget(self.warnings)
        splitter = QSplitter()
        splitter.addWidget(self.log)
        layout.addWidget(splitter)
        self.setCentralWidget(content)
        self.refresh_button.clicked.connect(self.refresh_status)
        self.validate_button.clicked.connect(self.validate)
        self.rehearse_button.clicked.connect(self.rehearse)
        self.publish_button.clicked.connect(self.publish)
        self.version.textChanged.connect(self.refresh_actions)
        self.receipt_button.clicked.connect(lambda: self.last_result and self.show_receipt(self.last_result.raw))
        self.refresh_actions()

    def refresh_actions(self) -> None:
        ready = bool(self.repository and self.repository.ready)
        publish = publish_rule(
            ToolState(
                busy=self._busy, repository_ready=ready, validation_passed=self.validation_passed, blockers=not ready
            )
        )
        self.validate_button.setEnabled(not self._busy)
        self.rehearse_button.setEnabled(not self._busy and ready and bool(self.version.text().strip()))
        self.publish_button.setEnabled(publish.enabled and bool(self.version.text().strip()))
        self.publish_button.setToolTip(publish.reason)

    def refresh_status(self) -> None:
        def done(value: tuple[RepositoryStatus, OperationResult]) -> None:
            self.repository, result = value
            self.details.set_values(
                {
                    "Branch": self.repository.branch,
                    "Commit": self.repository.commit,
                    "Version": self.repository.version,
                    "Clean": self.repository.clean,
                    "Ready to package": self.repository.ready,
                }
            )
            self.show_result(result)
            self.refresh_actions()

        self.run_operation("Repository status refresh", self.service.inspect_status, done)

    def validate(self) -> None:
        def done(result: OperationResult) -> None:
            self.validation_passed = result.status == "PASSED"
            self.last_result = result
            self.show_result(result)
            self.receipt_button.setEnabled(True)
            self.refresh_actions()

        self.run_operation("Release validation", self.service.validate, done)

    def rehearse(self) -> None:
        version = self.version.text().strip()

        def done(result: OperationResult) -> None:
            self.last_result = result
            self.show_result(result)
            self.receipt_button.setEnabled(True)

        self.run_operation("Dry-run package", lambda: self.service.rehearse_package(version), done)

    def publish(self) -> None:
        version = self.version.text().strip()
        dialog = TypedConfirmationDialog(
            "Publish active release",
            f"This will create and publish EOAT Atlas {version}. Git, tags, and GitHub may change if the backend succeeds.",
            f"PUBLISH {version}",
            self,
        )
        if not dialog.exec():
            return

        def done(result: OperationResult) -> None:
            self.last_result = result
            self.show_result(result)
            self.receipt_button.setEnabled(True)

        self.run_operation("Active release publication", lambda: self.service.publish_release(version), done)


def main() -> int:
    app = ensure_application()
    window = ReleasePackagerWindow()
    window.show()
    return app.exec()
