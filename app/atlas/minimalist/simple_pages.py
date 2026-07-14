from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .data import loaded_status_text
from .fit_check import FIT_CHECK_STYLES
from .widgets import GlassPanel, MinimalistToast, StatusDot, TitleAccentBar, glyph_icon

SIMPLE_PAGE_STYLES = (
    FIT_CHECK_STYLES
    + """
QWidget#AtlasMinimalistSimplePage,
QWidget#MinimalistSimpleContent,
QWidget#SimplePageBody,
QWidget#SimplePageCardGrid {
    background: transparent;
}
QScrollArea#SimplePageScroll {
    background: transparent;
    border: 0;
}
QScrollArea#SimplePageScroll QWidget {
    background: transparent;
}
QLabel#SimplePageTitle {
    color: #f8fbff;
    font-size: 31pt;
    font-weight: 820;
}
QLabel#SimplePageSubtitle {
    color: #d7e2f0;
    font-size: 10.5pt;
    font-weight: 500;
}
QFrame#SimplePageTitleAccent {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(0, 89, 200, 0), stop:.52 #047aff, stop:1 rgba(0, 89, 200, 0));
    border: 0;
    min-height: 3px;
    max-height: 3px;
}
QLabel#SimpleCardTitle {
    color: #ffffff;
    font-size: 11pt;
    font-weight: 780;
}
QLabel#SimpleCardText {
    color: #c6d3e3;
    font-size: 9pt;
    font-weight: 520;
}
QLabel#SimpleMetricValue {
    color: #ffffff;
    font-size: 20pt;
    font-weight: 820;
}
QPushButton#SimplePageButton {
    background: rgba(6, 18, 38, 128);
    color: #ffffff;
    border: 1px solid rgba(73, 111, 157, 134);
    border-radius: 7px;
    min-height: 38px;
    padding: 0 14px;
    font-size: 8.8pt;
    font-weight: 700;
}
QPushButton#SimplePageButton:hover {
    background: rgba(12, 42, 88, 174);
    border-color: rgba(31, 135, 255, 196);
}
"""
)


