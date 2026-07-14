from __future__ import annotations

import os
from contextlib import suppress

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    Qt,
    Signal,
)
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel, QStackedWidget, QWidget


class PageTransitionController(QObject):
    """Shared, state-preserving transition helper for major Atlas page changes."""

    transition_started = Signal()
    transition_finished = Signal()

    def __init__(
        self,
        stack: QStackedWidget,
        *,
        incoming_offset: QPoint | None = None,
        incoming_duration_ms: int = 320,
        outgoing_duration_ms: int = 160,
        reduced_motion_duration_ms: int = 90,
        reduced_motion: bool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or stack)
        self.stack = stack
        self.incoming_offset = incoming_offset or QPoint(0, 10)
        self.incoming_duration_ms = max(120, min(400, int(incoming_duration_ms)))
        self.outgoing_duration_ms = max(80, min(220, int(outgoing_duration_ms)))
        self.reduced_motion_duration_ms = max(0, min(120, int(reduced_motion_duration_ms)))
        self.reduced_motion = motion_reduced() if reduced_motion is None else bool(reduced_motion)
        self._group: QParallelAnimationGroup | None = None
        self._overlay: QLabel | None = None
        self._incoming_widget: QWidget | None = None
        self._incoming_effect: QGraphicsOpacityEffect | None = None
        self._incoming_base_pos = QPoint()
        self._animating = False
        self.stack.installEventFilter(self)

    @property
    def is_animating(self) -> bool:
        return self._animating

    def switch_to_index(self, index: int, *, animated: bool = True) -> bool:
        if index < 0 or index >= self.stack.count():
            return False
        return self.switch_to_widget(self.stack.widget(index), animated=animated)

    def switch_to_widget(self, target: QWidget, *, animated: bool = True) -> bool:
        if target is None or self.stack.indexOf(target) < 0:
            return False
        current = self.stack.currentWidget()
        if current is target:
            return True
        if not self._should_animate(animated, current, target):
            self._finish_active_transition(emit_finished=False)
            self.stack.setCurrentWidget(target)
            return True

        self._finish_active_transition(emit_finished=False)
        overlay = self._outgoing_snapshot(current)
        self.stack.setCurrentWidget(target)
        target.raise_()
        self._animate_incoming(target, overlay)
        return True

    def eventFilter(self, watched, event) -> bool:
        if watched is self.stack and event.type() == QEvent.Type.Resize and self._overlay is not None:
            self._overlay.setGeometry(self.stack.rect())
            self._overlay.raise_()
        return super().eventFilter(watched, event)

    def _should_animate(self, animated: bool, current: QWidget | None, target: QWidget) -> bool:
        if not animated or current is None or current is target:
            return False
        if self.stack.width() <= 0 or self.stack.height() <= 0:
            return False
        window = self.stack.window()
        return bool(self.stack.isVisible() and (window is None or window.isVisible()))

    def _outgoing_snapshot(self, current: QWidget | None) -> QLabel | None:
        if current is None or current.width() <= 0 or current.height() <= 0:
            return None
        pixmap = current.grab()
        if pixmap.isNull():
            return None
        overlay = QLabel(self.stack)
        overlay.setObjectName("AtlasPageTransitionSnapshot")
        overlay.setPixmap(pixmap)
        overlay.setScaledContents(False)
        overlay.setGeometry(self.stack.rect())
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        overlay.show()
        overlay.raise_()
        return overlay

    def _animate_incoming(self, target: QWidget, overlay: QLabel | None) -> None:
        self._animating = True
        self._incoming_widget = target
        self._incoming_base_pos = target.pos()
        duration = self.reduced_motion_duration_ms if self.reduced_motion else self.incoming_duration_ms
        outgoing_duration = self.reduced_motion_duration_ms if self.reduced_motion else self.outgoing_duration_ms
        offset = QPoint() if self.reduced_motion else self.incoming_offset
        group = QParallelAnimationGroup(self)

        existing_effect = target.graphicsEffect()
        if existing_effect is None:
            self._incoming_effect = QGraphicsOpacityEffect(target)
            self._incoming_effect.setOpacity(0.0 if not self.reduced_motion else 0.92)
            target.setGraphicsEffect(self._incoming_effect)
            fade_in = QPropertyAnimation(self._incoming_effect, b"opacity", group)
            fade_in.setStartValue(self._incoming_effect.opacity())
            fade_in.setEndValue(1.0)
            fade_in.setDuration(duration)
            fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(fade_in)
        else:
            self._incoming_effect = None

        if not offset.isNull():
            target.move(self._incoming_base_pos + offset)
            slide = QPropertyAnimation(target, b"pos", group)
            slide.setStartValue(self._incoming_base_pos + offset)
            slide.setEndValue(self._incoming_base_pos)
            slide.setDuration(duration)
            slide.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(slide)

        self._overlay = overlay
        if overlay is not None:
            overlay.raise_()
            overlay_effect = QGraphicsOpacityEffect(overlay)
            overlay_effect.setOpacity(1.0)
            overlay.setGraphicsEffect(overlay_effect)
            fade_out = QPropertyAnimation(overlay_effect, b"opacity", group)
            fade_out.setStartValue(1.0)
            fade_out.setEndValue(0.0)
            fade_out.setDuration(outgoing_duration)
            fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(fade_out)

        if group.animationCount() == 0:
            self._finish_active_transition()
            return

        self._group = group
        group.finished.connect(self._finish_active_transition)
        self.transition_started.emit()
        group.start()

    def _finish_active_transition(self, *, emit_finished: bool = True) -> None:
        group = self._group
        self._group = None
        if group is not None:
            with suppress(RuntimeError, TypeError):
                group.finished.disconnect(self._finish_active_transition)
            group.stop()
            group.deleteLater()

        if self._incoming_widget is not None:
            self._incoming_widget.move(self._incoming_base_pos)
            if self._incoming_effect is not None and self._incoming_widget.graphicsEffect() is self._incoming_effect:
                self._incoming_widget.setGraphicsEffect(None)

        if self._overlay is not None:
            self._overlay.hide()
            self._overlay.deleteLater()

        was_animating = self._animating
        self._overlay = None
        self._incoming_widget = None
        self._incoming_effect = None
        self._incoming_base_pos = QPoint()
        self._animating = False
        if emit_finished and was_animating:
            self.transition_finished.emit()


def motion_reduced() -> bool:
    for name in ("EOAT_REDUCED_MOTION", "QT_REDUCED_MOTION", "NO_MOTION"):
        value = os.environ.get(name, "").strip().casefold()
        if value in {"1", "true", "yes", "on"}:
            return True

    app = QApplication.instance()
    hints = app.styleHints().accessibility() if app is not None and hasattr(app.styleHints(), "accessibility") else None
    for attr_name in ("animationsDisabled", "reducedMotion", "reduceMotion"):
        attr = getattr(hints, attr_name, None)
        try:
            if callable(attr) and bool(attr()):
                return True
            if attr is not None and not callable(attr) and bool(attr):
                return True
        except TypeError:
            continue
    return False


__all__ = ["PageTransitionController", "motion_reduced"]
