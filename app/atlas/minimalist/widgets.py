from __future__ import annotations

import math
import os

from PySide6.QtCore import (
    Property,
    QAbstractAnimation,
    QEasingCurve,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

ACCENT = QColor("#1f87ff")
ACCENT_BRIGHT = QColor("#00c9ff")
GREEN = QColor("#36d86a")


def paint_soft_ribbon(
    painter: QPainter,
    path: QPainterPath,
    color: QColor,
    *,
    alpha_scale: float = 1.0,
    width_scale: float = 1.0,
    core: bool = True,
) -> None:
    painter.save()
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    bands = [(72.0, 3), (44.0, 5), (24.0, 8), (9.0, 14)]
    if core:
        bands.append((1.2, 24))
    for width, alpha in bands:
        ribbon_color = QColor(color)
        ribbon_color.setAlpha(max(1, min(255, round(alpha * alpha_scale))))
        pen = QPen(ribbon_color, max(0.7, width * width_scale))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
    painter.restore()


def prefers_reduced_motion() -> bool:
    for name in ("EOAT_REDUCED_MOTION", "QT_REDUCED_MOTION", "NO_MOTION"):
        value = os.environ.get(name, "").strip().casefold()
        if value in {"1", "true", "yes", "on"}:
            return True
    app = QApplication.instance()
    if app is not None:
        hints = app.styleHints()
        duration = getattr(hints, "animationDuration", None)
        if callable(duration):
            try:
                return int(duration()) == 0
            except (TypeError, ValueError):
                return False
    return False


class GlassPanel(QFrame):
    def __init__(self, parent=None, *, radius: int = 18, streaks: bool = False):
        super().__init__(parent)
        self.radius = radius
        self.streaks = streaks
        self._fill_alpha = 145
        self._fill_color = QColor("#050e1d")
        self._border_alpha = 76
        self._border_color = QColor("#8ab9ff")
        self._outer_glow_alpha = 0
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def set_glass(
        self,
        *,
        alpha: int,
        border_alpha: int,
        border_color: QColor | None = None,
        fill_color: QColor | None = None,
        outer_glow_alpha: int | None = None,
    ) -> None:
        self._fill_alpha = alpha
        self._border_alpha = border_alpha
        if border_color is not None:
            self._border_color = QColor(border_color)
        if fill_color is not None:
            self._fill_color = QColor(fill_color)
        if outer_glow_alpha is not None:
            self._outer_glow_alpha = outer_glow_alpha
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.7, 0.7, -0.7, -0.7)
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)
        if self._outer_glow_alpha:
            for width, alpha_scale in ((5.2, 0.28), (2.6, 0.52)):
                glow = QColor(self._border_color)
                glow.setAlpha(max(1, min(255, round(self._outer_glow_alpha * alpha_scale))))
                painter.setPen(QPen(glow, width))
                painter.drawPath(path)
        fill = QColor(self._fill_color)
        fill.setAlpha(self._fill_alpha)
        painter.fillPath(path, fill)
        if self.streaks:
            painter.save()
            painter.setClipPath(path)
            self._paint_internal_streaks(painter, rect)
            painter.restore()
        border = QColor(self._border_color.red(), self._border_color.green(), self._border_color.blue(), self._border_alpha)
        painter.setPen(QPen(border, 1.05))
        painter.drawPath(path)
        super().paintEvent(event)

    def _paint_internal_streaks(self, painter: QPainter, rect: QRectF) -> None:
        glow = QRadialGradient(rect.right() * 0.78, rect.top() + rect.height() * 0.28, rect.width() * 0.52)
        glow.setColorAt(0.0, QColor(0, 104, 255, 52))
        glow.setColorAt(0.50, QColor(0, 55, 140, 18))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, glow)
        main = QPainterPath()
        main.moveTo(rect.left() + rect.width() * 0.60, rect.top() + rect.height() * 0.64)
        main.cubicTo(
            rect.left() + rect.width() * 0.71,
            rect.top() + rect.height() * 0.54,
            rect.left() + rect.width() * 0.78,
            rect.top() + rect.height() * 0.20,
            rect.right() + 22,
            rect.top() - 18,
        )
        lower = QPainterPath()
        lower.moveTo(rect.left() + rect.width() * 0.43, rect.top() + rect.height() * 0.78)
        lower.cubicTo(
            rect.left() + rect.width() * 0.62,
            rect.top() + rect.height() * 0.70,
            rect.left() + rect.width() * 0.74,
            rect.top() + rect.height() * 0.48,
            rect.right() + 16,
            rect.top() + rect.height() * 0.10,
        )
        paint_soft_ribbon(painter, lower, QColor("#0064d7"), alpha_scale=0.72, width_scale=0.48)
        paint_soft_ribbon(painter, main, QColor("#168dff"), alpha_scale=0.78, width_scale=0.46)


