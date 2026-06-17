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
    def __init__(
        self,
        parent=None,
        *,
        elevated: bool = False,
        object_name: str = "AtlasCard",
        margins: tuple[int, int, int, int] = (14, 14, 14, 14),
        spacing: int = 8,
    ):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(*margins)
        self.layout.setSpacing(spacing)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        if elevated:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(18)
            shadow.setOffset(0, 5)
            shadow.setColor(QColor(15, 32, 51, 34))
            self.setGraphicsEffect(shadow)


Card = AtlasCard


class TitledCard(AtlasCard):
    title_object_name = "CardTitle"
    eyebrow_object_name = "EyebrowLabel"
    subtitle_object_name = "MutedText"

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        *,
        eyebrow: str = "",
        object_name: str = "PrimaryCard",
        elevated: bool = False,
        margins: tuple[int, int, int, int] = (16, 16, 16, 16),
        spacing: int = 10,
        parent=None,
    ):
        super().__init__(parent, elevated=elevated, object_name=object_name, margins=margins, spacing=spacing)
        if eyebrow:
            eyebrow_label = QLabel(eyebrow.upper())
            eyebrow_label.setObjectName(self.eyebrow_object_name)
            eyebrow_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            self.layout.addWidget(eyebrow_label)
        if title:
            title_label = QLabel(title)
            title_label.setObjectName(self.title_object_name)
            title_label.setWordWrap(True)
            title_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            self.layout.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName(self.subtitle_object_name)
            subtitle_label.setWordWrap(True)
            subtitle_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            self.layout.addWidget(subtitle_label)


class HeroPanel(TitledCard):
    title_object_name = "HeroTitle"
    subtitle_object_name = "HeroSubtitle"

    def __init__(self, title: str = "", subtitle: str = "", *, eyebrow: str = "", parent=None):
        super().__init__(
            title,
            subtitle,
            eyebrow=eyebrow,
            object_name="HeroPanel",
            elevated=True,
            margins=(18, 18, 18, 18),
            spacing=10,
            parent=parent,
        )


class AtlasHero(HeroPanel):
    pass


class PrimaryCard(TitledCard):
    def __init__(self, title: str = "", subtitle: str = "", *, eyebrow: str = "", parent=None):
        super().__init__(title, subtitle, eyebrow=eyebrow, object_name="PrimaryCard", elevated=True, parent=parent)


class SecondaryCard(TitledCard):
    title_object_name = "CardTitle"

    def __init__(self, title: str = "", subtitle: str = "", *, eyebrow: str = "", parent=None):
        super().__init__(title, subtitle, eyebrow=eyebrow, object_name="SecondaryCard", parent=parent)


class DetailCard(TitledCard):
    title_object_name = "DetailTitle"

    def __init__(self, title: str = "", subtitle: str = "", *, eyebrow: str = "", parent=None):
        super().__init__(
            title,
            subtitle,
            eyebrow=eyebrow,
            object_name="DetailCard",
            margins=(12, 12, 12, 12),
            spacing=7,
            parent=parent,
        )


class WarningCard(TitledCard):
    title_object_name = "WarningTitle"

    def __init__(self, title: str = "", subtitle: str = "", *, severity: str = "warn", parent=None):
        object_name = "WarningCard" if severity != "bad" else "DangerCard"
        super().__init__(title, subtitle, object_name=object_name, margins=(14, 14, 14, 14), spacing=8, parent=parent)


class SuccessCard(TitledCard):
    def __init__(self, title: str = "", subtitle: str = "", *, parent=None):
        super().__init__(title, subtitle, object_name="SuccessCard", margins=(14, 14, 14, 14), spacing=8, parent=parent)


class InfoPanel(TitledCard):
    title_object_name = "DetailTitle"

    def __init__(self, title: str = "", subtitle: str = "", *, parent=None):
        super().__init__(title, subtitle, object_name="InfoPanel", margins=(12, 12, 12, 12), spacing=7, parent=parent)


class CompactStatCard(AtlasCard):
    def __init__(self, title: str, value: str = "-", subtitle: str = "", *, kind: str = "neutral", parent=None):
        super().__init__(parent, object_name="CompactStatCard", margins=(12, 12, 12, 12), spacing=4)
        self.setMinimumHeight(82)
        self.kind = kind
        title_label = QLabel(title)
        title_label.setObjectName("MetricLabel")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("MetricValue")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("MicroText")
        self.subtitle_label.setWordWrap(True)
        self.layout.addWidget(title_label)
        self.layout.addWidget(self.value_label)
        self.layout.addWidget(self.subtitle_label)

    def set_value(self, value: str, subtitle: str = "") -> None:
        self.value_label.setText(value)
        self.subtitle_label.setText(subtitle)


