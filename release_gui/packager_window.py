from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
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
from .services import ReleaseManagerService
from .state_rules import ToolState, package_rule
from .widgets import KeyValuePanel, OperationLog, StatusCard, WarningPanel
from .window_base import ToolWindow, ensure_application


class ReleasePackagerWindow(ToolWindow):
    """A direct, intentionally small interface over the release-manager backend."""

    def __init__(self, root: Path | None = None, *, auto_refresh: bool = True) -> None:
        super().__init__("EOAT Atlas Release Packager")
        self.service = ReleaseManagerService(root or Path.cwd())
        self.repository: RepositoryStatus | None = None
        self.last_result: OperationResult | None = None
        self._loading_choices = False

        self.status_card = StatusCard("Release readiness")
        self.status_card.set_status("CHECKING", "Loading the current checkout")
        self.details = KeyValuePanel("Selected software source")
        self.warnings = WarningPanel()
        self.log = OperationLog()
        self.branch = QComboBox()
        self.commit = QComboBox()
        self.package_version = QLineEdit()
        self.package_version.setPlaceholderText("New package version, e.g. 0.18.2")
        self.refresh_button = QPushButton("Refresh repository")
        self.package_button = QPushButton("Package Software")
        self.receipt_button = QPushButton("Inspect latest receipt")
        self.receipt_button.setEnabled(False)

        controls = QFormLayout()
        controls.addRow("Branch", self.branch)
        controls.addRow("Commit", self.commit)
        controls.addRow("App version", QLabel("Shown below for the selected branch and commit."))
        controls.addRow("Package version", self.package_version)
        actions = QHBoxLayout()
        for button in (self.refresh_button, self.package_button, self.receipt_button):
            actions.addWidget(button)
        controls.addRow(actions)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(
            QLabel(
                "<h1>EOAT Atlas Release Packager</h1>"
                "<p>Select the exact branch and commit to inspect its app version. "
                "Packaging is enabled only for the clean checkout currently on disk.</p>"
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
        self.branch.currentTextChanged.connect(self._branch_changed)
        self.commit.currentIndexChanged.connect(self._commit_changed)
        self.package_version.textChanged.connect(self.refresh_actions)
        self.package_button.clicked.connect(self.package_software)
        self.receipt_button.clicked.connect(lambda: self.last_result and self.show_receipt(self.last_result.raw))
        self.refresh_actions()
        if auto_refresh:
            QTimer.singleShot(0, self.refresh_status)

    def refresh_actions(self) -> None:
        selected_current = bool(self.repository and self.repository.raw.get("selection_matches_checkout"))
        rule = package_rule(
            ToolState(
                busy=self._busy,
                repository_ready=bool(self.repository and self.repository.ready),
                selected_reference_current=selected_current,
                blockers=not bool(self.repository and self.repository.ready),
            )
        )
        self.package_button.setEnabled(rule.enabled and bool(self.package_version.text().strip()))
        self.package_button.setToolTip(rule.reason)
        self.refresh_button.setEnabled(not self._busy)
        self.branch.setEnabled(not self._busy)
        self.commit.setEnabled(not self._busy)

    def refresh_status(self) -> None:
        self.status_card.set_status("CHECKING", "Reading branches, commits, and current release state")

        def done(value: tuple[RepositoryStatus, OperationResult, list[str]]) -> None:
            status, result, branches = value
            self._loading_choices = True
            self.branch.clear()
            self.branch.addItems(branches)
            self.branch.setCurrentText(status.branch)
            self._loading_choices = False
            self._show_selection((status, result))
            QTimer.singleShot(0, lambda: self._load_commits(status.branch, status.commit))

        self.run_operation("Repository refresh", self.service.repository_view, done)

    def _set_commits(self, commits: list[tuple[str, str]], selected: str | None = None) -> None:
        self.commit.clear()
        for sha, subject in commits:
            self.commit.addItem(f"{sha[:12]}  {subject}", sha)
        if selected:
            index = self.commit.findData(selected)
            if index >= 0:
                self.commit.setCurrentIndex(index)

    def _branch_changed(self, branch: str) -> None:
        if self._loading_choices or not branch:
            return

        self._load_commits(branch)

    def _load_commits(self, branch: str, selected: str | None = None) -> None:
        def done(commits: list[tuple[str, str]]) -> None:
            self._loading_choices = True
            self._set_commits(commits, selected)
            self._loading_choices = False
            self._inspect_selected_reference()

        self.run_operation("Branch inspection", lambda: self.service.commits_for_branch(branch), done)

    def _commit_changed(self, _index: int) -> None:
        if not self._loading_choices:
            self._inspect_selected_reference()

    def _inspect_selected_reference(self) -> None:
        branch = self.branch.currentText()
        commit = self.commit.currentData()
        if not branch or not isinstance(commit, str):
            return
        self.run_operation(
            "Reference inspection", lambda: self.service.inspect_reference(branch, commit), self._show_selection
        )

    def _show_selection(self, value: tuple[RepositoryStatus, OperationResult]) -> None:
        self.repository, result = value
        self.last_result = result
        self.details.set_values(
            {
                "Branch": self.repository.branch,
                "Commit": self.repository.commit,
                "App version": self.repository.version or "Unavailable in this commit",
                "Checkout clean": self.repository.clean,
                "Selected commit is checked out": bool(self.repository.raw.get("selection_matches_checkout")),
                "Ready to package": self.repository.ready,
            }
        )
        self.show_result(result)
        self.receipt_button.setEnabled(True)
        self.refresh_actions()

    def package_software(self) -> None:
        version = self.package_version.text().strip()
        dialog = TypedConfirmationDialog(
            "Package Software",
            f"This creates EOAT Atlas {version} using the existing packager. "
            "It runs validation and writes the local release commit and artifacts. "
            "It will not push a branch, create a tag, or publish a GitHub release.",
            f"PACKAGE {version}",
            self,
        )
        if not dialog.exec():
            return

        def done(result: OperationResult) -> None:
            self.last_result = result
            self.show_result(result)
            self.receipt_button.setEnabled(True)
            QTimer.singleShot(0, self.refresh_status)

        self.run_operation("Package software", lambda: self.service.package_software(version), done)


def main() -> int:
    app = ensure_application()
    window = ReleasePackagerWindow()
    window.show()
    return app.exec()