class AnimatedGlassPanel(GlassPanel):
    def __init__(self, parent=None, *, radius: int = 18):
        super().__init__(parent, radius=radius, streaks=False)
        self._closing = False
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._geometry_animation = QPropertyAnimation(self, b"geometry", self)
        self._opacity_animation = QPropertyAnimation(self._opacity, b"opacity", self)
        self._geometry_animation.finished.connect(self._animation_finished)

    def animate_open(self, rect: QRect) -> None:
        self._closing = False
        self._geometry_animation.stop()
        self._opacity_animation.stop()
        start = QRect(rect.x(), rect.y() - 28, rect.width(), rect.height())
        self.setGeometry(start)
        self.show()
        self.raise_()
        self._start_animation(start, rect, 0.0, 1.0, QEasingCurve.Type.OutCubic)

    def animate_close(self, rect: QRect) -> None:
        if not self.isVisible():
            return
        self._closing = True
        self._geometry_animation.stop()
        self._opacity_animation.stop()
        current = self.geometry()
        if rect.isNull():
            rect = current
        end = QRect(rect.x(), rect.y() - 26, rect.width(), rect.height())
        self._start_animation(current, end, self._opacity.opacity(), 0.0, QEasingCurve.Type.InCubic)

    def _start_animation(
        self,
        start_rect: QRect,
        end_rect: QRect,
        start_opacity: float,
        end_opacity: float,
        easing: QEasingCurve.Type,
    ) -> None:
        self._geometry_animation.setDuration(280 if end_opacity > start_opacity else 230)
        self._geometry_animation.setEasingCurve(easing)
        self._geometry_animation.setStartValue(start_rect)
        self._geometry_animation.setEndValue(end_rect)
        self._opacity_animation.setDuration(260 if end_opacity > start_opacity else 220)
        self._opacity_animation.setEasingCurve(easing)
        self._opacity_animation.setStartValue(start_opacity)
        self._opacity_animation.setEndValue(end_opacity)
        self._geometry_animation.start()
        self._opacity_animation.start()

    def _animation_finished(self) -> None:
        if self._closing:
            self.hide()
            self._opacity.setOpacity(0.0)
            self._closing = False