class MetricCard(CompactStatCard):
    def __init__(self, title: str, value: str = "-", subtitle: str = "", parent=None):
        super().__init__(title, value, subtitle, parent=parent)


class FeatureActionCard(TitledCard):
    def __init__(self, title: str, description: str, button_text: str = "Open", *, accent: str = "", parent=None):
        super().__init__(
            title,
            description,
            eyebrow=accent,
            object_name="FeatureActionCard",
            elevated=True,
            margins=(14, 14, 14, 14),
            spacing=9,
            parent=parent,
        )
        self.setMinimumHeight(132)
        self.button = QPushButton(button_text)
        self.button.setObjectName("PrimaryButton")
        self.button.setFixedHeight(28)
        self.button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.layout.addWidget(self.button)


class ExportActionCard(FeatureActionCard):
    def __init__(self, title: str, description: str, button_text: str = "Export", parent=None):
        super().__init__(title, description, button_text, accent="Report", parent=parent)
        self.setObjectName("ExportActionCard")


class ProfileHeaderCard(HeroPanel):
    title_object_name = "ProfileTitle"
    subtitle_object_name = "ProfileSubtitle"

    def __init__(self, title: str = "", subtitle: str = "", *, eyebrow: str = "", parent=None):
        super().__init__(title, subtitle, eyebrow=eyebrow, parent=parent)
        self.setObjectName("ProfileHeaderCard")


class CompatibilityCard(PrimaryCard):
    def __init__(self, title: str = "Compatibility", subtitle: str = "", *, parent=None):
        super().__init__(title, subtitle, eyebrow="Flow", parent=parent)
        self.setObjectName("CompatibilityCard")


class PhotoGalleryCard(PrimaryCard):
    def __init__(self, title: str = "Photos", subtitle: str = "", *, parent=None):
        super().__init__(title, subtitle, eyebrow="Visual Evidence", parent=parent)
        self.setObjectName("PhotoGalleryCard")


class ChecklistCard(PrimaryCard):
    def __init__(self, title: str = "Checklist", subtitle: str = "", *, parent=None):
        super().__init__(title, subtitle, eyebrow="Readiness", parent=parent)
        self.setObjectName("ChecklistCard")


class DenseDataPanel(TitledCard):
    title_object_name = "DetailTitle"

    def __init__(self, title: str = "", subtitle: str = "", *, parent=None):
        super().__init__(
            title,
            subtitle,
            object_name="DenseDataPanel",
            margins=(12, 12, 12, 12),
            spacing=8,
            parent=parent,
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)


class EOATProfileCard(SecondaryCard):
    def __init__(self, title: str = "", subtitle: str = "", *, parent=None):
        super().__init__(title, subtitle, eyebrow="EOAT", parent=parent)


class MachineProfileCard(SecondaryCard):
    def __init__(self, title: str = "", subtitle: str = "", *, parent=None):
        super().__init__(title, subtitle, eyebrow="Machine", parent=parent)


class ToolCompatibilityCard(CompatibilityCard):
    def __init__(self, title: str = "", subtitle: str = "", *, parent=None):
        super().__init__(title or "Tool Compatibility", subtitle, parent=parent)


class ModernSearchBar(QLineEdit):
    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("ModernSearchBar")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)


class Section(SecondaryCard):
    def __init__(self, title: str, parent=None):
        super().__init__(title, parent=parent)


class SectionHeader(QLabel):
    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.setObjectName("CardTitle")


class StatusChip(QLabel):
    KIND_NAMES = {
        "primary": "PrimaryChip",
        "neutral": "NeutralChip",
        "success": "SuccessChip",
        "warning": "WarningChip",
        "danger": "DangerChip",
        "outline": "OutlineChip",
        "ghost": "GhostChip",
        "count": "CountChip",
        "good": "SuccessChip",
        "warn": "WarningChip",
        "bad": "DangerChip",
        "info": "PrimaryChip",
    }

    def __init__(self, text: str, kind: str = "info", parent=None):
        super().__init__(text, parent)
        self.setObjectName(self.KIND_NAMES.get(kind, "NeutralChip"))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


class WarningChip(StatusChip):
    def __init__(self, text: str, parent=None):
        super().__init__(text, "warning", parent)


class EmptyStateWidget(InfoPanel):
    def __init__(self, title: str, message: str = "", parent=None):
        super().__init__(title, message, parent=parent)
        self.setObjectName("EmptyState")


