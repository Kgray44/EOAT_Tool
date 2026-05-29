from __future__ import annotations

import os
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from core.config import load_config
from core.constants import APP_NAME
from core.performance import log_performance

from .dashboard_ui import DashboardWindow
from .single_instance import SingleInstanceGuard
from .theme import app_stylesheet


def main() -> int:
    startup_started = time.perf_counter()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    config_started = time.perf_counter()
    config = load_config()
    log_performance(config.project_root, "app_start.load_config", time.perf_counter() - config_started, source="app_start", page_tool="main")
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
    window_started = time.perf_counter()
    window = DashboardWindow(config)
    log_performance(config.project_root, "app_start.window_create", time.perf_counter() - window_started, source="app_start", page_tool="main")
    window._single_instance_guard = instance_guard
    window.show()
    log_performance(config.project_root, "app_start.shell_visible", time.perf_counter() - startup_started, source="app_start", page_tool="main")
    if os.environ.get("EOAT_COMMAND_CENTER_SMOKE_TEST") == "1":
        QTimer.singleShot(1000, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
