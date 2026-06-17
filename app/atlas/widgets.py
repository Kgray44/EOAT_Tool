from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class AtlasCard(QFrame):
    def __init__(self, parent=None, *, elevated: bool = False, object_name: str = "AtlasCard"):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 14, 14, 14)
        self.layout.setSpacing(8)
        if elevated:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(18)
            shadow.setOffset(0, 5)
            shadow.setColor(QColor(15, 32, 51, 34))
            self.setGraphicsEffect(shadow)


Card = AtlasCard


class AtlasHero(AtlasCard):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent, elevated=True, object_name="AtlasHero")
        self.title_label = QLabel(title)
        self.title_label.setObjectName("HeroTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("HeroSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.layout.addWidget(self.title_label)
        if subtitle:
            self.layout.addWidget(self.subtitle_label)


class ModernSearchBar(QLineEdit):
    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("ModernSearchBar")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)


class MetricCard(Card):
    def __init__(self, title: str, value: str = "-", subtitle: str = "", parent=None):
        super().__init__(parent, elevated=True, object_name="MetricCard")
        title_label = QLabel(title)
        title_label.setObjectName("MutedText")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("MetricValue")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("MutedText")
        self.subtitle_label.setWordWrap(True)
        self.layout.addWidget(title_label)
        self.layout.addWidget(self.value_label)
        self.layout.addWidget(self.subtitle_label)

    def set_value(self, value: str, subtitle: str = "") -> None:
        self.value_label.setText(value)
        self.subtitle_label.setText(subtitle)


class Section(Card):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.layout.addWidget(SectionHeader(title))


class SectionHeader(QLabel):
    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.setObjectName("SectionTitle")


class StatusChip(QLabel):
    def __init__(self, text: str, kind: str = "info", parent=None):
        super().__init__(text, parent)
        self.setObjectName({"good": "BadgeGood", "warn": "BadgeWarn", "bad": "BadgeBad", "info": "BadgeInfo"}.get(kind, "BadgeInfo"))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class WarningChip(StatusChip):
    def __init__(self, text: str, parent=None):
        super().__init__(text, "warn", parent)


class EmptyStateWidget(AtlasCard):
    def __init__(self, title: str, message: str = "", parent=None):
        super().__init__(parent, object_name="EmptyState")
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        message_label = QLabel(message)
        message_label.setObjectName("MutedText")
        message_label.setWordWrap(True)
        self.layout.addWidget(title_label)
        if message:
            self.layout.addWidget(message_label)


class CompatibilityPathWidget(QWidget):
    def __init__(self, tool: str, eoat: str, machines: list[str] | tuple[str, ...], parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(StatusChip(f"Tool {tool}" if tool else "Tool missing", "info" if tool else "bad"))
        layout.addWidget(QLabel("->"))
        layout.addWidget(StatusChip(eoat or "EOAT missing", "good" if eoat else "bad"))
        layout.addWidget(QLabel("->"))
        if machines:
            layout.addWidget(chip_group(machines, kind="info", per_row=5, limit=10))
        else:
            layout.addWidget(StatusChip("Machine link missing", "bad"))
        layout.addStretch(1)


class PhotoStripWidget(QWidget):
    def __init__(self, photo_paths: list[str] | tuple[str, ...], *, max_items: int = 8, thumb_size: tuple[int, int] = (118, 88), parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for path in list(photo_paths)[:max_items]:
            layout.addWidget(photo_thumb(path, size=thumb_size))
        if not photo_paths:
            empty = QLabel("No linked photos found.")
            empty.setObjectName("MutedText")
            layout.addWidget(empty)
        layout.addStretch(1)


class ReadinessScoreWidget(AtlasCard):
    def __init__(self, score: int, summary: str, items: list[dict[str, object]], title: str = "Installation Readiness", parent=None):
        super().__init__(parent)
        self.layout.addWidget(SectionHeader(title))
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(StatusChip(f"Readiness {score}%", score_kind(score)))
        label = QLabel(summary)
        label.setWordWrap(True)
        header.addWidget(label, 1)
        self.layout.addLayout(header)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)
        for row, item in enumerate(items):
            grid.addWidget(StatusChip(str(item["status"]), str(item["kind"])), row, 0)
            name = QLabel(str(item["name"]))
            name.setObjectName("MutedText")
            detail = QLabel(str(item["detail"]))
            detail.setWordWrap(True)
            grid.addWidget(name, row, 1)
            grid.addWidget(detail, row, 2)
        grid.setColumnStretch(2, 1)
        self.layout.addLayout(grid)


class ExportActionCard(AtlasCard):
    def __init__(self, title: str, description: str, button_text: str = "Export", parent=None):
        super().__init__(parent, elevated=True, object_name="ActionCard")
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        description_label = QLabel(description)
        description_label.setObjectName("MutedText")
        description_label.setWordWrap(True)
        self.button = QPushButton(button_text)
        self.button.setObjectName("PrimaryButton")
        self.layout.addWidget(title_label)
        self.layout.addWidget(description_label)
        self.layout.addWidget(self.button)


class EOATProfileCard(AtlasCard):
    pass


class MachineProfileCard(AtlasCard):
    pass


class ToolCompatibilityCard(AtlasCard):
    pass


def page_title(title: str, subtitle: str = "") -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 6)
    title_label = QLabel(title)
    title_label.setObjectName("PageTitle")
    layout.addWidget(title_label)
    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("MutedText")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)
    return container


