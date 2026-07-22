from __future__ import annotations

import logging
import math

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..command_palette import (
    ITEM_ENTITY_SEARCH,
    ITEM_NAVIGATION,
    ITEM_RECENT_SEARCH,
    VALID_PALETTE_ITEM_TYPES,
    AtlasCommand,
    _log_palette_selection,
    resolve_atlas_commands,
)
from .data import MinimalistSearchEntry, recent_entries
from .entity_search import EntitySearchDropdown
from .home import MinimalistPanelSearchBox
from .theme import active_minimalist_tokens, apply_glass_theme, effective_minimalist_theme
from .widgets import (
    AnimatedGlassPanel,
    CloseIconButton,
    clear_layout,
    glyph_icon,
    prefers_reduced_motion,
)

LOGGER = logging.getLogger(__name__)


class MinimalistMenuOverlay(AnimatedGlassPanel):
    close_requested = Signal()
    navigate_requested = Signal(str)

    def __init__(self, controller, parent=None):
        super().__init__(parent, radius=10)
        self.controller = controller
        self.setObjectName("MinimalistMenuOverlay")
        apply_glass_theme(self, "overlay")
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
            ("fit_check", "Fit Check", "status", "fit_check", "#00d6ff"),
            ("library", "Library", "library", "library", "#00c9ff"),
            ("settings", "Settings", "gear", "settings", "#cce7ff"),
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

    def apply_theme_preference(self, preference: str | None) -> None:
        apply_glass_theme(self, "overlay", preference)
        for button in self.buttons_by_key.values():
            button.apply_theme_preference(preference)

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
        self._glyph = glyph
        self._base_icon_color = QColor(icon_color)
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
        self.apply_theme_preference(None)

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

    def apply_theme_preference(self, _preference: str | None) -> None:
        tokens = active_minimalist_tokens()
        if effective_minimalist_theme() == "light":
            base_color = QColor(tokens.text_secondary)
            active_color = QColor(tokens.accent_hover)
        else:
            base_color = QColor(self._base_icon_color)
            active_color = QColor("#f6fbff")
        self._icon = glyph_icon(self._glyph, base_color, 28)
        self._active_icon = glyph_icon(self._glyph, active_color, 28)
        self.setIcon(self._active_icon if self.property("active") else self._icon)
        self.style().unpolish(self)
        self.style().polish(self)
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

        tokens = active_minimalist_tokens()
        light = effective_minimalist_theme() == "light"
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
        if light:
            fill.setColorAt(0.0, QColor(tokens.selected_sidebar_background))
            fill.setColorAt(0.55, QColor(tokens.accent_soft))
            fill.setColorAt(1.0, QColor(tokens.card_background_hover))
        else:
            fill.setColorAt(0.0, QColor(19, 82, 218, 178 + hover_boost))
            fill.setColorAt(0.36, QColor(18, 60, 142, 118 + hover_boost // 2))
            fill.setColorAt(1.0, QColor(11, 31, 76, 78))
        painter.fillPath(path, fill)

        left_glow = QRadialGradient(
            rect.left() + rect.width() * (0.11 + 0.05 * wave),
            rect.top() + rect.height() * (0.36 + 0.06 * math.cos(phase * math.tau)),
            rect.height() * 0.95,
        )
        accent = QColor(tokens.accent)
        left_glow.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), (30 if light else 118) + int(18 * breathe)))
        left_glow.setColorAt(0.33, QColor(accent.red(), accent.green(), accent.blue(), 24 if light else 52))
        left_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, left_glow)

        sheen_x = rect.left() + rect.width() * (0.18 + 0.24 * wave)
        sheen = QLinearGradient(sheen_x - rect.width() * 0.12, rect.top(), sheen_x + rect.width() * 0.34, rect.bottom())
        sheen.setColorAt(0.0, QColor(0, 0, 0, 0))
        sheen.setColorAt(0.48, QColor(accent.red(), accent.green(), accent.blue(), (12 if light else 22) + int(10 * breathe)))
        sheen.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillPath(path, sheen)

        inner_edge = QLinearGradient(rect.topLeft(), rect.topRight())
        inner_edge.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), (28 if light else 54) + int(14 * breathe)))
        inner_edge.setColorAt(0.22, QColor(accent.red(), accent.green(), accent.blue(), 16 if light else 22))
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
        corner_bloom.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), (18 if light else 46) + int(10 * breathe)))
        corner_bloom.setColorAt(0.32, QColor(accent.red(), accent.green(), accent.blue(), 10 if light else 20))
        corner_bloom.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, corner_bloom)

        side_bloom = QRadialGradient(
            rect.left() + 10,
            rect.center().y() + rect.height() * (0.08 * math.sin(phase * math.tau)),
            rect.height() * 0.90,
        )
        side_bloom.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), (12 if light else 28) + int(8 * breathe)))
        side_bloom.setColorAt(0.46, QColor(accent.red(), accent.green(), accent.blue(), 8 if light else 14))
        side_bloom.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, side_bloom)
        painter.restore()

        border_color = QColor(tokens.selected_sidebar_border)
        border_color.setAlpha(155 if light else 64)
        border = QPen(border_color, 0.85)
        border.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(border)
        painter.drawPath(path)

        icon_center = QPointF(rect.left() + 24, rect.center().y())
        icon_glow = QRadialGradient(icon_center, 34)
        icon_glow.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), (28 if light else 90) + int(30 * breathe)))
        icon_glow.setColorAt(0.36, QColor(accent.red(), accent.green(), accent.blue(), 18 if light else 34))
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
        painter.setPen(QColor(tokens.accent_hover if light else "#fbfdff"))
        text_rect = QRectF(rect.left() + 52, rect.top(), rect.width() - 64, rect.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._raw_label)


