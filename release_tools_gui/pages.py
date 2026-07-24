"""Read-only Packager and Updater pages; dangerous operations have no UI path."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .models import DANGEROUS_PHASE_ONE_ACTIONS, GuiStatus, OperationResult
from .receipts import ReceiptStore
from .services import ReleaseManagerAdapter, ServerUpdaterAdapter, failure_result
from .widgets import DetailTree, StatusBanner
from .workers import ToolRunner


class ToolPage(QWidget):
    def __init__(self, tool: str, store: ReceiptStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tool, self.store, self.current_result = tool, store, None
        self.runner = ToolRunner(self)
        self.banner = StatusBanner("NOT RUN — no operation has completed")
        self.banner.setWordWrap(True)
        self.details = DetailTree()
        self.progress = QLabel("Idle")
        self.progress.setAccessibleName("Operation progress")
        self.cancel = QPushButton("Cancel queued operation")
        self.cancel.setEnabled(False)
        self.cancel.setToolTip("Only queued work can be cancelled; running engine calls are not interrupted safely.")
        self.cancel.clicked.connect(self._cancel)
        self._buttons: list[QPushButton] = []
        self.runner.state_changed.connect(self._state_changed)

    def action(self, text: str, callback: Callable[[], None], tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        self._buttons.append(button)
        return button

    def _run(self, name: str, operation: Callable[[], OperationResult]) -> None:
        self.runner.submit(
            name,
            operation,
            succeeded=self._success,
            failed=lambda error: self._failure(name, error),
            cancelled=lambda message: self._cancelled(name, message),
        )

    def _state_changed(self, busy: bool, name: str) -> None:
        for button in self._buttons:
            button.setEnabled(not busy)
        self.cancel.setEnabled(busy)
        self.progress.setText(f"Running: {name}" if busy else "Idle")

    def _success(self, result: OperationResult) -> None:
        self.current_result = result
        receipt = self.store.save(result)
        self.current_result = OperationResult(**{**result.__dict__, "receipt_path": str(receipt)})
        self._show(self.current_result)

    def _failure(self, operation: str, error: str) -> None:
        self._show(failure_result(self.tool, operation, error))

    def _cancelled(self, operation: str, message: str) -> None:
        result = OperationResult(self.tool, operation, GuiStatus.NOT_RUN, message, {"cancellation": message})
        self._show(result)

    def _show(self, result: OperationResult) -> None:
        self.current_result = result
        self.banner.set_result(result)
        self.details.set_result(result)

    def _cancel(self) -> None:
        if self.runner.request_cancel():
            self.progress.setText("Cancellation accepted before engine work began")
        else:
            self.progress.setText("Engine work has begun and will finish safely; it cannot be interrupted")

    def _danger_zone(self) -> QGroupBox:
        box = QGroupBox("Phase 1 safety boundary")
        disabled = QLabel("Disabled: " + ", ".join(sorted(DANGEROUS_PHASE_ONE_ACTIONS)) + ".")
        disabled.setWordWrap(True)
        disabled.setAccessibleName("Dangerous actions disabled in Phase 1")
        layout = QVBoxLayout(box)
        layout.addWidget(disabled)
        return box

    def content(self, title: str, explanation: str, form: QFormLayout, buttons: list[QPushButton]) -> None:
        body = QWidget()
        layout = QVBoxLayout(body)
        heading = QLabel(f"<h1>{title}</h1><p>{explanation}</p>")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(self.banner)
        layout.addLayout(form)
        actions = QHBoxLayout()
        for button in buttons:
            actions.addWidget(button)
        actions.addWidget(self.cancel)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addWidget(self.progress)
        layout.addWidget(self._danger_zone())
        layout.addWidget(QLabel("Structured details"))
        layout.addWidget(self.details, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.addWidget(scroll)


class PackagerPage(ToolPage):
    def __init__(self, root: Path, store: ReceiptStore, parent: QWidget | None = None) -> None:
        super().__init__("packager", store, parent)
        self.adapter = ReleaseManagerAdapter(root)
        self.root = QLabel(str(root))
        self.root.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.proposed = QLineEdit()
        self.proposed.setPlaceholderText("MAJOR.MINOR.PATCH; dry-run only")
        status = self.action(
            "Refresh status", self.refresh_status, "Run the existing read-only release-manager status function"
        )
        validate = self.action("Run validation", self.run_validation, "Run the existing release validation plan")
        dry_run = self.action(
            "Package dry-run",
            self.run_dry_run,
            "Use an isolated clone; no version, Git, artifact, or publication mutation",
        )
        form = QFormLayout()
        form.addRow("Repository root", self.root)
        form.addRow("Proposed version", self.proposed)
        form.addRow(
            "Version controls", QLabel("Active version bump, commit, tag, push, and publication are unavailable.")
        )
        self.content(
            "EOAT Atlas Release Packager",
            "Read-only release readiness and isolated package rehearsal.",
            form,
            [status, validate, dry_run],
        )

    def refresh_status(self) -> None:
        self._run("status", self.adapter.status)

    def run_validation(self) -> None:
        self._run("validate", self.adapter.validate)

    def run_dry_run(self) -> None:
        version = self.proposed.text().strip()
        if not version:
            self._show(
                failure_result("packager", "package-dry-run", "Enter a proposed semantic version before the dry run")
            )
            return
        self._run("package-dry-run", lambda: self.adapter.package_dry_run(version))


class UpdaterPage(ToolPage):
    def __init__(self, root: Path, store: ReceiptStore, parent: QWidget | None = None) -> None:
        super().__init__("updater", store, parent)
        self.adapter = ServerUpdaterAdapter(root)
        self.root = root
        self.config_path: Path | None = None
        self.config = QLineEdit()
        self.config.setReadOnly(True)
        self.version = QComboBox()
        self.version.setEditable(True)
        self.version.setAccessibleName("Release version selected for inspection")
        choose = self.action(
            "Choose approved configuration",
            self.choose_config,
            "Choose a non-secret JSON file under config and validate it",
        )
        status = self.action(
            "Updater status", lambda: self._run("status", self.adapter.status), "Show strict read-only updater status"
        )
        releases = self.action(
            "List eligible releases", self.list_releases, "Read eligible GitHub Releases without mutation"
        )
        inspect_release = self.action(
            "Inspect selected release", self.inspect_release, "Download/cache and verify only"
        )
        inspect_server = self.action(
            "Inspect server", self.inspect_server, "Use the engine's read-only SSH inspection allowlist"
        )
        preflight = self.action("Deployment preflight", self.preflight, "Run the engine's dry-run receipt only")
        form = QFormLayout()
        form.addRow("Configuration", self.config)
        form.addRow("Selected release", self.version)
        form.addRow(
            "Deployment controls",
            QLabel("Upload, stage, activate, migrate, rollback, recovery, host and service mutation are unavailable."),
        )
        self.content(
            "EOAT Atlas Server Updater",
            "Read-only server facts, release verification, and deployment rehearsal.",
            form,
            [choose, status, releases, inspect_release, inspect_server, preflight],
        )

    def choose_config(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Choose approved non-secret configuration", str(self.root / "config"), "JSON files (*.json)"
        )
        if not filename:
            return
        path = Path(filename)

        def applied(result: OperationResult) -> None:
            if result.status is GuiStatus.PASS:
                self.config_path = path
                self.config.setText(str(path))
            self._success(result)

        self.runner.submit(
            "load-config",
            lambda: self.adapter.load_config(path),
            succeeded=applied,
            failed=lambda error: self._failure("load-config", error),
            cancelled=lambda message: self._cancelled("load-config", message),
        )

    def list_releases(self) -> None:
        def apply(result: OperationResult) -> None:
            releases = result.details.get("releases", [])
            self.version.clear()
            for release in releases if isinstance(releases, list) else []:
                version = release.get("version") if isinstance(release, dict) else None
                if version:
                    self.version.addItem(str(version))
            self._success(result)

        self.runner.submit(
            "list-releases",
            self.adapter.list_releases,
            succeeded=apply,
            failed=lambda error: self._failure("list-releases", error),
            cancelled=lambda message: self._cancelled("list-releases", message),
        )

    def inspect_release(self) -> None:
        self._run("inspect-release", lambda: self.adapter.inspect_release(self.version.currentText().strip() or None))

    def inspect_server(self) -> None:
        if self.config_path is None:
            self._show(
                failure_result("updater", "inspect-server", "Choose an approved non-secret server configuration first")
            )
            return
        self._run("inspect-server", lambda: self.adapter.inspect_server(self.config_path))

    def preflight(self) -> None:
        if self.config_path is None:
            self._show(
                failure_result("updater", "preflight", "Choose an approved non-secret server configuration first")
            )
            return
        self._run(
            "preflight", lambda: self.adapter.preflight(self.config_path, self.version.currentText().strip() or None)
        )
