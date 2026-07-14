from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
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
    QToolButton,
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


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", actions: list[QWidget] | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("PageHeader")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(12)
        text = QWidget()
        text_layout = QVBoxLayout(text)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        title_label.setWordWrap(True)
        text_layout.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("PageSubtitle")
            subtitle_label.setWordWrap(True)
            text_layout.addWidget(subtitle_label)
        layout.addWidget(text, 1)
        if actions:
            action_row_widget = QWidget()
            action_layout = QHBoxLayout(action_row_widget)
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_layout.setSpacing(8)
            for action in actions:
                action_layout.addWidget(action)
            layout.addWidget(action_row_widget, 0, Qt.AlignmentFlag.AlignTop)


class SectionCard(TitledCard):
    def __init__(self, title: str = "", subtitle: str = "", actions: list[QWidget] | None = None, *, parent=None):
        super().__init__(title, subtitle, object_name="SectionCard", margins=(16, 16, 16, 16), spacing=10, parent=parent)
        if actions:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addStretch(1)
            for action in actions:
                row_layout.addWidget(action)
            self.layout.insertWidget(0, row)


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
    def __init__(self, title: str, value: str = "-", subtitle: str = "", *, kind: str = "neutral", icon: str = "", parent=None):
        super().__init__(title, value, subtitle, kind=kind, parent=parent)
        self.setObjectName("MetricCard")
        self.setMinimumHeight(110)
        self.setProperty("metricKind", kind)
        accent = QFrame()
        accent.setObjectName({
            "good": "MetricAccentGood",
            "success": "MetricAccentGood",
            "warn": "MetricAccentWarn",
            "warning": "MetricAccentWarn",
            "bad": "MetricAccentBad",
            "danger": "MetricAccentBad",
            "primary": "MetricAccentPrimary",
            "info": "MetricAccentPrimary",
        }.get(kind, "MetricAccentNeutral"))
        accent.setFixedHeight(4)
        self.layout.insertWidget(0, accent)
        if icon:
            icon_label = QLabel(icon)
            icon_label.setObjectName("MetricIcon")
            self.layout.insertWidget(1, icon_label, 0, Qt.AlignmentFlag.AlignRight)


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
    def __init__(self, title: str = "Fit Check", subtitle: str = "", *, parent=None):
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
        super().__init__(title or "Tool Fit Check", subtitle, parent=parent)


class ModernSearchBar(QLineEdit):
    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("ModernSearchBar")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)


class ToolbarFilterRow(QWidget):
    def __init__(self, *, search_placeholder: str = "Search", parent=None):
        super().__init__(parent)
        self.setObjectName("ToolbarFilterRow")
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(8)
        self.search = ModernSearchBar(search_placeholder)
        self.layout.addWidget(self.search, 1)

    def add_filter(self, widget: QWidget) -> QWidget:
        self.layout.addWidget(widget)
        return widget

    def add_combo(self, labels: list[str]) -> QComboBox:
        combo = QComboBox()
        combo.addItems(labels)
        combo.setMinimumWidth(150)
        self.add_filter(combo)
        return combo

    def add_toggle(self, toggle: QAbstractButton) -> QAbstractButton:
        self.add_filter(toggle)
        return toggle

    def add_reset_button(self, text: str = "Reset") -> QPushButton:
        button = QPushButton(text)
        self.add_filter(button)
        return button


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
        "verified": "BadgeVerified",
        "review": "BadgeReview",
        "missing": "BadgeMissing",
        "invalid": "BadgeInvalid",
        "unknown": "BadgeUnknown",
    }

    def __init__(self, text: str, kind: str = "info", parent=None):
        super().__init__(text, parent)
        self.setObjectName(self.KIND_NAMES.get(kind, "NeutralChip"))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


class Pill(StatusChip):
    pass


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