class InteractiveTopIconButton(QAbstractButton):
    HOVER_SCALE = 1.08
    POP_SCALE = 1.24
    SETTLE_SCALE = 0.97

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icon_scale = 1.0
        self._hovered = False
        self._pressed_flash = False
        self._reduced_motion = prefers_reduced_motion()
        self._scale_animation = QPropertyAnimation(self, b"iconScale", self)
        self._scale_animation.setDuration(170)
        self._scale_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._bounce_animation: QSequentialAnimationGroup | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setMouseTracking(True)
        self.pressed.connect(self._play_press_feedback)

    def get_icon_scale(self) -> float:
        return self._icon_scale

    def set_icon_scale(self, value: float) -> None:
        self._icon_scale = float(value)
        self.update()

    iconScale = Property(float, get_icon_scale, set_icon_scale)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._sync_hover_scale()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._sync_hover_scale()
        self.update()
        super().leaveEvent(event)

    def _desired_scale(self) -> float:
        if self._reduced_motion:
            return 1.0
        return self.HOVER_SCALE if self._hovered else 1.0

    def _sync_hover_scale(self) -> None:
        if self._bounce_animation is not None and self._bounce_animation.state() == QAbstractAnimation.State.Running:
            return
        self._animate_icon_scale(self._desired_scale())

    def play_bounce(self) -> None:
        self._play_press_feedback()

    def _animate_icon_scale(self, target: float, *, duration: int = 170) -> None:
        if self._reduced_motion:
            self.set_icon_scale(1.0)
            return
        self._scale_animation.stop()
        self._scale_animation.setDuration(duration)
        self._scale_animation.setStartValue(self._icon_scale)
        self._scale_animation.setEndValue(target)
        self._scale_animation.start()

    def _play_press_feedback(self) -> None:
        if self._reduced_motion:
            self._pressed_flash = True
            self.update()
            QTimer.singleShot(120, self._clear_pressed_flash)
            return
        self._scale_animation.stop()
        if self._bounce_animation is not None:
            self._bounce_animation.stop()
            self._bounce_animation.deleteLater()
        final_scale = self._desired_scale()
        group = QSequentialAnimationGroup(self)
        start_scale = self._icon_scale
        for duration, next_scale, easing in (
            (75, self.POP_SCALE, QEasingCurve.Type.OutQuad),
            (85, self.SETTLE_SCALE, QEasingCurve.Type.InOutCubic),
            (120, final_scale, QEasingCurve.Type.OutBack),
        ):
            animation = QPropertyAnimation(self, b"iconScale", group)
            animation.setDuration(duration)
            animation.setStartValue(start_scale)
            animation.setEndValue(next_scale)
            animation.setEasingCurve(easing)
            group.addAnimation(animation)
            start_scale = next_scale
        self._bounce_animation = group
        group.finished.connect(lambda group=group: self._finish_bounce(group))
        group.start()

    def _finish_bounce(self, group: QSequentialAnimationGroup) -> None:
        if self._bounce_animation is group:
            self._bounce_animation = None
        group.deleteLater()
        self._sync_hover_scale()

    def _clear_pressed_flash(self) -> None:
        self._pressed_flash = False
        self.update()

    def _glow_alpha(self) -> int:
        alpha = 0
        if self._hovered:
            alpha += 58
        if self.isChecked():
            alpha += 34
        if self._pressed_flash:
            alpha += 72
        alpha += max(0, int((self._icon_scale - 1.0) * 250))
        return min(150, alpha)


class HamburgerButton(InteractiveTopIconButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0.0
        self._animation = QPropertyAnimation(self, b"angle", self)
        self._animation.setDuration(220)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def sizeHint(self) -> QSize:
        return QSize(52, 52)

    def get_angle(self) -> float:
        return self._angle

    def set_angle(self, value: float) -> None:
        self._angle = float(value)
        self.update()

    angle = Property(float, get_angle, set_angle)

    def set_open(self, open_: bool) -> None:
        self.setChecked(open_)
        self._animation.stop()
        self._animation.setStartValue(self._angle)
        self._animation.setEndValue(90.0 if open_ else 0.0)
        self._animation.start()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(self._icon_scale, self._icon_scale)
        painter.rotate(self._angle)
        glow_alpha = self._glow_alpha()
        if glow_alpha:
            glow = QPen(QColor(31, 135, 255, glow_alpha), 7.5)
            glow.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(glow)
            for y in (-10, 0, 10):
                painter.drawLine(-16, y, 16, y)
        pen = QPen(QColor("#f7f8fb"), 3.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for y in (-10, 0, 10):
            painter.drawLine(-16, y, 16, y)


class SearchIconButton(InteractiveTopIconButton):
    def __init__(self, parent=None):
        super().__init__(parent)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(self._icon_scale, self._icon_scale)
        painter.translate(-self.width() / 2, -self.height() / 2)
        glow_alpha = self._glow_alpha()
        if glow_alpha:
            glow = QPen(QColor(31, 135, 255, glow_alpha), 7.0)
            glow.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(glow)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(13, 12, 24, 24))
            painter.drawLine(32, 32, 45, 45)
        pen = QPen(QColor("#ffffff"), 3.1)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(13, 12, 24, 24))
        painter.drawLine(32, 32, 45, 45)