def badge(text: str, kind: str = "info") -> QLabel:
    return StatusChip(text, kind)


def score_kind(score: int) -> str:
    if score >= 80:
        return "good"
    if score >= 50:
        return "warn"
    return "bad"


def chip_group(values, *, kind: str = "info", empty: str = "-", per_row: int = 4, limit: int = 18) -> QWidget:
    widget = QWidget()
    layout = QGridLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(6)
    layout.setVerticalSpacing(5)
    items = [str(value).strip() for value in values if str(value).strip()]
    chip_kind = kind
    if not items:
        items = [empty]
        chip_kind = "warn"
    visible = items[:limit]
    for index, text in enumerate(visible):
        chip = StatusChip(_short_label(text), chip_kind)
        chip.setToolTip(text)
        layout.addWidget(chip, index // per_row, index % per_row)
    if len(items) > limit:
        index = len(visible)
        layout.addWidget(StatusChip(f"+{len(items) - limit} more", "info"), index // per_row, index % per_row)
    layout.setColumnStretch(per_row, 1)
    return widget


def fill_table(table: QTableWidget, rows: list[dict[str, Any]], columns: list[str]) -> None:
    table.setSortingEnabled(False)
    table.clear()
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column_index, column in enumerate(columns):
            item = QTableWidgetItem(str(row.get(column, "")))
            item.setData(Qt.ItemDataRole.UserRole, row)
            table.setItem(row_index, column_index, item)
    table.resizeColumnsToContents()
    table.setSortingEnabled(True)


def key_value_grid(values: list[tuple[str, str]]) -> QWidget:
    widget = QWidget()
    layout = QGridLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(18)
    layout.setVerticalSpacing(6)
    for row, (key, value) in enumerate(values):
        key_label = QLabel(key)
        key_label.setObjectName("MutedText")
        value_label = QLabel(value or "-")
        value_label.setWordWrap(True)
        layout.addWidget(key_label, row, 0)
        layout.addWidget(value_label, row, 1)
    layout.setColumnStretch(1, 1)
    return widget


def action_row(*buttons: QPushButton) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for button in buttons:
        layout.addWidget(button)
    layout.addStretch(1)
    return widget


def photo_thumb(path: str, *, size: tuple[int, int] = (150, 110)) -> QLabel:
    label = QLabel()
    label.setFixedSize(size[0], size[1])
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet("background: #eef3f9; border: 1px solid #d7dee8; border-radius: 6px;")
    target = Path(path)
    if target.exists():
        pixmap = QPixmap(str(target))
        if not pixmap.isNull():
            label.setPixmap(
                pixmap.scaled(size[0] - 8, size[1] - 8, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
            label.setToolTip(str(target))
            return label
    label.setText(target.name or "Photo")
    label.setWordWrap(True)
    return label


def _short_label(value: str, limit: int = 34) -> str:
    return value if len(value) <= limit else f"{value[: limit - 3]}..."


__all__ = [
    "AtlasCard",
    "AtlasHero",
    "Card",
    "CompatibilityPathWidget",
    "EOATProfileCard",
    "EmptyStateWidget",
    "ExportActionCard",
    "MachineProfileCard",
    "MetricCard",
    "ModernSearchBar",
    "PhotoStripWidget",
    "ReadinessScoreWidget",
    "Section",
    "SectionHeader",
    "StatusChip",
    "ToolCompatibilityCard",
    "WarningChip",
    "action_row",
    "badge",
    "chip_group",
    "fill_table",
    "key_value_grid",
    "page_title",
    "photo_thumb",
    "score_kind",
]
