from __future__ import annotations

import math

from PySide6.QtCore import Property, QEasingCurve, QPointF, QRectF, QSize, Qt, QPropertyAnimation, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..command_palette import AtlasCommand, resolve_atlas_commands
from .data import MinimalistSearchEntry, recent_entries
from .home import MinimalistPanelSearchBox
from .widgets import ACCENT_BRIGHT, AnimatedGlassPanel, CloseIconButton, clear_layout, glyph_icon, prefers_reduced_motion


class MinimalistMenuOverlay(AnimatedGlassPanel):
    close_requested = Signal()
    navigate_requested = Signal(str)

    def __init__(self, controller, parent=None):
        super().__init__(parent, radius=10)
        self.controller = controller
        self.setObjectName("MinimalistMenuOverlay")
        self.set_glass(
            alpha=232,
            border_alpha=184,
            border_color=QColor("#8cc4ff"),
            fill_color=QColor("#020b1b"),
            outer_glow_alpha=82,
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 18, 16, 22)
        layout.setSpacing(8)
        close = CloseIconButton()
        close.setAccessibleName("Close navigation menu")
        close.clicked.connect(self.close_requested.emit)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignLeft)
        self.active_key = "minimalist_home"
        self.buttons_by_key: dict[str, QPushButton] = {}

        items = [
            ("home", "Home", "home", "minimalist_home", "#f6fbff"),
            ("doc", "Changeover Builder", "doc", "setup_packet", "#b9d7ff"),
            ("library", "Library", "library", "library", "#00c9ff"),
            ("compatibility", "Compatibility", "grid", "matrix", "#00d6ff"),
            ("photos", "Photos", "image", "photos", "#00bfff"),
            ("standards", "Standards & WI", "book", "standards", "#bcd7ff"),
            ("reports", "Reports", "report", "reports", "#a855ff"),
            ("settings", "Settings & Diagnostics", "gear", "diagnostics", "#cce7ff"),
        ]
        for item_id, label, glyph, key, color in items:
            if item_id == "divider":
                line = QFrame()
                line.setObjectName("MinimalistDivider")
                layout.addWidget(line)
                continue
            button = MinimalistMenuButton(label, glyph, QColor(color))
            button.set_active_visual(key == self.active_key)
            button.clicked.connect(lambda _checked=False, key=key: self._select_nav(key))
            self.buttons_by_key[key] = button
            layout.addWidget(button)
        layout.addStretch(1)

    def set_active_key(self, key: str) -> None:
        normalized = "minimalist_home" if key in {"home", "minimalist_home"} else str(key or "")
        self.active_key = normalized
        for item_key, button in self.buttons_by_key.items():
            is_active = item_key == normalized
            button.set_active_visual(is_active)

    def _select_nav(self, key: str) -> None:
        self.set_active_key(key)
        self.navigate_requested.emit(key)


