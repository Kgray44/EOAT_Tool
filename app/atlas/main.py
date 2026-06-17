from __future__ import annotations

import os
import sys
import threading

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from core.config import UserConfig, load_config
from core.constants import DEFAULT_PROJECT_ROOT

from .assets import ATLAS_LOGO_PATH
from .atlas_window import AtlasWindow
from .loading_screen import AtlasLoadingScreen
from .styles import atlas_stylesheet


def main() -> int:
    smoke_test_arg = "--smoke-test" in sys.argv
    if smoke_test_arg:
        sys.argv.remove("--smoke-test")
    smoke_test = smoke_test_arg or os.environ.get("EOAT_ATLAS_SMOKE_TEST") == "1"
    if smoke_test:
        watchdog = threading.Timer(15.0, lambda: os._exit(0))
        watchdog.daemon = True
        watchdog.start()
    app = QApplication(sys.argv)
    app.setApplicationName("EOAT Atlas")
    app.setFont(QFont("Segoe UI", 10))
    if ATLAS_LOGO_PATH.exists():
        app.setWindowIcon(QIcon(str(ATLAS_LOGO_PATH)))
    app.setStyleSheet(atlas_stylesheet())
    config = UserConfig(project_root=str(DEFAULT_PROJECT_ROOT)) if smoke_test else load_config()
    loading = AtlasLoadingScreen(ATLAS_LOGO_PATH)
    loading.center_on_screen()
    loading.show()
    app.processEvents()
    window = AtlasWindow(config, auto_refresh=False)
    startup_state = {"done": False}

    def _reveal_window() -> None:
        if startup_state["done"]:
            return
        startup_state["done"] = True
        loading.close()
        window.show()

    def _reveal_after_failure(message: str) -> None:
        if startup_state["done"]:
            return
        loading.set_status(f"Atlas could not finish loading data: {message}")
        QTimer.singleShot(900, _reveal_window)

    window.loading_progress.connect(loading.set_status)
    window.data_ready.connect(lambda _bundle: _reveal_window())
    window.data_failed.connect(_reveal_after_failure)
    if smoke_test:
        loading.set_status("Smoke testing EOAT Atlas startup...")

        def _finish_smoke_test() -> None:
            loading.close()
            window.close()
            app.quit()

        QTimer.singleShot(700, _finish_smoke_test)
        QTimer.singleShot(6000, lambda: os._exit(0))
    else:
        window.refresh_data(force=False)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
