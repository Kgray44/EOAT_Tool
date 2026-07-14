from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..command_palette import ITEM_ENTITY_SEARCH, AtlasCommand, resolve_atlas_commands
from .entity_search import EntitySearchDropdown
from .data import MinimalistSearchEntry, loaded_status_text, recent_entries
from .theme import active_minimalist_tokens, apply_glass_theme, effective_minimalist_theme
from .widgets import (
    ArrowButton,
    GlassPanel,
    MinimalistToast,
    SearchMiniIcon,
    StatusDot,
    TitleAccentBar,
    clear_layout,
    set_placeholder_color,
)


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
        self.shell.close_overlays(immediate=True)
        self.home_content.close_search_overlays()
        self.shell.top_bar.set_back_visible(False, animated=False)
        self.home_content.set_bundle(self.bundle)
        self.shell.setFocus(Qt.FocusReason.OtherFocusReason)

    def open_search_overlay(self) -> None:
        self.home_content.close_search_overlays()
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

        self.title_accent = TitleAccentBar(self)
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
        self.title_label.setGeometry((width - title_width) // 2, title_y, title_width, 56)
        self.title_accent.setGeometry((width - 78) // 2, title_y + 74, 78, 9)

        card_width = min(940, max(720, width - 360))
        if width < 900:
            card_width = width - 44
        card_height = min(536, max(430, int(height * 0.525)))
        card_y = max(title_y + 112, int(height * 0.286))
        self.card.setGeometry((width - card_width) // 2, card_y, card_width, card_height)

        status_width = min(340, width - 60)
        self.status.setGeometry(width - status_width - 62, height - 88, status_width, 30)
        toast_width = min(720, width - 120)
        self.toast.setGeometry((width - toast_width) // 2, height - 152, toast_width, 72)

    def show_toast(self, message: str) -> None:
        self.toast.show_message(message)

    def focus_search_text(self, text: str) -> None:
        self.card.focus_search_text(text)

    def close_search_overlays(self) -> None:
        self.card.close_search_dropdown()


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
        self.subtitle = QLabel("Find the right EOAT for you application")
        self.subtitle.setObjectName("MinimalistCardSubtitle")

        self.search_bar = MinimalistHomeSearchBar()
        self.search_bar.input.setPlaceholderText(
            "Enter Tool #, Mold #, Machine #, or EOAT ID..."
        )
        self.search_bar.input.installEventFilter(self)
        self.search_bar.input.textChanged.connect(self._schedule_search_refresh)
        self.search_bar.input.returnPressed.connect(self._run_selected_lookup)
        self.search_bar.submit.clicked.connect(self._run_query)
        self.lookup_dropdown = EntitySearchDropdown(self, compact=False)
        self.lookup_dropdown.result_clicked.connect(self._open_search_result)
        self.lookup_dropdown.recent_clicked.connect(self._run_entry)
        self.lookup_dropdown.hide()
        self._search_refresh_timer = QTimer(self)
        self._search_refresh_timer.setSingleShot(True)
        self._search_refresh_timer.setInterval(125)
        self._search_refresh_timer.timeout.connect(self._refresh_search_results)
        self._current_query_result = None
        self._current_query_text = ""

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
        self.root_layout.addSpacing(54)
        self.root_layout.addWidget(self.recent_label)
        self.root_layout.addSpacing(26)
        self.root_layout.addWidget(self.empty_recent)
        self.root_layout.addWidget(self.pill_container)
        self.root_layout.addStretch(1)
        self._render_pills()

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle
        self._render_pills()
        if self.lookup_dropdown.isVisible():
            self._refresh_search_results()

    def refresh_recent_searches(self) -> None:
        self._render_pills()
        if self.lookup_dropdown.isVisible() and not self.search_bar.input.text().strip():
            self._refresh_search_results()

    def _run_query(self) -> None:
        query = self.search_bar.input.text().strip()
        if not query:
            self._show_recent_dropdown()
            return
        if self._current_query_result is None or self._current_query_text != query:
            self._refresh_search_results()
        exact = getattr(self._current_query_result, "top_exact_match", None)
        if exact is not None:
            self._open_search_result(exact)
            return
        if self.lookup_dropdown.isVisible() and self.lookup_dropdown.run_current():
            return
        self.controller.show_status("No matching Library profile found.")

    def _run_selected_lookup(self) -> None:
        self.search_bar.submit.play_bounce()
        self._run_query()

    def focus_search_text(self, text: str) -> None:
        self.search_bar.input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_bar.set_query_text(text)
        self._schedule_search_refresh(text, immediate=True)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.search_bar.input and event.type() == QEvent.Type.KeyPress and self.lookup_dropdown.isVisible():
            if event.key() == Qt.Key.Key_Down:
                self.lookup_dropdown.move_highlight(1)
                return True
            if event.key() == Qt.Key.Key_Up:
                self.lookup_dropdown.move_highlight(-1)
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.close_search_dropdown()
                return True
        if watched is self.search_bar.input and event.type() in {QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress}:
            self._schedule_search_refresh(self.search_bar.input.text(), immediate=True)
        if watched is self.search_bar.input and event.type() == QEvent.Type.FocusOut:
            QTimer.singleShot(0, self._hide_dropdown_if_focus_left)
        return super().eventFilter(watched, event)

    def _schedule_search_refresh(self, _text: str = "", *, immediate: bool = False) -> None:
        if immediate:
            self._search_refresh_timer.stop()
            self._refresh_search_results()
            return
        self._search_refresh_timer.start()

    def _refresh_search_results(self) -> None:
        query = self.search_bar.input.text().strip()
        if not self._home_route_active() or not self.search_bar.input.hasFocus():
            self.close_search_dropdown()
            return
        if not query:
            self._show_recent_dropdown()
            return
        searcher = getattr(self.controller, "search_entities", None)
        result = searcher(query, limit=24) if callable(searcher) else None
        self._current_query_result = result
        self._current_query_text = query
        rows = list(getattr(result, "results", ()) or ())
        self.lookup_dropdown.set_results(query, rows)
        self._position_dropdown()
        self.lookup_dropdown.show()
        self.lookup_dropdown.raise_()

    def _show_recent_dropdown(self) -> None:
        self._current_query_result = None
        self._current_query_text = ""
        entries = recent_entries(self.controller, self.bundle, limit=8)
        self.lookup_dropdown.set_recent_entries(entries)
        self._position_dropdown()
        self.lookup_dropdown.show()
        self.lookup_dropdown.raise_()

    def _open_search_result(self, result) -> None:
        query = self.search_bar.input.text().strip()
        self.close_search_dropdown()
        navigator = getattr(self.controller, "navigate_to_entity", None)
        if callable(navigator):
            navigator(result.entity_type, result.entity_id, source="home-search", raw_query=query or result.entity_id)
            return
        fallback = getattr(self.controller, "navigate_to_profile", None)
        if callable(fallback):
            fallback(result, source="home-search", raw_query=query or result.entity_id)

    def close_search_dropdown(self) -> None:
        self._search_refresh_timer.stop()
        self.lookup_dropdown.reset_highlight()
        self.lookup_dropdown.hide()

    def _lookup_commands(self, query: str) -> list[AtlasCommand]:
        return [
            command
            for command in resolve_atlas_commands(self.controller, query, limit=12)
            if command.category == "Records" and command.command_id.split(".", 1)[0] in {"eoat", "machine", "tool"}
        ][:6]

    def _home_route_active(self) -> bool:
        return getattr(self.controller, "current_page_key", "minimalist_home") in {"home", "minimalist_home"}

    def _hide_dropdown_if_focus_left(self) -> None:
        focus = QApplication.focusWidget()
        widget = focus
        while widget is not None:
            if widget in {self.search_bar.input, self.lookup_dropdown}:
                return
            widget = widget.parentWidget() if hasattr(widget, "parentWidget") else None
        self.close_search_dropdown()

    def _position_dropdown(self) -> None:
        if self.search_bar.width() <= 0:
            return
        x = self.search_bar.x()
        y = self.search_bar.y() + self.search_bar.height() + 8
        width = self.search_bar.width()
        height = min(self.lookup_dropdown.preferred_height(), max(80, self.height() - y - 20))
        self.lookup_dropdown.setGeometry(x, y, width, height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.lookup_dropdown.isVisible():
            self._position_dropdown()

    def mousePressEvent(self, event) -> None:
        position = event.position().toPoint()
        if not self.search_bar.geometry().contains(position) and not self.lookup_dropdown.geometry().contains(position):
            self.close_search_dropdown()
        super().mousePressEvent(event)

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
        self.close_search_dropdown()
        if entry.opener is not None:
            entry.opener()
            return
        self.search_bar.input.setText(entry.query)
        self._run_query()


class MinimalistHomeSearchBar(GlassPanel):
    def __init__(self, parent=None):
        super().__init__(parent, radius=13)
        self.setObjectName("MinimalistHomeSearchFrame")
        self.setFixedHeight(96)
        self._focused = False
        apply_glass_theme(self, "search_box")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(34, 0, 4, 0)
        layout.setSpacing(16)
        self.input = QLineEdit()
        self.input.setObjectName("MinimalistHomeSearchInput")
        self.input.setClearButtonEnabled(True)
        self.input.installEventFilter(self)
        set_placeholder_color(self.input, QColor(active_minimalist_tokens().text_muted))
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
        tokens = active_minimalist_tokens()
        light = effective_minimalist_theme() == "light"
        if focused:
            self.set_glass(
                alpha=252 if light else 132,
                border_alpha=220 if light else 178,
                border_color=QColor(tokens.accent),
                fill_color=QColor(tokens.input_background if light else "#07172f"),
                outer_glow_alpha=8 if light else 62,
            )
            set_placeholder_color(self.input, QColor(tokens.text_muted))
            return
        self.apply_theme_preference(None)

    def apply_theme_preference(self, _preference: str | None) -> None:
        tokens = active_minimalist_tokens()
        light = effective_minimalist_theme() == "light"
        apply_glass_theme(self, "search_box")
        set_placeholder_color(self.input, QColor(tokens.text_muted))


class HomeLookupDropdown(GlassPanel):
    result_clicked = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent, radius=10)
        self.commands: list[AtlasCommand] = []
        self.rows: list[HomeLookupRow] = []
        self.highlight_index = 0
        apply_glass_theme(self, "search_overlay")
        self.setMinimumHeight(54)
        self.setMaximumHeight(276)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(6)

    def apply_theme_preference(self, preference: str | None) -> None:
        apply_glass_theme(self, "search_overlay", preference)

    def set_results(self, commands: list[AtlasCommand], *, query: str) -> None:
        clear_layout(self.layout)
        self.commands = list(commands)
        self.rows = []
        self.highlight_index = 0
        if not commands:
            empty = QLabel("No matching records")
            empty.setObjectName("MinimalistPanelEmpty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(42)
            self.layout.addWidget(empty)
            self.setFixedHeight(58)
            return
        for index, command in enumerate(commands):
            row = HomeLookupRow(command)
            row.set_highlighted(index == self.highlight_index)
            row.clicked.connect(lambda _checked=False, command=command: self.result_clicked.emit(command))
            self.rows.append(row)
            self.layout.addWidget(row)
        self.setFixedHeight(min(276, 16 + len(commands) * 54))

    def move_highlight(self, delta: int) -> None:
        if not self.rows:
            return
        self.highlight_index = (self.highlight_index + delta) % len(self.rows)
        for index, row in enumerate(self.rows):
            row.set_highlighted(index == self.highlight_index)

    def run_current(self) -> bool:
        if not self.commands:
            return False
        index = max(0, min(self.highlight_index, len(self.commands) - 1))
        self.result_clicked.emit(self.commands[index])
        return True


class HomeLookupRow(QPushButton):
    def __init__(self, command: AtlasCommand, parent=None):
        super().__init__(parent)
        self.command = command
        self.setObjectName("MinimalistSearchRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setMinimumHeight(54)
        self._highlighted = False
        self.title = QLabel(command.title.replace("Open ", "", 1), self)
        self.title.setObjectName("MinimalistRowTitle")
        self.kind = QLabel(_home_command_kind(command), self)
        self.kind.setObjectName("MinimalistRowKind")
        self.kind.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.subtitle = QLabel(command.subtitle or command.result_text, self)
        self.subtitle.setObjectName("MinimalistRowSubtitle")

    def set_highlighted(self, highlighted: bool) -> None:
        self._highlighted = bool(highlighted)
        self.setProperty("active", self._highlighted)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        kind_width = 92
        self.title.setGeometry(42, 7, self.width() - kind_width - 52, 22)
        self.kind.setGeometry(self.width() - kind_width, 8, kind_width - 4, 22)
        self.subtitle.setGeometry(42, 30, self.width() - 56, 18)

    def paintEvent(self, event) -> None:
        if self._highlighted:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            tokens = active_minimalist_tokens()
            color = QColor(tokens.accent_soft if effective_minimalist_theme() == "light" else "#145cb2")
            color.setAlpha(220 if effective_minimalist_theme() == "light" else 120)
            painter.setBrush(color)
            painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)
            painter.end()
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QColor(active_minimalist_tokens().text_secondary))
        painter.drawEllipse(12, 19, 14, 14)


def _home_command_kind(command: AtlasCommand) -> str:
    command_id = command.command_id.split(".", 1)[0]
    return {"eoat": "EOAT", "machine": "Machine", "tool": "Tool"}.get(command_id, "Record")


class MinimalistPanelSearchBox(GlassPanel):
    def __init__(self, parent=None):
        super().__init__(parent, radius=7)
        self.setObjectName("MinimalistPanelSearchBox")
        self.setFixedHeight(48)
        apply_glass_theme(self, "search_box")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 10, 0)
        layout.setSpacing(10)
        icon = SearchMiniIcon()
        self.input = QLineEdit()
        self.input.setObjectName("MinimalistPanelSearchInput")
        set_placeholder_color(self.input, QColor(active_minimalist_tokens().text_muted))
        layout.addWidget(icon)
        layout.addWidget(self.input, 1)

    def apply_theme_preference(self, _preference: str | None) -> None:
        apply_glass_theme(self, "search_box")
        set_placeholder_color(self.input, QColor(active_minimalist_tokens().text_muted))


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
