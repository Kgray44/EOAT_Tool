from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from .models import OperationResult
from .receipt_viewer import ReceiptViewer
from .workers import BackgroundRunner


class ToolWindow(QMainWindow):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setWindowTitle(title)
        self.resize(1100, 760)
        self.runner = BackgroundRunner(self)
        self._busy = False

    def run_operation(self, name: str, operation: Callable[[], Any], success: Callable[[Any], None]) -> None:
        self._busy = True
        self.log.add(f"{name}: started")
        self.refresh_actions()
        self.runner.submit(
            name,
            operation,
            success=lambda result: self._success(name, result, success),
            failure=self._failure,
            finished=self._finished,
        )

    def _success(self, name: str, result: Any, callback: Callable[[Any], None]) -> None:
        callback(result)
        self.log.add(f"{name}: completed")

    def _failure(self, detail: str, technical: str) -> None:
        self.log.add(f"Operation failed: {detail}")
        QMessageBox.critical(
            self,
            "EOAT Atlas operation failed",
            f"The operation did not complete.\n\n{detail}\n\nProduction state is unknown for mutating operations; inspect deployment status and receipts.",
        )

    def _finished(self) -> None:
        self._busy = False
        self.refresh_actions()

    def show_result(self, result: OperationResult) -> None:
        self.status_card.set_status(result.status, result.summary)
        self.warnings.show_messages(result.warnings, result.blockers)

    def show_receipt(self, payload: dict[str, Any]) -> None:
        ReceiptViewer(payload, self).exec()

    def refresh_actions(self) -> None:  # overridden by windows
        pass


def ensure_application() -> QApplication:
    return QApplication.instance() or QApplication([])
