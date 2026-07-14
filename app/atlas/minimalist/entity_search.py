from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from core.atlas_entity_search import EntitySearchResult, entity_type_label

from .data import MinimalistSearchEntry
from .widgets import GlassPanel, clear_layout, glyph_icon


ENTITY_GROUP_ORDER = ("eoat", "tool", "machine")


class EntitySearchDropdown(GlassPanel):
    result_clicked = Signal(object)
    recent_clicked = Signal(object)

    def __init__(self, parent=None, *, compact: bool = False):
        super().__init__(parent, radius=10)
        self.compact = bool(compact)
        self._rows: list[EntitySearchRow] = []
        self._selectable: list[object] = []
        self._highlight_index = -1
        self._row_count = 0
        self._section_count = 0
        self.setObjectName("EntitySearchDropdown")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.set_glass(
            alpha=236,
            border_alpha=150,
            border_color=QColor("#2b86e7"),
            fill_color=QColor("#020b18"),
            outer_glow_alpha=54,
        )

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("EntitySearchScroll")
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName("EntitySearchDropdownBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(6)
        self.scroll.setWidget(self.body)
        self._layout.addWidget(self.scroll)

    def set_recent_entries(self, entries: list[MinimalistSearchEntry]) -> None:
        self._reset()
        self._add_section("Recent Searches")
        if not entries:
            self._add_empty("No recent Library profiles yet.")
        for entry in entries:
            row = EntitySearchRow(entry, compact=self.compact, recent=True)
            row.clicked.connect(lambda entry=entry: self.recent_clicked.emit(entry))
            row.hovered.connect(self._row_hovered)
            self._append_row(row, entry)
        self._finish()

    def set_results(self, query: str, results: Iterable[EntitySearchResult]) -> None:
        self._reset()
        rows = list(results)
        exact = [result for result in rows if result.exact]
        partial = [result for result in rows if not result.exact]
        if exact:
            self._add_section("Exact Matches")
            for result in exact:
                self._append_result(result)
        if partial:
            for entity_type in ENTITY_GROUP_ORDER:
                group = [result for result in partial if result.entity_type == entity_type]
                if not group:
                    continue
                self._add_section(_group_title(entity_type))
                for result in group:
                    self._append_result(result)
        if not rows:
            self._add_section("Results")
            self._add_empty(f"No Library profiles match \"{str(query or '').strip()}\".")
        self._finish()

    def preferred_height(self) -> int:
        row_height = 50 if self.compact else 60
        section_height = 28
        chrome = 18
        desired = chrome + self._row_count * row_height + self._section_count * section_height
        maximum = 360 if self.compact else 430
        minimum = 72
        return max(minimum, min(maximum, desired))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(320, self.preferred_height())

    def move_highlight(self, delta: int) -> None:
        if not self._rows:
            return
        self._set_highlight((self._highlight_index + int(delta)) % len(self._rows))

    def run_current(self) -> bool:
        if not (0 <= self._highlight_index < len(self._selectable)):
            return False
        item = self._selectable[self._highlight_index]
        if isinstance(item, MinimalistSearchEntry):
            self.recent_clicked.emit(item)
        else:
            self.result_clicked.emit(item)
        return True

    def highlighted_result(self) -> object | None:
        if 0 <= self._highlight_index < len(self._selectable):
            return self._selectable[self._highlight_index]
        return None

    def reset_highlight(self) -> None:
        self._highlight_index = -1
        for row in self._rows:
            row.set_highlighted(False)

    def _reset(self) -> None:
        clear_layout(self.body_layout)
        self._rows = []
        self._selectable = []
        self._highlight_index = -1
        self._row_count = 0
        self._section_count = 0

    def _finish(self) -> None:
        self.body_layout.addStretch(1)
        if self._rows:
            self._set_highlight(0)
        self.setMinimumHeight(72)
        self.setMaximumHeight(self.preferred_height())
        self.updateGeometry()

    def _append_result(self, result: EntitySearchResult) -> None:
        row = EntitySearchRow(result, compact=self.compact)
        row.clicked.connect(lambda result=result: self.result_clicked.emit(result))
        row.hovered.connect(self._row_hovered)
        self._append_row(row, result)

    def _append_row(self, row: "EntitySearchRow", item: object) -> None:
        self._rows.append(row)
        self._selectable.append(item)
        self._row_count += 1
        self.body_layout.addWidget(row)

    def _add_section(self, title: str) -> None:
        self._section_count += 1
        label = QLabel(title)
        label.setObjectName("FitCheckDropdownGroup")
        self.body_layout.addWidget(label)

    def _add_empty(self, text: str) -> None:
        self._row_count += 1
        empty = QLabel(text)
        empty.setObjectName("MinimalistPanelEmpty")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setWordWrap(True)
        empty.setMinimumHeight(54)
        self.body_layout.addWidget(empty)

    def _row_hovered(self, row: "EntitySearchRow") -> None:
        if row not in self._rows:
            return
        self._set_highlight(self._rows.index(row))

    def _set_highlight(self, index: int) -> None:
        if not self._rows:
            self._highlight_index = -1
            return
        self._highlight_index = max(0, min(index, len(self._rows) - 1))
        for row_index, row in enumerate(self._rows):
            row.set_highlighted(row_index == self._highlight_index)
        row = self._rows[self._highlight_index]
        self.scroll.ensureWidgetVisible(row, 0, 8)


class EntitySearchRow(QPushButton):
    clicked = Signal()
    hovered = Signal(object)

    def __init__(self, item: EntitySearchResult | MinimalistSearchEntry, *, compact: bool = False, recent: bool = False, parent=None):
        super().__init__(parent)
        self.item = item
        self.compact = bool(compact)
        self.recent = bool(recent)
        self._hovered = False
        self._highlighted = False
        self.setObjectName("MinimalistSearchRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFlat(True)
        self.setFixedHeight(50 if compact else 58)
        self.setMinimumWidth(260)
        super().clicked.connect(self.clicked.emit)

    def set_highlighted(self, highlighted: bool) -> None:
        self._highlighted = bool(highlighted)
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.hovered.emit(self)
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        active = self._hovered or self._highlighted
        fill = QColor("#09234a" if active else "#05152d")
        fill.setAlpha(220 if active else 174)
        border = QColor("#52aaff" if active else "#2d6aa5")
        border.setAlpha(190 if active else 100)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 7, 7)

        entity_type = _item_entity_type(self.item)
        icon = glyph_icon(_glyph_for_entity(entity_type), QColor("#d7e8ff"), 24)
        painter.drawPixmap(12, max(0, (self.height() - 24) // 2), icon.pixmap(24, 24))

        title_font = QFont(painter.font())
        title_font.setPointSize(8 if self.compact else 9)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor("#f7fbff"))
        pill = "RECENT" if self.recent else entity_type_label(entity_type).upper()
        pill_w = min(86, max(48, painter.fontMetrics().horizontalAdvance(pill) + 18))
        title_rect = QRect(48, 7 if not self.compact else 6, max(60, self.width() - pill_w - 72), 22)
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            painter.fontMetrics().elidedText(_item_title(self.item), Qt.TextElideMode.ElideRight, title_rect.width()),
        )

        subtitle = _item_subtitle(self.item)
        subtitle_font = QFont(painter.font())
        subtitle_font.setPointSize(7 if self.compact else 8)
        subtitle_font.setWeight(QFont.Weight.Normal)
        painter.setFont(subtitle_font)
        painter.setPen(QColor("#b8c7d9"))
        subtitle_top = 28 if self.compact else 30
        subtitle_rect = QRect(48, subtitle_top, max(60, self.width() - 62), 18)
        painter.drawText(
            subtitle_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            painter.fontMetrics().elidedText(subtitle, Qt.TextElideMode.ElideRight, subtitle_rect.width()),
        )

        pill_font = QFont(painter.font())
        pill_font.setPointSize(7)
        pill_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(pill_font)
        pill_rect = QRectF(self.width() - pill_w - 12, 13 if not self.compact else 12, pill_w, 24)
        pill_fill = QColor("#0a2b55")
        pill_fill.setAlpha(218 if active else 192)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pill_fill)
        painter.drawRoundedRect(pill_rect, 12, 12)
        painter.setPen(QColor("#83d8ff"))
        painter.drawText(pill_rect.toRect(), Qt.AlignmentFlag.AlignCenter, pill)