class MinimalistMenuButton(QPushButton):
    def __init__(self, label: str, glyph: str, icon_color: QColor, parent=None):
        super().__init__(label.replace("&", "&&"), parent)
        self.setObjectName("MinimalistMenuItem")
        self.setCheckable(False)
        self.setProperty("active", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._raw_label = label
        self._icon = glyph_icon(glyph, icon_color, 28)
        self._active_icon = glyph_icon(glyph, QColor("#f6fbff"), 28)
        self._icon_size = QSize(24, 24)
        self.setIcon(self._icon)
        self.setIconSize(self._icon_size)
        self._reduced_motion = prefers_reduced_motion()
        self._glow_phase = 0.0
        self._glow_animation = QPropertyAnimation(self, b"glowPhase", self)
        self._glow_animation.setDuration(6800)
        self._glow_animation.setStartValue(0.0)
        self._glow_animation.setEndValue(1.0)
        self._glow_animation.setLoopCount(-1)
        self._glow_animation.setEasingCurve(QEasingCurve.Type.InOutSine)

    def get_glow_phase(self) -> float:
        return self._glow_phase

    def set_glow_phase(self, value: float) -> None:
        self._glow_phase = float(value)
        if self.property("active"):
            self.update()

    glowPhase = Property(float, get_glow_phase, set_glow_phase)

    def set_active_visual(self, active: bool) -> None:
        active = bool(active)
        if self.property("active") == active:
            self._sync_glow_animation()
            return
        self.setProperty("active", active)
        self.setIcon(self._active_icon if active else self._icon)
        self.style().unpolish(self)
        self.style().polish(self)
        self._sync_glow_animation()
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_glow_animation()

    def hideEvent(self, event) -> None:
        self._glow_animation.stop()
        super().hideEvent(event)

    def _sync_glow_animation(self) -> None:
        if not self.property("active") or self._reduced_motion or not self.isVisible():
            self._glow_animation.stop()
            if not self.property("active"):
                self.set_glow_phase(0.0)
            return
        if self._glow_animation.state() != QPropertyAnimation.State.Running:
            self._glow_animation.start()

    def paintEvent(self, event) -> None:
        if not self.property("active"):
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        radius = 9.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        phase = self._glow_phase
        wave = 0.5 + 0.5 * math.sin(phase * math.tau)
        breathe = 0.5 + 0.5 * math.sin((phase * math.tau) + 1.25)
        hover_boost = 12 if self.underMouse() else 0

        painter.save()
        painter.setClipPath(path)
        fill = QLinearGradient(rect.topLeft(), rect.topRight())
        fill.setColorAt(0.0, QColor(19, 82, 218, 178 + hover_boost))
        fill.setColorAt(0.36, QColor(18, 60, 142, 118 + hover_boost // 2))
        fill.setColorAt(1.0, QColor(11, 31, 76, 78))
        painter.fillPath(path, fill)

        left_glow = QRadialGradient(
            rect.left() + rect.width() * (0.11 + 0.05 * wave),
            rect.top() + rect.height() * (0.36 + 0.06 * math.cos(phase * math.tau)),
            rect.height() * 0.95,
        )
        left_glow.setColorAt(0.0, QColor(52, 151, 255, 118 + int(18 * breathe)))
        left_glow.setColorAt(0.33, QColor(33, 126, 255, 52))
        left_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, left_glow)

        sheen_x = rect.left() + rect.width() * (0.18 + 0.24 * wave)
        sheen = QLinearGradient(sheen_x - rect.width() * 0.12, rect.top(), sheen_x + rect.width() * 0.34, rect.bottom())
        sheen.setColorAt(0.0, QColor(0, 0, 0, 0))
        sheen.setColorAt(0.48, QColor(76, 168, 255, 22 + int(10 * breathe)))
        sheen.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillPath(path, sheen)

        inner_edge = QLinearGradient(rect.topLeft(), rect.topRight())
        inner_edge.setColorAt(0.0, QColor(51, 152, 255, 54 + int(14 * breathe)))
        inner_edge.setColorAt(0.22, QColor(40, 134, 255, 22))
        inner_edge.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillPath(path, inner_edge)
        painter.restore()

        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        painter.setClipPath(path)
        corner_bloom = QRadialGradient(
            rect.left() + rect.width() * (0.13 + 0.03 * wave),
            rect.top() + rect.height() * (0.24 + 0.05 * breathe),
            rect.width() * 0.48,
        )
        corner_bloom.setColorAt(0.0, QColor(38, 138, 255, 46 + int(10 * breathe)))
        corner_bloom.setColorAt(0.32, QColor(34, 124, 255, 20))
        corner_bloom.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, corner_bloom)

        side_bloom = QRadialGradient(
            rect.left() + 10,
            rect.center().y() + rect.height() * (0.08 * math.sin(phase * math.tau)),
            rect.height() * 0.90,
        )
        side_bloom.setColorAt(0.0, QColor(41, 135, 255, 28 + int(8 * breathe)))
        side_bloom.setColorAt(0.46, QColor(24, 102, 220, 14))
        side_bloom.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, side_bloom)
        painter.restore()

        border = QPen(QColor(52, 135, 255, 64), 0.85)
        border.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(border)
        painter.drawPath(path)

        icon_center = QPointF(rect.left() + 24, rect.center().y())
        icon_glow = QRadialGradient(icon_center, 34)
        icon_glow.setColorAt(0.0, QColor(71, 166, 255, 90 + int(30 * breathe)))
        icon_glow.setColorAt(0.36, QColor(31, 128, 255, 34))
        icon_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, icon_glow)

        pixmap: QPixmap = self._active_icon.pixmap(self._icon_size)
        icon_x = int(rect.left() + 12)
        icon_y = int(rect.center().y() - self._icon_size.height() / 2)
        painter.setOpacity(0.36 + 0.12 * breathe)
        painter.drawPixmap(icon_x - 1, icon_y, pixmap)
        painter.drawPixmap(icon_x + 1, icon_y, pixmap)
        painter.setOpacity(1.0)
        painter.drawPixmap(icon_x, icon_y, pixmap)

        font = self.font()
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#fbfdff"))
        text_rect = QRectF(rect.left() + 52, rect.top(), rect.width() - 64, rect.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._raw_label)


