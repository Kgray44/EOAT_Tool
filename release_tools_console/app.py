"""PySide6 operator console over the shared convergence application services."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from deployment.common import to_jsonable
from deployment.convergence.models import DeploymentState
from deployment.convergence.services import ReleaseDeploymentService


class OperationWorker(QObject):
    completed = Signal(str, object)
    failed = Signal(str, str)
    finished = Signal()

    def __init__(self, name: str, operation: Callable[[], object]) -> None:
        super().__init__()
        self.name, self.operation = name, operation

    def run(self) -> None:
        try:
            self.completed.emit(self.name, self.operation())
        except Exception as exc:
            self.failed.emit(self.name, str(exc))
        finally:
            self.finished.emit()


class ReleaseDeploymentConsole(QMainWindow):
    """Operator-facing state console. All business decisions live in services."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.service = ReleaseDeploymentService(root)
        self._thread: QThread | None = None
        self._worker: OperationWorker | None = None
        self._buttons: list[QPushButton] = []
        self.setWindowTitle("EOAT Atlas Release and Deployment Console")
        self.setAccessibleName("EOAT Atlas Release and Deployment Console")
        self.resize(1120, 760)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._overview_page(), "Overview")
        self.tabs.addTab(self._preparation_page(), "Release Preparation")
        self.tabs.addTab(self._inventory_page(), "Release Inventory")
        self.tabs.addTab(self._target_page(), "Target Inspection")
        self.tabs.addTab(self._plan_page(), "Deployment Plan")
        self.tabs.addTab(self._transaction_page(), "Deployment Transaction")
        self.tabs.addTab(self._receipts_page(), "Logs and Receipts")
        self.tabs.addTab(self._settings_page(), "Settings")
        self.setCentralWidget(self.tabs)

    def _button(self, text: str, accessible: str, callback: Callable[[], None]) -> QPushButton:
        button = QPushButton(text)
        button.setAccessibleName(accessible)
        button.clicked.connect(callback)
        self._buttons.append(button)
        return button

    def _overview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        cards = QFormLayout()
        self.local_card = QLabel("NOT RUN")
        self.candidate_card = QLabel("No retained candidate selected")
        self.release_card = QLabel("No verified release selected")
        self.target_card = QLabel("No target inspection selected")
        self.decision_card = QLabel("Run readiness diagnostics.")
        for label, value in (
            ("Local source", self.local_card),
            ("Candidate", self.candidate_card),
            ("Selected release", self.release_card),
            ("Target", self.target_card),
            ("Decision / next safe action", self.decision_card),
        ):
            value.setWordWrap(True)
            cards.addRow(label, value)
        layout.addLayout(cards)
        self.overview = QPlainTextEdit(readOnly=True)
        self.overview.setAccessibleName("Concise readiness overview")
        self.overview.setPlainText("Status: NOT RUN\nUse Refresh readiness to begin a read-only diagnostic.")
        layout.addWidget(self.overview)
        self.refresh = self._button(
            "Refresh readiness",
            "Refresh candidate readiness",
            lambda: self._start("readiness", self.service.status),
        )
        layout.addWidget(self.refresh)
        return page

    def _preparation_page(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        self.bump = QComboBox()
        self.bump.addItems(["patch", "minor", "major"])
        self.bump.setAccessibleName("Candidate version increment")
        self.explicit_version = QLineEdit()
        self.explicit_version.setAccessibleName("Explicit candidate version")
        self.candidate_id = QLineEdit()
        self.candidate_id.setAccessibleName("Selected candidate ID")
        self.attachment_path = QLineEdit()
        self.attachment_path.setAccessibleName("Windows platform attachment path")
        self.component_summary = QLabel("No component inventory loaded")
        self.component_summary.setWordWrap(True)
        layout.addRow("Increment", self.bump)
        layout.addRow("Explicit version (advanced)", self.explicit_version)
        layout.addRow("Candidate ID", self.candidate_id)
        layout.addRow("Windows attachment", self.attachment_path)
        layout.addRow("Component inventory", self.component_summary)
        layout.addRow(self._button("Rehearse candidate", "Run dry-run candidate rehearsal", self._rehearse))
        self.prepare = self._button("Prepare immutable candidate", "Prepare immutable release candidate", self._prepare)
        layout.addRow(self.prepare)
        layout.addRow(self._button("Build Core Artifacts", "Build and verify core artifacts", self._build_core_artifacts))
        layout.addRow(self._button("Verify Core Artifacts", "Verify retained core artifacts", self._verify_core_artifacts))
        layout.addRow(self._button("Inspect Windows Attachment", "Inspect Windows artifact attachment", self._inspect_attachment))
        layout.addRow(self._button("Attach Platform Artifacts", "Attach validated Windows artifacts", self._attach_platform_artifacts))
        layout.addRow(self._button("Verify Attached Artifacts", "Verify attached Windows artifacts", self._verify_platform_artifacts))
        layout.addRow(self._button("Show Candidate Components", "Show candidate component inventory", self._show_components))
        layout.addRow(
            self._button(
                "Refresh candidates",
                "Refresh retained candidate list",
                lambda: self._start("candidates", self.service.candidates),
            )
        )
        layout.addRow(self._button("Discard candidate", "Discard unpromoted candidate", self._discard_candidate))
        layout.addRow(self._button("Start publication", "Start candidate publication", self._publish))
        layout.addRow(self._button("Resume publication", "Resume publication", self._resume_publication))
        return page

    def _inventory_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.inventory_table = QTableWidget(0, 6)
        self.inventory_table.setHorizontalHeaderLabels(
            ["Version", "Tag", "Draft", "Assets", "Deployable", "Blocking reasons"]
        )
        self.inventory_table.setAccessibleName("Structured release inventory")
        layout.addWidget(self.inventory_table)
        layout.addWidget(
            self._button(
                "Refresh release inventory",
                "Refresh GitHub release inventory",
                lambda: self._start("inventory", self.service.inventory),
            )
        )
        return page

    def _target_page(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        self.target_config = QLineEdit()
        self.target_config.setAccessibleName("Non-production target configuration path")
        self.inspection_id = QLineEdit()
        self.inspection_id.setAccessibleName("Selected target inspection ID")
        self.target_summary = QLabel("NOT RUN")
        self.target_summary.setWordWrap(True)
        layout.addRow("Test-target config", self.target_config)
        layout.addRow("Inspection ID", self.inspection_id)
        layout.addRow("Target facts", self.target_summary)
        layout.addRow(
            self._button("Run read-only inspection", "Run read-only test target inspection", self._inspect_target)
        )
        return page

    def _plan_page(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        self.release_version = QLineEdit()
        self.release_version.setAccessibleName("Verified release version")
        self.plan_inspection_id = QLineEdit()
        self.plan_inspection_id.setAccessibleName("Deployment plan inspection ID")
        self.plan_id = QLineEdit()
        self.plan_id.setAccessibleName("Deployment plan ID")
        self.plan_summary = QLabel("NOT RUN")
        self.plan_summary.setWordWrap(True)
        layout.addRow("Verified release version", self.release_version)
        layout.addRow("Inspection ID", self.plan_inspection_id)
        layout.addRow("Plan ID", self.plan_id)
        layout.addRow("Plan summary", self.plan_summary)
        layout.addRow(self._button("Verify selected release", "Verify selected release", self._verify_release))
        layout.addRow(self._button("Create plan from stored facts", "Create deployment plan", self._create_plan))
        return page

    def _transaction_page(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        self.transaction_plan_id = QLineEdit()
        self.transaction_plan_id.setAccessibleName("Deployment transaction plan ID")
        self.transaction_id = QLineEdit()
        self.transaction_id.setAccessibleName("Deployment transaction ID")
        self.transaction_summary = QLabel("NOT STARTED")
        self.transaction_summary.setWordWrap(True)
        layout.addRow("Plan ID", self.transaction_plan_id)
        layout.addRow("Transaction ID", self.transaction_id)
        layout.addRow("Transaction state", self.transaction_summary)
        layout.addRow(
            self._button("Stage (initialize only)", "Initialize no-mutation deployment transaction", self._stage)
        )
        for text, state in (
            ("Approve migration", DeploymentState.MIGRATION_APPROVED),
            ("Activate", DeploymentState.ACTIVATION_STARTED),
            ("Roll back application", DeploymentState.ROLLBACK_STARTED),
            ("Begin database recovery", DeploymentState.DATABASE_RESTORE_STARTED),
        ):
            layout.addRow(self._button(text, text, lambda state=state: self._dangerous_transition(state)))
        layout.addRow(
            self._button("Check transaction status", "Check deployment transaction status", self._transaction_status)
        )
        return page

    def _receipts_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.receipt_summary = QPlainTextEdit(readOnly=True)
        self.receipt_summary.setAccessibleName("Human-readable receipt summary")
        self.raw_diagnostics = QPlainTextEdit(readOnly=True)
        self.raw_diagnostics.setAccessibleName("Expanded redacted technical diagnostics")
        layout.addWidget(self.receipt_summary)
        layout.addWidget(self.raw_diagnostics)
        layout.addWidget(
            self._button(
                "Refresh receipts", "Refresh receipt inventory", lambda: self._start("receipts", self.service.receipts)
            )
        )
        return page

    def _settings_page(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        layout.addRow("Repository root", QLabel(str(self.service.root)))
        layout.addRow("Receipt/cache root", QLabel(str(self.service.store.root)))
        layout.addRow("Default mode", QLabel("Dry run / read-only"))
        layout.addRow("Structured diagnostic fallback", QLabel("Permitted only for explicitly configured test targets"))
        return page

    def _rehearse(self) -> None:
        self._start(
            "rehearse",
            lambda: self.service.rehearse_candidate(self.bump.currentText(), self.explicit_version.text() or None),
        )

    def _prepare(self) -> None:
        version = self.explicit_version.text() or f"next {self.bump.currentText()} increment"
        if self._confirm(
            "Prepare immutable candidate",
            f"Prepare {version} in an isolated worktree? No remote or target mutation occurs.",
        ):
            self._start(
                "prepare",
                lambda: self.service.prepare_candidate(self.bump.currentText(), self.explicit_version.text() or None),
            )

    def _discard_candidate(self) -> None:
        self._start("discard", lambda: self.service.discard_candidate(self.candidate_id.text()))

    def _build_core_artifacts(self) -> None:
        self._start("core-build", lambda: self.service.build_core_artifacts(self.candidate_id.text()))

    def _verify_core_artifacts(self) -> None:
        self._start("core-verify", lambda: self.service.verify_core_artifacts(self.candidate_id.text()))

    def _inspect_attachment(self) -> None:
        self._start("attachment-inspect", lambda: self.service.inspect_platform_attachment(self.candidate_id.text(), Path(self.attachment_path.text())))

    def _attach_platform_artifacts(self) -> None:
        self._start("attachment-attach", lambda: self.service.attach_platform_artifacts(self.candidate_id.text(), Path(self.attachment_path.text())))

    def _verify_platform_artifacts(self) -> None:
        self._start("platform-verify", lambda: self.service.verify_platform_artifacts(self.candidate_id.text()))

    def _show_components(self) -> None:
        self._start("components", lambda: self.service.candidate(self.candidate_id.text()))

    def _publish(self) -> None:
        candidate = self.candidate_id.text()
        version, accepted = self._typed_confirmation(
            "Start publication", "Type the exact candidate version to publish:"
        )
        if accepted:
            self._start("publish", lambda: self.service.publish_start(candidate, version))

    def _resume_publication(self) -> None:
        self._start("publication", lambda: self.service.publish_resume(self.candidate_id.text()))

    def _inspect_target(self) -> None:
        self._start("target", lambda: self.service.inspect_target(Path(self.target_config.text())))

    def _verify_release(self) -> None:
        self._start("release", lambda: self.service.verify_release(self.release_version.text()))

    def _create_plan(self) -> None:
        self._start(
            "plan", lambda: self.service.create_plan(self.release_version.text(), self.plan_inspection_id.text())
        )

    def _stage(self) -> None:
        version, accepted = self._typed_confirmation(
            "Initialize deployment transaction", "Type the selected release version:"
        )
        if accepted:
            self._start("stage", lambda: self.service.begin_transaction(self.transaction_plan_id.text(), version))

    def _dangerous_transition(self, state: DeploymentState) -> None:
        confirmation, accepted = self._typed_confirmation(state.value, "Type the exact transaction ID:")
        if accepted:
            self._start(
                "transaction",
                lambda: self.service.transition_transaction(self.transaction_id.text(), state, confirmation),
            )

    def _transaction_status(self) -> None:
        self._start("transaction", lambda: self.service.transaction(self.transaction_id.text()))

    def _confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes

    def _typed_confirmation(self, title: str, prompt: str) -> tuple[str, bool]:
        dialog = QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setText(prompt)
        field = QLineEdit(dialog)
        field.setAccessibleName(f"{title} confirmation text")
        dialog.layout().addWidget(field, 1, 1)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        accepted = dialog.exec() == QMessageBox.StandardButton.Ok
        return field.text(), accepted

    def _start(self, name: str, operation: Callable[[], object]) -> None:
        if self._thread is not None:
            return
        self._set_busy(True)
        self._thread = QThread(self)
        self._worker = OperationWorker(name, operation)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.completed.connect(self._completed)
        self._worker.failed.connect(self._failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()

    def _completed(self, name: str, result: object) -> None:
        payload = to_jsonable(result)
        self.raw_diagnostics.appendPlainText(json.dumps(payload, indent=2, sort_keys=True))
        self._render(name, payload)

    def _render(self, name: str, payload: dict[str, Any]) -> None:
        data = payload.get("data", {})
        self.decision_card.setText(
            f"{payload.get('status', 'UNKNOWN')}: {payload.get('next_safe_action', 'Review receipt.')}"
        )
        if name == "readiness":
            repository = data.get("repository", {})
            self.local_card.setText(
                f"{repository.get('branch', 'unknown')} @ {repository.get('commit', '')[:12]} | version {repository.get('version', 'unknown')}"
            )
            self.overview.setPlainText(
                f"{payload.get('status')}: {payload.get('summary')}\n{payload.get('next_safe_action')}"
            )
        elif name in {"prepare", "rehearse"}:
            candidate = data.get("candidate", {})
            self.candidate_id.setText(candidate.get("candidate_id", ""))
            self.candidate_card.setText(
                f"{candidate.get('state')} | {candidate.get('version')} | {candidate.get('artifact_sha256', '')[:12]}"
            )
        elif name in {"core-build", "core-verify", "attachment-inspect", "attachment-attach", "platform-verify", "components"}:
            receipt = self.service.candidate(self.candidate_id.text()) if self.candidate_id.text() else {}
            working = receipt.get("working_release_set") or {}
            components = working.get("components") or []
            pending = [str(item.get("kind")) for item in components if isinstance(item, dict) and item.get("disposition") == "PENDING"]
            self.component_summary.setText(f"{len(components)} components; pending: {', '.join(sorted(pending)) or 'none'}")
            self.candidate_card.setText(f"{receipt.get('state', 'UNKNOWN')} | publication eligible: {receipt.get('publication_eligible', False)}")
        elif name == "inventory":
            releases = data.get("releases", [])
            self.inventory_table.setRowCount(len(releases))
            for row, release in enumerate(releases):
                values = (
                    release.get("version"),
                    release.get("tag"),
                    str(release.get("draft")),
                    str(len(release.get("assets", []))),
                    str(release.get("deployable")),
                    "; ".join(release.get("blocking_reasons", [])),
                )
                for column, value in enumerate(values):
                    self.inventory_table.setItem(row, column, QTableWidgetItem(str(value)))
        elif name == "target":
            self.inspection_id.setText(data.get("inspection_id", ""))
            self.plan_inspection_id.setText(data.get("inspection_id", ""))
            self.target_summary.setText(
                f"{data.get('target_name')} via {data.get('diagnostic_method')}; blockers: {len(data.get('blocking_failures', []))}"
            )
        elif name == "release":
            release = data.get("release", {})
            self.release_card.setText(
                f"{release.get('version')} | {release.get('commit_sha', '')[:12]} | schema {data.get('schema_target')}"
            )
        elif name == "plan":
            plan = data.get("plan", {})
            self.plan_id.setText(plan.get("plan_id", ""))
            self.transaction_plan_id.setText(plan.get("plan_id", ""))
            self.plan_summary.setText(f"{plan.get('mode')} | {plan.get('next_safe_action')}")
        elif name in {"stage", "transaction"}:
            transaction = data.get("transaction", {})
            self.transaction_id.setText(transaction.get("transaction_id", self.transaction_id.text()))
            self.transaction_summary.setText(f"{transaction.get('state')} | {transaction.get('next_safe_action')}")
        elif name == "receipts":
            self.receipt_summary.setPlainText(self._receipt_text(data))

    @staticmethod
    def _receipt_text(data: dict[str, Any]) -> str:
        inventories = data.get("receipts", {})
        lines = ["Receipt inventory"]
        for kind, records in inventories.items():
            lines.append(f"{kind}: {len(records)} record(s)")
        lines.append(f"quarantine: {len(data.get('quarantine', []))} record(s)")
        return "\n".join(lines)

    def _failed(self, _name: str, message: str) -> None:
        self.raw_diagnostics.appendPlainText(f"BLOCKED: {message}")
        self.decision_card.setText("BLOCKED: review redacted diagnostics; no success was recorded.")
        QMessageBox.warning(self, "Operation blocked", message)

    def _thread_finished(self) -> None:
        if self._thread:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        for button in self._buttons:
            button.setDisabled(busy)

    def closeEvent(self, event: Any) -> None:
        if self._thread is not None and not self._confirm(
            "Operation in progress",
            "A release operation is running. Closing preserves its receipt but does not cancel it. Close anyway?",
        ):
            event.ignore()
            return
        event.accept()


def main(root: Path | None = None) -> int:
    application = QApplication.instance() or QApplication([])
    window = ReleaseDeploymentConsole((root or Path(__file__).resolve().parents[1]).resolve())
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
