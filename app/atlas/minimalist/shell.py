from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QLinearGradient, QPainter, QPainterPath, QRadialGradient, QShortcut
from PySide6.QtWidgets import QApplication, QAbstractSpinBox, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit, QWidget

from .overlays import MinimalistMenuOverlay, MinimalistSearchOverlay
from .style import MINIMALIST_STYLES
from .topbar import MinimalistTopBar
from .widgets import MinimalistClickCatcher, TopChromeFade, paint_soft_ribbon


class AtlasMinimalistShell(QWidget):
    def __init__(self, controller, content: QWidget, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.bundle = None
        self.setObjectName("MinimalistAtlasShell")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setStyleSheet(MINIMALIST_STYLES)

        self.content_host = QWidget(self)
        self.content_host.setObjectName("MinimalistContentHost")
        self.content_host.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.content = content
        self.content.setParent(self.content_host)
        self.content.show()

        self.click_catcher = MinimalistClickCatcher(self)
        self.click_catcher.clicked.connect(self.close_overlays)
        self.click_catcher.hide()

        self.top_fade = TopChromeFade(self)
        self.top_fade.show()

        self.top_bar = MinimalistTopBar(self)
        self.top_bar.menu_requested.connect(self.toggle_menu)
        self.top_bar.search_requested.connect(self.toggle_search)

        self.menu_overlay = MinimalistMenuOverlay(controller, self)
        self.menu_overlay.close_requested.connect(self.close_overlays)
        self.menu_overlay.navigate_requested.connect(self._navigate)
        self.menu_overlay.hide()

        self.search_overlay = MinimalistSearchOverlay(controller, self)
        self.search_overlay.close_requested.connect(self.close_overlays)
        self.search_overlay.hide()
        self.escape_shortcut = QShortcut(QKeySequence("Escape"), self)
        self.escape_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.escape_shortcut.activated.connect(self._escape_pressed)

        self._open_overlay = ""
        self._last_menu_rect = QRect()
        self._last_search_rect = QRect()
        self._event_filter_app = None if os.environ.get("EOAT_DISABLE_GLOBAL_TYPE_SEARCH") else QApplication.instance()
        if self._event_filter_app is not None:
            self._event_filter_app.installEventFilter(self)
        self._connect_scroll_fade()

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle
        self.search_overlay.set_bundle(bundle)

    def set_active_nav(self, key: str) -> None:
        self.menu_overlay.set_active_key(key)

    def toggle_menu(self) -> None:
        if self._open_overlay == "menu" or (not self._open_overlay and self.menu_overlay.isVisible()):
            self.close_overlays()
            return
        self.open_menu()

    def toggle_search(self) -> None:
        if self._open_overlay == "search" or (not self._open_overlay and self.search_overlay.isVisible()):
            self.close_overlays()
            return
        self.open_search()

    def open_menu(self) -> None:
        self.search_overlay.animate_close(self._last_search_rect)
        self._open_overlay = "menu"
        self._show_catcher()
        self.top_bar.set_menu_open(True)
        self.top_bar.set_search_open(False)
        self.set_active_nav(getattr(self.controller, "current_page_key", "minimalist_home"))
        rect = self._menu_rect()
        self._last_menu_rect = rect
        self.menu_overlay.raise_()
        self.menu_overlay.animate_open(rect)

    def open_search(self, initial_text: str = "", *, select_all: bool = True) -> None:
        self.menu_overlay.animate_close(self._last_menu_rect)
        self._open_overlay = "search"
        self._show_catcher()
        self.top_bar.set_menu_open(False)
        self.top_bar.set_search_open(True)
        rect = self._search_rect()
        self._last_search_rect = rect
        self.search_overlay.set_bundle(self.bundle)
        if initial_text:
            self.search_overlay.set_search_text(initial_text)
        self.search_overlay.raise_()
        self.search_overlay.animate_open(rect)
        QTimer.singleShot(80, lambda: self.search_overlay.focus_search(select_all=select_all))

    def close_overlays(self) -> None:
        closing = self._open_overlay
        if not closing:
            if self.search_overlay.isVisible():
                closing = "search"
            elif self.menu_overlay.isVisible():
                closing = "menu"
            else:
                self.top_bar.set_menu_open(False)
                self.top_bar.set_search_open(False)
                self.click_catcher.fade_out()
                return
        if not closing:
            return
        self._open_overlay = ""
        self.top_bar.set_menu_open(False)
        self.top_bar.set_search_open(False)
        if closing == "menu":
            self.menu_overlay.animate_close(self._last_menu_rect)
        elif closing == "search":
            self.search_overlay.animate_close(self._last_search_rect)
        self.click_catcher.fade_out()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.content_host.setGeometry(self.rect())
        self.content.setGeometry(self.content_host.rect())
        self.click_catcher.setGeometry(self.rect())
        self.top_fade.setGeometry(0, 0, self.width(), self.top_fade.HEIGHT)
        self.top_bar.setGeometry(0, 0, self.width(), 106)
        self._last_menu_rect = self._menu_rect()
        self._last_search_rect = self._search_rect()
        if self._open_overlay == "menu":
            self.menu_overlay.setGeometry(self._last_menu_rect)
        elif self._open_overlay == "search":
            self.search_overlay.setGeometry(self._last_search_rect)
        self.content_host.lower()
        self.top_fade.raise_()
        if self.click_catcher.isVisible():
            self.click_catcher.raise_()
        self.menu_overlay.raise_()
        self.search_overlay.raise_()
        self.top_bar.raise_()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self._open_overlay:
            self._escape_pressed()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.KeyPress and self._should_start_type_search(watched, event):
            self._start_type_search(event.text())
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.Destroy:
            self.remove_app_event_filter()
        return super().event(event)

    def closeEvent(self, event) -> None:
        self.remove_app_event_filter()
        super().closeEvent(event)

    def hideEvent(self, event) -> None:
        if self.window() is not None and not self.window().isVisible():
            self.remove_app_event_filter()
        super().hideEvent(event)

    def remove_app_event_filter(self) -> None:
        if self._event_filter_app is not None:
            self._event_filter_app.removeEventFilter(self)
            self._event_filter_app = None

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor("#020812"))
        gradient.setColorAt(0.48, QColor("#061222"))
        gradient.setColorAt(1.0, QColor("#01040a"))
        painter.fillRect(rect, gradient)
        self._paint_ambient_light(painter, rect)
        self._paint_streaks(painter, rect)
        super().paintEvent(event)

    def _show_catcher(self) -> None:
        self.click_catcher.setGeometry(self.rect())
        self.click_catcher.fade_in()
        self.click_catcher.raise_()
        self.top_bar.raise_()

    def _hide_catcher_if_closed(self) -> None:
        if not self._open_overlay:
            self.click_catcher.fade_out()

    def _connect_scroll_fade(self) -> None:
        body_scroll = getattr(self.content, "body_scroll", None)
        if body_scroll is None:
            return
        scroll_bar = body_scroll.verticalScrollBar()
        scroll_bar.valueChanged.connect(self._top_scroll_changed)
        self._top_scroll_changed(scroll_bar.value())

    def _top_scroll_changed(self, value: int) -> None:
        self.top_fade.set_scrolled(int(value or 0) > 10)

    def _navigate(self, key: str) -> None:
        self.set_active_nav(key)
        self.controller.show_page(key)

    def _escape_pressed(self) -> None:
        if self._open_overlay or self.search_overlay.isVisible() or self.menu_overlay.isVisible():
            self.close_overlays()
            return
        handle_escape = getattr(self.content, "handle_escape", None)
        if callable(handle_escape) and handle_escape():
            return
        self.close_overlays()

    def _should_start_type_search(self, target, event) -> bool:
        if not self.isVisible() or self.window() is None or not self.window().isActiveWindow():
            return False
        focus_widget = QApplication.focusWidget()
        if self._is_editable_target(target) or self._is_editable_target(focus_widget):
            return False
        modifiers = event.modifiers()
        blocked_modifiers = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.MetaModifier
            | Qt.KeyboardModifier.AltModifier
        )
        if modifiers & blocked_modifiers:
            return False
        text = event.text()
        if len(text) != 1 or text.isspace() or not text.isprintable():
            return False
        return True

    def _is_editable_target(self, target) -> bool:
        widget = target
        while widget is not None:
            if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
                return True
            if isinstance(widget, QComboBox) and widget.isEditable():
                return True
            widget = widget.parent() if hasattr(widget, "parent") else None
        return False

    def _start_type_search(self, text: str) -> None:
        current_page = getattr(self.controller, "current_page_key", "minimalist_home")
        focus_search = getattr(self.content, "focus_search_text", None)
        if current_page in {"home", "minimalist_home", "library"} and callable(focus_search):
            if self._open_overlay:
                self.close_overlays()
                self.click_catcher.hide()
            focus_search(text)
            return
        self.open_search(text, select_all=False)

    def _menu_rect(self) -> QRect:
        panel_width = min(280, max(252, self.width() - 40))
        panel_height = min(748, max(520, self.height() - 172))
        return QRect(12, 102, panel_width, panel_height)

    def _search_rect(self) -> QRect:
        panel_width = min(368, max(330, self.width() - 40))
        panel_height = min(738, max(500, self.height() - 176))
        return QRect(self.width() - panel_width - 8, 138, panel_width, panel_height)

    def _paint_ambient_light(self, painter: QPainter, rect: QRectF) -> None:
        for center_x, center_y, radius, alpha in (
            (rect.width() * 0.50, rect.height() * 0.10, rect.width() * 0.45, 14),
            (rect.width() * 0.80, rect.height() * 0.48, rect.width() * 0.36, 22),
            (rect.width() * 0.08, rect.height() * 0.82, rect.width() * 0.32, 16),
        ):
            glow = QRadialGradient(center_x, center_y, radius)
            glow.setColorAt(0.0, QColor(0, 118, 255, alpha))
            glow.setColorAt(0.65, QColor(0, 55, 140, max(4, alpha // 4)))
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.fillRect(rect, glow)

    def _paint_streaks(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        glows = (
            (rect.width() * 0.56, rect.height() * 0.54, rect.width() * 0.20, 12),
            (rect.width() * 0.72, rect.height() * 0.34, rect.width() * 0.18, 14),
            (rect.width() * 0.04, rect.height() * 0.85, rect.width() * 0.20, 10),
            (rect.width() * 0.90, rect.height() * 0.44, rect.width() * 0.17, 9),
        )
        for center_x, center_y, radius, alpha in glows:
            glow = QRadialGradient(center_x, center_y, radius)
            glow.setColorAt(0.0, QColor(0, 108, 255, alpha))
            glow.setColorAt(0.55, QColor(0, 68, 170, max(3, alpha // 5)))
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.fillRect(rect, glow)

        lower_sweep = QPainterPath()
        lower_sweep.moveTo(-80, rect.height() * 0.92)
        lower_sweep.cubicTo(
            rect.width() * 0.18,
            rect.height() * 0.82,
            rect.width() * 0.30,
            rect.height() * 0.66,
            rect.width() * 0.53,
            rect.height() * 0.61,
        )
        lower_sweep.cubicTo(
            rect.width() * 0.58,
            rect.height() * 0.59,
            rect.width() * 0.64,
            rect.height() * 0.45,
            rect.width() * 0.73,
            rect.height() * 0.32,
        )
        upper_sweep = QPainterPath()
        upper_sweep.moveTo(rect.width() * 0.57, rect.height() * 0.56)
        upper_sweep.cubicTo(
            rect.width() * 0.66,
            rect.height() * 0.45,
            rect.width() * 0.76,
            rect.height() * 0.41,
            rect.width() * 0.97,
            rect.height() * 0.19,
        )
        far_right = QPainterPath()
        far_right.moveTo(rect.width() * 0.80, rect.height() * 0.51)
        far_right.cubicTo(
            rect.width() * 0.90,
            rect.height() * 0.44,
            rect.width() * 0.92,
            rect.height() * 0.35,
            rect.width() * 1.06,
            rect.height() * 0.30,
        )
        paint_soft_ribbon(painter, lower_sweep, QColor("#0a73ff"), alpha_scale=0.60, width_scale=0.62, core=False)
        paint_soft_ribbon(painter, upper_sweep, QColor("#168dff"), alpha_scale=0.66, width_scale=0.58, core=False)
        paint_soft_ribbon(painter, far_right, QColor("#0478ff"), alpha_scale=0.46, width_scale=0.52, core=False)
        painter.restore()


__all__ = ["AtlasMinimalistShell"]