class MinimalistSearchOverlay(AnimatedGlassPanel):
    close_requested = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent, radius=18)
        self.controller = controller
        self.bundle = None
        self._current_commands: list[AtlasCommand] = []
        self.setObjectName("MinimalistSearchOverlay")
        self.set_glass(
            alpha=232,
            border_alpha=182,
            border_color=QColor("#8cc4ff"),
            fill_color=QColor("#020b1b"),
            outer_glow_alpha=78,
        )

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(20, 24, 18, 0)
        self.root_layout.setSpacing(0)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 0, 0, 0)
        header_layout.setSpacing(8)
        title = QLabel("Search EOAT Atlas")
        title.setObjectName("MinimalistPanelTitle")
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        close = CloseIconButton(size=32)
        close.setAccessibleName("Close search")
        close.clicked.connect(self.close_requested.emit)
        header_layout.addWidget(close)
        self.root_layout.addWidget(header)
        self.root_layout.addSpacing(18)

        self.search_box = MinimalistPanelSearchBox()
        self.search_box.input.setPlaceholderText("Search machines, EOATs, tools, parts, documents...")
        self.search_box.input.textChanged.connect(self.refresh_results)
        self.search_box.input.returnPressed.connect(self.run_first_result)
        self.root_layout.addWidget(self.search_box)
        self.root_layout.addSpacing(18)

        self.results_host = QWidget()
        self.results_layout = QVBoxLayout(self.results_host)
        self.results_layout.setContentsMargins(4, 0, 4, 0)
        self.results_layout.setSpacing(9)
        self.root_layout.addWidget(self.results_host, 1)

        footer = QWidget()
        footer.setObjectName("MinimalistSearchFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.addStretch(1)
        shortcut = QLabel("Press  Ctrl K  anytime to search")
        shortcut.setObjectName("MinimalistFooterText")
        footer_layout.addWidget(shortcut)
        footer_layout.addStretch(1)
        self.root_layout.addWidget(footer)
        self.refresh_results()

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle
        self.refresh_results()

    def focus_search(self, *, select_all: bool = True) -> None:
        self.search_box.input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        if select_all:
            self.search_box.input.selectAll()
        else:
            self.search_box.input.setCursorPosition(len(self.search_box.input.text()))

    def set_search_text(self, text: str) -> None:
        self.search_box.input.setText(text)
        self.search_box.input.setCursorPosition(len(text))

    def refresh_results(self) -> None:
        query = self.search_box.input.text().strip()
        clear_layout(self.results_layout)
        self._current_commands = []
        if query:
            commands = resolve_atlas_commands(self.controller, query, limit=8)
            self._current_commands = commands
            self._add_section("Results")
            if commands:
                for command in commands:
                    row = SearchResultRow(command.title, command.category, command.subtitle or command.result_text)
                    row.clicked.connect(lambda command=command: self._run_command(command))
                    self.results_layout.addWidget(row)
            else:
                self.results_layout.addWidget(PanelEmptyRow("No command results found."))
            self.results_layout.addStretch(1)
            return

        recent = recent_entries(self.controller, self.bundle, limit=5)
        self._add_section("Recent Searches")
        if recent:
            for entry in recent:
                row = SearchResultRow(entry.label, entry.kind, "", compact=True)
                row.clicked.connect(lambda entry=entry: self._run_entry(entry))
                self.results_layout.addWidget(row)
        else:
            self.results_layout.addWidget(PanelEmptyRow("No recent searches yet."))

        self.results_layout.addSpacing(24)
        self._add_section("Suggestions")
        for label, key, glyph in (
            ("Changeover Builder", "setup_packet", "doc"),
            ("Library", "library", "library"),
            ("Compatibility Table", "matrix", "grid"),
            ("Photos", "photos", "image"),
            ("Standards & WI", "standards", "book"),
        ):
            row = SearchSuggestionRow(label, glyph)
            row.clicked.connect(lambda key=key: self._navigate(key))
            self.results_layout.addWidget(row)
        self.results_layout.addStretch(1)

    def run_first_result(self) -> None:
        if self._current_commands:
            self._run_command(self._current_commands[0])
            return
        query = self.search_box.input.text().strip()
        if query:
            self._run_search_text(query)

    def _add_section(self, title: str) -> None:
        label = QLabel(title)
        label.setObjectName("MinimalistSectionLabel")
        self.results_layout.addWidget(label)

    def _run_entry(self, entry: MinimalistSearchEntry) -> None:
        self._close_then_run(lambda entry=entry: self._open_entry(entry))

    def _open_entry(self, entry: MinimalistSearchEntry) -> None:
        if entry.opener is not None:
            entry.opener()
        else:
            self.controller.open_recommendation(entry.query)

    def _run_command(self, command: AtlasCommand) -> None:
        query = self.search_box.input.text().strip()
        if query:
            self._record_query(query, command.category)
        self._close_then_run(command.handler)

    def _navigate(self, key: str) -> None:
        self._close_then_run(lambda key=key: self.controller.show_page(key))

    def _run_search_text(self, query: str) -> None:
        self._close_then_run(lambda query=query: self.controller.open_recommendation(query))

    def _close_then_run(self, callback) -> None:
        self.close_requested.emit()
        QTimer.singleShot(260, callback)

    def _record_query(self, query: str, kind: str = "") -> None:
        recorder = getattr(self.controller, "record_minimalist_search", None)
        if callable(recorder):
            concrete_kind = kind if kind in {"Machine", "Tool / Mold", "Part", "EOAT"} else ""
            recorder(query, kind=concrete_kind)


class SearchResultRow(QPushButton):
    clicked = Signal()

    def __init__(self, title: str, kind: str, subtitle: str = "", *, compact: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("MinimalistSearchRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setMinimumHeight(38 if compact else 48)
        self._title = QLabel(title, self)
        self._title.setObjectName("MinimalistRowTitle")
        self._kind = QLabel(kind, self)
        self._kind.setObjectName("MinimalistRowKind")
        self._subtitle = QLabel(subtitle, self)
        self._subtitle.setObjectName("MinimalistRowSubtitle")
        self._subtitle.setVisible(bool(subtitle and not compact))
        super().clicked.connect(self.clicked.emit)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        kind_width = 104
        self._title.setGeometry(38, 3, self.width() - kind_width - 48, 23)
        self._kind.setGeometry(self.width() - kind_width, 4, kind_width - 4, 22)
        self._subtitle.setGeometry(38, 24, self.width() - 60, 18)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#cfe4ff"), 1.25))
        painter.drawEllipse(6, 11, 16, 16)
        painter.drawLine(14, 14, 14, 20)
        painter.drawLine(14, 20, 9, 20)
        super().paintEvent(event)


class SearchSuggestionRow(QPushButton):
    clicked = Signal()

    def __init__(self, title: str, glyph: str, parent=None):
        super().__init__(title.replace("&", "&&"), parent)
        self.setObjectName("MinimalistSuggestionRow")
        self.setIcon(glyph_icon(glyph, ACCENT_BRIGHT, 22))
        self.setIconSize(QSize(22, 22))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(42)
        super().clicked.connect(self.clicked.emit)


class PanelEmptyRow(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("MinimalistPanelEmpty")
        self.setWordWrap(True)
        self.setMinimumHeight(34)


__all__ = ["MinimalistMenuOverlay", "MinimalistSearchOverlay"]