class MinimalistSearchOverlay(AnimatedGlassPanel):
    close_requested = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent, radius=18)
        self.controller = controller
        self.bundle = None
        self._current_commands: list[AtlasCommand] = []
        self._command_dispatch_in_progress = False
        self._callback_dispatch_pending = False
        self._deferred_callback = None
        self.setObjectName("MinimalistSearchOverlay")
        apply_glass_theme(self, "search_overlay")

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(20, 24, 18, 0)
        self.root_layout.setSpacing(0)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 0, 0, 0)
        header_layout.setSpacing(8)
        title = QLabel("Command Palette")
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
        self.search_box.input.setPlaceholderText("Search or run a command...")
        self.search_box.input.installEventFilter(self)
        self.search_box.input.textChanged.connect(self._schedule_refresh_results)
        self.search_box.input.returnPressed.connect(self.run_first_result)
        self.root_layout.addWidget(self.search_box)
        self.root_layout.addSpacing(18)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(125)
        self._refresh_timer.timeout.connect(self.refresh_results)
        # Commands close the palette before changing pages.  Keep that queued
        # step on an owned timer so teardown can cancel it instead of leaving a
        # Python closure posted after its overlay or main window is deleted.
        self._callback_dispatch_timer = QTimer(self)
        self._callback_dispatch_timer.setSingleShot(True)
        self._callback_dispatch_timer.timeout.connect(self._run_deferred_callback)
        self._current_entity_query = None
        self._current_entity_query_text = ""
        self.entity_dropdown: EntitySearchDropdown | None = None
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
        shortcut = QLabel("Press  Ctrl K  anytime to search or run a command")
        shortcut.setObjectName("MinimalistFooterText")
        footer_layout.addWidget(shortcut)
        footer_layout.addStretch(1)
        self.root_layout.addWidget(footer)
        self.refresh_results()

    def apply_theme_preference(self, preference: str | None) -> None:
        apply_glass_theme(self, "search_overlay", preference)
        apply_theme = getattr(self.search_box, "apply_theme_preference", None)
        if callable(apply_theme):
            apply_theme(preference)
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
        self._refresh_timer.stop()
        self.refresh_results()

    def eventFilter(self, watched, event) -> bool:
        search_box = getattr(self, "search_box", None)
        search_input = getattr(search_box, "input", None)
        if watched is search_input and event.type() == QEvent.Type.KeyPress:
            entity_dropdown = getattr(self, "entity_dropdown", None)
            if entity_dropdown is not None and entity_dropdown.isVisible():
                if event.key() == Qt.Key.Key_Down:
                    entity_dropdown.move_highlight(1)
                    return True
                if event.key() == Qt.Key.Key_Up:
                    entity_dropdown.move_highlight(-1)
                    return True
                if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                    self.run_first_result()
                    return True
            if event.key() == Qt.Key.Key_Escape:
                self.close_requested.emit()
                return True
        return super().eventFilter(watched, event)

    def _schedule_refresh_results(self) -> None:
        self._refresh_timer.start()

    def refresh_results(self) -> None:
        query = self.search_box.input.text().strip()
        clear_layout(self.results_layout)
        self._current_commands = []
        self._current_entity_query = None
        self._current_entity_query_text = ""
        self.entity_dropdown = None
        if query:
            searcher = getattr(self.controller, "search_entities", None)
            self._current_entity_query = searcher(query, limit=18) if callable(searcher) else None
            self._current_entity_query_text = query
            entity_results = list(getattr(self._current_entity_query, "results", ()) or ())
            if entity_results:
                dropdown = EntitySearchDropdown(compact=True)
                dropdown.set_results(query, entity_results)
                dropdown.result_clicked.connect(self._run_entity_result)
                dropdown.recent_clicked.connect(self._run_entry)
                self.entity_dropdown = dropdown
                self.results_layout.addWidget(dropdown)
                self.results_layout.addSpacing(10)
            commands = [
                command
                for command in resolve_atlas_commands(self.controller, query, limit=8, include_entity_records=False)
                if command.category != "Records" and command.item_type not in {ITEM_ENTITY_SEARCH, ITEM_RECENT_SEARCH}
            ][:5]
            self._current_commands = commands
            if commands:
                grouped: dict[str, list[AtlasCommand]] = {}
                for command in commands:
                    grouped.setdefault(command.category, []).append(command)
                for category in ("Records", "Pages", "Actions", "Reports", "Filters / Views", "Questions", "Recent", "Pinned", "Settings"):
                    rows = grouped.get(category, [])
                    if not rows:
                        continue
                    self._add_section(category)
                    for command in rows:
                        row = SearchResultRow(
                            command.title,
                            _palette_row_kind(command),
                            command.subtitle or command.result_text,
                            glyph=_palette_row_glyph(command),
                        )
                        row.clicked.connect(lambda _checked=False, command=command: self._run_command(command))
                        self.results_layout.addWidget(row)
            elif not entity_results:
                self._add_section("Results")
                self.results_layout.addWidget(PanelEmptyRow("No Library profile found."))
            self.results_layout.addStretch(1)
            return

        recent = recent_entries(self.controller, self.bundle, limit=5)
        dropdown = EntitySearchDropdown(compact=True)
        dropdown.set_recent_entries(recent)
        dropdown.result_clicked.connect(self._run_entity_result)
        dropdown.recent_clicked.connect(self._run_entry)
        self.entity_dropdown = dropdown
        self.results_layout.addWidget(dropdown)

        self.results_layout.addSpacing(24)
        self._add_section("Suggestions")
        for label, key, glyph in (
            ("Fit Check", "fit_check", "status"),
            ("Library", "library", "library"),
            ("Settings", "settings", "gear"),
        ):
            command = _navigation_suggestion(self.controller, key, label)
            row = SearchSuggestionRow(label, glyph)
            row.clicked.connect(lambda _checked=False, command=command: self._run_command(command))
            self.results_layout.addWidget(row)
        self.results_layout.addStretch(1)

    def run_first_result(self) -> None:
        query = self.search_box.input.text().strip()
        if query:
            searcher = getattr(self.controller, "search_entities", None)
            entity_query = (
                self._current_entity_query
                if self._current_entity_query_text == query
                else (searcher(query, limit=18) if callable(searcher) else None)
            )
            exact = getattr(entity_query, "top_exact_match", None)
            if exact is not None:
                self._run_entity_result(exact)
                return
            highlighted = self.entity_dropdown.highlighted_result() if self.entity_dropdown is not None else None
            if highlighted is not None and not isinstance(highlighted, MinimalistSearchEntry):
                self._run_entity_result(highlighted)
                return
        elif self.entity_dropdown is not None and self.entity_dropdown.run_current():
            return
        if not self._current_commands and query:
            self._current_commands = [
                command
                for command in resolve_atlas_commands(self.controller, query, limit=8, include_entity_records=False)
                if command.category != "Records" and command.item_type not in {ITEM_ENTITY_SEARCH, ITEM_RECENT_SEARCH}
            ][:5]
        if self._current_commands:
            self._run_command(self._current_commands[0])
            return
        if query:
            status = getattr(self.controller, "show_status", None)
            if callable(status):
                status("No matching Library profile found.")
            self.refresh_results()
            return

    def _run_entity_result(self, result) -> None:
        query = self.search_box.input.text().strip()
        def _execute() -> None:
            navigator = getattr(self.controller, "navigate_to_entity", None)
            if callable(navigator):
                navigator(result.entity_type, result.entity_id, source="global-search", raw_query=query or result.entity_id)
                return
            fallback = getattr(self.controller, "navigate_to_profile", None)
            if callable(fallback):
                fallback(result, source="global-search", raw_query=query or result.entity_id)
        self._close_then_run(_execute)

    def _add_section(self, title: str) -> None:
        label = QLabel(title)
        label.setObjectName("MinimalistSectionLabel")
        self.results_layout.addWidget(label)

    def _run_entry(self, entry: MinimalistSearchEntry) -> None:
        _log_recent_entry_selection(self.controller, entry)
        self._close_then_run(lambda entry=entry: self._open_entry(entry))

    def _open_entry(self, entry: MinimalistSearchEntry) -> None:
        if entry.opener is not None:
            entry.opener()
        else:
            try:
                self.controller.open_recommendation(entry.query, kind=entry.kind, record_search=False)
            except TypeError:
                self.controller.open_recommendation(entry.query)

    def _run_command(self, command: AtlasCommand) -> None:
        if self._command_dispatch_in_progress:
            return
        self._command_dispatch_in_progress = True
        query = self.search_box.input.text().strip()
        _log_palette_selection(self.controller, command, query=query)
        if command.item_type not in VALID_PALETTE_ITEM_TYPES:
            status = getattr(self.controller, "show_status", None)
            if callable(status):
                status(f"Command Palette item type is not supported: {command.item_type or 'unknown'}.")
            LOGGER.warning("Unknown command palette item type: id=%s type=%s", command.command_id, command.item_type)
            self._command_dispatch_in_progress = False
            return
        def _execute_command() -> None:
            try:
                navigator = getattr(self.controller, "navigate_to_profile", None)
                if command.item_type in {ITEM_ENTITY_SEARCH, ITEM_RECENT_SEARCH} and getattr(command, "entity_type", "") and callable(navigator):
                    navigator(command, source="global-search", raw_query=query or command.search_query)
                else:
                    command.handler()
                if query and command.item_type == ITEM_ENTITY_SEARCH:
                    self._record_query(query, _recent_kind_for_command(command))
            finally:
                self._command_dispatch_in_progress = False

        try:
            self._close_then_run(_execute_command)
        except Exception:
            self._command_dispatch_in_progress = False
            raise

    def _navigate(self, key: str) -> None:
        command = _navigation_suggestion(self.controller, key, _navigation_label(key))
        self._run_command(command)

    def _run_search_text(self, query: str) -> None:
        _log_raw_search_selection(self.controller, query)
        resolver = getattr(self.controller, "resolve_search_query", None)
        runner = getattr(self.controller, "run_search_query", None)
        if callable(resolver) and callable(runner):
            resolution = resolver(query)
            if getattr(resolution, "entity_type", "") == "ambiguous":
                runner(query, source="global-search", allow_recommendation=False, resolution=resolution)
                self.refresh_results()
                return
            self._close_then_run(lambda query=query, resolution=resolution: runner(query, source="global-search", resolution=resolution))
            return
        self._close_then_run(lambda query=query: self.controller.open_recommendation(query))

    def _close_then_run(self, callback) -> None:
        if self._callback_dispatch_pending:
            return
        self._callback_dispatch_pending = True
        self.search_box.input.clear()
        self._current_commands = []
        self._close_and_run(callback)

    def _close_and_run(self, callback) -> None:
        close_all = getattr(self.controller, "close_all_search_overlays", None)
        if callable(close_all):
            close_all()
        else:
            self.close_requested.emit()
            self.hide()
        # Closing changes focus, visibility, and sometimes page ownership. Let
        # that teardown finish before a command mutates application pages.
        self._deferred_callback = callback
        self._callback_dispatch_timer.start(0)

    def _run_deferred_callback(self) -> None:
        callback = self._deferred_callback
        self._deferred_callback = None
        if callback is not None:
            self._run_callback_safely(callback)

    def _cancel_deferred_callback(self) -> None:
        self._callback_dispatch_timer.stop()
        self._deferred_callback = None
        self._callback_dispatch_pending = False

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.Destroy:
            self._cancel_deferred_callback()
        return super().event(event)

    def closeEvent(self, event) -> None:
        self._refresh_timer.stop()
        self._cancel_deferred_callback()
        super().closeEvent(event)

    def _run_callback_safely(self, callback) -> None:
        try:
            callback()
        except Exception as exc:
            LOGGER.exception("Command Palette callback failed")
            status = getattr(self.controller, "show_status", None)
            if callable(status):
                status(f"Command Palette action failed: {type(exc).__name__}: {exc}")
        finally:
            self._callback_dispatch_pending = False

    def _record_query(self, query: str, kind: str = "") -> None:
        recorder = getattr(self.controller, "record_minimalist_search", None)
        if callable(recorder):
            recorder(query, kind=kind)