class DocumentCard(AtlasCard):
    def __init__(
        self,
        *,
        category: str,
        title: str,
        description: str = "",
        badges: list[tuple[str, str]] | None = None,
        metadata: list[str] | None = None,
        preview: str = "",
        path_label: str = "",
        full_path: str = "",
        tags: list[str] | tuple[str, ...] = (),
        actions: list[QPushButton] | None = None,
        parent=None,
    ):
        super().__init__(parent, elevated=True, object_name="DocumentCard", margins=(16, 14, 16, 14), spacing=8)
        self.setMinimumHeight(190)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        category_label = QLabel(category.upper())
        category_label.setObjectName("DocumentCategory")
        top.addWidget(category_label)
        top.addStretch(1)
        for text, kind in badges or []:
            top.addWidget(StatusChip(text, kind))
        self.layout.addLayout(top)

        title_label = QLabel(title)
        title_label.setObjectName("DocumentTitle")
        title_label.setWordWrap(True)
        self.layout.addWidget(title_label)

        if description:
            description_label = QLabel(description)
            description_label.setObjectName("DocumentDescription")
            description_label.setWordWrap(True)
            self.layout.addWidget(description_label)

        if metadata:
            meta = QLabel("  |  ".join(item for item in metadata if item))
            meta.setObjectName("DocumentMetadata")
            meta.setWordWrap(True)
            self.layout.addWidget(meta)

        if preview:
            preview_label = QLabel(preview)
            preview_label.setObjectName("DocumentPreview")
            preview_label.setWordWrap(True)
            preview_label.setMaximumHeight(52)
            self.layout.addWidget(preview_label)

        if path_label:
            path = QLabel(path_label)
            path.setObjectName("DocumentPath")
            path.setWordWrap(False)
            path.setToolTip(full_path or path_label)
            self.layout.addWidget(path)

        if tags:
            self.layout.addWidget(chip_group(tags, kind="outline", per_row=5, limit=8))

        if actions:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            row.addStretch(1)
            for action in actions:
                row.addWidget(action)
            self.layout.addLayout(row)


class ChartCard(SectionCard):
    def __init__(self, title: str, subtitle: str = "", chart_widget: QWidget | None = None, *, parent=None):
        super().__init__(title, subtitle, parent=parent)
        self.setObjectName("ChartCard")
        self.setMinimumHeight(300)
        if chart_widget is None:
            chart_widget = EmptyStateWidget("No chart data", "Atlas does not have enough cached data for this chart yet.")
        chart_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.layout.addWidget(chart_widget, 1)


class AccordionSection(QFrame):
    def __init__(self, title: str, summary: str = "", *, status_text: str = "", status_kind: str = "info", expanded: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("AccordionSection")
        self.setProperty("expanded", expanded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        self.header = QToolButton()
        self.header.setObjectName("AccordionHeader")
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.ArrowType.UpArrow if expanded else Qt.ArrowType.DownArrow)
        self.header.setText(title)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header.setMinimumHeight(58)
        self.root_layout.addWidget(self.header)

        self.summary_row = QWidget()
        summary_layout = QHBoxLayout(self.summary_row)
        summary_layout.setContentsMargins(14, 0, 14, 10)
        summary_layout.setSpacing(8)
        self.summary_label = QLabel(summary)
        self.summary_label.setObjectName("AccordionSummary")
        self.summary_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_label, 1)
        self.status_chip = StatusChip(status_text, status_kind)
        self.status_chip.setVisible(bool(status_text))
        summary_layout.addWidget(self.status_chip)
        self.root_layout.addWidget(self.summary_row)

        self.body = QWidget()
        self.body.setObjectName("AccordionBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(14, 4, 14, 14)
        self.body_layout.setSpacing(10)
        self.body.setVisible(expanded)
        self.root_layout.addWidget(self.body)
        self.header.toggled.connect(self._set_expanded)

    def _set_expanded(self, expanded: bool) -> None:
        self.header.setArrowType(Qt.ArrowType.UpArrow if expanded else Qt.ArrowType.DownArrow)
        self.body.setVisible(expanded)
        self.setProperty("expanded", expanded)
        self.style().unpolish(self)
        self.style().polish(self)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.body_layout.addWidget(widget, stretch)

    def set_status(self, text: str, kind: str = "info") -> None:
        self.status_chip.setText(text)
        self.status_chip.setObjectName(StatusChip.KIND_NAMES.get(kind, "NeutralChip"))
        self.status_chip.setVisible(bool(text))
        self.status_chip.style().unpolish(self.status_chip)
        self.status_chip.style().polish(self.status_chip)

    def set_summary(self, text: str) -> None:
        self.summary_label.setText(text)


def page_title(title: str, subtitle: str = "") -> QWidget:
    return PageHeader(title, subtitle)


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
    "AccordionSection",
    "AtlasCard",
    "AtlasHero",
    "Card",
    "ChartCard",
    "ChecklistCard",
    "CompactStatCard",
    "CompatibilityCard",
    "CompatibilityPathWidget",
    "DenseDataPanel",
    "DetailCard",
    "DocumentCard",
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
    "PageHeader",
    "Pill",
    "PhotoGalleryCard",
    "PhotoStripWidget",
    "PrimaryCard",
    "ProfileHeaderCard",
    "ReadinessScoreWidget",
    "SecondaryCard",
    "Section",
    "SectionCard",
    "SectionHeader",
    "StatusChip",
    "SuccessCard",
    "ToolbarFilterRow",
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
