from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AtlasCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 14, 14, 14)
        self.layout.setSpacing(8)


class MetricCard(Card):
    def __init__(self, title: str, value: str = "-", subtitle: str = "", parent=None):
        super().__init__(parent)
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
        label = QLabel(title)
        label.setObjectName("SectionTitle")
        self.layout.addWidget(label)


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
    label = QLabel(text)
    label.setObjectName({"good": "BadgeGood", "warn": "BadgeWarn", "info": "BadgeInfo"}.get(kind, "BadgeInfo"))
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


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


__all__ = ["Card", "MetricCard", "Section", "action_row", "badge", "fill_table", "key_value_grid", "page_title", "photo_thumb"]
