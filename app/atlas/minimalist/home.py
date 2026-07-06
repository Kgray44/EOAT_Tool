from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .data import MinimalistSearchEntry, loaded_status_text, recent_entries
from .widgets import ArrowButton, GlassPanel, MinimalistToast, SearchMiniIcon, StatusDot, clear_layout, set_placeholder_color


class AtlasMinimalistHomePage(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.bundle = None
        self.setObjectName("AtlasMinimalistHomePage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.home_content = MinimalistHomeContent(controller)
        from .shell import AtlasMinimalistShell

        self.shell = AtlasMinimalistShell(controller, self.home_content)
        layout.addWidget(self.shell)

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle
        self.home_content.set_bundle(bundle)
        self.shell.set_bundle(bundle)

    def refresh(self) -> None:
        self.home_content.set_bundle(self.bundle)
        self.shell.set_bundle(self.bundle)

    def page_shown(self) -> None:
        self.shell.close_overlays()
        self.home_content.set_bundle(self.bundle)
        self.shell.setFocus(Qt.FocusReason.OtherFocusReason)

    def open_search_overlay(self) -> None:
        self.shell.open_search()

    def show_toast(self, message: str) -> None:
        self.home_content.show_toast(message)


class MinimalistHomeContent(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.bundle = None
        self.setObjectName("MinimalistHomeContent")
        self.title_label = QLabel("Home", self)
        self.title_label.setObjectName("MinimalistPageTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_accent = QFrame(self)
        self.title_accent.setObjectName("MinimalistTitleAccent")

        self.card = MinimalistHomeCard(controller, self)
        self.status = MinimalistStatusLine(self)
        self.toast = MinimalistToast(self)
        self.toast.hide()

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle
        self.card.set_bundle(bundle)
        self.status.set_status(loaded_status_text(bundle), ready=bundle is not None)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = self.width()
        height = self.height()
        title_width = min(420, width - 80)
        title_y = max(128, int(height * 0.144))
        self.title_label.setGeometry((width - title_width) // 2, title_y, title_width, 72)
        self.title_accent.setGeometry((width - 94) // 2, title_y + 100, 94, 3)

        card_width = min(940, max(720, width - 360))
        if width < 900:
            card_width = width - 44
        card_height = min(536, max(430, int(height * 0.525)))
        card_y = max(title_y + 130, int(height * 0.286))
        self.card.setGeometry((width - card_width) // 2, card_y, card_width, card_height)

        status_width = min(340, width - 60)
        self.status.setGeometry(width - status_width - 62, height - 88, status_width, 30)
        toast_width = min(720, width - 120)
        self.toast.setGeometry((width - toast_width) // 2, height - 152, toast_width, 72)

    def show_toast(self, message: str) -> None:
        self.toast.show_message(message)

    def focus_search_text(self, text: str) -> None:
        self.card.focus_search_text(text)


class MinimalistHomeCard(GlassPanel):
    def __init__(self, controller, parent=None):
        super().__init__(parent, radius=20, streaks=True)
        self.controller = controller
        self.bundle = None
        self.setObjectName("MinimalistHomeCard")
        self.set_glass(alpha=138, border_alpha=78)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 16)
        shadow.setColor(QColor(0, 34, 92, 118))
        self.setGraphicsEffect(shadow)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(50, 52, 48, 44)
        self.root_layout.setSpacing(0)

        self.heading = QLabel("Get Started")
        self.heading.setObjectName("MinimalistCardHeading")
        self.subtitle = QLabel("Find the right EOAT for your application")
        self.subtitle.setObjectName("MinimalistCardSubtitle")

        self.search_bar = MinimalistHomeSearchBar()
        self.search_bar.input.setPlaceholderText(
            "Enter Tool #, Mold #, Part #, Machine #, or describe what you need..."
        )
        self.search_bar.input.returnPressed.connect(self._run_query_from_enter)
        self.search_bar.submit.clicked.connect(self._run_query)

        self.recent_label = QLabel("Recent Searches")
        self.recent_label.setObjectName("MinimalistRecentLabel")
        self.empty_recent = QLabel("No recent searches yet")
        self.empty_recent.setObjectName("MinimalistRecentEmpty")
        self.empty_recent.hide()
        self.pill_container = QWidget()
        self.pill_container.setObjectName("MinimalistPillContainer")
        self.pill_layout = QHBoxLayout(self.pill_container)
        self.pill_layout.setContentsMargins(0, 0, 0, 0)
        self.pill_layout.setSpacing(26)

        self.root_layout.addWidget(self.heading)
        self.root_layout.addSpacing(18)
        self.root_layout.addWidget(self.subtitle)
        self.root_layout.addSpacing(60)
        self.root_layout.addWidget(self.search_bar)
        self.root_layout.addSpacing(69)
        self.root_layout.addWidget(self.recent_label)
        self.root_layout.addSpacing(26)
        self.root_layout.addWidget(self.empty_recent)
        self.root_layout.addWidget(self.pill_container)
        self.root_layout.addStretch(1)
        self._render_pills()

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle
        self._render_pills()

    def refresh_recent_searches(self) -> None:
        self._render_pills()

    def _run_query(self) -> None:
        query = self.search_bar.input.text().strip()
        if query:
            self.controller.open_recommendation(query)
        else:
            self.controller.show_status("Enter a tool, mold, part, machine, EOAT, or description to search.")

    def _run_query_from_enter(self) -> None:
        self.search_bar.submit.play_bounce()
        self._run_query()

    def focus_search_text(self, text: str) -> None:
        self.search_bar.input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_bar.set_query_text(text)

    def _render_pills(self) -> None:
        clear_layout(self.pill_layout)
        entries = recent_entries(self.controller, self.bundle, limit=5)
        self.empty_recent.setVisible(not entries)
        self.pill_container.setVisible(bool(entries))
        for entry in entries:
            pill = QPushButton(entry.label)
            pill.setObjectName("MinimalistPill")
            pill.setCursor(Qt.CursorShape.PointingHandCursor)
            pill.setToolTip(entry.kind if entry.kind and entry.kind != "Search" else "Recent search")
            pill.clicked.connect(lambda _checked=False, entry=entry: self._run_entry(entry))
            self.pill_layout.addWidget(pill)
        self.pill_layout.addStretch(1)

    def _run_entry(self, entry: MinimalistSearchEntry) -> None:
        self.search_bar.input.setText(entry.query)
        if entry.opener is not None:
            entry.opener()
            return
        self._run_query()


class MinimalistHomeSearchBar(GlassPanel):
    def __init__(self, parent=None):
        super().__init__(parent, radius=13)
        self.setObjectName("MinimalistHomeSearchFrame")
        self.setFixedHeight(96)
        self._focused = False
        self.set_glass(alpha=112, border_alpha=88, border_color=QColor("#8ab9ff"), fill_color=QColor("#050e1d"))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(34, 0, 4, 0)
        layout.setSpacing(16)
        self.input = QLineEdit()
        self.input.setObjectName("MinimalistHomeSearchInput")
        self.input.setClearButtonEnabled(True)
        self.input.installEventFilter(self)
        set_placeholder_color(self.input, QColor("#c2ccda"))
        self.submit = ArrowButton()
        self.submit.setAccessibleName("Search EOAT Atlas")
        layout.addWidget(self.input, 1)
        layout.addWidget(self.submit)

    def set_query_text(self, text: str) -> None:
        self.input.setText(text)
        self.input.setCursorPosition(len(text))

    def eventFilter(self, watched, event) -> bool:
        if watched is self.input:
            if event.type() == QEvent.Type.FocusIn:
                self._set_focus_active(True)
            elif event.type() == QEvent.Type.FocusOut:
                self._set_focus_active(False)
        return super().eventFilter(watched, event)

    def _set_focus_active(self, focused: bool) -> None:
        if self._focused == focused:
            return
        self._focused = focused
        if focused:
            self.set_glass(
                alpha=132,
                border_alpha=178,
                border_color=QColor("#4e9cff"),
                fill_color=QColor("#07172f"),
                outer_glow_alpha=62,
            )
            set_placeholder_color(self.input, QColor("#d6e3f4"))
            return
        self.set_glass(alpha=112, border_alpha=88, border_color=QColor("#8ab9ff"), fill_color=QColor("#050e1d"), outer_glow_alpha=0)
        set_placeholder_color(self.input, QColor("#c2ccda"))


class MinimalistPanelSearchBox(GlassPanel):
    def __init__(self, parent=None):
        super().__init__(parent, radius=7)
        self.setObjectName("MinimalistPanelSearchBox")
        self.setFixedHeight(48)
        self.set_glass(alpha=70, border_alpha=140, border_color=QColor("#1f87ff"))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 10, 0)
        layout.setSpacing(10)
        icon = SearchMiniIcon()
        self.input = QLineEdit()
        self.input.setObjectName("MinimalistPanelSearchInput")
        set_placeholder_color(self.input, QColor("#aebbd0"))
        layout.addWidget(icon)
        layout.addWidget(self.input, 1)


class MinimalistStatusLine(QWidget):
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


__all__ = ["AtlasMinimalistHomePage", "MinimalistHomeContent", "MinimalistPanelSearchBox"]