class CloseIconButton(QAbstractButton):
    def __init__(self, parent=None, *, size: int = 42):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#ffffff"), 2.1)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        pad = self._size * 0.30
        painter.drawLine(pad, pad, self._size - pad, self._size - pad)
        painter.drawLine(self._size - pad, pad, pad, self._size - pad)


class ArrowButton(InteractiveTopIconButton):
    HOVER_SCALE = 1.08
    POP_SCALE = 1.20
    SETTLE_SCALE = 0.97

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(False)
        self.setFixedSize(80, 80)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(self._icon_scale, self._icon_scale)
        painter.translate(-self.width() / 2, -self.height() / 2)
        side = 64.0
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side).adjusted(0.5, 0.5, -0.5, -0.5)
        glow_alpha = self._glow_alpha()
        if glow_alpha:
            painter.save()
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            glow = QRadialGradient(rect.center(), rect.width() * 0.72)
            glow.setColorAt(0.0, QColor(45, 128, 255, min(135, glow_alpha)))
            glow.setColorAt(0.48, QColor(26, 101, 255, min(72, glow_alpha // 2)))
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.fillRect(QRectF(self.rect()), glow)
            painter.restore()
        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        fill.setColorAt(0.0, QColor("#2c68ff"))
        fill.setColorAt(1.0, QColor("#1165f4"))
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.fillPath(path, fill)
        painter.setPen(QPen(QColor(83, 158, 255, 180), 1.0))
        painter.drawPath(path)
        painter.setPen(QPen(QColor("#ffffff"), 2.6))
        center = rect.center()
        painter.drawLine(QPointF(center.x() - 10, center.y()), QPointF(center.x() + 9, center.y()))
        painter.drawLine(QPointF(center.x() + 2, center.y() - 8), QPointF(center.x() + 10, center.y()))
        painter.drawLine(QPointF(center.x() + 2, center.y() + 8), QPointF(center.x() + 10, center.y()))


class SearchMiniIcon(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#d7e6ff"), 1.6))
        painter.drawEllipse(QRectF(2.5, 2.5, 12, 12))
        painter.drawLine(13, 13, 20, 20)


class MinimalistLogoMark(QWidget):
    def sizeHint(self) -> QSize:
        return QSize(40, 40)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(3, 3, self.width() - 6, self.height() - 6)
        painter.setPen(QPen(ACCENT_BRIGHT, 1.4))
        painter.setBrush(QColor(0, 170, 255, 20))
        painter.drawEllipse(rect)
        path = QPainterPath()
        cx = rect.center().x()
        path.moveTo(cx, rect.top() + 6)
        path.lineTo(rect.right() - 8, rect.bottom() - 7)
        path.cubicTo(cx + 3, rect.bottom() - 2, cx - 3, rect.bottom() - 2, rect.left() + 8, rect.bottom() - 7)
        path.closeSubpath()
        painter.setPen(QPen(QColor("#6fe7ff"), 1.1))
        painter.setBrush(QColor("#008dff"))
        painter.drawPath(path)
        inner = QPainterPath()
        inner.moveTo(cx, rect.top() + 12)
        inner.lineTo(cx + 5, rect.bottom() - 11)
        inner.lineTo(cx, rect.bottom() - 15)
        inner.lineTo(cx - 5, rect.bottom() - 11)
        inner.closeSubpath()
        painter.setBrush(QColor("#07182b"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(inner)


class StatusDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ready = False

    def set_ready(self, ready: bool) -> None:
        self._ready = ready
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = GREEN if self._ready else QColor("#f5b342")
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(2, 2, 10, 10))


class MinimalistClickCatcher(QWidget):
    clicked = Signal()
    TARGET_SCRIM_OPACITY = 0.42

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scrim_opacity = 0.0
        self._hide_when_done = False
        self._scrim_animation = QPropertyAnimation(self, b"scrimOpacity", self)
        self._scrim_animation.finished.connect(self._finish_scrim_animation)

    def get_scrim_opacity(self) -> float:
        return self._scrim_opacity

    def set_scrim_opacity(self, value: float) -> None:
        self._scrim_opacity = max(0.0, min(1.0, float(value)))
        self.update()

    scrimOpacity = Property(float, get_scrim_opacity, set_scrim_opacity)

    def fade_in(self) -> None:
        self._hide_when_done = False
        self.show()
        self._animate_scrim(self.TARGET_SCRIM_OPACITY, 285, QEasingCurve.Type.OutCubic)

    def fade_out(self) -> None:
        if not self.isVisible():
            self.set_scrim_opacity(0.0)
            return
        self._hide_when_done = True
        self._animate_scrim(0.0, 245, QEasingCurve.Type.InOutCubic)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 5, 13, round(255 * self._scrim_opacity)))

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        event.accept()

    def _animate_scrim(self, target: float, duration: int, easing: QEasingCurve.Type) -> None:
        self._scrim_animation.stop()
        if prefers_reduced_motion():
            self.set_scrim_opacity(target)
            if target <= 0.0 and self._hide_when_done:
                self.hide()
            return
        self._scrim_animation.setDuration(duration)
        self._scrim_animation.setEasingCurve(easing)
        self._scrim_animation.setStartValue(self._scrim_opacity)
        self._scrim_animation.setEndValue(target)
        self._scrim_animation.start()

    def _finish_scrim_animation(self) -> None:
        if self._hide_when_done and self._scrim_opacity <= 0.001:
            self.hide()
            self._hide_when_done = False


class TopChromeFade(QWidget):
    HEIGHT = 168

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scroll_progress = 0.0
        self._scroll_animation = QPropertyAnimation(self, b"scrollProgress", self)
        self._scroll_animation.setDuration(160)
        self._scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("TopChromeFade")

    def get_scroll_progress(self) -> float:
        return self._scroll_progress

    def set_scroll_progress(self, value: float) -> None:
        self._scroll_progress = max(0.0, min(1.0, float(value)))
        self.update()

    scrollProgress = Property(float, get_scroll_progress, set_scroll_progress)

    def set_scrolled(self, scrolled: bool) -> None:
        target = 1.0 if scrolled else 0.0
        if abs(self._scroll_progress - target) < 0.01:
            return
        self._scroll_animation.stop()
        if prefers_reduced_motion():
            self.set_scroll_progress(target)
            return
        self._scroll_animation.setStartValue(self._scroll_progress)
        self._scroll_animation.setEndValue(target)
        self._scroll_animation.start()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        progress = self._scroll_progress
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QColor(2, 10, 24, round(240 + 10 * progress)))
        gradient.setColorAt(0.36, QColor(2, 10, 24, round(198 + 18 * progress)))
        gradient.setColorAt(0.74, QColor(2, 10, 24, round(96 + 18 * progress)))
        gradient.setColorAt(0.92, QColor(2, 10, 24, round(22 + 8 * progress)))
        gradient.setColorAt(1.0, QColor(2, 10, 24, 0))
        painter.fillRect(self.rect(), gradient)

        separator_alpha = round(14 + 20 * progress)
        painter.setPen(QPen(QColor(66, 142, 255, separator_alpha), 1))
        painter.drawLine(0, min(self.height() - 1, 108), self.width(), min(self.height() - 1, 108))


class MinimalistToast(GlassPanel):
    def __init__(self, parent=None):
        super().__init__(parent, radius=12)
        self.set_glass(alpha=186, border_alpha=100)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)
        self.label = QLabel("")
        self.label.setObjectName("MinimalistToastText")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_message(self, message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        self.label.setText(text)
        self.show()
        self.raise_()
        self._hide_timer.start(6200)

    def hideEvent(self, event) -> None:
        self._hide_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._hide_timer.stop()
        super().closeEvent(event)


def set_placeholder_color(line_edit: QLineEdit, color: QColor) -> None:
    palette = line_edit.palette()
    palette.setColor(QPalette.ColorRole.PlaceholderText, color)
    line_edit.setPalette(palette)


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()


def glyph_icon(glyph: str, color: QColor, size: int) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(color, max(1.5, size * 0.075)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    draw_glyph(painter, QRectF(2, 2, size - 4, size - 4), glyph, color)
    painter.end()
    return QIcon(pixmap)


def draw_glyph(painter: QPainter, rect: QRectF, glyph: str, color: QColor) -> None:
    pen = QPen(color, max(1.5, rect.width() * 0.08))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx = rect.center().x()
    cy = rect.center().y()
    if glyph == "home":
        roof = QPolygonF(
            [
                QPointF(rect.left() + rect.width() * 0.13, rect.top() + rect.height() * 0.46),
                QPointF(cx, rect.top() + rect.height() * 0.13),
                QPointF(rect.right() - rect.width() * 0.13, rect.top() + rect.height() * 0.46),
            ]
        )
        painter.drawPolyline(roof)
        house = QRectF(rect.left() + rect.width() * 0.22, rect.top() + rect.height() * 0.42, rect.width() * 0.56, rect.height() * 0.45)
        painter.drawRoundedRect(house, 2, 2)
        painter.drawLine(cx, house.bottom(), cx, house.top() + house.height() * 0.42)
    elif glyph == "target":
        painter.drawEllipse(rect.adjusted(3, 3, -3, -3))
        painter.drawEllipse(QRectF(cx - 4, cy - 4, 8, 8))
        painter.drawLine(cx, rect.top(), cx, rect.top() + rect.height() * 0.25)
        painter.drawLine(cx, rect.bottom(), cx, rect.bottom() - rect.height() * 0.25)
        painter.drawLine(rect.left(), cy, rect.left() + rect.width() * 0.25, cy)
        painter.drawLine(rect.right(), cy, rect.right() - rect.width() * 0.25, cy)
    elif glyph in {"doc", "report"}:
        body = rect.adjusted(rect.width() * 0.18, rect.height() * 0.06, -rect.width() * 0.12, -rect.height() * 0.08)
        painter.drawRoundedRect(body, 2, 2)
        painter.drawLine(body.left() + 5, body.top() + 8, body.right() - 5, body.top() + 8)
        painter.drawLine(body.left() + 5, body.top() + 15, body.right() - 5, body.top() + 15)
        if glyph == "report":
            painter.drawLine(body.left() + 5, body.bottom() - 7, body.left() + 10, body.bottom() - 13)
            painter.drawLine(body.left() + 10, body.bottom() - 13, body.left() + 16, body.bottom() - 10)
    elif glyph == "machine":
        painter.drawRoundedRect(rect.adjusted(3, 5, -3, -7), 3, 3)
        painter.drawLine(rect.left() + 5, rect.bottom() - 7, rect.right() - 5, rect.bottom() - 7)
        painter.drawEllipse(QRectF(rect.left() + 5, rect.bottom() - 8, 5, 5))
        painter.drawEllipse(QRectF(rect.right() - 10, rect.bottom() - 8, 5, 5))
        painter.drawLine(cx, rect.top() + 3, cx, rect.top() - 1)
    elif glyph == "grid":
        side = rect.width() * 0.28
        for row in range(2):
            for col in range(2):
                painter.drawRoundedRect(
                    QRectF(rect.left() + col * rect.width() * 0.48, rect.top() + row * rect.height() * 0.48, side, side),
                    2,
                    2,
                )
    elif glyph == "image":
        painter.drawRoundedRect(rect.adjusted(2, 4, -2, -4), 2, 2)
        painter.drawEllipse(QRectF(rect.right() - 9, rect.top() + 8, 4, 4))
        painter.drawLine(rect.left() + 4, rect.bottom() - 7, cx - 2, cy + 1)
        painter.drawLine(cx - 2, cy + 1, cx + 4, rect.bottom() - 10)
        painter.drawLine(cx + 4, rect.bottom() - 10, rect.right() - 4, rect.bottom() - 6)
    elif glyph == "book":
        painter.drawRoundedRect(QRectF(rect.left() + 2, rect.top() + 3, rect.width() * 0.42, rect.height() - 6), 2, 2)
        painter.drawRoundedRect(QRectF(cx + 1, rect.top() + 3, rect.width() * 0.42, rect.height() - 6), 2, 2)
        painter.drawLine(cx, rect.top() + 5, cx, rect.bottom() - 5)
    elif glyph == "library":
        back = rect.adjusted(rect.width() * 0.20, rect.height() * 0.08, -rect.width() * 0.06, -rect.height() * 0.24)
        mid = rect.adjusted(rect.width() * 0.12, rect.height() * 0.20, -rect.width() * 0.14, -rect.height() * 0.12)
        front = rect.adjusted(rect.width() * 0.04, rect.height() * 0.34, -rect.width() * 0.22, 0)
        painter.drawRoundedRect(back, 2, 2)
        painter.drawRoundedRect(mid, 2, 2)
        painter.drawRoundedRect(front, 2, 2)
        painter.drawLine(front.left() + 5, front.top() + front.height() * 0.35, front.right() - 5, front.top() + front.height() * 0.35)
    elif glyph in {"layers", "eoat"}:
        top = QPolygonF(
            [
                QPointF(cx, rect.top() + 4),
                QPointF(rect.right() - 4, cy - 3),
                QPointF(cx, cy + 6),
                QPointF(rect.left() + 4, cy - 3),
            ]
        )
        painter.drawPolygon(top)
        painter.drawLine(rect.left() + 6, cy + 5, cx, rect.bottom() - 4)
        painter.drawLine(cx, rect.bottom() - 4, rect.right() - 6, cy + 5)
        if glyph == "eoat":
            painter.drawEllipse(QRectF(cx - 3, cy - 1, 6, 6))
    elif glyph == "air":
        for offset in (-8, 0, 8):
            path = QPainterPath()
            path.moveTo(rect.left() + 3, cy + offset)
            path.cubicTo(cx - 5, cy + offset - 7, cx + 2, cy + offset + 7, rect.right() - 4, cy + offset)
            painter.drawPath(path)
        painter.drawLine(rect.right() - 9, cy - 5, rect.right() - 4, cy)
        painter.drawLine(rect.right() - 9, cy + 5, rect.right() - 4, cy)
    elif glyph == "robot":
        painter.drawLine(rect.left() + 5, rect.bottom() - 5, cx - 3, cy + 5)
        painter.drawLine(cx - 3, cy + 5, cx + 6, rect.top() + 7)
        painter.drawEllipse(QRectF(cx - 8, cy - 1, 8, 8))
        painter.drawEllipse(QRectF(cx + 2, rect.top() + 4, 8, 8))
        painter.drawRoundedRect(QRectF(rect.right() - 10, rect.top() + 2, 8, 10), 2, 2)
    elif glyph == "status":
        painter.drawEllipse(rect.adjusted(4, 4, -4, -4))
        painter.drawLine(rect.left() + 9, cy, cx - 2, rect.bottom() - 10)
        painter.drawLine(cx - 2, rect.bottom() - 10, rect.right() - 8, rect.top() + 10)
    elif glyph == "gear":
        painter.drawEllipse(QRectF(cx - 6, cy - 6, 12, 12))
        for index in range(8):
            angle = math.radians(index * 45)
            painter.drawLine(
                cx + math.cos(angle) * 10,
                cy + math.sin(angle) * 10,
                cx + math.cos(angle) * 13,
                cy + math.sin(angle) * 13,
            )
    else:
        painter.drawEllipse(rect.adjusted(4, 4, -4, -4))


__all__ = [
    "ACCENT",
    "ACCENT_BRIGHT",
    "AnimatedGlassPanel",
    "ArrowButton",
    "CloseIconButton",
    "GlassPanel",
    "HamburgerButton",
    "MinimalistClickCatcher",
    "MinimalistLogoMark",
    "MinimalistToast",
    "TopChromeFade",
    "paint_soft_ribbon",
    "SearchIconButton",
    "SearchMiniIcon",
    "StatusDot",
    "clear_layout",
    "glyph_icon",
    "set_placeholder_color",
]
