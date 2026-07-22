from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from .packager_window import ReleasePackagerWindow
from .updater_window import ServerUpdaterWindow
from .window_base import ensure_application


class ReleaseToolsLauncher(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EOAT Atlas Release Tools")
        self.resize(440, 220)
        self.windows: list[QWidget] = []
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("<h1>EOAT Atlas Release Tools</h1><p>Choose a safe, state-gated operator workflow.</p>")
        )
        package, updater = QPushButton("Open Release Packager"), QPushButton("Open Server Updater")
        layout.addWidget(package)
        layout.addWidget(updater)
        package.clicked.connect(lambda: self.open(ReleasePackagerWindow))
        updater.clicked.connect(lambda: self.open(ServerUpdaterWindow))

    def open(self, window_type: type[QWidget]) -> None:
        window = window_type()
        window.show()
        self.windows.append(window)


def main() -> int:
    app = ensure_application()
    window = ReleaseToolsLauncher()
    window.show()
    return app.exec()
