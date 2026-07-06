from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtCore import QPropertyAnimation
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from .widgets import HamburgerButton, MinimalistLogoMark, SearchIconButton


class MinimalistTopBar(QWidget):
    menu_requested = Signal()
    back_requested = Signal()
    search_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MinimalistTopBar")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.menu_button = HamburgerButton(self)
        self.menu_button.setAccessibleName("Open navigation menu")
        self.menu_button.clicked.connect(self.menu_requested.emit)
        self.back_button = TopBarBackToLibraryButton(self)
        self.back_button.clicked.connect(self.back_requested.emit)
        self.back_button.hide()
        self.logo = MinimalistLogo(self)
        self.search_button = SearchIconButton(self)
        self.search_button.setAccessibleName("Open search")
        self.search_button.clicked.connect(self.search_requested.emit)

    def set_menu_open(self, open_: bool) -> None:
        self.menu_button.set_open(open_)
        self.menu_button.setAccessibleName("Close navigation menu" if open_ else "Open navigation menu")

    def set_search_open(self, open_: bool) -> None:
        self.search_button.setChecked(open_)
        self.search_button.setAccessibleName("Close search" if open_ else "Open search")

    def set_back_visible(self, visible: bool) -> None:
        self.back_button.setVisible(bool(visible))
        self.back_button.setEnabled(bool(visible))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.menu_button.setGeometry(42, 27, 52, 52)
        self.back_button.setGeometry(self.menu_button.geometry().right() + 14, 36, 152, 34)
        logo_width = 244
        self.logo.setGeometry((self.width() - logo_width) // 2, 27, logo_width, 48)
        self.search_button.setGeometry(self.width() - 92, 25, 58, 58)


class TopBarBackToLibraryButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover_progress = 0.0
        self._hover_animation = QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_animation.setDuration(150)
        self._hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setObjectName("BackToLibraryButton")
        self.setAccessibleName("Back to Library")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(152, 34)

    def get_hover_progress(self) -> float:
        return self._hover_progress

    def set_hover_progress(self, value: float) -> None:
        self._hover_progress = max(0.0, min(1.0, float(value)))
        self.update()

    hoverProgress = Property(float, get_hover_progress, set_hover_progress)

    def enterEvent(self, event) -> None:
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        hover = self._hover_progress
        rect = QRectF(self.rect()).adjusted(0.7, 0.7, -0.7, -0.7)
        path = QPainterPath()
        path.addRoundedRect(rect, 17, 17)
        painter.fillPath(path, QColor(5, 17, 35, 88 + round(58 * hover)))
        if hover:
            painter.setPen(QPen(QColor(22, 141, 255, round(68 * hover)), 3.4))
            painter.drawPath(path)
        painter.setPen(QPen(QColor(78, 124, 174, 78 + round(102 * hover)), 1.0))
        painter.drawPath(path)

        color = QColor(
            188 + round(50 * hover),
            202 + round(34 * hover),
            222 + round(24 * hover),
        )
        arrow_x = 22 - hover * 2.5
        arrow_y = rect.center().y()
        painter.setPen(QPen(color, 1.8))
        painter.drawLine(QPointF(arrow_x, arrow_y), QPointF(arrow_x + 8, arrow_y - 8))
        painter.drawLine(QPointF(arrow_x, arrow_y), QPointF(arrow_x + 8, arrow_y + 8))
        font = QFont("Segoe UI")
        font.setPointSizeF(9.5)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(QRectF(38, 0, self.width() - 44, self.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Back to Library")

    def _animate_hover(self, target: float) -> None:
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover_progress)
        self._hover_animation.setEndValue(target)
        self._hover_animation.start()


class MinimalistLogo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mark = MinimalistLogoMark(self)
        self.eoat = QLabel("EOAT", self)
        self.eoat.setObjectName("MinimalistLogoEOAT")
        self.atlas = QLabel("Atlas", self)
        self.atlas.setObjectName("MinimalistLogoAtlas")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.mark.setGeometry(0, 4, 40, 40)
        self.eoat.setGeometry(53, 3, 78, 42)
        self.atlas.setGeometry(131, 3, 92, 42)


__all__ = ["MinimalistLogo", "MinimalistTopBar", "TopBarBackToLibraryButton"]
