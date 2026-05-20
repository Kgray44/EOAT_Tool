from __future__ import annotations

import sys
import os

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from core.config import load_config
from core.constants import APP_NAME
from .dashboard_ui import DashboardWindow
from .single_instance import SingleInstanceGuard
from .theme import app_stylesheet


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    config = load_config()
    app.setStyleSheet(app_stylesheet(config.theme))
    instance_guard = SingleInstanceGuard("EOAT_Command_Center_KGray")
    if not instance_guard.acquire():
        QMessageBox.information(
            None,
            APP_NAME,
            "EOAT Command Center is already running. Use the existing window instead of opening another copy.",
        )
        return 0
    app.aboutToQuit.connect(instance_guard.release)
    window = DashboardWindow()
    window._single_instance_guard = instance_guard
    window.show()
    if os.environ.get("EOAT_COMMAND_CENTER_SMOKE_TEST") == "1":
        QTimer.singleShot(1000, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