def _group_title(entity_type: str) -> str:
    return {"eoat": "EOATS", "tool": "TOOLS", "machine": "MACHINES"}.get(entity_type, "RECORDS")


def _item_entity_type(item: EntitySearchResult | MinimalistSearchEntry) -> str:
    return str(getattr(item, "entity_type", "") or "record")


def _item_title(item: EntitySearchResult | MinimalistSearchEntry) -> str:
    return str(getattr(item, "display_label", "") or getattr(item, "label", "") or getattr(item, "entity_id", "") or getattr(item, "query", "") or "Atlas record")


def _item_subtitle(item: EntitySearchResult | MinimalistSearchEntry) -> str:
    subtitle = str(getattr(item, "subtitle", "") or "")
    metadata = getattr(item, "metadata", {}) if isinstance(item, EntitySearchResult) else {}
    extras = []
    if isinstance(metadata, dict):
        for key in ("status", "current_machine", "current_eoat", "relationships", "robot", "part", "id_value"):
            value = str(metadata.get(key) or "").strip()
            if value and value not in extras:
                extras.append(value)
    text = " | ".join(piece for piece in (subtitle, *extras[:2]) if piece)
    return text or str(getattr(item, "kind", "") or entity_type_label(_item_entity_type(item)))


def _glyph_for_entity(entity_type: str) -> str:
    return {"eoat": "eoat", "tool": "mold", "machine": "machine"}.get(entity_type, "search")


__all__ = ["EntitySearchDropdown", "EntitySearchRow"]