class CompatibilityPathWidget(QWidget):
    def __init__(self, tool: str, eoat: str, machines: list[str] | tuple[str, ...], parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(StatusChip(f"Tool {tool}" if tool else "Tool missing", "outline" if tool else "bad"))
        layout.addWidget(_flow_arrow())
        layout.addWidget(StatusChip(eoat or "EOAT missing", "success" if eoat else "bad"))
        layout.addWidget(_flow_arrow())
        if machines:
            layout.addWidget(chip_group(machines, kind="primary", per_row=5, limit=10))
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


class MiniProgressBar(QWidget):
    def __init__(self, value: int, *, kind: str = "good", parent=None):
        super().__init__(parent)
        self.setObjectName("MiniProgressTrack")
        self.setFixedHeight(8)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        fill = QFrame()
        fill.setObjectName({"good": "MiniProgressGood", "warn": "MiniProgressWarn", "bad": "MiniProgressBad"}.get(kind, "MiniProgressGood"))
        fill.setMinimumWidth(max(8, min(100, int(value))))
        fill.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.layout.addWidget(fill, max(1, min(100, int(value))))
        self.layout.addWidget(spacer, max(1, 100 - max(0, min(100, int(value)))))


class ReadinessScoreWidget(ChecklistCard):
    def __init__(self, score: int, summary: str, items: list[dict[str, object]], title: str = "Installation Readiness", parent=None):
        super().__init__(title, summary, parent=parent)
        score_kind_value = score_kind(score)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        score_label = QLabel(f"{score}%")
        score_label.setObjectName("MetricValue")
        header.addWidget(score_label)
        header.addWidget(StatusChip(_score_label(score), score_kind_value))
        header.addStretch(1)
        self.layout.addLayout(header)
        self.layout.addWidget(MiniProgressBar(score, kind=score_kind_value))

        grid = QGridLayout()
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)
        for row, item in enumerate(items):
            grid.addWidget(StatusChip(str(item["status"]), str(item["kind"])), row, 0)
            name = QLabel(str(item["name"]))
            name.setObjectName("MetricLabel")
            detail = QLabel(str(item["detail"]))
            detail.setObjectName("BodyText")
            detail.setWordWrap(True)
            grid.addWidget(name, row, 1)
            grid.addWidget(detail, row, 2)
        grid.setColumnStretch(2, 1)
        self.layout.addLayout(grid)


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
        layout.addWidget(StatusChip(f"+{len(items) - limit} more", "count"), index // per_row, index % per_row)
    layout.setColumnStretch(per_row, 1)
    return widget


def fill_table(table: QTableWidget, rows: list[dict[str, Any]], columns: list[str]) -> None:
    table.setSortingEnabled(False)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setCornerButtonEnabled(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(34)
    table.horizontalHeader().setStretchLastSection(True)
    table.clear()
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setRowCount(len(rows))
    table.setMinimumHeight(120)
    for row_index, row in enumerate(rows):
        for column_index, column in enumerate(columns):
            item = QTableWidgetItem(str(row.get(column, "")))
            item.setData(Qt.ItemDataRole.UserRole, row)
            table.setItem(row_index, column_index, item)
        table.setRowHeight(row_index, 34)
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
        key_label.setObjectName("MetricLabel")
        value_label = QLabel(value or "-")
        value_label.setObjectName("BodyText")
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
    label.setObjectName("PhotoThumb")
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


def _flow_arrow() -> QLabel:
    arrow = QLabel("->")
    arrow.setObjectName("MicroText")
    arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return arrow


def _score_label(score: int) -> str:
    if score >= 80:
        return "Ready"
    if score >= 50:
        return "Review"
    return "Needs cleanup"


def _short_label(value: str, limit: int = 34) -> str:
    return value if len(value) <= limit else f"{value[: limit - 3]}..."


__all__ = [
    "AtlasCard",
    "AtlasHero",
    "Card",
    "ChecklistCard",
    "CompactStatCard",
    "CompatibilityCard",
    "CompatibilityPathWidget",
    "DenseDataPanel",
    "DetailCard",
    "EOATProfileCard",
    "EmptyStateWidget",
    "ExportActionCard",
    "FeatureActionCard",
    "HeroPanel",
    "InfoPanel",
    "MachineProfileCard",
    "MetricCard",
    "MiniProgressBar",
    "ModernSearchBar",
    "PhotoGalleryCard",
    "PhotoStripWidget",
    "PrimaryCard",
    "ProfileHeaderCard",
    "ReadinessScoreWidget",
    "SecondaryCard",
    "Section",
    "SectionHeader",
    "StatusChip",
    "SuccessCard",
    "ToolCompatibilityCard",
    "WarningCard",
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
