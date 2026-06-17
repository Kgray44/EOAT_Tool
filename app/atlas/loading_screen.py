from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from .assets import ATLAS_LOGO_PATH

ATLAS_LOADING_TIPS = (
    "Try What Do I Need? with a Tool #, Machine #, EOAT ID, part name, robot type, or keyword.",
    "Atlas is read-only by default. Use Command Center when a source workbook or photo link needs editing.",
    "EOAT profiles show compatibility, documentation score, warnings, photos, and install checks in one place.",
    "The compatibility matrix can switch between EOAT vs Machine, Tool vs EOAT, and Tool vs Machine views.",
    "Photo browsing uses the existing EOAT photo folders. Atlas will not move or rename photos.",
    "Settings / Diagnostics shows workbook load time, photo index time, and cache build time.",
    "Search is forgiving: Machine 12, Press 12, M12, and 12 all point to the same normalized machine key.",
    "Exports are timestamped under 06_Final_Handoff/Atlas_Exports so source files are not overwritten.",
)


class AtlasLoadingScreen(QWidget):
    def __init__(self, logo_path: str | Path = ATLAS_LOGO_PATH, parent=None):
        super().__init__(parent, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(620, 560)
        self._tip_index = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 30, 34, 30)
        layout.setSpacing(14)

        self.logo = QLabel()
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(logo_path))
        if not pixmap.isNull():
            self.logo.setPixmap(
                pixmap.scaled(230, 230, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self.logo.setText("EOAT Atlas")
        layout.addWidget(self.logo)

        title = QLabel("EOAT Atlas")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setObjectName("LoadingTitle")
        layout.addWidget(title)

        subtitle = QLabel("Warming up your EOAT search engine, compatibility calculator, and install assistant.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setObjectName("LoadingSubtitle")
        layout.addWidget(subtitle)

        self.tip = QLabel(ATLAS_LOADING_TIPS[0])
        self.tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tip.setWordWrap(True)
        self.tip.setObjectName("LoadingTip")
        layout.addWidget(self.tip)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        self.status = QLabel("Preparing Atlas...")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setObjectName("LoadingStatus")
        layout.addWidget(self.status)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._next_tip)
        self._timer.start(2600)

    def set_status(self, message: str) -> None:
        self.status.setText(message or "Preparing Atlas...")

    def center_on_screen(self) -> None:
        screen = self.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.move(available.center() - self.rect().center())

    def _next_tip(self) -> None:
        self._tip_index = (self._tip_index + 1) % len(ATLAS_LOADING_TIPS)
        self.tip.setText(ATLAS_LOADING_TIPS[self._tip_index])


__all__ = ["ATLAS_LOADING_TIPS", "AtlasLoadingScreen"]