class AtlasMinimalistSimplePage(QWidget):
    def __init__(self, controller, *, page_key: str, title: str, subtitle: str, mode: str, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.page_key = page_key
        self.bundle = None
        self.setObjectName("AtlasMinimalistSimplePage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.simple_content = MinimalistSimpleContent(controller, title=title, subtitle=subtitle, mode=mode)
        from .shell import AtlasMinimalistShell

        self.shell = AtlasMinimalistShell(controller, self.simple_content)
        layout.addWidget(self.shell)

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle
        self.simple_content.set_bundle(bundle)
        self.shell.set_bundle(bundle)

    def page_shown(self) -> None:
        self.shell.close_overlays(immediate=True)
        self.shell.set_active_nav(self.page_key)
        self.shell.top_bar.set_back_visible(False, animated=False)
        self.simple_content.set_bundle(self.bundle)
        self.shell.setFocus(Qt.FocusReason.OtherFocusReason)

    def open_search_overlay(self) -> None:
        self.shell.open_search()

    def show_toast(self, message: str) -> None:
        self.simple_content.show_toast(message)


class MinimalistSimpleContent(QWidget):
    def __init__(self, controller, *, title: str, subtitle: str, mode: str, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.bundle = None
        self.mode = mode
        self.setObjectName("MinimalistSimpleContent")
        self.setStyleSheet(SIMPLE_PAGE_STYLES)
        self.body_scroll = QScrollArea(self)
        self.body_scroll.setObjectName("SimplePageScroll")
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setWidgetResizable(False)
        self.body = QWidget()
        self.body.setObjectName("SimplePageBody")
        self.body_scroll.setWidget(self.body)
        self.title = QLabel(title, self.body)
        self.title.setObjectName("SimplePageTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle = QLabel(subtitle, self.body)
        self.subtitle.setObjectName("SimplePageSubtitle")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.accent = TitleAccentBar(self.body)
        self.accent.setObjectName("SimplePageTitleAccent")
        self.card = GlassPanel(self.body, radius=8, streaks=True)
        self.card.set_glass(alpha=116, border_alpha=78, border_color=QColor("#1f87ff"), fill_color=QColor("#051226"))
        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(26, 22, 26, 22)
        self.card_layout.setSpacing(14)
        self.status = SimpleStatusLine(self)
        self.toast = MinimalistToast(self)
        self.toast.hide()
        self._render_cards()

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle
        self.status.set_status(loaded_status_text(bundle), ready=bundle is not None)
        self._render_cards()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = self.width()
        height = self.height()
        self.body_scroll.setGeometry(self.rect())
        content_width = min(1120, max(820, width - 220))
        if width < 920:
            content_width = max(320, width - 44)
        x = (width - content_width) // 2
        title_y = 116
        self.body.resize(width, max(height, 760))
        self.title.setGeometry((width - 620) // 2, title_y, 620, 48)
        self.accent.setGeometry((width - 78) // 2, title_y + 56, 78, 9)
        self.subtitle.setGeometry((width - 780) // 2, title_y + 68, 780, 24)
        self.card.setGeometry(x, title_y + 112, content_width, 430)
        status_width = min(340, max(220, width - 80))
        self.status.setGeometry(width - status_width - 62, height - 48, status_width, 30)
        toast_width = min(720, max(260, width - 90))
        self.toast.setGeometry((width - toast_width) // 2, height - 116, toast_width, 72)

    def show_toast(self, message: str) -> None:
        self.toast.show_message(message)

    def _render_cards(self) -> None:
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if self.mode == "settings":
            self._render_settings()
        elif self.mode == "standards":
            self._render_placeholder("Standards and work instructions will be added later.")
        else:
            self._render_placeholder("Data validation tools will be added later.")
        self.card_layout.addStretch(1)

    def _render_placeholder(self, message: str) -> None:
        card = SimpleInfoCard("Coming Later", message, "doc")
        card.setMinimumHeight(118)
        self.card_layout.addWidget(card)

    def _render_settings(self) -> None:
        bundle = self.bundle
        config = getattr(self.controller, "config", None)
        project_root = Path(str(getattr(config, "project_root", "") or "."))
        loaded_text = loaded_status_text(bundle)
        pdf_folder = project_root / "output" / "pdf"
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        cards = (
            ("Data Refresh", loaded_text, "Refresh reloads from the local cache.", "status"),
            ("PDF Output", str(pdf_folder), "Profile PDFs use the existing output folder.", "doc"),
            ("Search Index", "Refresh available", "Deep Refresh rebuilds the local cache from workbook data.", "library"),
        )
        for index, (title, value, text, glyph) in enumerate(cards):
            grid.addWidget(SimpleMetricCard(title, value, text, glyph), index // 3, index % 3)
        self.card_layout.addLayout(grid)
        row = QHBoxLayout()
        row.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("SimplePageButton")
        refresh.setIcon(glyph_icon("status", QColor("#ffffff"), 16))
        refresh.clicked.connect(lambda: self.controller.refresh_data(force=False))
        rebuild = QPushButton("Deep Refresh")
        rebuild.setObjectName("SimplePageButton")
        rebuild.setIcon(glyph_icon("library", QColor("#ffffff"), 16))
        rebuild.clicked.connect(self.controller.deep_refresh_data)
        row.addWidget(refresh)
        row.addWidget(rebuild)
        self.card_layout.addLayout(row)


class SimpleInfoCard(GlassPanel):
    def __init__(self, title: str, text: str, glyph: str, parent=None):
        super().__init__(parent, radius=8)
        self.set_glass(alpha=88, border_alpha=68, border_color=QColor("#286fa8"), fill_color=QColor("#061329"))
        self.setMinimumHeight(132)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        icon = QLabel()
        icon.setPixmap(glyph_icon(glyph, QColor("#dfeeff"), 28).pixmap(28, 28))
        label = QLabel(title)
        label.setObjectName("SimpleCardTitle")
        body = QLabel(text)
        body.setObjectName("SimpleCardText")
        body.setWordWrap(True)
        layout.addWidget(icon)
        layout.addWidget(label)
        layout.addWidget(body)
        layout.addStretch(1)


class SimpleMetricCard(SimpleInfoCard):
    def __init__(self, title: str, value: str, text: str, glyph: str, parent=None):
        super().__init__(title, text, glyph, parent)
        value_label = QLabel(value)
        value_label.setObjectName("SimpleMetricValue")
        self.layout().insertWidget(1, value_label)


class SimpleStatusLine(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dot = StatusDot(self)
        self.label = QLabel("Data loading...", self)
        self.label.setObjectName("MinimalistStatusText")

    def set_status(self, text: str, *, ready: bool) -> None:
        self.label.setText(text)
        self.dot.set_ready(ready)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.dot.setGeometry(0, 8, 14, 14)
        self.label.setGeometry(24, 1, self.width() - 24, 26)


__all__ = ["AtlasMinimalistSimplePage"]