class SearchResultRow(QPushButton):
    def __init__(self, title: str, kind: str, subtitle: str = "", *, compact: bool = False, glyph: str = "search", parent=None):
        super().__init__(parent)
        self.setObjectName("MinimalistSearchRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self._compact = compact
        self._has_subtitle = bool(subtitle and not compact)
        self._icon = glyph_icon(glyph, QColor("#cfe4ff"), 22)
        self.setMinimumHeight(44 if compact else (56 if self._has_subtitle else 48))
        self._title = QLabel(title, self)
        self._title.setObjectName("MinimalistRowTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._kind = QLabel(kind, self)
        self._kind.setObjectName("MinimalistRowKind")
        self._kind.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._subtitle = QLabel(subtitle, self)
        self._subtitle.setObjectName("MinimalistRowSubtitle")
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._subtitle.setVisible(self._has_subtitle)
        self._apply_icon_theme(glyph)

    def _apply_icon_theme(self, glyph: str) -> None:
        tokens = active_minimalist_tokens()
        self._icon = glyph_icon(glyph, QColor(tokens.text_secondary), 22)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        kind_width = 104
        left = 42
        available_width = max(40, self.width() - kind_width - left - 10)
        if self._has_subtitle:
            self._title.setGeometry(left, 7, available_width, 22)
            self._subtitle.setGeometry(left, 30, max(40, self.width() - left - 14), 18)
        else:
            self._title.setGeometry(left, max(0, (self.height() - 22) // 2), available_width, 22)
            self._subtitle.setGeometry(left, self.height(), 0, 0)
        self._kind.setGeometry(self.width() - kind_width - 8, max(0, (self.height() - 22) // 2), kind_width, 22)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pixmap = self._icon.pixmap(22, 22)
        painter.drawPixmap(11, max(0, (self.height() - pixmap.height()) // 2), pixmap)


class SearchSuggestionRow(QPushButton):
    def __init__(self, title: str, glyph: str, parent=None):
        super().__init__(title.replace("&", "&&"), parent)
        self.setObjectName("MinimalistSuggestionRow")
        self.setIcon(glyph_icon(glyph, QColor(active_minimalist_tokens().accent_hover), 22))
        self.setIconSize(QSize(22, 22))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(44)


class PanelEmptyRow(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("MinimalistPanelEmpty")
        self.setWordWrap(True)
        self.setMinimumHeight(38)


def _navigation_suggestion(controller, key: str, label: str) -> AtlasCommand:
    route = str(key or "").strip() or "library"
    command_id = "open_library" if route == "library" else f"nav.{route}"
    return AtlasCommand(
        command_id,
        "Pages",
        label,
        f"Navigate to {label}.",
        lambda route=route: controller.show_page(route),
        (route, f"open {label}"),
        item_type=ITEM_NAVIGATION,
        route=route,
    )


def _navigation_label(key: str) -> str:
    return {
        "fit_check": "Fit Check",
        "library": "Library",
        "settings": "Settings",
    }.get(str(key or ""), str(key or "Page"))


def _palette_row_kind(command: AtlasCommand) -> str:
    if command.item_type == ITEM_ENTITY_SEARCH:
        prefix = command.command_id.split(".", 1)[0]
        return {"eoat": "EOAT", "machine": "Machine", "tool": "Tool"}.get(prefix, "Record")
    if command.item_type == ITEM_NAVIGATION:
        return "Page"
    if command.item_type == ITEM_RECENT_SEARCH:
        return "Recent"
    return command.category


def _palette_row_glyph(command: AtlasCommand) -> str:
    prefix = command.command_id.split(".", 1)[0]
    if command.item_type == ITEM_NAVIGATION:
        return "library" if command.route == "library" else ("gear" if command.route == "settings" else "home")
    if prefix == "machine":
        return "machine"
    if prefix == "tool":
        return "grid"
    if prefix == "eoat":
        return "robot"
    if command.command_id == "action.refresh":
        return "swap"
    return "target"


def _recent_kind_for_command(command: AtlasCommand) -> str:
    prefix = command.command_id.split(".", 1)[0]
    return {"eoat": "EOAT", "machine": "Machine", "tool": "Tool / Mold"}.get(prefix, "")


def _log_recent_entry_selection(controller, entry: MinimalistSearchEntry) -> None:
    command = AtlasCommand(
        f"recent_search.{entry.query}",
        "Recent",
        entry.label,
        "Recently searched Atlas entity.",
        lambda: None,
        item_type=ITEM_RECENT_SEARCH,
        search_query=entry.query,
    )
    _log_palette_selection(controller, command, query=entry.query)


def _log_raw_search_selection(controller, query: str) -> None:
    command = AtlasCommand(
        "entity_search.raw",
        "Records",
        query,
        "Typed entity search.",
        lambda: None,
        item_type=ITEM_ENTITY_SEARCH,
        search_query=query,
    )
    _log_palette_selection(controller, command, query=query)


__all__ = ["MinimalistMenuOverlay", "MinimalistSearchOverlay"]
