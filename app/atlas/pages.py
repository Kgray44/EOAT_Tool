from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QMargins, QPointF, QPropertyAnimation, QSize, Qt, QTimer, Slot
from PySide6.QtGui import QAction, QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
except ImportError:  # pragma: no cover - depends on the installed Qt build
    QPdfDocument = None
    QPdfView = None

try:
    from PySide6.QtCharts import (
        QBarCategoryAxis,
        QBarSeries,
        QBarSet,
        QChart,
        QChartView,
        QHorizontalBarSeries,
        QPieSeries,
        QValueAxis,
    )
except ImportError:  # pragma: no cover - depends on the installed Qt build
    QBarCategoryAxis = None
    QBarSeries = None
    QBarSet = None
    QChart = None
    QChartView = None
    QHorizontalBarSeries = None
    QPieSeries = None
    QValueAxis = None

from core.atlas_exports import (
    atlas_export_dir,
    build_eoat_qr_payload,
    decode_qr_payload_from_image,
    export_compare_summary,
    export_compatibility_matrix,
    export_eoat_qr_label,
    export_eoat_summary,
    export_install_packet,
    export_machine_summary,
    export_recommendation_summary,
    export_tool_summary,
    qr_payload_warning,
    recommended_qr_print_size,
    validate_eoat_qr_payload,
)
from core.atlas_health import (
    RelationshipHealth,
    eoat_relationship_health,
    health_badge_kind,
    health_label,
    machine_relationship_health,
    tool_relationship_health,
    validation_relationship_health,
)
from core.atlas_information_library import (
    InformationLibraryEntry,
    InformationSection,
    LibrarySource,
    build_information_entries,
    entry_type_label,
    information_score,
    information_snippet,
    seed_information_entries,
)
from core.atlas_models import (
    AtlasDataBundle,
    EOATRecord,
    MachineRecord,
    RecommendationResult,
    StandardReference,
    ToolRecord,
    WarningItem,
)
from core.atlas_recommendations import recommend_for_query
from core.atlas_reports import atlas_report_catalog, generate_atlas_report, latest_atlas_report
from core.atlas_setup_packets import (
    COMPATIBILITY_CONFIRMED,
    PACKET_TYPE_CHOICES,
    PACKET_TYPE_LABELS,
    PHOTO_INCLUSION_CHOICES,
    PHOTO_INCLUSION_LABELS,
    SetupPacketOptions,
    build_setup_packet_context,
    selectable_eoats,
    selectable_machines,
    selectable_tools,
    validate_setup_context,
)
from core.atlas_utils import normalized_eoat_key, normalized_machine_key, normalized_tool_key
from core.compatibility_engine import compatibility_matrix_rows
from core.openers import open_path
from core.paths import resolve_project_paths
from core.performance import log_perf_marker, perf_timer
from core.setup_packet_pdf import export_setup_packet_pdf
from core.standards_index import STANDARD_EXTENSIONS

from .photo_loader import SUPPORTED_IMAGE_SUFFIXES, THUMB_PRELOAD_SIZE, PhotoLoadManager, decode_photo_image
from .photo_loader import PhotoLoadResult as AsyncPhotoLoadResult
from .widgets import (
    AccordionSection,
    AtlasHero,
    ChartCard,
    ChecklistCard,
    CompactStatCard,
    CompatibilityCard,
    CompatibilityPathWidget,
    DenseDataPanel,
    DetailCard,
    DocumentCard,
    EmptyStateWidget,
    EOATProfileCard,
    ExportActionCard,
    FeatureActionCard,
    InfoPanel,
    MetricCard,
    MiniProgressBar,
    ModernSearchBar,
    PageHeader,
    PhotoGalleryCard,
    PhotoStripWidget,
    PrimaryCard,
    ProfileHeaderCard,
    ReadinessScoreWidget,
    SecondaryCard,
    SectionCard,
    SuccessCard,
    ToolbarFilterRow,
    ToolCompatibilityCard,
    WarningCard,
    action_row,
    badge,
    fill_table,
    key_value_grid,
    page_title,
)

LOGGER = logging.getLogger(__name__)


class BaseAtlasPage(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.bundle: AtlasDataBundle | None = None

    def set_bundle(self, bundle: AtlasDataBundle | None) -> None:
        self.bundle = bundle
        self.refresh()

    def refresh(self) -> None:
        return None

    def settings_changed(self) -> None:
        return None

    def require_bundle(self) -> AtlasDataBundle | None:
        if self.bundle is None:
            QMessageBox.information(self, "EOAT Atlas", "Atlas data is still loading.")
            return None
        return self.bundle


class HomePage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        hero = AtlasHero("EOAT Atlas", "Fast read-only lookup for EOAT compatibility, photos, warnings, and install readiness.", eyebrow="Command Deck")
        self.search = ModernSearchBar("Enter Tool #, Machine #, EOAT ID, part name, robot type, or keyword")
        self.search.returnPressed.connect(self._run_search)
        what_button = QPushButton("What Do I Need?")
        what_button.setObjectName("PrimaryButton")
        what_button.clicked.connect(self._run_search)
        row = QHBoxLayout()
        row.addWidget(self.search, 1)
        row.addWidget(what_button)
        hero.layout.addLayout(row)
        layout.addWidget(hero)

        quick_grid = QGridLayout()
        quick_grid.setSpacing(10)
        quick_actions = [
            ("Search EOAT", "Profile, readiness, warnings, photos.", "eoats", "Profile"),
            ("Search Machine", "Robot context and compatible EOATs.", "machines", "Machine"),
            ("Search Tool #", "Find linked EOATs and machines.", "tools", "Tool"),
            ("Browse Photos", "Photo folders and missing categories.", "photos", "Visual"),
            ("Analytics Dashboard", "Coverage, documentation, and warning trends.", "overview", "Insights"),
            ("Standards & Work Instructions", "Controlled standards, PM guidance, and useful reports.", "standards", "Library"),
        ]
        for index, (title, description, page, accent) in enumerate(quick_actions):
            card = FeatureActionCard(title, description, "Open", accent=accent)
            card.button.clicked.connect(lambda _checked=False, page=page: self.controller.show_page(page))
            quick_grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(quick_grid)

        self.metrics = {
            "eoats": CompactStatCard("EOATs documented"),
            "machines": CompactStatCard("Machines covered"),
            "tools": CompactStatCard("Tools covered"),
            "photos": CompactStatCard("Photos linked"),
            "docs": CompactStatCard("Avg. documentation"),
            "warnings": CompactStatCard("Open warnings"),
        }
        metric_grid = QGridLayout()
        for index, card in enumerate(self.metrics.values()):
            metric_grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(metric_grid)

        self.source_card = InfoPanel("Source Status", "Background sources are cached and refreshed manually when needed.")
        self.source_grid = QGridLayout()
        self.source_grid.setContentsMargins(0, 0, 0, 0)
        self.source_grid.setSpacing(8)
        self.source_card.layout.addLayout(self.source_grid)
        layout.addWidget(self.source_card)
        layout.addStretch(1)

    def refresh(self) -> None:
        if self.bundle is None:
            for card in self.metrics.values():
                card.set_value("-", "Loading")
            return
        metrics = self.bundle.metrics
        self.metrics["eoats"].set_value(str(metrics.get("eoats_documented", 0)))
        self.metrics["machines"].set_value(str(metrics.get("machines_covered", 0)))
        self.metrics["tools"].set_value(str(metrics.get("tools_covered", 0)))
        self.metrics["photos"].set_value(str(metrics.get("photos_linked", 0)))
        self.metrics["docs"].set_value(f"{metrics.get('documentation_average', 0)}%")
        self.metrics["warnings"].set_value(str(metrics.get("open_warnings", 0)), f"Refreshed {self.bundle.loaded_at}")
        _clear_layout(self.source_grid)
        for index, status in enumerate(self.bundle.source_statuses):
            chip = badge(f"{status.label}: {'Ready' if status.available else 'Missing'}", "good" if status.available else "warn")
            chip.setToolTip(f"{status.message}\n{status.path}")
            self.source_grid.addWidget(chip, index // 3, index % 3)

    def _run_search(self) -> None:
        query = self.search.text().strip()
        if query:
            self.controller.open_recommendation(query)
        else:
            self.controller.show_page("what")


class WhatNeedPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.result: RecommendationResult | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("What Do I Need?", "Enter any known tool, machine, EOAT, part, robot, or keyword."))
        row = QHBoxLayout()
        self.input = ModernSearchBar("Example: Tool 12345, Machine 14, P4-EOAT-0041, silicone OD")
        self.input.returnPressed.connect(self.run)
        run_button = QPushButton("Get Recommendation")
        run_button.setObjectName("PrimaryButton")
        run_button.clicked.connect(self.run)
        row.addWidget(self.input, 1)
        row.addWidget(run_button)
        layout.addLayout(row)
        self.result_scroll = QScrollArea()
        self.result_scroll.setWidgetResizable(True)
        self.result_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.result_widget = QWidget()
        self.result_layout = QVBoxLayout(self.result_widget)
        self.result_layout.setContentsMargins(0, 0, 0, 0)
        self.result_layout.setSpacing(12)
        self.result_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.result_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.result_scroll.setWidget(self.result_widget)
        layout.addWidget(self.result_scroll, 1)
        open_button = QPushButton("Open EOAT Profile")
        open_button.clicked.connect(self.open_best)
        packet_button = QPushButton("Changeover Packet")
        packet_button.clicked.connect(self.generate_install_packet)
        copy_button = QPushButton("Copy Recommendation")
        copy_button.clicked.connect(self.copy_result)
        export_button = QPushButton("Export Summary")
        export_button.clicked.connect(self.export_result)
        layout.addWidget(action_row(open_button, packet_button, copy_button, export_button))
        self._render_empty()

    def run_query(self, query: str) -> None:
        self.input.setText(query)
        self.run()

    def run(self) -> None:
        bundle = self.require_bundle()
        if bundle is None:
            return
        query = self.input.text().strip()
        if not query:
            return
        self.result = recommend_for_query(bundle, query)
        if hasattr(self.controller, "photo_loader"):
            self.controller.photo_loader.update_related_photo_paths(
                [photo.path for photo in self.result.photos],
                reason="Idle preload: What Do I Need? result",
            )
        self._render_result()

    def open_best(self) -> None:
        if self.result and self.result.best:
            self.controller.open_eoat(self.result.best.eoat_id)

    def open_photos_for(self, eoat_id: str) -> None:
        if hasattr(self.controller, "open_photos"):
            self.controller.open_photos(eoat_id)

    def open_tool_value(self, tool: str) -> None:
        if tool and hasattr(self.controller, "open_tool"):
            self.controller.open_tool(tool)

    def open_machine_value(self, machine: str) -> None:
        if machine and hasattr(self.controller, "open_machine"):
            self.controller.open_machine(machine)

    def copy_result(self) -> None:
        if self.result:
            QApplication.clipboard().setText(_recommendation_text(self.result))

    def export_result(self) -> None:
        bundle = self.require_bundle()
        if bundle is None or self.result is None:
            return
        path = export_recommendation_summary(bundle, self.result)
        self.controller.show_status(f"Exported recommendation: {path}")

    def generate_install_packet(self) -> None:
        bundle = self.require_bundle()
        if bundle is None or self.result is None:
            return
        if hasattr(self.controller, "open_setup_packet"):
            self.controller.open_setup_packet(recommendation=self.result, context_label="What Do I Need?")

    def _render_empty(self) -> None:
        _clear_layout(self.result_layout)
        self.result_layout.addWidget(
            EmptyStateWidget(
                "Ask Atlas what you need",
                "Type a tool, machine, EOAT ID, part description, robot type, or keyword to get a ranked read-only recommendation.",
            )
        )
        self.result_layout.addStretch(1)

    def _render_result(self) -> None:
        if self.result is None:
            self._render_empty()
            return
        _clear_layout(self.result_layout)
        best_title = self.result.best.eoat_id if self.result.best else "No direct EOAT match"
        summary = ProfileHeaderCard(best_title, self.result.summary, eyebrow="Best Recommendation")
        summary.layout.addWidget(badge(f"Interpreted as: {self.result.interpreted_as}", "outline"))
        if self.result.best:
            best = self.result.best
            score_row = QHBoxLayout()
            score_row.setContentsMargins(0, 0, 0, 0)
            score_row.addWidget(badge(f"Score {best.score}", "success" if best.score >= 80 else "warning"))
            score_row.addWidget(badge(f"Documentation {best.documentation_score}%", _score_kind(best.documentation_score)))
            score_row.addWidget(badge(f"{best.photo_count} photo(s)", "success" if best.photo_count else "warning"))
            score_row.addStretch(1)
            summary.layout.addLayout(score_row)
            summary.layout.addWidget(MiniProgressBar(best.score, kind="good" if best.score >= 80 else "warn"))
            summary.layout.addWidget(_labeled_chips("Compatible machines", best.machines, empty="No compatible machines"))
            summary.layout.addWidget(_labeled_chips("Tools", best.tools, empty="No linked tools"))
            summary.layout.addWidget(_recommendation_action_row(best, self, primary=True))
        self.result_layout.addWidget(summary)
        if self.result.best:
            self.result_layout.addWidget(_recommendation_explanation_panel(self.result))

        checklist = ChecklistCard("Before Install", "Use this as a quick readiness sequence before staging.")
        for index, item in enumerate(self.result.install_checklist, start=1):
            checklist.layout.addWidget(_checklist_row(str(index), item, kind="primary"))
        self.result_layout.addWidget(checklist)

        candidate_section, candidate_layout = _group_container(
            "Ranked EOAT Candidates",
            "Secondary options stay available without competing with the best answer.",
        )
        for candidate in self.result.candidates[:12]:
            card = EOATProfileCard(candidate.eoat_id, candidate.summary)
            top = QHBoxLayout()
            top.setContentsMargins(0, 0, 0, 0)
            top.addWidget(badge(f"#{candidate.rank}", "count"))
            top.addWidget(badge(f"Score {candidate.score}", "success" if candidate.score >= 80 else "warning"))
            top.addWidget(badge(f"{candidate.documentation_score}% docs", _score_kind(candidate.documentation_score)))
            top.addStretch(1)
            card.layout.addLayout(top)
            card.layout.addWidget(MiniProgressBar(candidate.score, kind="good" if candidate.score >= 80 else "warn"))
            card.layout.addWidget(_labeled_chips("Machines", candidate.machines, empty="No linked machines", per_row=5))
            card.layout.addWidget(_labeled_chips("Tools", candidate.tools, empty="No linked tools", per_row=5))
            card.layout.addWidget(_compact_score_summary(candidate))
            card.layout.addWidget(_recommendation_action_row(candidate, self, primary=False))
            candidate_layout.addWidget(card)
        if not self.result.candidates:
            candidate_layout.addWidget(EmptyStateWidget("No candidates found", "Try a different tool, machine, or EOAT identifier."))
        self.result_layout.addWidget(candidate_section)
        context_section = _recommendation_context_section(self.result, self)
        if context_section is not None:
            self.result_layout.addWidget(context_section)
        if self.result.warnings:
            warnings, warnings_layout = _group_container("Warnings", "Recommendation caveats that should be reviewed before install.")
            for warning in self.result.warnings[:8]:
                warnings_layout.addWidget(
                    _warning_block(warning.title, warning.message, warning.why_it_matters, warning.suggested_fix, _warning_kind(warning.severity))
                )
            self.result_layout.addWidget(warnings)
        self.result_layout.addStretch(1)


class EOATBrowserPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.current: EOATRecord | None = None
        self._records_by_key: dict[str, EOATRecord] = {}
        self.compare_keys: set[str] = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("EOAT Profiles", "Search EOATs, review profile details, photos, warnings, and install context."))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by EOAT ID, tool, machine, type, status, part, or warning")
        self.filter.textChanged.connect(self.refresh)
        layout.addWidget(self.filter)
        self.compare_bar = InfoPanel("Compare Selected", "Choose two or more EOATs to compare key setup fields.")
        compare_button = QPushButton("Compare Selected")
        compare_button.setObjectName("PrimaryButton")
        compare_button.clicked.connect(self.open_compare_selected)
        clear_compare_button = QPushButton("Clear")
        clear_compare_button.clicked.connect(self.clear_compare_selection)
        self.compare_bar.layout.addWidget(action_row(compare_button, clear_compare_button))
        self.compare_bar.setVisible(False)
        layout.addWidget(self.compare_bar)
        splitter = QSplitter()
        self.list = QListWidget()
        self.list.setObjectName("CardList")
        self.list.setMinimumWidth(330)
        self.list.setMaximumWidth(430)
        self.list.currentItemChanged.connect(self._selection_changed)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.detail_scroll.setMinimumWidth(720)
        self.detail_panel = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_panel)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(12)
        self.detail_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.detail_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.detail_scroll.setWidget(self.detail_panel)
        splitter.addWidget(self.list)
        splitter.addWidget(self.detail_scroll)
        splitter.setSizes([390, 860])
        layout.addWidget(splitter, 1)
        copy_button = QPushButton("Copy EOAT ID")
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.current.eoat_id if self.current else ""))
        self.pin_button = QPushButton("Pin")
        self.pin_button.clicked.connect(self.toggle_pin_current)
        folder_button = QPushButton("Open Photos")
        folder_button.clicked.connect(self.open_photos)
        packet_button = QPushButton("Changeover Packet")
        packet_button.clicked.connect(self.generate_install_packet)
        self.qr_button = QPushButton("Make QR")
        self.qr_button.clicked.connect(self.make_qr_label)
        export_button = QPushButton("Export EOAT Summary")
        export_button.clicked.connect(self.export_current)
        machine_button = QPushButton("Open Machine Profile")
        machine_button.clicked.connect(self.open_related_machine)
        tool_button = QPushButton("Open Tool Lookup")
        tool_button.clicked.connect(self.open_related_tool)
        what_button = QPushButton("What Do I Need?")
        what_button.clicked.connect(self.open_recommendation)
        layout.addWidget(
            action_row(
                copy_button,
                self.pin_button,
                folder_button,
                packet_button,
                self.qr_button,
                export_button,
                machine_button,
                tool_button,
                what_button,
            )
        )
        self._show_detail(None)

    def refresh(self) -> None:
        if self.bundle is None:
            return
        raw_query = self.filter.text().strip()
        query = raw_query.casefold()
        scored_rows: list[tuple[int, EOATRecord]] = []
        self._records_by_key = {}
        for eoat in self.bundle.eoats:
            self._records_by_key[normalized_eoat_key(eoat.eoat_id)] = eoat
            score = _eoat_search_rank(eoat, raw_query)
            if raw_query and score <= 0:
                continue
            haystack = " ".join(
                [eoat.eoat_id, eoat.eoat_type, eoat.status, " ".join(eoat.tools), " ".join(eoat.machines), eoat.part_description]
            ).casefold()
            if query and score < 80 and query not in haystack:
                continue
            scored_rows.append((score, eoat))
        scored_rows.sort(key=lambda item: (-item[0], item[1].eoat_id.casefold()))
        rows = [eoat for _score, eoat in scored_rows]
        sections = [("Results", rows)] if query else _sectioned_eoats(rows, self.controller.settings)
        self.list.blockSignals(True)
        self.list.clear()
        visible_records: list[EOATRecord] = []
        for section_name, section_rows in sections:
            if not section_rows:
                continue
            if not query:
                header = QListWidgetItem(section_name)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                self.list.addItem(header)
            for eoat in section_rows:
                if len(visible_records) >= 200:
                    break
                key = normalized_eoat_key(eoat.eoat_id)
                tile = EOATListTile(
                    eoat,
                    compact=self.controller.settings.compact_list_mode,
                    compare_checked=key in self.compare_keys,
                    compare_callback=lambda checked, eoat_id=eoat.eoat_id: self.set_compare_selected(eoat_id, checked),
                    pinned=self.controller.is_pinned("eoat", eoat.eoat_id),
                    recent=_contains_id(self.controller.settings.recent_eoats, eoat.eoat_id),
                )
                item = QListWidgetItem()
                item.setSizeHint(tile.sizeHint())
                item.setData(Qt.ItemDataRole.UserRole, eoat)
                self.list.addItem(item)
                self.list.setItemWidget(item, tile)
                visible_records.append(eoat)
        if len(rows) > 200:
            item = QListWidgetItem(f"Showing first 200 of {len(rows)} matches. Refine the search to narrow results.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._update_compare_bar()
        if visible_records:
            target = normalized_eoat_key(self.current.eoat_id) if self.current else normalized_eoat_key(rows[0].eoat_id)
            selected_row = -1
            for index in range(self.list.count()):
                item = self.list.item(index)
                eoat = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(eoat, EOATRecord) and normalized_eoat_key(eoat.eoat_id) == target:
                    selected_row = index
                    break
            self.list.setCurrentRow(selected_row if selected_row >= 0 else 0)
        else:
            self._show_detail(None)

    def settings_changed(self) -> None:
        self.refresh()

    def open_record(self, eoat_id: str) -> None:
        self.filter.setText(eoat_id)
        self.refresh()
        self._show_detail(self._records_by_key.get(normalized_eoat_key(eoat_id)) or _find_eoat(self.bundle, eoat_id))

    def _selection_changed(self) -> None:
        item = self.list.currentItem()
        if item:
            record = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(record, EOATRecord):
                self.controller.record_recent("eoat", record.eoat_id)
                self._show_detail(record)

    def _show_detail(self, eoat: EOATRecord | None) -> None:
        self.current = eoat
        self._render_eoat_profile(eoat)
        self._sync_action_state()

    def open_photos(self) -> None:
        if self.current and self.current.photos.folder_path:
            open_path(self.current.photos.folder_path)

    def export_current(self) -> None:
        bundle = self.require_bundle()
        if bundle and self.current:
            path = export_eoat_summary(bundle, self.current)
            self.controller.show_status(f"Exported EOAT summary: {path}")

    def generate_install_packet(self) -> None:
        bundle = self.require_bundle()
        if bundle and self.current:
            if hasattr(self.controller, "open_setup_packet"):
                self.controller.open_setup_packet(
                    eoat=self.current.eoat_id,
                    tool=self.current.tools[0] if self.current.tools else "",
                    machine=self.current.machines[0] if self.current.machines else "",
                    context_label="EOAT Profile",
                )

    def make_qr_label(self) -> None:
        bundle = self.require_bundle()
        if bundle is None or self.current is None:
            return
        if not self.controller.settings.enable_qr_codes:
            QMessageBox.information(self, "QR Codes", "Enable QR Codes in Settings before generating labels.")
            return
        payload = build_eoat_qr_payload(self.current, mode=self.controller.settings.qr_payload_mode)
        validation_errors = validate_eoat_qr_payload(
            payload,
            mode=self.controller.settings.qr_payload_mode,
            eoat_id=self.current.eoat_id,
        )
        if validation_errors:
            QMessageBox.warning(self, "QR Payload", "\n".join(validation_errors))
            return
        if warning := qr_payload_warning(
            payload,
            mode=self.controller.settings.qr_payload_mode,
            error_correction=self.controller.settings.qr_error_correction,
        ):
            QMessageBox.warning(self, "QR Payload Size", warning)
        dialog = QRLabelPreviewDialog(bundle, self.current, self.controller.settings, parent=self)
        dialog.exec()

    def toggle_pin_current(self) -> None:
        if not self.current:
            return
        pinned = self.controller.toggle_pin("eoat", self.current.eoat_id)
        self.controller.show_status(f"{'Pinned' if pinned else 'Unpinned'} EOAT {self.current.eoat_id}.")
        self.refresh()

    def set_compare_selected(self, eoat_id: str, checked: bool) -> None:
        key = normalized_eoat_key(eoat_id)
        if checked:
            self.compare_keys.add(key)
        else:
            self.compare_keys.discard(key)
        self._update_compare_bar()

    def clear_compare_selection(self) -> None:
        self.compare_keys.clear()
        self.refresh()

    def open_compare_selected(self, allow_fallback: bool = False) -> None:
        bundle = self.require_bundle()
        if bundle is None:
            return
        records = [record for record in bundle.eoats if normalized_eoat_key(record.eoat_id) in self.compare_keys]
        if allow_fallback and len(records) < 2:
            records = list(bundle.eoats[: min(3, len(bundle.eoats))])
        if len(records) < 2:
            QMessageBox.information(self, "Compare EOATs", "Select two or more EOATs to compare.")
            return
        CompareDialog("EOAT Compare", _eoat_compare_rows(records), [record.eoat_id for record in records], parent=self).exec()

    def _update_compare_bar(self) -> None:
        self.compare_bar.setVisible(len(self.compare_keys) >= 2)

    def _sync_action_state(self) -> None:
        has_current = self.current is not None
        self.pin_button.setEnabled(has_current)
        self.pin_button.setText("Unpin" if has_current and self.controller.is_pinned("eoat", self.current.eoat_id) else "Pin")
        self.qr_button.setVisible(bool(self.controller.settings.enable_qr_codes))
        self.qr_button.setEnabled(has_current)

    def open_related_machine(self) -> None:
        if self.current and self.current.machines:
            self.controller.open_machine(self.current.machines[0])

    def open_related_tool(self) -> None:
        if self.current and self.current.tools and hasattr(self.controller, "open_tool"):
            self.controller.open_tool(self.current.tools[0])

    def open_recommendation(self) -> None:
        if self.current:
            self.controller.open_recommendation(self.current.eoat_id)

    def _render_eoat_profile(self, eoat: EOATRecord | None) -> None:
        self.detail_panel.setUpdatesEnabled(False)
        _clear_layout(self.detail_layout)
        if eoat is None:
            empty = EmptyStateWidget("EOAT Profile", "Select an EOAT from the list to see compatibility, readiness, photos, warnings, and technical details.")
            self.detail_layout.addWidget(empty)
            self.detail_layout.addStretch(1)
            _finalize_scroll_panel(self.detail_scroll, self.detail_panel, self.detail_layout)
            self.detail_panel.setUpdatesEnabled(True)
            return
        profile_columns = 2 if self.detail_scroll.viewport().width() >= 980 else 1
        self.detail_layout.addWidget(_eoat_hero_section(eoat))
        self.detail_layout.addWidget(_eoat_relationship_map(eoat))
        primary_container = QWidget()
        primary_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        primary_grid = QGridLayout(primary_container)
        primary_grid.setContentsMargins(0, 0, 0, 0)
        primary_grid.setSpacing(10)
        primary_grid.addWidget(_eoat_compatibility_section(eoat), 0, 0)
        primary_grid.addWidget(_eoat_readiness_section(eoat), 0 if profile_columns == 2 else 1, 1 if profile_columns == 2 else 0)
        primary_grid.setColumnStretch(0, 1)
        if profile_columns == 2:
            primary_grid.setColumnStretch(1, 1)
        self.detail_layout.addWidget(primary_container)
        self.detail_layout.addWidget(_eoat_applicable_standards_section(eoat))
        evidence_container = QWidget()
        evidence_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        evidence_grid = QGridLayout(evidence_container)
        evidence_grid.setContentsMargins(0, 0, 0, 0)
        evidence_grid.setSpacing(10)
        evidence_grid.addWidget(_eoat_photo_section(eoat), 0, 0)
        evidence_grid.addWidget(_eoat_warnings_section(eoat), 0 if profile_columns == 2 else 1, 1 if profile_columns == 2 else 0)
        evidence_grid.setColumnStretch(0, 1)
        if profile_columns == 2:
            evidence_grid.setColumnStretch(1, 1)
        self.detail_layout.addWidget(evidence_container)
        self.detail_layout.addWidget(_eoat_technical_details(eoat, columns=2 if self.detail_scroll.viewport().width() >= 1100 else 1))
        self.detail_layout.addStretch(1)
        _finalize_scroll_panel(self.detail_scroll, self.detail_panel, self.detail_layout)
        self.detail_panel.setUpdatesEnabled(True)


class MachineBrowserPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.current: MachineRecord | None = None
        self._records_by_key: dict[str, MachineRecord] = {}
        self.compare_keys: set[str] = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Machine Profiles", "Find machine EOAT compatibility, robot context, and warning status."))
        self.filter = ModernSearchBar("Filter by machine, robot, tool, EOAT, or part")
        self.filter.textChanged.connect(self.refresh)
        layout.addWidget(self.filter)
        self.compare_bar = InfoPanel("Compare Selected", "Choose two or more machines to compare robot and compatibility context.")
        compare_button = QPushButton("Compare Selected")
        compare_button.setObjectName("PrimaryButton")
        compare_button.clicked.connect(self.open_compare_selected)
        clear_compare_button = QPushButton("Clear")
        clear_compare_button.clicked.connect(self.clear_compare_selection)
        self.compare_bar.layout.addWidget(action_row(compare_button, clear_compare_button))
        self.compare_bar.setVisible(False)
        layout.addWidget(self.compare_bar)
        splitter = QSplitter()
        self.list = QListWidget()
        self.list.setObjectName("CardList")
        self.list.setMinimumWidth(320)
        self.list.setMaximumWidth(420)
        self.list.currentItemChanged.connect(self._selection_changed)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.detail_scroll.setMinimumWidth(720)
        self.detail_panel = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_panel)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(12)
        self.detail_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.detail_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.detail_scroll.setWidget(self.detail_panel)
        splitter.addWidget(self.list)
        splitter.addWidget(self.detail_scroll)
        splitter.setSizes([360, 900])
        layout.addWidget(splitter, 1)
        eoat_button = QPushButton("Open Related EOAT")
        eoat_button.clicked.connect(self.open_related_eoat)
        self.pin_button = QPushButton("Pin")
        self.pin_button.clicked.connect(self.toggle_pin_current)
        packet_button = QPushButton("Changeover Packet")
        packet_button.clicked.connect(self.generate_install_packet)
        export_button = QPushButton("Export Machine Summary")
        export_button.clicked.connect(self.export_current)
        matrix_button = QPushButton("Open Matrix")
        matrix_button.clicked.connect(lambda: self.controller.show_page("matrix"))
        layout.addWidget(action_row(eoat_button, self.pin_button, packet_button, matrix_button, export_button))
        self._show_detail(None)

    def refresh(self) -> None:
        if self.bundle is None:
            return
        raw_query = self.filter.text().strip()
        query = raw_query.casefold()
        exact_machine_key = _exact_machine_filter_key(raw_query)
        rows = []
        self._records_by_key = {}
        for machine in self.bundle.machines:
            self._records_by_key[normalized_machine_key(machine.machine)] = machine
            if exact_machine_key:
                if normalized_machine_key(machine.machine) == exact_machine_key:
                    rows.append(machine)
                continue
            haystack = " ".join(
                [machine.machine, machine.robot_type, machine.robot_model, " ".join(machine.compatible_eoats), " ".join(machine.compatible_tools)]
            ).casefold()
            if query and query not in haystack:
                continue
            rows.append(machine)
        sections = [("Results", rows)] if query else _sectioned_machines(rows, self.controller.settings)
        self.list.blockSignals(True)
        self.list.clear()
        visible_records: list[MachineRecord] = []
        for section_name, section_rows in sections:
            if not section_rows:
                continue
            if not query:
                header = QListWidgetItem(section_name)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                self.list.addItem(header)
            for machine in section_rows:
                if len(visible_records) >= 200:
                    break
                key = normalized_machine_key(machine.machine)
                tile = MachineListTile(
                    machine,
                    compact=self.controller.settings.compact_list_mode,
                    compare_checked=key in self.compare_keys,
                    compare_callback=lambda checked, machine_id=machine.machine: self.set_compare_selected(machine_id, checked),
                    pinned=self.controller.is_pinned("machine", machine.machine),
                    recent=_contains_id(self.controller.settings.recent_machines, machine.machine),
                )
                item = QListWidgetItem()
                item.setSizeHint(tile.sizeHint())
                item.setData(Qt.ItemDataRole.UserRole, machine)
                self.list.addItem(item)
                self.list.setItemWidget(item, tile)
                visible_records.append(machine)
        if len(rows) > 200:
            item = QListWidgetItem(f"Showing first 200 of {len(rows)} matches. Refine the search to narrow results.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._update_compare_bar()
        if visible_records:
            target = normalized_machine_key(self.current.machine) if self.current else normalized_machine_key(rows[0].machine)
            selected_row = -1
            for index in range(self.list.count()):
                item = self.list.item(index)
                machine = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(machine, MachineRecord) and normalized_machine_key(machine.machine) == target:
                    selected_row = index
                    break
            self.list.setCurrentRow(selected_row if selected_row >= 0 else 0)
        else:
            self._show_detail(None)

    def settings_changed(self) -> None:
        self.refresh()

    def open_record(self, machine_id: str) -> None:
        self.filter.setText(machine_id)
        self.refresh()
        self._show_detail(self._records_by_key.get(normalized_machine_key(machine_id)) or _find_machine(self.bundle, machine_id))

    def _selection_changed(self) -> None:
        item = self.list.currentItem()
        if item:
            record = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(record, MachineRecord):
                self.controller.record_recent("machine", record.machine)
                self._show_detail(record)

    def _show_detail(self, machine: MachineRecord | None) -> None:
        self.current = machine
        self._render_machine_profile(machine)
        self._sync_action_state()

    def export_current(self) -> None:
        bundle = self.require_bundle()
        if bundle and self.current:
            path = export_machine_summary(bundle, self.current)
            self.controller.show_status(f"Exported machine summary: {path}")

    def generate_install_packet(self) -> None:
        bundle = self.require_bundle()
        if bundle and self.current:
            if hasattr(self.controller, "open_setup_packet"):
                self.controller.open_setup_packet(
                    machine=self.current.machine,
                    eoat=self.current.current_eoat or (self.current.compatible_eoats[0] if self.current.compatible_eoats else ""),
                    tool=self.current.compatible_tools[0] if self.current.compatible_tools else "",
                    context_label="Machine Profile",
                )

    def toggle_pin_current(self) -> None:
        if not self.current:
            return
        pinned = self.controller.toggle_pin("machine", self.current.machine)
        self.controller.show_status(f"{'Pinned' if pinned else 'Unpinned'} Machine {self.current.machine}.")
        self.refresh()

    def set_compare_selected(self, machine_id: str, checked: bool) -> None:
        key = normalized_machine_key(machine_id)
        if checked:
            self.compare_keys.add(key)
        else:
            self.compare_keys.discard(key)
        self._update_compare_bar()

    def clear_compare_selection(self) -> None:
        self.compare_keys.clear()
        self.refresh()

    def open_compare_selected(self, allow_fallback: bool = False) -> None:
        bundle = self.require_bundle()
        if bundle is None:
            return
        records = [record for record in bundle.machines if normalized_machine_key(record.machine) in self.compare_keys]
        if allow_fallback and len(records) < 2:
            records = list(bundle.machines[: min(3, len(bundle.machines))])
        if len(records) < 2:
            QMessageBox.information(self, "Compare Machines", "Select two or more machines to compare.")
            return
        CompareDialog("Machine Compare", _machine_compare_rows(records), [f"Machine {record.machine}" for record in records], parent=self).exec()

    def _update_compare_bar(self) -> None:
        self.compare_bar.setVisible(len(self.compare_keys) >= 2)

    def _sync_action_state(self) -> None:
        has_current = self.current is not None
        self.pin_button.setEnabled(has_current)
        self.pin_button.setText("Unpin" if has_current and self.controller.is_pinned("machine", self.current.machine) else "Pin")

    def open_related_eoat(self) -> None:
        if self.current:
            eoat_id = self.current.current_eoat or (self.current.compatible_eoats[0] if self.current.compatible_eoats else "")
            if eoat_id:
                self.controller.open_eoat(eoat_id)

    def _render_machine_profile(self, machine: MachineRecord | None) -> None:
        self.detail_panel.setUpdatesEnabled(False)
        _clear_layout(self.detail_layout)
        if machine is None:
            self.detail_layout.addWidget(EmptyStateWidget("Machine Profile", "Select a machine to see robot context, compatible EOATs, tools, and warnings."))
            self.detail_layout.addStretch(1)
            _finalize_scroll_panel(self.detail_scroll, self.detail_panel, self.detail_layout)
            self.detail_panel.setUpdatesEnabled(True)
            return
        self.detail_layout.addWidget(_machine_hero_section(machine))
        self.detail_layout.addWidget(_machine_relationship_map(machine))
        primary_container = QWidget()
        primary_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        primary_grid = QGridLayout(primary_container)
        primary_grid.setContentsMargins(0, 0, 0, 0)
        primary_grid.setSpacing(10)
        primary_grid.addWidget(_machine_compatibility_section(machine), 0, 0)
        primary_grid.addWidget(_machine_technical_section(machine), 0, 1)
        primary_grid.setColumnStretch(0, 1)
        primary_grid.setColumnStretch(1, 1)
        self.detail_layout.addWidget(primary_container)
        self.detail_layout.addWidget(_machine_warnings_section(machine))
        self.detail_layout.addStretch(1)
        _finalize_scroll_panel(self.detail_scroll, self.detail_panel, self.detail_layout)
        self.detail_panel.setUpdatesEnabled(True)


class ToolSearchPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.compare_keys: set[str] = set()
        self.current_tool: ToolRecord | None = None
        self._records_by_key: dict[str, ToolRecord] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Tool / Mold / Part", "Find compatible EOATs and machines from tool, mold, part number, or description."))
        self.search = ModernSearchBar("Search tool, mold, part number, or description")
        self.search.textChanged.connect(self.refresh)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        self.hide_missing_check = QCheckBox("Hide missing EOAT links")
        self.hide_missing_check.toggled.connect(self._set_hide_missing_tools)
        self.filter_chip = badge("Hiding tools missing EOAT links", "warning")
        self.filter_chip.setVisible(False)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.hide_missing_check)
        search_row.addWidget(self.filter_chip)
        layout.addLayout(search_row)
        self.compare_bar = InfoPanel("Compare Selected", "Choose two or more tools to compare EOAT and machine compatibility.")
        compare_button = QPushButton("Compare Selected")
        compare_button.setObjectName("PrimaryButton")
        compare_button.clicked.connect(self.open_compare_selected)
        clear_compare_button = QPushButton("Clear")
        clear_compare_button.clicked.connect(self.clear_compare_selection)
        self.compare_count_label = QLabel("0 selected")
        self.compare_count_label.setObjectName("MetricLabel")
        self.compare_bar.layout.addWidget(action_row(compare_button, clear_compare_button))
        self.compare_bar.layout.addWidget(self.compare_count_label)
        self.compare_bar.setVisible(False)
        layout.addWidget(self.compare_bar)

        splitter = QSplitter()
        self.list = QListWidget()
        self.list.setObjectName("CardList")
        self.list.setMinimumWidth(360)
        self.list.setMaximumWidth(520)
        self.list.currentItemChanged.connect(self._selection_changed)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.detail_scroll.setMinimumWidth(720)
        self.detail_panel = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_panel)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(12)
        self.detail_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.detail_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.detail_scroll.setWidget(self.detail_panel)
        splitter.addWidget(self.list)
        splitter.addWidget(self.detail_scroll)
        splitter.setSizes([420, 860])
        layout.addWidget(splitter, 1)
        self.hide_missing_check.blockSignals(True)
        self.hide_missing_check.setChecked(bool(self.controller.settings.hide_tools_missing_eoat_links))
        self.hide_missing_check.blockSignals(False)
        self.filter_chip.setVisible(bool(self.controller.settings.hide_tools_missing_eoat_links))
        self._show_detail(None)

    def settings_changed(self) -> None:
        self.hide_missing_check.blockSignals(True)
        self.hide_missing_check.setChecked(bool(self.controller.settings.hide_tools_missing_eoat_links))
        self.hide_missing_check.blockSignals(False)
        self.filter_chip.setVisible(bool(self.controller.settings.hide_tools_missing_eoat_links))
        self.refresh()

    def refresh(self) -> None:
        if self.bundle is None:
            return
        raw_query = self.search.text().strip()
        query = raw_query.casefold()
        hide_missing = bool(self.controller.settings.hide_tools_missing_eoat_links)
        scored_matches: list[tuple[int, ToolRecord]] = []
        self._records_by_key = {}
        for tool in self.bundle.tools:
            if hide_missing and _tool_missing_eoat_link(tool):
                continue
            score = _tool_search_rank(tool, raw_query)
            if raw_query and score <= 0:
                continue
            self._records_by_key[normalized_tool_key(tool.tool)] = tool
            scored_matches.append((score, tool))
        strong_match = bool(raw_query and any(score >= 80 for score, _tool in scored_matches))
        if strong_match:
            scored_matches = [(score, tool) for score, tool in scored_matches if score >= 80]
        scored_matches.sort(key=lambda item: (-item[0], _natural_sort_key(item[1].tool)))
        matches = [tool for _score, tool in scored_matches]
        self.filter_chip.setVisible(hide_missing)
        if hide_missing:
            visible_keys = {normalized_tool_key(tool.tool) for tool in matches}
            self.compare_keys.intersection_update(visible_keys)
        sections = [("Results", matches)] if query else _tool_navigation_sections(matches, self.controller.settings)
        self.list.blockSignals(True)
        self.list.clear()
        visible_records: list[ToolRecord] = []
        for section_name, section_tools in sections:
            if not section_tools:
                continue
            if not query:
                header = QListWidgetItem(section_name)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                self.list.addItem(header)
            for tool in section_tools:
                if len(visible_records) >= 200:
                    break
                key = normalized_tool_key(tool.tool)
                tile = ToolListTile(
                    tool,
                    compact=self.controller.settings.compact_list_mode,
                    compare_checked=key in self.compare_keys,
                    compare_callback=lambda checked, tool_id=tool.tool: self.set_compare_selected(tool_id, checked),
                    recent=_contains_id(self.controller.settings.recent_tools, tool.tool),
                )
                item = QListWidgetItem()
                item.setSizeHint(tile.sizeHint())
                item.setData(Qt.ItemDataRole.UserRole, tool)
                self.list.addItem(item)
                self.list.setItemWidget(item, tile)
                visible_records.append(tool)
            if len(visible_records) >= 200:
                break
        if len(matches) > 200:
            item = QListWidgetItem(f"Showing first 200 of {len(matches)} matches. Refine the search to narrow results.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._update_compare_bar()
        if visible_records:
            target = normalized_tool_key(self.current_tool.tool) if self.current_tool else normalized_tool_key(visible_records[0].tool)
            selected_row = -1
            for index in range(self.list.count()):
                item = self.list.item(index)
                tool = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(tool, ToolRecord) and normalized_tool_key(tool.tool) == target:
                    selected_row = index
                    break
            self.list.setCurrentRow(selected_row if selected_row >= 0 else 0)
        else:
            self._show_detail(None)

    def _set_hide_missing_tools(self, value: bool) -> None:
        self.controller.update_settings(replace(self.controller.settings, hide_tools_missing_eoat_links=bool(value)))

    def mark_tool_viewed(self, tool: ToolRecord) -> None:
        self.current_tool = tool
        self.controller.record_recent("tool", tool.tool)

    def open_record(self, tool_id: str) -> None:
        self.search.setText(tool_id)
        self.refresh()
        record = self._records_by_key.get(normalized_tool_key(tool_id))
        if record is None and not self.controller.settings.hide_tools_missing_eoat_links:
            record = _find_tool(self.bundle, tool_id)
        self._show_detail(record)

    def _selection_changed(self) -> None:
        item = self.list.currentItem()
        if item:
            record = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(record, ToolRecord):
                self.mark_tool_viewed(record)
                self._show_detail(record)

    def _show_detail(self, tool: ToolRecord | None) -> None:
        self.current_tool = tool
        self._render_tool_profile(tool)

    def set_compare_selected(self, tool_id: str, checked: bool) -> None:
        key = normalized_tool_key(tool_id)
        if checked:
            self.compare_keys.add(key)
        else:
            self.compare_keys.discard(key)
        self._update_compare_bar()
        if self.current_tool and normalized_tool_key(self.current_tool.tool) == key:
            self._render_tool_profile(self.current_tool)

    def clear_compare_selection(self) -> None:
        self.compare_keys.clear()
        self.refresh()

    def open_compare_selected(self, allow_fallback: bool = False) -> None:
        bundle = self.require_bundle()
        if bundle is None:
            return
        records = [
            record
            for record in bundle.tools
            if normalized_tool_key(record.tool) in self.compare_keys
            and not (self.controller.settings.hide_tools_missing_eoat_links and _tool_missing_eoat_link(record))
        ]
        if allow_fallback and len(records) < 2:
            records = list(bundle.tools[: min(3, len(bundle.tools))])
        if len(records) < 2:
            QMessageBox.information(self, "Compare Tools", "Select two or more tools to compare.")
            return
        CompareDialog("Tool Compare", _tool_compare_rows(records), [f"Tool {record.tool}" for record in records], parent=self).exec()

    def generate_install_packet(self) -> None:
        bundle = self.require_bundle()
        if bundle is None:
            return
        tool = self.current_tool or _find_tool(bundle, self.search.text().strip())
        if tool is None and bundle.tools:
            query = self.search.text().strip().casefold()
            tool = next((record for record in bundle.tools if query and query in record.tool.casefold()), bundle.tools[0])
        if tool is None:
            return
        if hasattr(self.controller, "open_setup_packet"):
            self.controller.open_setup_packet(
                tool=tool.tool,
                eoat=tool.compatible_eoats[0] if tool.compatible_eoats else "",
                machine=tool.compatible_machines[0] if tool.compatible_machines else "",
                context_label="Tool / Mold / Part",
            )

    def _update_compare_bar(self) -> None:
        self.compare_bar.setVisible(len(self.compare_keys) >= 2)
        self.compare_count_label.setText(f"{len(self.compare_keys)} selected")

    def open_related_eoat(self) -> None:
        if self.current_tool and self.current_tool.compatible_eoats:
            self.controller.open_eoat(self.current_tool.compatible_eoats[0])

    def open_related_machine(self) -> None:
        if self.current_tool and self.current_tool.compatible_machines:
            self.controller.open_machine(self.current_tool.compatible_machines[0])

    def run_current_recommendation(self) -> None:
        if self.current_tool:
            self.controller.open_recommendation(self.current_tool.tool)
        else:
            self.controller.open_recommendation(self.search.text().strip())

    def toggle_compare_current(self) -> None:
        if not self.current_tool:
            return
        key = normalized_tool_key(self.current_tool.tool)
        self.set_compare_selected(self.current_tool.tool, key not in self.compare_keys)
        self.refresh()

    def export_current_tool(self) -> None:
        bundle = self.require_bundle()
        if bundle and self.current_tool:
            path = export_tool_summary(bundle, self.current_tool)
            self.controller.show_status(f"Exported tool summary: {path}")

    def _render_tool_profile(self, tool: ToolRecord | None) -> None:
        self.detail_panel.setUpdatesEnabled(False)
        _clear_layout(self.detail_layout)
        if tool is None:
            self.detail_layout.addWidget(
                EmptyStateWidget("Tool / Mold / Part Detail", "Select a tool from the left panel to see EOAT links, machines, warnings, and actions.")
            )
            self.detail_layout.addStretch(1)
            _finalize_scroll_panel(self.detail_scroll, self.detail_panel, self.detail_layout)
            self.detail_panel.setUpdatesEnabled(True)
            return
        self.detail_layout.addWidget(_tool_hero_section(tool))
        self.detail_layout.addWidget(_tool_action_section(tool, self))
        self.detail_layout.addWidget(_tool_relationship_map(tool))
        profile_columns = 2 if self.detail_scroll.viewport().width() >= 1050 else 1
        primary = QWidget()
        grid = QGridLayout(primary)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        grid.addWidget(_tool_compatibility_section(tool), 0, 0)
        grid.addWidget(_tool_source_section(tool), 0 if profile_columns == 2 else 1, 1 if profile_columns == 2 else 0)
        grid.setColumnStretch(0, 1)
        if profile_columns == 2:
            grid.setColumnStretch(1, 1)
        self.detail_layout.addWidget(primary)
        self.detail_layout.addWidget(_tool_warning_section(tool))
        self.detail_layout.addStretch(1)
        _finalize_scroll_panel(self.detail_scroll, self.detail_panel, self.detail_layout)
        self.detail_panel.setUpdatesEnabled(True)


class MatrixPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Fit Check", "Advanced table view of Fit Check rows."))
        explanation = InfoPanel(
            "Advanced table view",
            "Advanced table view of Fit Check rows. Use this for filtering, auditing, and export. For normal lookup, use EOAT Profiles, Machine Profiles, Tool/Mold/Part, or What Do I Need?",
        )
        layout.addWidget(explanation)
        controls = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["eoat_machine", "tool_eoat", "tool_machine"])
        self.mode.currentTextChanged.connect(self.refresh)
        self.quick_filter = QComboBox()
        self.quick_filter.addItems(
            [
                "All rows",
                "Missing validated EOAT",
                "Verified only",
                "Review/warning only",
                "No photos",
                "Low documentation score",
                "Manual override rows",
                "Current machine only",
                "Current tool only",
                "Current EOAT only",
            ]
        )
        self.quick_filter.currentTextChanged.connect(self.refresh)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter matrix")
        self.filter.textChanged.connect(self.refresh)
        export_button = QPushButton("Export CSV")
        export_button.clicked.connect(self.export_csv)
        controls.addWidget(self.mode)
        controls.addWidget(self.quick_filter)
        controls.addWidget(self.filter, 1)
        controls.addWidget(export_button)
        panel = DenseDataPanel("Fit Check Rows", "Dense matrix view for sorting, filtering, and export.")
        panel.layout.addLayout(controls)
        self.table = QTableWidget(self)
        panel.layout.addWidget(self.table, 1)
        layout.addWidget(panel, 1)

    def refresh(self) -> None:
        if self.bundle is None:
            return
        rows = compatibility_matrix_rows(self.bundle, mode=self.mode.currentText())
        query = self.filter.text().strip().casefold()
        if query:
            rows = [row for row in rows if query in " ".join(str(value) for value in row.values()).casefold()]
        rows = self._apply_quick_filter(rows)
        columns = list(rows[0].keys()) if rows else ["EOAT", "Machine", "Status"]
        fill_table(self.table, rows, columns)

    def export_csv(self) -> None:
        bundle = self.require_bundle()
        if bundle:
            path = export_compatibility_matrix(bundle, mode=self.mode.currentText())
            self.controller.show_status(f"Exported matrix: {path}")

    def _apply_quick_filter(self, rows: list[dict]) -> list[dict]:
        label = self.quick_filter.currentText()
        if label == "Missing validated EOAT":
            return [row for row in rows if not str(row.get("EOAT", "")).strip()]
        if label == "Verified only":
            return [row for row in rows if "confirmed" in str(row.get("Status", "")).casefold() and "not" not in str(row.get("Status", "")).casefold()]
        if label == "Review/warning only":
            return [row for row in rows if "warn" in " ".join(str(value) for value in row.values()).casefold() or "review" in " ".join(str(value) for value in row.values()).casefold()]
        if label == "No photos":
            photo_counts = {eoat.eoat_id.casefold(): eoat.photo_count for eoat in self.bundle.eoats} if self.bundle else {}
            return [row for row in rows if photo_counts.get(str(row.get("EOAT", "")).casefold(), 0) == 0]
        if label == "Low documentation score":
            scores = {eoat.eoat_id.casefold(): eoat.documentation.score for eoat in self.bundle.eoats} if self.bundle else {}
            return [row for row in rows if scores.get(str(row.get("EOAT", "")).casefold(), 100) < 75]
        if label == "Manual override rows":
            return [row for row in rows if "manual" in " ".join(str(value) for value in row.values()).casefold()]
        if label == "Current machine only":
            current = _current_record_value(self.controller, "machine")
            return [row for row in rows if current and str(row.get("Machine", "")).casefold() == current.casefold()]
        if label == "Current tool only":
            current = _current_record_value(self.controller, "tool")
            return [row for row in rows if current and str(row.get("Tool", "")).casefold() == current.casefold()]
        if label == "Current EOAT only":
            current = _current_record_value(self.controller, "eoat")
            return [row for row in rows if current and str(row.get("EOAT", "")).casefold() == current.casefold()]
        return rows


class OverviewPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(PageHeader("Analytics Dashboard", "Coverage, documentation, photo, warning, and standards trends from cached Atlas data."))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        self.content_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)

    def refresh(self) -> None:
        if self.bundle is None:
            return
        _clear_layout(self.content_layout)
        snapshot = build_analytics_snapshot(self.bundle)
        metric_grid = QGridLayout()
        metric_grid.setSpacing(10)
        metric_cards = _analytics_metric_cards(snapshot)
        for index, card in enumerate(metric_cards):
            metric_grid.addWidget(card, index // 4, index % 4)
        self.content_layout.addLayout(metric_grid)

        chart_grid = QGridLayout()
        chart_grid.setSpacing(12)
        charts = [
            ChartCard(
                "Documentation Completeness Distribution",
                "EOAT documentation score bands.",
                _qt_bar_chart(snapshot["documentation_bins"], axis_title="EOATs"),
            ),
            ChartCard(
                "EOAT Count by Type",
                "EOAT records grouped by normalized type.",
                _qt_donut_chart(snapshot["eoat_type_counts"]),
            ),
            ChartCard(
                "EOAT Count by Status",
                "Current source status categories.",
                _qt_donut_chart(snapshot["eoat_status_counts"]),
            ),
            ChartCard(
                "Photo Coverage by EOAT Type",
                "Average linked photo count by type.",
                _qt_bar_chart(snapshot["photo_coverage_by_type"], axis_title="Avg photos"),
            ),
            ChartCard(
                "Warnings by Category",
                "Warning volume grouped by likely source area.",
                _qt_horizontal_bar_chart(snapshot["warnings_by_category"], axis_title="Warnings"),
            ),
            ChartCard(
                "Top Machines by Warning Count",
                "Machines with the highest indexed warning counts.",
                _qt_horizontal_bar_chart(snapshot["top_warning_machines"], axis_title="Warnings", limit=10),
            ),
            ChartCard(
                "Tools Missing Validated EOATs",
                f"{snapshot['coverage_metrics']['tools_missing_validated_eoat']} total tools need EOAT links.",
                _qt_horizontal_bar_chart(snapshot["tools_missing_validated_eoat"], axis_title="Missing links", limit=10),
            ),
            ChartCard(
                "Standards Compliance Summary",
                "Applicable standard status inferred from EOAT evidence.",
                _qt_donut_chart(snapshot["standards_compliance_summary"]),
            ),
        ]
        for index, chart in enumerate(charts):
            chart_grid.addWidget(chart, index // 2, index % 2)
        self.content_layout.addLayout(chart_grid)

        heatmap = SectionCard(
            "Machine Coverage Health",
            "Compact machine tiles use the same verified/review/missing health colors as profile relationship badges.",
        )
        heatmap.layout.addWidget(_machine_health_grid(snapshot["machine_health_tiles"]))
        self.content_layout.addWidget(heatmap)

        warning_section = SectionCard(
            "Highest-warning records",
            "Records with the most warnings rise to the top for cleanup planning.",
        )
        warning_section.layout.addWidget(_chip_group(snapshot["highest_warning_records"], kind="review", empty="No warning-heavy records", per_row=3, limit=18))
        self.content_layout.addWidget(warning_section)
        self.content_layout.addStretch(1)


class PhotosPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.current: EOATRecord | None = None
        self._records_by_key: dict[str, EOATRecord] = {}
        self._selected_eoat_key = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Photos", "Browse linked EOAT photos without moving or renaming source files."))
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        self.filter = ModernSearchBar("Filter by EOAT, tool, machine, or category")
        self.filter.textChanged.connect(self.refresh)
        self.filter_mode = QComboBox()
        self.filter_mode.addItems(
            [
                "All EOATs",
                "Has photos",
                "Missing folder",
                "Missing categories",
                "By tool",
                "By machine",
                "By photo category",
            ]
        )
        self.filter_mode.currentTextChanged.connect(self.refresh)
        controls.addWidget(self.filter, 1)
        controls.addWidget(self.filter_mode)
        layout.addLayout(controls)

        splitter = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setObjectName("InformationTree")
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(340)
        self.tree.setMaximumWidth(500)
        self.tree.itemSelectionChanged.connect(self._tree_selection_changed)

        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.detail_panel = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_panel)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(12)
        self.detail_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.detail_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.detail_scroll.setWidget(self.detail_panel)

        splitter.addWidget(self.tree)
        splitter.addWidget(self.detail_scroll)
        splitter.setSizes([390, 900])
        layout.addWidget(splitter, 1)
        self._render_detail(None)

    def refresh(self) -> None:
        if self.bundle is None:
            return
        query = self.filter.text().strip()
        matches: list[EOATRecord] = []
        self._records_by_key = {}
        for eoat in self.bundle.eoats:
            key = normalized_eoat_key(eoat.eoat_id)
            self._records_by_key[key] = eoat
            if not _photo_record_matches(eoat, query, self.filter_mode.currentText()):
                continue
            matches.append(eoat)
        if hasattr(self.controller, "photo_loader"):
            self.controller.photo_loader.update_visible_photo_context(matches[:36])
        self._rebuild_tree(matches, bool(query))
        selected = self._records_by_key.get(self._selected_eoat_key)
        if selected not in matches:
            selected = matches[0] if matches else None
        self._render_detail(selected)

    def open_record(self, eoat_id: str) -> None:
        self.filter.setText(eoat_id)
        self.refresh()
        self._select_record(_find_eoat(self.bundle, eoat_id))

    def _rebuild_tree(self, records: list[EOATRecord], expand_all: bool) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()

        all_root = QTreeWidgetItem(["All EOAT Photo Sets"])
        all_root.setData(0, Qt.ItemDataRole.UserRole, "")
        self.tree.addTopLevelItem(all_root)
        for eoat in records:
            self._add_eoat_leaf(all_root, eoat)

        status_root = QTreeWidgetItem(["By Photo Status"])
        self.tree.addTopLevelItem(status_root)
        for label, subset in [
            ("Has Photos", [eoat for eoat in records if eoat.photo_count > 0]),
            ("Missing Folder", [eoat for eoat in records if not eoat.photos.folder_exists]),
            ("Missing Required Categories", [eoat for eoat in records if eoat.photos.missing_categories]),
        ]:
            self._add_group(status_root, label, subset)

        tool_root = QTreeWidgetItem(["By Tool"])
        self.tree.addTopLevelItem(tool_root)
        for tool in sorted({tool for eoat in records for tool in eoat.tools}, key=str.casefold):
            self._add_group(tool_root, f"Tool {tool}", [eoat for eoat in records if tool in eoat.tools])

        machine_root = QTreeWidgetItem(["By Machine"])
        self.tree.addTopLevelItem(machine_root)
        for machine in sorted({machine for eoat in records for machine in eoat.machines}, key=_natural_sort_key):
            self._add_group(machine_root, f"Machine {machine}", [eoat for eoat in records if machine in eoat.machines])

        category_root = QTreeWidgetItem(["By Category Coverage"])
        self.tree.addTopLevelItem(category_root)
        for category in _photo_library_categories(records):
            subset = [eoat for eoat in records if category in eoat.photos.missing_categories]
            if subset:
                self._add_group(category_root, f"{category} Missing", subset)

        if not records:
            empty = QTreeWidgetItem(["No matching photo sets"])
            empty.setData(0, Qt.ItemDataRole.UserRole, "")
            self.tree.addTopLevelItem(empty)

        selected_item = self._find_tree_item(self._selected_eoat_key)
        if selected_item is None and records:
            selected_item = self._find_tree_item(normalized_eoat_key(records[0].eoat_id))
        if expand_all:
            self.tree.expandAll()
        else:
            for index in range(self.tree.topLevelItemCount()):
                self.tree.topLevelItem(index).setExpanded(index < 2)
        if selected_item is not None:
            self.tree.setCurrentItem(selected_item)
            self.tree.scrollToItem(selected_item)
        self.tree.blockSignals(False)

    def _add_group(self, parent: QTreeWidgetItem, label: str, records: list[EOATRecord]) -> None:
        item = QTreeWidgetItem([f"{label} ({len(records)})"])
        item.setData(0, Qt.ItemDataRole.UserRole, "")
        parent.addChild(item)
        for eoat in records:
            self._add_eoat_leaf(item, eoat)

    def _add_eoat_leaf(self, parent: QTreeWidgetItem, eoat: EOATRecord) -> None:
        label = f"{eoat.eoat_id}  -  {eoat.photo_count} photo(s)"
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.ItemDataRole.UserRole, normalized_eoat_key(eoat.eoat_id))
        item.setToolTip(0, _photo_leaf_tooltip(eoat))
        parent.addChild(item)

    def _find_tree_item(self, key: str) -> QTreeWidgetItem | None:
        if not key:
            return None
        queue = [self.tree.topLevelItem(index) for index in range(self.tree.topLevelItemCount())]
        while queue:
            item = queue.pop(0)
            if item.data(0, Qt.ItemDataRole.UserRole) == key:
                return item
            queue.extend(item.child(index) for index in range(item.childCount()))
        return None

    def _tree_selection_changed(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        key = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if not key:
            item.setExpanded(not item.isExpanded())
            return
        self._select_record(self._records_by_key.get(key))

    def _select_record(self, eoat: EOATRecord | None) -> None:
        if eoat is not None:
            self._selected_eoat_key = normalized_eoat_key(eoat.eoat_id)
        if hasattr(self.controller, "photo_loader"):
            self.controller.photo_loader.update_selected_photo_context(eoat)
        self._render_detail(eoat)

    def open_folder(self) -> None:
        if self.current and self.current.photos.folder_path:
            open_path(self.current.photos.folder_path)

    def open_profile(self) -> None:
        if self.current is not None:
            self.controller.open_eoat(self.current.eoat_id)

    def copy_folder_path(self) -> None:
        path = self.current.photos.folder_path if self.current else ""
        QApplication.clipboard().setText(path)
        if path:
            self.controller.show_status("Copied photo folder path.")

    def view_photos(self, eoat: EOATRecord) -> None:
        photos = _combined_photos(eoat)
        if not photos:
            QMessageBox.information(self, "EOAT Photos", f"No linked photos were found for {eoat.eoat_id}.")
            return
        if self.controller.settings.photo_viewer_behavior == "open_folder":
            if eoat.photos.folder_path:
                open_path(eoat.photos.folder_path)
            return
        if self.controller.settings.photo_viewer_behavior == "external":
            open_path(photos[0].path)
            return
        viewer = PhotoCarouselDialog(eoat, parent=self, prefetch=self.controller.settings.carousel_prefetch)
        viewer.exec()

    def _render_detail(self, eoat: EOATRecord | None) -> None:
        self.current = eoat
        self.detail_panel.setUpdatesEnabled(False)
        _clear_layout(self.detail_layout)
        if eoat is None:
            self.detail_layout.addWidget(
                EmptyStateWidget(
                    "EOAT Photo Library",
                    "Select an EOAT photo set from the tree to review folder status, missing categories, and photo actions.",
                )
            )
            self.detail_layout.addStretch(1)
            _finalize_scroll_panel(self.detail_scroll, self.detail_panel, self.detail_layout)
            self.detail_panel.setUpdatesEnabled(True)
            return
        self.detail_layout.addWidget(_photo_detail_hero(eoat))
        self.detail_layout.addWidget(_photo_detail_actions(eoat, self))
        category_card = DetailCard("Photo Category Checklist", "Required categories show whether Atlas found indexed evidence.")
        category_card.layout.addWidget(_photo_category_checklist(eoat))
        self.detail_layout.addWidget(category_card)
        if _combined_photos(eoat):
            note = InfoPanel("Preview Loading", "Atlas keeps this library fast by loading full images only when View Photos opens the carousel.")
            note.layout.addWidget(_chip_group([f"{eoat.photo_count} image path(s) indexed", "Async carousel loading retained"], kind="info", per_row=2))
            self.detail_layout.addWidget(note)
        self.detail_layout.addStretch(1)
        _finalize_scroll_panel(self.detail_scroll, self.detail_panel, self.detail_layout)
        self.detail_panel.setUpdatesEnabled(True)


class StandardsPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.active_category = "All"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(PageHeader("Standards & Work Instructions", "Controlled standards, work instructions, checklists, and useful generated reports."))

        toolbar = ToolbarFilterRow(search_placeholder="Search title, preview, tags, EOAT ID, machine, tool, or category")
        self.filter = toolbar.search
        self.filter.textChanged.connect(self.refresh)
        self.type_filter = toolbar.add_combo(["All document types", "Controlled Standards", "Work Instructions", "PM / Inspection Checklists", "Generated Reports", "Templates", "Archived / Blank Templates"])
        self.type_filter.currentTextChanged.connect(self.refresh)
        self.status_filter = toolbar.add_combo(["All statuses", "Controlled", "Draft", "Template", "Generated", "Blank", "Archived"])
        self.status_filter.currentTextChanged.connect(self.refresh)
        self.sort_combo = toolbar.add_combo(["Relevance", "Modified date", "Type", "Title"])
        self.sort_combo.currentTextChanged.connect(self.refresh)
        self.show_templates_check = QCheckBox("Show templates")
        self.show_templates_check.toggled.connect(self.refresh)
        toolbar.add_toggle(self.show_templates_check)
        self.show_blank_check = QCheckBox("Show empty/blank documents")
        self.show_blank_check.toggled.connect(self.refresh)
        toolbar.add_toggle(self.show_blank_check)
        reset_button = toolbar.add_reset_button("Reset")
        reset_button.clicked.connect(self._reset_filters)

        self.category_row = QWidget()
        self.category_layout = QHBoxLayout(self.category_row)
        self.category_layout.setContentsMargins(0, 0, 0, 0)
        self.category_layout.setSpacing(8)
        self.category_buttons: dict[str, QPushButton] = {}
        for label in ["All", "Controlled Standards", "Work Instructions", "PM / Inspection Checklists", "Generated Reports", "Templates", "Archived / Blank Templates"]:
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, value=label: self._set_category(value))
            self.category_layout.addWidget(button)
            self.category_buttons[label] = button
        self.category_layout.addStretch(1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.card_widget = QWidget()
        self.card_layout = QVBoxLayout(self.card_widget)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(10)
        self.card_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.card_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.scroll.setWidget(self.card_widget)
        layout.addWidget(toolbar)
        layout.addWidget(self.category_row)
        layout.addWidget(self.scroll, 1)
        self._sync_category_buttons()

    def refresh(self) -> None:
        if self.bundle is None:
            return
        query = self.filter.text().strip().casefold()
        _clear_layout(self.card_layout)
        documents = _standards_documents(self.bundle)
        self.card_layout.addWidget(_standards_summary_grid(documents))
        matches = []
        for document in documents:
            haystack = " ".join([document["title"], document["type"], document["status"], document["snippet"], document["path"], " ".join(document["tags"])]).casefold()
            if query and query not in haystack:
                continue
            if not self.show_templates_check.isChecked() and document["status"] == "Template":
                continue
            if not self.show_blank_check.isChecked() and document["is_blank"]:
                continue
            if self.type_filter.currentText() != "All document types" and document["type"] != self.type_filter.currentText():
                continue
            if self.status_filter.currentText() != "All statuses" and document["status"] != self.status_filter.currentText():
                continue
            if self.active_category != "All" and document["type"] != self.active_category:
                continue
            matches.append(document)

        library = SectionCard("Document Library", f"{len(matches)} visible document(s). Blank/templates stay hidden until enabled.")
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for index, document in enumerate(_sort_documents(matches, self.sort_combo.currentText())):
            grid.addWidget(_standard_document_card(document, self.bundle), index // 2, index % 2)
        for column in range(2):
            grid.setColumnStretch(column, 1)
        library.layout.addLayout(grid)
        self.card_layout.addWidget(library)
        if not matches:
            self.card_layout.addWidget(EmptyStateWidget("No standards matched", "Try a category, document title, EOAT ID, machine, tool, tag, or keyword."))
        self.card_layout.addStretch(1)

    def _set_category(self, category: str) -> None:
        self.active_category = category
        self._sync_category_buttons()
        self.refresh()

    def _sync_category_buttons(self) -> None:
        for label, button in self.category_buttons.items():
            button.blockSignals(True)
            button.setChecked(label == self.active_category)
            button.blockSignals(False)

    def _reset_filters(self) -> None:
        self.filter.clear()
        self.type_filter.setCurrentIndex(0)
        self.status_filter.setCurrentIndex(0)
        self.sort_combo.setCurrentIndex(0)
        self.show_templates_check.setChecked(False)
        self.show_blank_check.setChecked(False)
        self._set_category("All")

    def open_selected(self) -> None:
        return None


class PMInspectionPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("PM / Inspection", "Generated PM and pre-install guidance from loaded EOAT data."))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        self.content_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)

    def refresh(self) -> None:
        if self.bundle is None:
            return
        _clear_layout(self.content_layout)
        missing_pm = [eoat.eoat_id for eoat in self.bundle.eoats if "Maintenance Frequency" in eoat.documentation.missing_fields]
        groups = [
            (
                "Weekly Inspection",
                [
                    "Check cups/grippers for wear, cracks, looseness, or missing hardware.",
                    "Inspect tubing and cable routing for pinch, rub, kink, or strain points.",
                    "Verify quick disconnects, sensors, and confirmation signals before production.",
                    "Review known issues for the EOAT and machine before install.",
                ],
            ),
            (
                "Monthly Inspection",
                [
                    "Verify EOAT documentation, BOM/spare parts, and revision references.",
                    "Review repeated wear/damage notes and update PM frequency if needed.",
                    "Confirm photo evidence still represents current EOAT condition.",
                ],
            ),
            (
                "Pre-Install Readiness",
                [
                    "Confirm EOAT, tool, and machine compatibility before staging.",
                    "Check robot information and pneumatic/vacuum requirements.",
                    "Review warning cards and missing photo categories.",
                ],
            ),
        ]
        grid = QGridLayout()
        grid.setSpacing(10)
        for index, (title, items) in enumerate(groups):
            card = ChecklistCard(title, "Inspection guidance generated from Atlas context.")
            card.layout.addWidget(badge("Weekly" if "Weekly" in title else ("Monthly" if "Monthly" in title else "Pre-install"), "outline"))
            for item_index, item in enumerate(items, start=1):
                card.layout.addWidget(_checklist_row(str(item_index), item, kind="outline"))
            grid.addWidget(card, index // 2, index % 2)
        self.content_layout.addLayout(grid)
        missing = WarningCard("EOATs Missing PM Frequency", "These records need source data cleanup.", severity="warn") if missing_pm else SuccessCard("PM Frequency Coverage", "No missing PM frequency fields found.")
        if missing_pm:
            missing.layout.addWidget(_chip_group(missing_pm[:80], kind="warn", per_row=6))
        self.content_layout.addWidget(missing)
        self.content_layout.addStretch(1)


class InformationLibraryPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.entries: list[InformationLibraryEntry] = []
        self.filtered_entries: list[InformationLibraryEntry] = []
        self.entry_by_id: dict[str, InformationLibraryEntry] = {}
        self._selected_entry_id = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(
            page_title(
                "Information Library",
                "Browse Atlas help, EOAT standards, compatibility logic, photo rules, PM guidance, and troubleshooting references.",
            )
        )
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        self.search = ModernSearchBar("Search title, summary, examples, fields, source document, or tags")
        self.search.textChanged.connect(self.refresh)
        self.type_filter = QComboBox()
        self.type_filter.currentTextChanged.connect(self.refresh)
        self.category = QComboBox()
        self.category.currentTextChanged.connect(self.refresh)
        self.sort = QComboBox()
        self.sort.addItems(["Relevance", "Category", "Source document", "Title", "Last modified"])
        self.sort.currentTextChanged.connect(self.refresh)
        controls.addWidget(self.search, 1)
        controls.addWidget(self.type_filter)
        controls.addWidget(self.category)
        controls.addWidget(self.sort)
        layout.addLayout(controls)
        self.result_label = QLabel("")
        self.result_label.setObjectName("MicroText")
        layout.addWidget(self.result_label)

        splitter = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setObjectName("InformationTree")
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(330)
        self.tree.setMaximumWidth(470)
        self.tree.itemSelectionChanged.connect(self._tree_selection_changed)

        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.detail_widget = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_widget)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(10)
        self.detail_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.detail_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.detail_scroll.setWidget(self.detail_widget)

        splitter.addWidget(self.tree)
        splitter.addWidget(self.detail_scroll)
        splitter.setSizes([390, 880])
        layout.addWidget(splitter, 1)

    def set_bundle(self, bundle: AtlasDataBundle | None) -> None:
        self.bundle = bundle
        self.entries = _build_information_entries(bundle) if bundle is not None else []
        self.entry_by_id = {entry.entry_id: entry for entry in self.entries}
        self._sync_entry_types()
        self._sync_categories()
        self.refresh()

    def _sync_entry_types(self) -> None:
        selected = self.type_filter.currentText() if self.type_filter.count() else "All Types"
        labels = {
            entry_type_label(entry.entry_type): entry.entry_type
            for entry in self.entries
        }
        self.type_filter.blockSignals(True)
        self.type_filter.clear()
        self.type_filter.addItem("All Types", "")
        for label in sorted(labels):
            self.type_filter.addItem(label, labels[label])
        if selected:
            index = self.type_filter.findText(selected)
            if index >= 0:
                self.type_filter.setCurrentIndex(index)
        self.type_filter.blockSignals(False)

    def _sync_categories(self) -> None:
        selected = self.category.currentText() if self.category.count() else "All Categories"
        categories = ["All Categories", *sorted({entry.category for entry in self.entries})]
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItems(categories)
        if selected in categories:
            self.category.setCurrentText(selected)
        self.category.blockSignals(False)

    def refresh(self) -> None:
        if self.bundle is None:
            return
        query = self.search.text().strip()
        selected_type = self.type_filter.currentData() if self.type_filter.count() else ""
        category = self.category.currentText()
        scored = []
        for entry in self.entries:
            if selected_type and entry.entry_type != selected_type:
                continue
            if category and category != "All Categories" and entry.category != category:
                continue
            score = _information_score(entry, query)
            if query and score <= 0:
                continue
            scored.append((score, entry))
        sort_mode = self.sort.currentText()
        if sort_mode == "Category":
            scored.sort(key=lambda item: (item[1].category.casefold(), item[1].title.casefold()))
        elif sort_mode == "Source document":
            scored.sort(key=lambda item: (item[1].source.document_name.casefold(), item[1].title.casefold()))
        elif sort_mode == "Title":
            scored.sort(key=lambda item: item[1].title.casefold())
        elif sort_mode == "Last modified":
            scored.sort(key=lambda item: (-item[1].modified, item[1].title.casefold()))
        else:
            scored.sort(key=lambda item: (-item[0], item[1].category.casefold(), item[1].title.casefold()))
        self.filtered_entries = [entry for _score, entry in scored]
        self.result_label.setText(f"{len(self.filtered_entries)} reference(s)")
        self._rebuild_tree(query)
        selected = self.entry_by_id.get(self._selected_entry_id)
        if selected not in self.filtered_entries:
            selected = self.filtered_entries[0] if self.filtered_entries else None
        self._render_detail(selected)

    def _rebuild_tree(self, query: str) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        nodes: dict[tuple[str, ...], QTreeWidgetItem] = {}
        selected_item: QTreeWidgetItem | None = None
        for entry in self.filtered_entries:
            if query:
                path_parts = ("Search Results", entry_type_label(entry.entry_type), entry.source.source_type)
            else:
                path_parts = _library_tree_path_for_entry(entry)
            if not path_parts:
                path_parts = (entry.category or "Library",)
            parent_item: QTreeWidgetItem | None = None
            current_path: tuple[str, ...] = ()
            for part in path_parts:
                current_path = (*current_path, part)
                item = nodes.get(current_path)
                if item is None:
                    item = QTreeWidgetItem([part])
                    item.setData(0, Qt.ItemDataRole.UserRole, "")
                    item.setToolTip(0, " / ".join(current_path))
                    if parent_item is None:
                        self.tree.addTopLevelItem(item)
                    else:
                        parent_item.addChild(item)
                    nodes[current_path] = item
                parent_item = item
            snippet = information_snippet(entry, query, limit=86) if query else ""
            leaf_title = f"{entry.title} - {snippet}" if snippet else entry.title
            leaf = QTreeWidgetItem([leaf_title])
            leaf.setData(0, Qt.ItemDataRole.UserRole, entry.entry_id)
            leaf.setToolTip(
                0,
                "\n".join(
                    part
                    for part in [
                        entry.title,
                        entry_type_label(entry.entry_type),
                        information_snippet(entry, query, limit=160) if query else entry.summary,
                        f"Source: {entry.source.source_type}",
                        f"Tags: {', '.join(entry.tags[:8])}" if entry.tags else "",
                    ]
                    if part
                ),
            )
            if parent_item is None:
                self.tree.addTopLevelItem(leaf)
            else:
                parent_item.addChild(leaf)
            if entry.entry_id == self._selected_entry_id:
                selected_item = leaf
        if query:
            self.tree.expandAll()
        else:
            for index in range(self.tree.topLevelItemCount()):
                self.tree.topLevelItem(index).setExpanded(index < 3)
        if selected_item is None and self.filtered_entries:
            selected_id = self.filtered_entries[0].entry_id
            selected_item = self._find_tree_item(selected_id)
        if selected_item is not None:
            self.tree.setCurrentItem(selected_item)
            self.tree.scrollToItem(selected_item)
        self.tree.blockSignals(False)

    def _find_tree_item(self, entry_id: str) -> QTreeWidgetItem | None:
        stack = [self.tree.topLevelItem(index) for index in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item.data(0, Qt.ItemDataRole.UserRole) == entry_id:
                return item
            stack.extend(item.child(index) for index in range(item.childCount()))
        return None

    def _tree_selection_changed(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        entry_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not entry_id:
            item.setExpanded(not item.isExpanded())
            return
        self._selected_entry_id = str(entry_id)
        self._render_detail(self.entry_by_id.get(self._selected_entry_id))

    def _render_detail(self, entry: InformationLibraryEntry | None) -> None:
        _clear_layout(self.detail_layout)
        if entry is None:
            self.detail_layout.addWidget(
                EmptyStateWidget(
                    "No library entry selected",
                    "Use the tree or search/filter controls to choose a standards, help, compatibility, photo, PM, report, or troubleshooting topic.",
                )
            )
            self.detail_layout.addStretch(1)
            _finalize_scroll_panel(self.detail_scroll, self.detail_widget, self.detail_layout)
            return
        self._selected_entry_id = entry.entry_id
        header = ProfileHeaderCard(
            entry.title,
            entry.summary,
            eyebrow=f"{entry_type_label(entry.entry_type)} / {entry.category}",
        )
        header.layout.addWidget(
            _chip_group(
                [
                    entry_type_label(entry.entry_type),
                    entry.category,
                    entry.source.source_type,
                    *_tree_label_parts(entry.tree_path)[1:3],
                    *entry.tags[:5],
                ],
                kind="info",
                per_row=4,
                limit=10,
            )
        )
        self.detail_layout.addWidget(header)

        takeaway = SuccessCard("Key Takeaway", entry.key_takeaway or entry.summary)
        self.detail_layout.addWidget(takeaway)

        toc_items = [section.title for section in entry.sections]
        if entry.examples:
            toc_items.append("Examples")
        if entry.warnings:
            toc_items.append("Warnings / Common Mistakes")
        if entry.related_fields:
            toc_items.append("Related Atlas Fields")
        if entry.related_pages or entry.related_references:
            toc_items.append("Related Pages / References")
        if len(toc_items) >= 6:
            toc = SecondaryCard("Contents", "Main sections in this reference.")
            toc.layout.addWidget(_chip_group(toc_items, kind="outline", per_row=4, limit=16))
            self.detail_layout.addWidget(toc)

        body = PrimaryCard(f"{entry_type_label(entry.entry_type)} Details", entry.summary, eyebrow="Main Content")
        for section in entry.sections:
            body.layout.addWidget(_information_section_block(section.title, section.items))
        self.detail_layout.addWidget(body)

        if entry.examples:
            examples = SecondaryCard("Examples", "Concrete inputs, logic, and outputs from Atlas behavior.")
            for example in entry.examples:
                examples.layout.addWidget(_information_example_block(example))
            self.detail_layout.addWidget(examples)

        if entry.warnings:
            warnings = WarningCard("Warnings / Common Mistakes", "Checks that commonly change the engineering interpretation.")
            warnings.layout.addWidget(_information_list_block(entry.warnings))
            self.detail_layout.addWidget(warnings)

        if entry.related_fields:
            fields = SecondaryCard("Related Atlas Fields", "Fields that affect or are affected by this reference.")
            fields.layout.addWidget(_chip_group(entry.related_fields, kind="outline", per_row=4, limit=16))
            self.detail_layout.addWidget(fields)

        if entry.related_pages or entry.related_references:
            related = SecondaryCard("Related Pages / References", "Nearby content that helps interpret or repair the issue.")
            if entry.related_pages:
                related.layout.addWidget(_information_section_block("Atlas Pages", entry.related_pages))
            if entry.related_references:
                related.layout.addWidget(_information_section_block("References", entry.related_references))
            self.detail_layout.addWidget(related)

        metadata = InfoPanel("Source Metadata", "Reference provenance and indexing details.")
        metadata.layout.addWidget(
            key_value_grid(
                [
                    ("Entry type", entry_type_label(entry.entry_type)),
                    ("Tree path", " / ".join(entry.tree_path) or entry.category),
                    ("Source type", entry.source.source_type),
                    ("Source document", entry.source.document_name),
                    ("Source section", entry.source.section_label),
                    ("File", _short_path(entry.source.file_label) if entry.path else entry.source.file_label),
                    ("Last modified", entry.source.modified_label),
                    ("Indexed", _format_modified(entry.indexed_at)),
                ]
            )
        )
        self.detail_layout.addWidget(metadata)

        buttons = []
        if entry.source.file_exists:
            open_button = QPushButton("Open Source Document")
            open_button.setObjectName("PrimaryButton")
            open_button.clicked.connect(lambda _checked=False, path=entry.path: open_path(path))
            buttons.append(open_button)
        copy_summary = QPushButton("Copy Summary")
        copy_summary.clicked.connect(lambda _checked=False, text=f"{entry.title}\n\n{entry.summary}": self._copy_text(text, "summary"))
        buttons.append(copy_summary)
        copy_full = QPushButton("Copy Full Text / Reference")
        copy_full.clicked.connect(lambda _checked=False, selected_entry=entry: self._copy_text(_information_reference_text(selected_entry), "reference"))
        buttons.append(copy_full)
        self.detail_layout.addWidget(action_row(*buttons))
        self.detail_layout.addStretch(1)
        _finalize_scroll_panel(self.detail_scroll, self.detail_widget, self.detail_layout)

    def _copy_text(self, text: str, label: str) -> None:
        QApplication.clipboard().setText(text)
        self.controller.show_status(f"Copied library {label}.")


class ReportsPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Reports & Handoff", "Timestamped report center for setup, compatibility, documentation, photos, PM, analytics, and final handoff."))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        self.content_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)

    def refresh(self) -> None:
        _clear_layout(self.content_layout)
        grouped: dict[str, list] = {}
        for definition in atlas_report_catalog():
            grouped.setdefault(definition.section, []).append(definition)
        for section, definitions in grouped.items():
            group, group_layout = _group_container(section, "Reports are timestamped and do not overwrite previous outputs.")
            grid = QGridLayout()
            grid.setSpacing(10)
            for index, definition in enumerate(definitions):
                grid.addWidget(self._report_card(definition), index // 3, index % 3)
            group_layout.addLayout(grid)
            self.content_layout.addWidget(group)
        self.content_layout.addStretch(1)

    def _report_card(self, definition) -> QWidget:
        latest = latest_atlas_report(self.bundle, definition.report_id) if self.bundle else None
        card = ExportActionCard(definition.name, definition.purpose, "Generate")
        card.layout.addWidget(
            _chip_group(
                [
                    f"Output: {definition.output_type}",
                    f"Last generated: {_format_modified(latest.stat().st_mtime) if latest else 'Never'}",
                    f"Source: {', '.join(definition.source_data)}",
                ],
                kind="outline",
                per_row=1,
                limit=3,
            )
        )
        card.button.clicked.connect(lambda _checked=False, definition=definition: self._run_report(definition))
        open_latest = QPushButton("Open Latest")
        open_latest.setEnabled(latest is not None)
        open_latest.clicked.connect(lambda _checked=False, path=latest: open_path(path) if path else None)
        open_folder = QPushButton("Open Folder")
        open_folder.clicked.connect(lambda _checked=False, definition=definition: self._open_report_folder(definition))
        card.layout.addWidget(action_row(open_latest, open_folder))
        return card

    def _run_report(self, definition) -> None:
        bundle = self.require_bundle()
        if bundle is None:
            return
        if definition.report_id == "setup.changeover_pdf":
            if hasattr(self.controller, "open_setup_packet"):
                self.controller.open_setup_packet(context_label="Reports & Handoff")
            return
        path = generate_atlas_report(bundle, definition.report_id)
        self.controller.show_status(f"Generated {definition.name}: {path}")
        self.refresh()

    def _open_report_folder(self, definition) -> None:
        bundle = self.require_bundle()
        if bundle is None:
            return
        latest = latest_atlas_report(bundle, definition.report_id)
        if latest:
            open_path(latest.parent)
            return
        open_path(atlas_export_dir(bundle.project_root))


class SetupPacketPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.machine_id = ""
        self.tool_id = ""
        self.eoat_id = ""
        self.context_label = ""
        self.override_confirmed = False
        self.last_packet_path: Path | None = None
        self._syncing_options = False
        self._pending_packet_settings = None
        self._packet_settings_timer = QTimer(self)
        self._packet_settings_timer.setSingleShot(True)
        self._packet_settings_timer.setInterval(450)
        self._packet_settings_timer.timeout.connect(self._flush_packet_settings)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(12)
        outer.addWidget(
            page_title(
                "Changeover Packet Builder",
                "Build a printable setup/changeover PDF for a selected Machine + Tool/Mold/Part + EOAT combination.",
            )
        )

        splitter = QSplitter()
        splitter.setObjectName("AtlasMainSplitter")
        self.workflow_scroll = QScrollArea()
        self.workflow_scroll.setWidgetResizable(True)
        self.workflow_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        workflow = QWidget()
        workflow_layout = QVBoxLayout(workflow)
        workflow_layout.setContentsMargins(0, 0, 0, 0)
        workflow_layout.setSpacing(10)
        workflow_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.workflow_scroll.setWidget(workflow)

        selector_card = PrimaryCard(
            "1. Start anywhere",
            "Start anywhere. Choose a Machine, Tool/Mold/Part, or EOAT. Atlas will filter the remaining choices to compatible options.",
        )
        selection_tools = QHBoxLayout()
        selection_tools.setContentsMargins(0, 0, 0, 0)
        self.prefill_note = QLabel("")
        self.prefill_note.setObjectName("MutedText")
        self.prefill_note.setVisible(False)
        self.reset_selection_button = QPushButton("Reset Selection")
        self.reset_selection_button.clicked.connect(self.reset_selection)
        self.clear_machine_button = QPushButton("Clear Machine")
        self.clear_machine_button.clicked.connect(lambda: self.clear_selection("machine"))
        self.clear_tool_button = QPushButton("Clear Tool")
        self.clear_tool_button.clicked.connect(lambda: self.clear_selection("tool"))
        self.clear_eoat_button = QPushButton("Clear EOAT")
        self.clear_eoat_button.clicked.connect(lambda: self.clear_selection("eoat"))
        selection_tools.addWidget(self.prefill_note)
        selection_tools.addStretch(1)
        selection_tools.addWidget(self.reset_selection_button)
        selection_tools.addWidget(self.clear_machine_button)
        selection_tools.addWidget(self.clear_tool_button)
        selection_tools.addWidget(self.clear_eoat_button)
        selector_card.layout.addLayout(selection_tools)
        selector_grid = QGridLayout()
        selector_grid.setContentsMargins(0, 0, 0, 0)
        selector_grid.setSpacing(10)
        self.machine_selector = _SetupPacketRecordSelector(
            "Machine", "Search machines", self._machine_rows, self._machine_selected, self._record_health
        )
        self.tool_selector = _SetupPacketRecordSelector(
            "Tool / Mold / Part", "Search tools, molds, parts", self._tool_rows, self._tool_selected, self._record_health
        )
        self.eoat_selector = _SetupPacketRecordSelector(
            "EOAT", "Search EOAT IDs", self._eoat_rows, self._eoat_selected, self._record_health
        )
        selector_grid.addWidget(self.machine_selector, 0, 0)
        selector_grid.addWidget(self.tool_selector, 0, 1)
        selector_grid.addWidget(self.eoat_selector, 0, 2)
        for column in range(3):
            selector_grid.setColumnStretch(column, 1)
        selector_card.layout.addLayout(selector_grid)
        self.empty_note = QLabel("")
        self.empty_note.setObjectName("MutedText")
        self.empty_note.setWordWrap(True)
        selector_card.layout.addWidget(self.empty_note)
        self.selection_status = QLabel("Start by selecting any Machine, Tool/Mold/Part, or EOAT.")
        self.selection_status.setObjectName("BodyText")
        self.selection_status.setWordWrap(True)
        selector_card.layout.addWidget(self.selection_status)
        workflow_layout.addWidget(selector_card)

        self.review_card = PrimaryCard("2. Fit Check Review", "Review the selected setup before generating.")
        self.review_layout = QVBoxLayout()
        self.review_layout.setContentsMargins(0, 0, 0, 0)
        self.review_layout.setSpacing(8)
        self.review_card.layout.addLayout(self.review_layout)
        workflow_layout.addWidget(self.review_card)

        options_card = PrimaryCard("3. Packet Options", "Feature-specific packet settings persist here and do not touch source workbooks.")
        options_grid = QGridLayout()
        options_grid.setContentsMargins(0, 0, 0, 0)
        options_grid.setHorizontalSpacing(12)
        options_grid.setVerticalSpacing(8)
        self.setup_packet_type_combo = _settings_combo([PACKET_TYPE_LABELS[key] for key in PACKET_TYPE_CHOICES])
        self.setup_packet_photo_combo = _settings_combo([PHOTO_INCLUSION_LABELS[key] for key in PHOTO_INCLUSION_CHOICES])
        self.setup_packet_detail_combo = _settings_combo(["Standard", "Detailed"])
        self.setup_packet_open_combo = _settings_combo(["Ask each time", "In app", "External PDF viewer", "Open folder"])
        for index, (label, widget) in enumerate(
            [
                ("Packet type", self.setup_packet_type_combo),
                ("Photo inclusion", self.setup_packet_photo_combo),
                ("Detail level", self.setup_packet_detail_combo),
                ("Open behavior", self.setup_packet_open_combo),
            ]
        ):
            label_widget = QLabel(label)
            label_widget.setObjectName("MetricLabel")
            options_grid.addWidget(label_widget, index // 2 * 2, (index % 2) * 2)
            options_grid.addWidget(widget, index // 2 * 2 + 1, (index % 2) * 2)
        options_card.layout.addLayout(options_grid)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Advanced Options")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.toggled.connect(self._toggle_advanced_options)
        options_card.layout.addWidget(self.advanced_toggle)
        self.advanced_options = QWidget()
        advanced_grid = QGridLayout(self.advanced_options)
        advanced_grid.setContentsMargins(0, 0, 0, 0)
        advanced_grid.setHorizontalSpacing(12)
        advanced_grid.setVerticalSpacing(8)
        self.setup_packet_qr_check = _settings_check("Include a QR label when QR Codes are enabled globally.")
        self.setup_packet_override_check = _settings_check("Show manual override controls for unconfirmed combinations.")
        self.setup_packet_qr_helper = QLabel("Enable QR Codes in Settings to include a QR label in changeover packets.")
        self.setup_packet_qr_helper.setObjectName("MutedText")
        self.setup_packet_qr_helper.setWordWrap(True)
        self.open_qr_settings_button = QPushButton("Open QR Settings")
        self.open_qr_settings_button.clicked.connect(self._open_qr_settings)
        self.override_button = QPushButton("Allow incompatible / unconfirmed selection")
        self.override_button.clicked.connect(self.confirm_override)
        qr_label = QLabel("Include QR label")
        qr_label.setObjectName("MetricLabel")
        advanced_grid.addWidget(qr_label, 0, 0)
        advanced_grid.addWidget(self.setup_packet_qr_check, 0, 1)
        qr_help_row = QHBoxLayout()
        qr_help_row.setContentsMargins(0, 0, 0, 0)
        qr_help_row.setSpacing(8)
        qr_help_row.addWidget(self.setup_packet_qr_helper, 1)
        qr_help_row.addWidget(self.open_qr_settings_button)
        advanced_grid.addLayout(qr_help_row, 1, 1)
        override_label = QLabel("Allow manual override combinations")
        override_label.setObjectName("MetricLabel")
        advanced_grid.addWidget(override_label, 2, 0)
        advanced_grid.addWidget(self.setup_packet_override_check, 2, 1)
        confirm_label = QLabel("Manual override confirmation")
        confirm_label.setObjectName("MetricLabel")
        advanced_grid.addWidget(confirm_label, 3, 0)
        advanced_grid.addWidget(self.override_button, 3, 1)
        advanced_grid.setColumnStretch(1, 1)
        self.advanced_options.setVisible(False)
        options_card.layout.addWidget(self.advanced_options)
        workflow_layout.addWidget(options_card)

        generate_card = PrimaryCard("4. Generate / View PDF", "Create the PDF export and open the result from Atlas.")
        self.generate_button = QPushButton("Generate PDF")
        self.generate_button.setObjectName("PrimaryButton")
        self.generate_button.clicked.connect(self.generate_pdf)
        self.open_last_button = QPushButton("Open Last Packet")
        self.open_last_button.clicked.connect(self.open_last_packet)
        self.open_folder_button = QPushButton("Open Packet Folder")
        self.open_folder_button.clicked.connect(self.open_packet_folder)
        self.copy_last_button = QPushButton("Copy Last Packet Path")
        self.copy_last_button.clicked.connect(self.copy_last_packet_path)
        self.last_packet_label = QLabel("No packet generated this session.")
        self.last_packet_label.setObjectName("MutedText")
        self.last_packet_label.setWordWrap(True)
        generate_card.layout.addWidget(
            action_row(self.generate_button, self.open_last_button, self.open_folder_button, self.copy_last_button)
        )
        generate_card.layout.addWidget(self.last_packet_label)
        workflow_layout.addWidget(generate_card)
        workflow_layout.addStretch(1)

        view_panel = QWidget()
        view_panel.setMinimumWidth(350)
        view_layout = QVBoxLayout(view_panel)
        view_layout.setContentsMargins(10, 0, 0, 0)
        view_layout.setSpacing(10)
        library_title = QLabel("Packet Library")
        library_title.setObjectName("CardTitle")
        library_title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        view_layout.addWidget(library_title)
        library_subtitle = QLabel("View, open, print, or share generated changeover packets.")
        library_subtitle.setObjectName("MutedText")
        library_subtitle.setWordWrap(True)
        library_subtitle.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        view_layout.addWidget(library_subtitle)

        preview = SecondaryCard("Latest Packet")
        self.latest_pdf_info = QLabel("")
        self.latest_pdf_info.setVisible(False)
        self.latest_setup_label = QLabel("No changeover packet generated yet.")
        self.latest_setup_label.setObjectName("TileTitle")
        self.latest_setup_label.setWordWrap(True)
        preview.layout.addWidget(self.latest_setup_label)
        self.latest_empty_label = QLabel("Generate a packet to preview it here.")
        self.latest_empty_label.setObjectName("MutedText")
        self.latest_empty_label.setWordWrap(True)
        preview.layout.addWidget(self.latest_empty_label)
        latest_chip_row = QHBoxLayout()
        latest_chip_row.setContentsMargins(0, 0, 0, 0)
        latest_chip_row.setSpacing(6)
        self.latest_type_chip = badge("Changeover Packet", "info")
        self.latest_compat_chip = badge("Fit Check", "info")
        latest_chip_row.addWidget(self.latest_type_chip)
        latest_chip_row.addWidget(self.latest_compat_chip)
        latest_chip_row.addStretch(1)
        preview.layout.addLayout(latest_chip_row)
        self.latest_generated_label = QLabel("Generated: -")
        self.latest_generated_label.setObjectName("MutedText")
        self.latest_size_label = QLabel("File size: -")
        self.latest_size_label.setObjectName("MutedText")
        self.latest_photo_label = QLabel("Photo inclusion: -")
        self.latest_photo_label.setObjectName("MutedText")
        self.latest_override_label = QLabel("")
        self.latest_override_label.setObjectName("MutedText")
        for label in (
            self.latest_generated_label,
            self.latest_size_label,
            self.latest_photo_label,
            self.latest_override_label,
        ):
            label.setWordWrap(True)
            preview.layout.addWidget(label)
        self.latest_filename_label = QLabel("")
        self.latest_filename_label.setObjectName("MutedText")
        self.latest_filename_label.setWordWrap(True)
        preview.layout.addWidget(self.latest_filename_label)
        self.latest_pdf_info.setObjectName("BodyText")
        preview.layout.addWidget(self.latest_pdf_info)
        self.view_in_app_button = QPushButton("View")
        self.view_in_app_button.setToolTip("View this changeover packet inside Atlas.")
        self.view_in_app_button.clicked.connect(self.view_latest_packet_in_app)
        self.latest_open_pdf_button = QPushButton("Open")
        self.latest_open_pdf_button.setToolTip("Open this changeover packet in the default PDF viewer.")
        self.latest_open_pdf_button.clicked.connect(self.open_last_packet)
        self.latest_open_folder_button = QPushButton("Folder")
        self.latest_open_folder_button.setToolTip("Open the packet export folder.")
        self.latest_open_folder_button.clicked.connect(self.open_latest_folder)
        self.latest_copy_path_button = QPushButton("Copy Path")
        self.latest_copy_path_button.clicked.connect(self.copy_last_packet_path)
        preview.layout.addWidget(
            action_row(
                self.view_in_app_button,
                self.latest_open_pdf_button,
                self.latest_open_folder_button,
                self.latest_copy_path_button,
            )
        )
        view_layout.addWidget(preview)
        previous = SecondaryCard("Previous Packets", "Recent changeover packet exports in the packet folder.")
        refresh_row = QHBoxLayout()
        refresh_row.setContentsMargins(0, 0, 0, 0)
        self.refresh_packets_button = QPushButton("Refresh")
        self.refresh_packets_button.clicked.connect(self.refresh_packet_list)
        self.library_open_folder_button = QPushButton("Open Packet Folder")
        self.library_open_folder_button.clicked.connect(self.open_packet_folder)
        refresh_row.addStretch(1)
        refresh_row.addWidget(self.refresh_packets_button)
        refresh_row.addWidget(self.library_open_folder_button)
        previous.layout.addLayout(refresh_row)
        self.packet_list = QListWidget()
        self.packet_list.setObjectName("CardList")
        self.packet_list.itemActivated.connect(self._view_selected_packet)
        previous.layout.addWidget(self.packet_list, 1)
        view_layout.addWidget(previous, 1)

        splitter.addWidget(self.workflow_scroll)
        splitter.addWidget(view_panel)
        splitter.setSizes([900, 360])
        outer.addWidget(splitter, 1)

        for option_name, widget in [
            ("packet_type", self.setup_packet_type_combo),
            ("photo_inclusion", self.setup_packet_photo_combo),
            ("detail_level", self.setup_packet_detail_combo),
            ("open_behavior", self.setup_packet_open_combo),
        ]:
            widget.currentTextChanged.connect(
                lambda _text="", option_name=option_name: self._packet_option_changed(option_name)
            )
        self.setup_packet_qr_check.toggled.connect(lambda _checked=False: self._packet_option_changed("include_qr"))
        self.setup_packet_override_check.toggled.connect(
            lambda _checked=False: self._packet_option_changed("allow_override")
        )
        self._sync_option_controls()
        self._update_latest_packet_summary()
        self.refresh_review()
        self._sync_generate_state()

    def set_bundle(self, bundle: AtlasDataBundle | None) -> None:
        self.bundle = bundle
        self.refresh()

    def settings_changed(self) -> None:
        self._sync_option_controls()
        self.refresh_review(preserve_scroll=True)
        self._sync_generate_state()

    def page_shown(self) -> None:
        self.refresh_packet_list()

    def prefill_context(
        self,
        *,
        machine_id: str = "",
        tool_id: str = "",
        eoat_id: str = "",
        recommendation: RecommendationResult | None = None,
        context_label: str = "Atlas",
    ) -> None:
        if recommendation is not None and recommendation.best is not None:
            eoat_id = eoat_id or recommendation.best.eoat_id
            tool_id = tool_id or (recommendation.best.tools[0] if recommendation.best.tools else "")
            machine_id = machine_id or (recommendation.best.machines[0] if recommendation.best.machines else "")
        if machine_id:
            self.machine_id = str(machine_id).strip()
        if tool_id:
            self.tool_id = str(tool_id).strip()
        if eoat_id:
            self.eoat_id = str(eoat_id).strip()
        self.context_label = context_label
        self.refresh()

    def refresh(self) -> None:
        self._refresh_selection_panels()
        self.refresh_review()
        self.refresh_packet_list()
        self._sync_generate_state()

    def _refresh_selection_panels(self) -> None:
        note = _setup_packet_prefill_note(self.context_label)
        self.prefill_note.setText(note)
        self.prefill_note.setVisible(bool(note))
        self.machine_selector.refresh(self.machine_id, selected_record=_find_machine(self.bundle, self.machine_id))
        self.tool_selector.refresh(self.tool_id, selected_record=_find_tool(self.bundle, self.tool_id))
        self.eoat_selector.refresh(self.eoat_id, selected_record=_find_eoat(self.bundle, self.eoat_id))
        self._refresh_empty_note()
        self._refresh_selection_status()

    def generate_install_packet(self) -> None:
        self.generate_pdf()

    def reset_selection(self) -> None:
        self.machine_id = ""
        self.tool_id = ""
        self.eoat_id = ""
        self.context_label = ""
        self.override_confirmed = False
        self.refresh()

    def clear_selection(self, item_type: str) -> None:
        if item_type == "machine":
            self.machine_id = ""
        elif item_type == "tool":
            self.tool_id = ""
        elif item_type == "eoat":
            self.eoat_id = ""
        self.override_confirmed = False
        self.refresh()

    def _machine_rows(self):
        if self.bundle is None:
            return ()
        return selectable_machines(
            self.bundle,
            tool_id=self.tool_id,
            eoat_id=self.eoat_id,
            allow_unconfirmed=self.override_confirmed,
        )

    def _tool_rows(self):
        if self.bundle is None:
            return ()
        return selectable_tools(
            self.bundle,
            machine_id=self.machine_id,
            eoat_id=self.eoat_id,
            allow_unconfirmed=self.override_confirmed,
        )

    def _eoat_rows(self):
        if self.bundle is None:
            return ()
        return selectable_eoats(
            self.bundle,
            machine_id=self.machine_id,
            tool_id=self.tool_id,
            allow_unconfirmed=self.override_confirmed,
        )

    def _record_health(self, record) -> RelationshipHealth:
        if isinstance(record, MachineRecord):
            return machine_relationship_health(record)
        if isinstance(record, ToolRecord):
            return tool_relationship_health(record)
        if isinstance(record, EOATRecord):
            return eoat_relationship_health(record)
        return RelationshipHealth.UNKNOWN

    def _refresh_selection_status(self) -> None:
        if self.bundle is None:
            self.selection_status.setText("Atlas data is loading.")
            return
        selected = [
            ("Machine", self.machine_id),
            ("Tool/Mold/Part", self.tool_id),
            ("EOAT", self.eoat_id),
        ]
        active = [(label, value) for label, value in selected if value]
        if not active:
            self.selection_status.setText("Start by selecting any Machine, Tool/Mold/Part, or EOAT.")
            return
        if len(active) < 3:
            self.selection_status.setText("Filtered by: " + ", ".join(f"{label} {value}" for label, value in active))
            return
        validation = validate_setup_context(
            self.bundle,
            self.machine_id,
            self.tool_id,
            self.eoat_id,
            manual_override_used=self.override_confirmed,
        )
        if validation.status == COMPATIBILITY_CONFIRMED:
            self.selection_status.setText("Ready to build packet.")
        elif self.override_confirmed:
            self.selection_status.setText("Manual override enabled. This combination will be clearly marked for review.")
        else:
            self.selection_status.setText("This combination is not validated. Enable manual override to continue.")

    def _machine_selected(self, record: MachineRecord) -> None:
        if self.bundle is None:
            return
        if not self.override_confirmed and record not in selectable_machines(self.bundle, tool_id=self.tool_id, eoat_id=self.eoat_id):
            return
        self.machine_id = record.machine
        self.refresh()

    def _tool_selected(self, record: ToolRecord) -> None:
        if self.bundle is None:
            return
        if not self.override_confirmed and record not in selectable_tools(self.bundle, machine_id=self.machine_id, eoat_id=self.eoat_id):
            return
        self.tool_id = record.tool
        self.refresh()

    def _eoat_selected(self, record: EOATRecord) -> None:
        if self.bundle is None:
            return
        if not self.override_confirmed and record not in selectable_eoats(self.bundle, machine_id=self.machine_id, tool_id=self.tool_id):
            return
        self.eoat_id = record.eoat_id
        self.refresh()

    def confirm_override(self) -> None:
        message = (
            "This combination is not confirmed by Atlas compatibility data.\n\n"
            "Generate this packet only if you have verified the setup through another approved source. "
            "The PDF will be marked Fit Check Not Confirmed."
        )
        result = QMessageBox.warning(
            self,
            "Allow incompatible / unconfirmed selection",
            message,
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Cancel,
        )
        if result != QMessageBox.StandardButton.Ok:
            return
        self.override_confirmed = True
        self.refresh()

    def refresh_review(self, *, preserve_scroll: bool = False) -> None:
        scroll_value = self.workflow_scroll.verticalScrollBar().value() if preserve_scroll else None
        _clear_layout(self.review_layout)
        if self.bundle is None:
            self.review_layout.addWidget(EmptyStateWidget("Atlas data is loading", "Changeover Packet Builder will be available after cached data loads."))
            self._restore_workflow_scroll(scroll_value)
            return
        if not self._has_all_selections():
            self.review_layout.addWidget(
                EmptyStateWidget("Selection incomplete", "Select Machine, Tool / Mold / Part, and EOAT to validate the setup.")
            )
            self._sync_generate_state()
            self._restore_workflow_scroll(scroll_value)
            return
        options = self._options()
        validation = validate_setup_context(
            self.bundle,
            self.machine_id,
            self.tool_id,
            self.eoat_id,
            manual_override_used=options.manual_override_used,
        )
        context = build_setup_packet_context(self.bundle, self.machine_id, self.tool_id, self.eoat_id, options)
        health = validation_relationship_health(validation.status, manual_override=validation.manual_override_used)
        self.review_layout.addWidget(badge(validation.status, health_badge_kind(health)))
        grid_values = [
            ("Selected Machine", context.machine_id),
            ("Selected Tool", context.tool_id),
            ("Selected EOAT", context.eoat_id),
            ("Fit Check status", validation.status),
            ("Manual override", "Yes" if validation.manual_override_used else "No"),
            ("Robot info", "Available" if context.robot_info else "Missing / partial"),
            ("Missing data", _compact_packet_missing(context.missing_key_data)),
            ("Warnings", str(context.warning_count)),
            ("Photos", str(context.photo_count)),
            ("Documentation score", f"{context.documentation_score}%"),
            ("Packet type", context.packet_type_label),
            ("Photo inclusion", context.photo_inclusion_label),
        ]
        self.review_layout.addWidget(key_value_grid(grid_values))
        if validation.warnings:
            warning = WarningCard("Warnings / Missing Information", severity="warn")
            warning.layout.addWidget(key_value_grid([(item.title, item.message) for item in validation.warnings[:5]]))
            self.review_layout.addWidget(warning)
        self._sync_generate_state(validation.status)
        self._restore_workflow_scroll(scroll_value)

    def _restore_workflow_scroll(self, scroll_value: int | None) -> None:
        if scroll_value is None:
            return
        bar = self.workflow_scroll.verticalScrollBar()
        bar.setValue(scroll_value)
        QTimer.singleShot(0, lambda value=scroll_value: self.workflow_scroll.verticalScrollBar().setValue(value))

    def generate_pdf(self) -> None:
        if self.bundle is None:
            QMessageBox.information(self, "Changeover Packet", "Atlas data is still loading.")
            return
        if not self._has_all_selections():
            QMessageBox.information(self, "Changeover Packet", "Select Machine, Tool / Mold / Part, and EOAT before generating.")
            return
        validation = validate_setup_context(
            self.bundle,
            self.machine_id,
            self.tool_id,
            self.eoat_id,
            manual_override_used=self.override_confirmed,
        )
        if not self._generation_allowed(validation.status):
            QMessageBox.warning(
                self,
                "Fit Check not confirmed",
                "Atlas cannot confirm this Machine + Tool + EOAT combination. Enable manual override and confirm the warning before generating.",
            )
            return
        context = build_setup_packet_context(self.bundle, self.machine_id, self.tool_id, self.eoat_id, self._options())
        result = export_setup_packet_pdf(context)
        _write_setup_packet_sidecar(result.path, context)
        self._set_latest_packet(result.path, context=context)
        self.refresh_packet_list()
        self._sync_generate_state()
        self._run_open_preference()
        self.controller.show_status("Changeover packet generated successfully.")

    def _run_open_preference(self) -> None:
        if self.last_packet_path is None:
            return
        preference = self._options().open_after_generation
        if preference == "in_app":
            self.view_latest_packet_in_app()
        elif preference == "external_pdf":
            open_path(self.last_packet_path)
        elif preference == "open_folder":
            open_path(self.last_packet_path.parent)
        else:
            self._ask_open_after_generation()

    def _ask_open_after_generation(self) -> None:
        if self.last_packet_path is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Changeover Packet Generated")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("Changeover Packet PDF generated. What would you like to do next?")
        if QPdfDocument is None or QPdfView is None:
            box.setInformativeText("Embedded PDF viewer is unavailable in this build. Use Open PDF or Open Folder.")
        view_button = box.addButton("View In App", QMessageBox.ButtonRole.AcceptRole)
        view_button.setEnabled(QPdfDocument is not None and QPdfView is not None)
        external_button = box.addButton("Open PDF", QMessageBox.ButtonRole.ActionRole)
        folder_button = box.addButton("Open Folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Stay Here", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is view_button:
            self.view_latest_packet_in_app()
        elif clicked is external_button:
            open_path(self.last_packet_path)
        elif clicked is folder_button:
            open_path(self.last_packet_path.parent)

    def _set_latest_packet(self, path: Path, *, context=None, load_in_viewer: bool = False) -> None:
        self.last_packet_path = Path(path)
        self.last_packet_label.setText(str(self.last_packet_path))
        self._update_latest_packet_summary(context=context)
        self._sync_latest_pdf_actions()
        if load_in_viewer:
            self.view_latest_packet_in_app()

    def _update_latest_packet_summary(self, *, context=None) -> None:
        if self.last_packet_path is None:
            self.latest_pdf_info.setText(
                "No packet generated yet\nGenerate a changeover packet to preview, print, share, or open it here."
            )
            self.latest_setup_label.setText("No changeover packet generated yet.")
            self.latest_empty_label.setVisible(True)
            for widget in (
                self.latest_type_chip,
                self.latest_compat_chip,
                self.latest_generated_label,
                self.latest_size_label,
                self.latest_photo_label,
                self.latest_override_label,
                self.latest_filename_label,
            ):
                widget.setVisible(False)
            return
        metadata = _setup_packet_metadata(self.last_packet_path)
        machine = getattr(context, "machine_id", "") or metadata.get("machine") or "-"
        tool = getattr(context, "tool_id", "") or metadata.get("tool") or "-"
        eoat = getattr(context, "eoat_id", "") or metadata.get("eoat") or "-"
        packet_type = getattr(context, "packet_type_label", "") or metadata.get("packet_type") or "Changeover Packet"
        photo_mode = getattr(context, "photo_inclusion_label", "") or metadata.get("photo_inclusion") or "-"
        status = getattr(getattr(context, "validation", None), "status", "") or metadata.get("compatibility_status") or "-"
        override = getattr(getattr(context, "validation", None), "manual_override_used", None)
        if override is None:
            override = bool(metadata.get("manual_override_used"))
        self.latest_pdf_info.setText(_setup_packet_pdf_info(self.last_packet_path, context=context))
        self.latest_setup_label.setText(f"Machine {machine} | Tool {tool} | EOAT {eoat}")
        self.latest_empty_label.setVisible(False)
        self.latest_type_chip.setText(str(packet_type))
        _set_chip_kind(self.latest_type_chip, "info")
        self.latest_compat_chip.setText(str(status))
        _set_chip_kind(self.latest_compat_chip, _compatibility_chip_kind(str(status)))
        self.latest_generated_label.setText(f"Generated: {_setup_packet_generated_time(self.last_packet_path, metadata)}")
        self.latest_size_label.setText(f"File size: {_format_file_size(self.last_packet_path)}")
        self.latest_photo_label.setText(f"Photo inclusion: {photo_mode}")
        self.latest_override_label.setText("Manual override used" if override else "")
        self.latest_override_label.setVisible(bool(override))
        self.latest_filename_label.setText(f"File: {_short_label(self.last_packet_path.name, 54)}")
        self.latest_filename_label.setToolTip(str(self.last_packet_path))
        for widget in (
            self.latest_type_chip,
            self.latest_compat_chip,
            self.latest_generated_label,
            self.latest_size_label,
            self.latest_photo_label,
            self.latest_filename_label,
        ):
            widget.setVisible(True)

    def open_last_packet(self) -> None:
        if self.last_packet_path:
            open_path(self.last_packet_path)

    def view_latest_packet_in_app(self) -> None:
        if self.last_packet_path:
            self.view_packet_in_app(self.last_packet_path)

    def view_packet_in_app(self, path: str | Path) -> None:
        target = Path(path)
        self._set_latest_packet(target)
        self.refresh_packet_list()
        dialog = _SetupPacketPdfViewerDialog(target, parent=self)
        dialog.exec()

    def open_packet_folder(self) -> None:
        folder = self._packet_folder()
        if folder is not None:
            folder.mkdir(parents=True, exist_ok=True)
            open_path(folder)

    def open_latest_folder(self) -> None:
        if self.last_packet_path:
            open_path(self.last_packet_path.parent)
        else:
            self.open_packet_folder()

    def copy_last_packet_path(self) -> None:
        if self.last_packet_path:
            QApplication.clipboard().setText(str(self.last_packet_path))
            self.controller.show_status("Copied changeover packet path.")

    def refresh_packet_list(self) -> None:
        self.packet_list.clear()
        folder = self._packet_folder()
        if folder is None or not folder.exists():
            item = QListWidgetItem("No changeover packet exports found.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setSizeHint(QSize(0, 52))
            self.packet_list.addItem(item)
            return
        paths = sorted(
            {*folder.glob("Setup_Packet*.pdf"), *folder.glob("EOAT_Setup_Packet*.pdf")},
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if self.last_packet_path is not None:
            latest_resolved = self.last_packet_path.resolve(strict=False)
            paths = [path for path in paths if path.resolve(strict=False) != latest_resolved]
        if not paths:
            item = QListWidgetItem("No previous changeover packet exports found.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setSizeHint(QSize(0, 52))
            self.packet_list.addItem(item)
            return
        for path in paths[:30]:
            row = _PreviousPacketRow(path, self)
            item = QListWidgetItem()
            item.setToolTip(str(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setSizeHint(row.sizeHint())
            self.packet_list.addItem(item)
            self.packet_list.setItemWidget(item, row)

    def _view_selected_packet(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.view_packet_in_app(path)

    def _packet_folder(self) -> Path | None:
        if self.bundle is None:
            return None
        return Path(self.bundle.project_root) / "06_Final_Handoff" / "Atlas_Exports" / "Setup_Packets"

    def _options(self) -> SetupPacketOptions:
        return SetupPacketOptions(
            packet_type=_setup_packet_type_value(self.setup_packet_type_combo.currentText()),
            photo_inclusion=_setup_packet_photo_value(self.setup_packet_photo_combo.currentText()),
            open_after_generation=_setup_packet_open_value(self.setup_packet_open_combo.currentText()),
            include_qr_label=bool(self.setup_packet_qr_check.isChecked() and self.controller.settings.enable_qr_codes),
            detail_level=self.setup_packet_detail_combo.currentText().casefold(),
            manual_override_used=self.override_confirmed,
        ).normalized()

    def _sync_option_controls(self) -> None:
        settings = self.controller.settings
        self._syncing_options = True
        controls = [
            self.setup_packet_type_combo,
            self.setup_packet_photo_combo,
            self.setup_packet_detail_combo,
            self.setup_packet_open_combo,
            self.setup_packet_qr_check,
            self.setup_packet_override_check,
        ]
        for control in controls:
            control.blockSignals(True)
        self.setup_packet_type_combo.setCurrentText(_setup_packet_type_display(settings.setup_packet_default_type))
        self.setup_packet_photo_combo.setCurrentText(_setup_packet_photo_display(settings.setup_packet_photo_inclusion))
        self.setup_packet_detail_combo.setCurrentText(settings.setup_packet_detail_level.title())
        self.setup_packet_open_combo.setCurrentText(_setup_packet_open_display(settings.setup_packet_open_after_generation))
        self.setup_packet_qr_check.setChecked(settings.setup_packet_include_qr_label)
        self.setup_packet_override_check.setChecked(settings.setup_packet_allow_manual_override_combinations)
        for control in controls:
            control.blockSignals(False)
        self._syncing_options = False
        self._sync_qr_option_state()

    def _packet_option_changed(self, option_name: str) -> None:
        if self._syncing_options:
            return
        scroll_value = self.workflow_scroll.verticalScrollBar().value()
        started = time.perf_counter()
        self._save_packet_options(option_name)
        if option_name == "allow_override" and not self.setup_packet_override_check.isChecked():
            self.override_confirmed = False
            self._refresh_selection_panels()
        self._sync_qr_option_state()
        if self._has_all_selections():
            self.refresh_review(preserve_scroll=True)
        else:
            self._sync_generate_state()
            self._restore_workflow_scroll(scroll_value)
        elapsed_ms = (time.perf_counter() - started) * 1000
        LOGGER.debug("Changeover Packet Builder option %s UI update completed in %.1f ms", option_name, elapsed_ms)

    def _save_packet_options(self, option_name: str = "packet_options", *_args) -> None:
        if self._syncing_options:
            return
        started = time.perf_counter()
        settings = replace(
            self.controller.settings,
            setup_packet_default_type=_setup_packet_type_value(self.setup_packet_type_combo.currentText()),
            setup_packet_photo_inclusion=_setup_packet_photo_value(self.setup_packet_photo_combo.currentText()),
            setup_packet_open_after_generation=_setup_packet_open_value(self.setup_packet_open_combo.currentText()),
            setup_packet_include_qr_label=bool(self.setup_packet_qr_check.isChecked()),
            setup_packet_detail_level=self.setup_packet_detail_combo.currentText().casefold(),
            setup_packet_allow_manual_override_combinations=bool(self.setup_packet_override_check.isChecked()),
        )
        normalized = settings.normalized()
        self.controller.settings = normalized
        self._pending_packet_settings = normalized
        self._packet_settings_timer.start()
        elapsed_ms = (time.perf_counter() - started) * 1000
        LOGGER.debug("Changeover Packet Builder option %s queued settings save in %.1f ms", option_name, elapsed_ms)

    def _flush_packet_settings(self) -> None:
        settings = self._pending_packet_settings
        if settings is None:
            return
        self._pending_packet_settings = None
        started = time.perf_counter()
        updater = getattr(self.controller, "update_setup_packet_settings", None)
        if callable(updater):
            updater(settings)
        else:
            self.controller.update_settings(settings)
        elapsed_ms = (time.perf_counter() - started) * 1000
        LOGGER.debug("Changeover Packet Builder settings persisted in %.1f ms", elapsed_ms)

    def _sync_qr_option_state(self) -> None:
        enabled = bool(self.controller.settings.enable_qr_codes)
        self.setup_packet_qr_check.setEnabled(enabled)
        self.setup_packet_qr_helper.setVisible(not enabled)
        self.open_qr_settings_button.setVisible(not enabled)
        if enabled:
            self.setup_packet_qr_check.setToolTip("Include a QR label in future generated changeover packets.")
        else:
            self.setup_packet_qr_check.setToolTip("Enable QR Codes in Settings to include a QR label in changeover packets.")

    def _open_qr_settings(self) -> None:
        if hasattr(self.controller, "show_page"):
            self.controller.show_page("diagnostics")

    def _toggle_advanced_options(self, checked: bool) -> None:
        self.advanced_options.setVisible(checked)

    def _refresh_empty_note(self) -> None:
        notes = []
        if self.machine_id and not self.tool_selector.records:
            notes.append("No compatible tools are indexed for the selected machine/EOAT context.")
        if self.tool_id and not self.machine_selector.records:
            notes.append("No compatible machines are indexed for the selected tool/EOAT context.")
        if (self.machine_id or self.tool_id) and not self.eoat_selector.records:
            notes.append("No compatible EOATs are indexed for the selected machine/tool context.")
        self.empty_note.setText(" ".join(notes) if notes and not self.override_confirmed else "")

    def _has_all_selections(self) -> bool:
        return bool(self.machine_id and self.tool_id and self.eoat_id)

    def _sync_generate_state(self, status: str = "") -> None:
        if not status and self.bundle is not None and self._has_all_selections():
            status = validate_setup_context(
                self.bundle,
                self.machine_id,
                self.tool_id,
                self.eoat_id,
                manual_override_used=self.override_confirmed,
            ).status
        can_generate = self.bundle is not None and self._has_all_selections() and self._generation_allowed(status)
        self.generate_button.setEnabled(can_generate)
        self.override_button.setEnabled(bool(self.setup_packet_override_check.isChecked()) and not self.override_confirmed)
        self.override_button.setText(
            "Manual Override Used" if self.override_confirmed else "Allow incompatible / unconfirmed selection"
        )
        has_any_selection = bool(self.machine_id or self.tool_id or self.eoat_id)
        self.reset_selection_button.setEnabled(has_any_selection)
        self.clear_machine_button.setEnabled(bool(self.machine_id))
        self.clear_tool_button.setEnabled(bool(self.tool_id))
        self.clear_eoat_button.setEnabled(bool(self.eoat_id))
        has_last = self.last_packet_path is not None
        self.open_last_button.setEnabled(has_last)
        self.copy_last_button.setEnabled(has_last)
        self._sync_latest_pdf_actions()

    def _sync_latest_pdf_actions(self) -> None:
        has_last = self.last_packet_path is not None
        for button in (
            self.view_in_app_button,
            self.latest_open_pdf_button,
            self.latest_open_folder_button,
            self.latest_copy_path_button,
        ):
            button.setEnabled(has_last)

    def _generation_allowed(self, status: str) -> bool:
        if self.override_confirmed:
            return True
        return status == COMPATIBILITY_CONFIRMED


class DiagnosticsPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(18, 18, 18, 18)
        outer_layout.addWidget(PageHeader("Settings / Diagnostics", "Calm controls up front. Detailed cache, source, and performance diagnostics stay tucked into accordions."))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.scroll.setWidget(content)
        outer_layout.addWidget(self.scroll, 1)

        self.theme_combo = _settings_combo(["Light", "Dark", "System/default"])
        self.color_scheme_combo = _settings_combo(["Atlas Blue", "Nolato Logo", "Industrial Graphite", "Aurora Tech"])
        self.startup_combo = _settings_combo(
            [
                "Home / Command Deck",
                "What Do I Need?",
                "Changeover Packet Builder",
                "EOAT Profiles",
                "Machine Profiles",
                "Tool / Mold / Part",
                "Fit Check",
                "Analytics Dashboard",
                "Photos",
                "Standards & Work Instructions",
                "PM / Inspection",
                "Information Library",
                "Reports & Handoff",
                "Settings / Diagnostics",
            ]
        )
        self.search_mode_combo = _settings_combo(["Smart", "EOAT", "Machine", "Tool"])
        self.photo_behavior_combo = _settings_combo(["Open in app", "Open folder", "Open external viewer"])
        self.photo_preload_combo = _settings_combo(["Off", "Conservative", "Balanced", "Aggressive"])
        self.photo_cache_limit_spin = QSpinBox()
        self.photo_cache_limit_spin.setRange(128, 8192)
        self.photo_cache_limit_spin.setSingleStep(128)
        self.photo_cache_limit_spin.setSuffix(" MB")
        self.photo_cache_limit_spin.setMinimumWidth(150)
        self.qr_payload_combo = _settings_combo(
            ["Compact Human-Readable Text", "Atlas Deep Link", "JSON Record", "Full Offline Record"]
        )
        self.qr_error_combo = _settings_combo(["Low", "Medium", "Quartile", "High"])
        self.qr_label_size_combo = _settings_combo(["Small", "Medium", "Large"])
        self.card_density_combo = _settings_combo(["Comfortable", "Compact"])
        self.qr_codes_check = _settings_check("Show Make QR on EOAT profiles and allow QR label exports.")
        self.qr_preview_check = _settings_check("Show exact QR payload text before export.")
        self.qr_phone_guard_check = _settings_check("Always prevent phone-number-like QR payloads.")
        self.qr_phone_guard_check.setEnabled(False)
        self.command_palette_check = _settings_check("Enable Ctrl+K universal command palette.")
        self.lazy_previews_check = _settings_check("Enable optional cheap/cached photo previews on summary cards.")
        self.prefetch_check = _settings_check("Load the previous and next carousel images in memory for smoother navigation.")
        self.advanced_check = _settings_check("Show dense source and raw performance diagnostics tables.")
        self.compact_list_check = _settings_check("Use shorter EOAT and machine selector tiles.")
        self.hide_missing_tools_check = _settings_check("Hide Tool / Mold / Part records that do not have linked compatible EOATs.")
        self.open_after_export_check = _settings_check("Open the export folder after report generation when practical.")
        self.confirm_external_check = _settings_check("Ask before opening folders or files outside Atlas.")
        self.auto_refresh_check = _settings_check("Refresh Atlas data automatically when the app starts.")

        settings_card = PrimaryCard("General Settings", "Common preferences are stored per user and do not touch source workbooks or photo folders.")
        settings_grid = QGridLayout()
        settings_grid.setContentsMargins(0, 0, 0, 0)
        settings_grid.setHorizontalSpacing(14)
        settings_grid.setVerticalSpacing(10)
        settings_widgets = [
            ("Theme mode", self.theme_combo),
            ("Color scheme", self.color_scheme_combo),
            ("Startup page", self.startup_combo),
            ("Default search mode", self.search_mode_combo),
            ("Photo viewer behavior", self.photo_behavior_combo),
            ("Enable QR Codes", self.qr_codes_check),
            ("Command palette", self.command_palette_check),
            ("Enable diagnostics", self.advanced_check),
            ("Startup refresh", self.auto_refresh_check),
        ]
        settings_body = QWidget()
        settings_body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        settings_body.setLayout(settings_grid)
        _add_settings_rows(settings_grid, settings_widgets)
        settings_card.layout.addWidget(settings_body)
        layout.addWidget(settings_card)

        control_card = InfoPanel("Data Refresh", "Manual refresh rebuilds cached Atlas data without modifying source files.")
        refresh_button = QPushButton("Refresh Data")
        refresh_button.setObjectName("PrimaryButton")
        refresh_button.clicked.connect(lambda: self.controller.refresh_data(force=True))
        self.refresh_status_label = QLabel("Last refreshed: not available")
        self.refresh_status_label.setObjectName("MicroText")
        note = QLabel("Atlas is read-only. Refresh rebuilds the in-memory cache/indexes from configured sources.")
        note.setObjectName("BodyText")
        note.setWordWrap(True)
        control_card.layout.addWidget(note)
        control_card.layout.addWidget(self.refresh_status_label)
        control_card.layout.addWidget(refresh_button)
        layout.addWidget(control_card)

        qr_section = AccordionSection("QR Code Settings", "Payload, labels, preview, and phone-safe QR options")
        self.qr_section = qr_section
        qr_grid_widget = QWidget()
        qr_grid = QGridLayout(qr_grid_widget)
        qr_grid.setContentsMargins(0, 0, 0, 0)
        _add_settings_rows(
            qr_grid,
            [
                ("QR payload mode", self.qr_payload_combo),
                ("QR label size", self.qr_label_size_combo),
                ("QR error correction", self.qr_error_combo),
                ("QR payload preview", self.qr_preview_check),
                ("QR phone guard", self.qr_phone_guard_check),
            ],
        )
        qr_section.add_widget(qr_grid_widget)
        layout.addWidget(qr_section)

        photo_section = AccordionSection("Photo Loading / Cache", "Async loader behavior, decoded images, failed loads, and cache controls", status_text="Paused", status_kind="review")
        self.photo_cache_section = photo_section
        photo_settings_widget = QWidget()
        photo_settings_grid = QGridLayout(photo_settings_widget)
        photo_settings_grid.setContentsMargins(0, 0, 0, 0)
        _add_settings_rows(
            photo_settings_grid,
            [
                ("Photo preload mode", self.photo_preload_combo),
                ("Cache memory limit", self.photo_cache_limit_spin),
                ("Thumbnail/card previews", self.lazy_previews_check),
                ("Carousel prefetch", self.prefetch_check),
            ],
        )
        photo_section.add_widget(photo_settings_widget)
        self.photo_cache_card = SectionCard("Cache Metrics", "Counts update once per second without decoding new images.")
        self.photo_cache_grid = QGridLayout()
        self.photo_cache_grid.setContentsMargins(0, 0, 0, 0)
        self.photo_cache_grid.setSpacing(8)
        self.photo_cache_card.layout.addLayout(self.photo_cache_grid)
        clear_cache_button = QPushButton("Clear Photo Cache")
        clear_cache_button.clicked.connect(self.clear_photo_cache)
        prime_cache_button = QPushButton("Prime Photo Cache")
        prime_cache_button.clicked.connect(self.prime_photo_cache)
        self.photo_cache_card.layout.addWidget(action_row(clear_cache_button, prime_cache_button))
        photo_section.add_widget(self.photo_cache_card)
        layout.addWidget(photo_section)

        source_section = AccordionSection("Data Sources", "Master Tracker, Press Capacity, Robot workbook, photos, standards, and path details", status_text="Waiting", status_kind="unknown")
        self.source_section = source_section
        self.source_card = SectionCard("Source Availability", "Configured Atlas sources and current availability status.")
        self.source_grid = QGridLayout()
        self.source_grid.setContentsMargins(0, 0, 0, 0)
        self.source_grid.setSpacing(8)
        self.source_card.layout.addLayout(self.source_grid)
        source_section.add_widget(self.source_card)
        self.sources = QTableWidget()
        self.source_panel = DenseDataPanel("Source Path Details", "Compact reference table for configured Atlas source paths.")
        self.source_panel.layout.addWidget(self.sources, 1)
        source_section.add_widget(self.source_panel)
        layout.addWidget(source_section)

        perf_section = AccordionSection("Performance", "Refresh timing, indexed record counts, and cache build timing", status_text="OK", status_kind="good")
        self.perf_section = perf_section
        self.perf_card = SectionCard("Performance Summary", "Refresh, index, photo, command palette, cache, and slow-operation timings.")
        self.perf_grid = QGridLayout()
        self.perf_grid.setContentsMargins(0, 0, 0, 0)
        self.perf_grid.setSpacing(8)
        self.perf_card.layout.addLayout(self.perf_grid)
        perf_section.add_widget(self.perf_card)
        layout.addWidget(perf_section)

        reports_section = AccordionSection("Reports & Export", "Default export behavior and file-opening preferences", status_text="Ready", status_kind="good")
        reports_settings_widget = QWidget()
        reports_settings_grid = QGridLayout(reports_settings_widget)
        reports_settings_grid.setContentsMargins(0, 0, 0, 0)
        _add_settings_rows(
            reports_settings_grid,
            [
                ("Open after export", self.open_after_export_check),
                ("Confirm external open", self.confirm_external_check),
            ],
        )
        reports_section.add_widget(reports_settings_widget)
        layout.addWidget(reports_section)

        advanced_section = AccordionSection("Advanced Diagnostics", "Logs, validation, debug tools, dense UI controls, and raw performance diagnostics", status_text="Hidden", status_kind="unknown")
        self.advanced_section = advanced_section
        advanced_settings_widget = QWidget()
        advanced_settings_grid = QGridLayout(advanced_settings_widget)
        advanced_settings_grid.setContentsMargins(0, 0, 0, 0)
        _add_settings_rows(
            advanced_settings_grid,
            [
                ("Card density", self.card_density_combo),
                ("List density", self.compact_list_check),
                ("Hide tools missing EOAT links", self.hide_missing_tools_check),
            ],
        )
        advanced_section.add_widget(advanced_settings_widget)
        self.metrics = QTableWidget()
        self.metrics_panel = DenseDataPanel("Raw Performance Diagnostics", "Developer timings and cache counters.")
        self.metrics_panel.layout.addWidget(self.metrics, 1)
        advanced_section.add_widget(self.metrics_panel)
        layout.addWidget(advanced_section)

        self._wire_settings_controls()
        self._sync_settings_controls()
        self._photo_stats_timer = QTimer(self)
        self._photo_stats_timer.setInterval(1000)
        self._photo_stats_timer.timeout.connect(lambda: self._refresh_photo_cache_stats() if self.isVisible() else None)
        self._photo_stats_timer.start()

    def refresh(self) -> None:
        if self.bundle is None:
            return
        self.refresh_status_label.setText(f"Last refreshed: {self.bundle.loaded_at or 'not available'}")
        _clear_layout(self.source_grid)
        available_sources = 0
        for index, source in enumerate(self.bundle.source_statuses):
            if source.available:
                available_sources += 1
            chip = badge(f"{source.label}: {'Ready' if source.available else 'Missing'}", "good" if source.available else "warn")
            chip.setToolTip(f"{source.message}\n{source.path}")
            self.source_grid.addWidget(chip, index // 3, index % 3)
        total_sources = len(self.bundle.source_statuses)
        if hasattr(self, "source_section"):
            self.source_section.set_summary(f"{available_sources} / {total_sources} sources available. Expand for path details.")
            self.source_section.set_status("Ready" if available_sources == total_sources else "Review", "good" if available_sources == total_sources else "review")
        _clear_layout(self.perf_grid)
        perf_items = [
            ("Workbook load", self.bundle.metrics.get("workbook_load_seconds", self.bundle.metrics.get("workbook_load_time", "-"))),
            ("Photo index", self.bundle.metrics.get("photo_index_seconds", self.bundle.metrics.get("photo_index_time", "-"))),
            ("Cache build", self.bundle.metrics.get("cache_build_seconds", self.bundle.metrics.get("cache_build_time", "-"))),
            ("EOATs", len(self.bundle.eoats)),
            ("Machines", len(self.bundle.machines)),
            ("Tools", len(self.bundle.tools)),
        ]
        for index, (title, value) in enumerate(perf_items):
            self.perf_grid.addWidget(CompactStatCard(title, str(value)), 0, index)
        if hasattr(self, "perf_section"):
            self.perf_section.set_summary(f"{len(self.bundle.eoats)} EOATs, {len(self.bundle.machines)} machines, {len(self.bundle.tools)} tools indexed.")
            self.perf_section.set_status("OK", "good")
        self._refresh_photo_cache_stats()
        fill_table(
            self.sources,
            [
                {"Source": source.label, "Available": source.available, "Message": source.message, "Path": source.path}
                for source in self.bundle.source_statuses
            ],
            ["Source", "Available", "Message", "Path"],
        )
        metric_rows = [{"Metric": key, "Value": value} for key, value in sorted(self.bundle.metrics.items())]
        fill_table(self.metrics, metric_rows, ["Metric", "Value"])
        self._apply_diagnostics_visibility()

    def settings_changed(self) -> None:
        self._sync_settings_controls()
        self.update_settings_status_badges()
        self._refresh_photo_cache_stats()
        self._apply_diagnostics_visibility()

    def _wire_settings_controls(self) -> None:
        self.theme_combo.currentTextChanged.connect(lambda: self._save_setting(theme=_theme_value(self.theme_combo.currentText())))
        self.color_scheme_combo.currentTextChanged.connect(
            lambda: self._save_setting(color_scheme=_color_scheme_value(self.color_scheme_combo.currentText()))
        )
        self.startup_combo.currentTextChanged.connect(lambda: self._save_setting(startup_page=_page_key_for_label(self.startup_combo.currentText())))
        self.search_mode_combo.currentTextChanged.connect(lambda: self._save_setting(default_search_mode=self.search_mode_combo.currentText().casefold()))
        self.photo_behavior_combo.currentTextChanged.connect(lambda: self._save_setting(photo_viewer_behavior=_photo_behavior_value(self.photo_behavior_combo.currentText())))
        self.photo_preload_combo.currentTextChanged.connect(lambda: self._save_setting(photo_preload_mode=_photo_preload_value(self.photo_preload_combo.currentText())))
        self.photo_cache_limit_spin.valueChanged.connect(lambda value: self._save_setting(photo_cache_limit_mb=value))
        self.qr_payload_combo.currentTextChanged.connect(lambda: self._save_setting(qr_payload_mode=_qr_payload_value(self.qr_payload_combo.currentText())))
        self.qr_error_combo.currentTextChanged.connect(lambda: self._save_setting(qr_error_correction=_qr_error_value(self.qr_error_combo.currentText())))
        self.qr_label_size_combo.currentTextChanged.connect(lambda: self._save_setting(qr_default_label_size=self.qr_label_size_combo.currentText().casefold()))
        self.qr_codes_check.toggled.connect(lambda value: self._save_setting(enable_qr_codes=value))
        self.qr_preview_check.toggled.connect(lambda value: self._save_setting(qr_show_payload_preview_before_export=value))
        self.command_palette_check.toggled.connect(lambda value: self._save_setting(command_palette_enabled=value))
        self.card_density_combo.currentTextChanged.connect(lambda: self._save_setting(card_density=self.card_density_combo.currentText().casefold()))
        self.lazy_previews_check.toggled.connect(lambda value: self._save_setting(lazy_photo_previews=value))
        self.prefetch_check.toggled.connect(lambda value: self._save_setting(carousel_prefetch=value))
        self.advanced_check.toggled.connect(lambda value: self._save_setting(show_advanced_diagnostics=value))
        self.compact_list_check.toggled.connect(lambda value: self._save_setting(compact_list_mode=value))
        self.hide_missing_tools_check.toggled.connect(lambda value: self._save_setting(hide_tools_missing_eoat_links=value))
        self.open_after_export_check.toggled.connect(lambda value: self._save_setting(open_after_export=value))
        self.confirm_external_check.toggled.connect(lambda value: self._save_setting(confirm_external_open=value))
        self.auto_refresh_check.toggled.connect(lambda value: self._save_setting(auto_refresh_on_startup=value))

    def _sync_settings_controls(self) -> None:
        settings = self.controller.settings
        controls = [
            self.theme_combo,
            self.color_scheme_combo,
            self.startup_combo,
            self.search_mode_combo,
            self.photo_behavior_combo,
            self.photo_preload_combo,
            self.photo_cache_limit_spin,
            self.qr_payload_combo,
            self.qr_error_combo,
            self.qr_label_size_combo,
            self.qr_codes_check,
            self.qr_preview_check,
            self.qr_phone_guard_check,
            self.command_palette_check,
            self.card_density_combo,
            self.lazy_previews_check,
            self.prefetch_check,
            self.advanced_check,
            self.compact_list_check,
            self.hide_missing_tools_check,
            self.open_after_export_check,
            self.confirm_external_check,
            self.auto_refresh_check,
        ]
        for control in controls:
            control.blockSignals(True)
        self.theme_combo.setCurrentText({"light": "Light", "dark": "Dark", "system": "System/default"}.get(settings.theme, "Light"))
        self.color_scheme_combo.setCurrentText(
            {
                "atlas_blue": "Atlas Blue",
                "nolato_logo": "Nolato Logo",
                "industrial_graphite": "Industrial Graphite",
                "aurora_tech": "Aurora Tech",
            }.get(settings.color_scheme, "Atlas Blue")
        )
        self.startup_combo.setCurrentText(_label_for_page_key(settings.startup_page))
        self.search_mode_combo.setCurrentText(settings.default_search_mode.upper() if settings.default_search_mode == "eoat" else settings.default_search_mode.title())
        self.photo_behavior_combo.setCurrentText(
            {"in_app": "Open in app", "open_folder": "Open folder", "external": "Open external viewer"}.get(
                settings.photo_viewer_behavior, "Open in app"
            )
        )
        self.photo_preload_combo.setCurrentText(settings.photo_preload_mode.replace("_", " ").title())
        self.photo_cache_limit_spin.setValue(settings.photo_cache_limit_mb)
        self.qr_payload_combo.setCurrentText(_qr_mode_display(settings.qr_payload_mode))
        self.qr_error_combo.setCurrentText(_qr_error_display(settings.qr_error_correction))
        self.qr_label_size_combo.setCurrentText(settings.qr_default_label_size.title())
        self.qr_codes_check.setChecked(settings.enable_qr_codes)
        self.qr_preview_check.setChecked(settings.qr_show_payload_preview_before_export)
        self.qr_phone_guard_check.setChecked(True)
        self.command_palette_check.setChecked(settings.command_palette_enabled)
        self.card_density_combo.setCurrentText(settings.card_density.title())
        self.lazy_previews_check.setChecked(settings.lazy_photo_previews)
        self.prefetch_check.setChecked(settings.carousel_prefetch)
        self.advanced_check.setChecked(settings.show_advanced_diagnostics)
        self.compact_list_check.setChecked(settings.compact_list_mode)
        self.hide_missing_tools_check.setChecked(settings.hide_tools_missing_eoat_links)
        self.open_after_export_check.setChecked(settings.open_after_export)
        self.confirm_external_check.setChecked(settings.confirm_external_open)
        self.auto_refresh_check.setChecked(settings.auto_refresh_on_startup)
        for control in controls:
            control.blockSignals(False)
        self.update_settings_status_badges()

    def _save_setting(self, **changes) -> None:
        self.controller.update_settings(replace(self.controller.settings, **changes))
        self.update_settings_status_badges()
        self._refresh_photo_cache_stats()

    def update_settings_status_badges(self) -> None:
        if hasattr(self, "qr_section"):
            qr_enabled = bool(self.controller.settings.enable_qr_codes)
            self.qr_section.set_status("Enabled" if qr_enabled else "Disabled", "success" if qr_enabled else "neutral")

    def clear_photo_cache(self) -> None:
        self.controller.photo_loader.clear_cache()
        self.controller.show_status("Photo cache cleared.")
        self._refresh_photo_cache_stats()

    def prime_photo_cache(self) -> None:
        queued = self.controller.photo_loader.prime_photo_cache()
        self.controller.show_status(f"Photo cache prime queued {queued} image(s).")
        self._refresh_photo_cache_stats()

    def _refresh_photo_cache_stats(self) -> None:
        _clear_layout(self.photo_cache_grid)
        stats = self.controller.photo_loader.stats()
        if hasattr(self, "photo_cache_section"):
            cache_summary = f"{stats.get('decoded_images', 0)} decoded images, {stats.get('cache_memory_mb', 0)} / {stats.get('cache_memory_limit_mb', 0)} MB cache"
            self.photo_cache_section.set_summary(cache_summary)
            paused = not bool(stats.get("idle")) or bool(stats.get("jobs_queued", 0))
            self.photo_cache_section.set_status("Paused" if paused else "Ready", "review" if paused else "good")
        items = [
            ("Status", stats.get("cache_status", "Ready")),
            ("Preload mode", str(stats.get("preload_mode", "")).title()),
            ("Cache entries", stats.get("cache_entries", 0)),
            ("Decoded images", stats.get("decoded_images", 0)),
            ("Thumbnails", stats.get("thumbnail_entries", 0)),
            ("Full images", stats.get("full_entries", 0)),
            ("Cache memory", f"{stats.get('cache_memory_mb', 0)} / {stats.get('cache_memory_limit_mb', 0)} MB"),
            ("Queued jobs", stats.get("jobs_queued", 0)),
            ("Active jobs", stats.get("active_jobs", 0)),
            ("Last decode", f"{stats.get('last_decode_ms', 0)} ms"),
            ("Failed loads", stats.get("failed_loads", 0)),
            ("Event-loop lag", f"{stats.get('event_loop_lag_ms', 0)} ms"),
            ("Idle/preload", "Ready" if stats.get("idle") else "Paused"),
            ("App active", "Yes" if stats.get("app_active", True) else "No"),
            ("Last reason", stats.get("last_preload_reason", "")),
            ("Last completed", stats.get("last_completed_file", "")),
        ]
        for index, (title, value) in enumerate(items):
            card = CompactStatCard(title, str(value))
            self.photo_cache_grid.addWidget(card, index // 4, index % 4)
            card.show()

    def _apply_diagnostics_visibility(self) -> None:
        if hasattr(self, "advanced_section"):
            show = bool(self.controller.settings.show_advanced_diagnostics)
            self.advanced_section.set_status("Enabled" if show else "Hidden", "review" if show else "unknown")


def _recommendation_text(result: RecommendationResult) -> str:
    lines = [result.summary, "", f"Interpreted as: {result.interpreted_as}"]
    if result.best:
        lines.extend(
            [
                "",
                "Best match:",
                f"- EOAT ID: {result.best.eoat_id}",
                f"- Compatible Machines: {', '.join(result.best.machines)}",
                f"- Tool(s): {', '.join(result.best.tools)}",
                f"- Documentation Status: {result.best.documentation_score}% complete",
                f"- Photos: {result.best.photo_count} linked",
            ]
        )
        lines.extend(["", "Score breakdown:", *_candidate_factor_text_lines(result.best)])
    lines.extend(["", "Before install:", *[f"{index}. {item}" for index, item in enumerate(result.install_checklist, start=1)]])
    if result.warnings:
        lines.extend(["", "Warnings:", *[f"- {warning.title}: {warning.message}" for warning in result.warnings]])
    if len(result.candidates) > 1:
        lines.extend(["", "Backup EOATs:", *[f"- {candidate.eoat_id}: {candidate.summary}" for candidate in result.candidates[1:]]])
    return "\n".join(lines)


def _recommendation_explanation_panel(result: RecommendationResult) -> QWidget:
    wrapper = SecondaryCard("Why this recommendation?", "Score math, evidence, and penalties behind the recommendation.")
    toggle = QCheckBox("Show score breakdown")
    content = QWidget()
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(8)
    if result.best:
        best = result.best
        best_card = _score_breakdown_card(best, f"Best match: {best.eoat_id}", expanded=True)
        for reason in ():
            best_card.layout.addWidget(_checklist_row("•", reason, kind="primary"))
        content_layout.addWidget(best_card)
    for candidate in result.candidates[1:5]:
        candidate_card = _score_breakdown_card(candidate, f"Candidate #{candidate.rank}: {candidate.eoat_id}", expanded=False)
        for reason in ():
            candidate_card.layout.addWidget(_checklist_row("•", reason, kind="outline"))
        content_layout.addWidget(candidate_card)
    if result.warnings:
        warning_card = WarningCard("Limits / warnings", "Review these before install.", severity="warn")
        for warning in result.warnings[:4]:
            warning_card.layout.addWidget(_checklist_row("!", f"{warning.title}: {warning.message}", kind="warning"))
        content_layout.addWidget(warning_card)
    content.setVisible(False)
    toggle.toggled.connect(content.setVisible)
    wrapper.layout.addWidget(toggle)
    wrapper.layout.addWidget(content)
    return wrapper


def _score_breakdown_card(candidate, title: str, *, expanded: bool) -> QWidget:
    card = DetailCard(title, f"Total Score: {candidate.score}")
    total = QLabel(f"Total Score: {candidate.score}")
    total.setObjectName("ScoreTotal")
    card.layout.addWidget(total)
    for label, polarity, kind in (
        ("Positive Factors", "positive", "good"),
        ("Neutral / Middle Factors", "neutral", "info"),
        ("Penalties / Warnings", "negative", "warn"),
    ):
        factors = [factor for factor in candidate.factors if factor.polarity == polarity]
        if not factors:
            continue
        group_label = QLabel(label)
        group_label.setObjectName("SectionTitle")
        card.layout.addWidget(group_label)
        for factor in factors if expanded else factors[:3]:
            card.layout.addWidget(_score_factor_row(factor, kind))
        if not expanded and len(factors) > 3:
            card.layout.addWidget(badge(f"+{len(factors) - 3} more factor(s)", "ghost"))
    return card


def _score_factor_row(factor, kind: str) -> QWidget:
    row = QFrame()
    row.setObjectName(
        {
            "positive": "ScoreFactorPositive",
            "neutral": "ScoreFactorNeutral",
            "negative": "ScoreFactorNegative",
        }.get(factor.polarity, "ScoreFactorNeutral")
    )
    layout = QHBoxLayout(row)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(10)
    points = QLabel(f"{factor.points:+d}")
    points.setObjectName("ScorePoints")
    points.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(points)
    body = QVBoxLayout()
    body.setContentsMargins(0, 0, 0, 0)
    title = QLabel(factor.label)
    title.setObjectName("BodyText")
    title.setWordWrap(True)
    body.addWidget(title)
    detail_parts = [part for part in [factor.details, f"Evidence: {factor.evidence}" if factor.evidence else ""] if part]
    if detail_parts:
        details = QLabel(" ".join(detail_parts))
        details.setObjectName("MutedText")
        details.setWordWrap(True)
        body.addWidget(details)
    layout.addLayout(body, 1)
    layout.addWidget(badge(_factor_polarity_label(factor.polarity), kind))
    return row


def _compact_score_summary(candidate) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    factors = sorted(candidate.factors, key=lambda factor: abs(factor.points), reverse=True)[:4]
    for factor in factors:
        kind = "good" if factor.polarity == "positive" else ("warn" if factor.polarity == "negative" else "info")
        layout.addWidget(badge(f"{factor.points:+d} {_short_label(factor.label, 34)}", kind))
    layout.addStretch(1)
    return widget


def _candidate_factor_text_lines(candidate) -> list[str]:
    lines = [f"- Total Score: {candidate.score}"]
    for label, polarity in (("Positive", "positive"), ("Neutral", "neutral"), ("Penalties / Warnings", "negative")):
        factors = [factor for factor in candidate.factors if factor.polarity == polarity]
        if not factors:
            continue
        lines.append(f"- {label}:")
        for factor in factors:
            evidence = f" Evidence: {factor.evidence}." if factor.evidence else ""
            details = f" {factor.details}" if factor.details else ""
            lines.append(f"  - {factor.points:+d} {factor.label}.{evidence}{details}".rstrip())
    return lines


def _factor_polarity_label(polarity: str) -> str:
    return {"positive": "Bonus", "negative": "Penalty", "neutral": "Neutral"}.get(polarity, "Factor")


def _recommendation_reason_lines(candidate) -> list[str]:
    lines = [reason.rstrip(".") for reason in candidate.reasons]
    lines.extend(
        [
            f"{candidate.documentation_score}% documentation complete",
            f"{candidate.photo_count} linked photo(s) found",
        ]
    )
    if candidate.warnings:
        lines.append(f"{len(candidate.warnings)} warning(s) found")
    else:
        lines.append("No candidate-specific warnings found")
    return list(dict.fromkeys(line for line in lines if line))


def _recommendation_action_row(candidate, page: WhatNeedPage, *, primary: bool) -> QWidget:
    buttons = []
    eoat_button = QPushButton("Open EOAT Profile")
    if primary:
        eoat_button.setObjectName("HeroPrimaryButton")
    eoat_button.clicked.connect(lambda _checked=False, eoat_id=candidate.eoat_id: page.controller.open_eoat(eoat_id))
    buttons.append(eoat_button)

    photos_button = QPushButton("View Photos")
    if primary:
        photos_button.setObjectName("HeroSecondaryButton")
    if candidate.photo_count <= 0:
        photos_button.setEnabled(False)
        photos_button.setToolTip("No linked photos were found for this EOAT.")
        if primary:
            photos_button.setObjectName("HeroDisabledButton")
    photos_button.clicked.connect(lambda _checked=False, eoat_id=candidate.eoat_id: page.open_photos_for(eoat_id))
    buttons.append(photos_button)

    if primary or candidate.tools:
        tool_button = QPushButton("Open Related Tool" if primary else "Open Tool")
        if primary:
            tool_button.setObjectName("HeroSecondaryButton" if candidate.tools else "HeroDisabledButton")
        if not candidate.tools:
            tool_button.setEnabled(False)
            tool_button.setToolTip("This recommendation does not have a linked tool.")
        else:
            tool_button.setToolTip(f"Open Tool / Mold / Part for {candidate.tools[0]}.")
            tool_button.clicked.connect(lambda _checked=False, tool=candidate.tools[0]: page.open_tool_value(tool))
        buttons.append(tool_button)

    if primary or candidate.machines:
        machine_button = QPushButton("Open Related Machine" if primary else "Open Machine")
        if primary:
            machine_button.setObjectName("HeroSecondaryButton" if candidate.machines else "HeroDisabledButton")
        if not candidate.machines:
            machine_button.setEnabled(False)
            machine_button.setToolTip("This recommendation does not have a linked compatible machine.")
        else:
            machine_button.setToolTip(f"Open Machine Profile for {candidate.machines[0]}.")
            machine_button.clicked.connect(lambda _checked=False, machine=candidate.machines[0]: page.open_machine_value(machine))
        buttons.append(machine_button)

    if primary:
        export_button = QPushButton("Export Recommendation")
        export_button.setObjectName("HeroSecondaryButton")
        export_button.clicked.connect(page.export_result)
        buttons.append(export_button)

    return action_row(*buttons)


def _recommendation_context_section(result: RecommendationResult, page: WhatNeedPage) -> QWidget | None:
    seen: set[tuple[str, str]] = set()
    matches = []
    for match in result.matches:
        identity = (match.result_type, match.key)
        if identity in seen or match.result_type not in {"eoat", "machine", "tool"}:
            continue
        seen.add(identity)
        matches.append(match)
        if len(matches) >= 6:
            break
    if not matches:
        return None
    section, layout = _group_container("Related Search Context", "Open the full profile for matching EOATs, machines, and tools.")
    for match in matches:
        card = DetailCard(match.title, match.subtitle, eyebrow=match.result_type.upper())
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(badge(match.result_type.title(), "outline"))
        if match.matched_fields:
            row.addWidget(badge(", ".join(match.matched_fields[:2]), "ghost"))
        row.addStretch(1)
        card.layout.addLayout(row)
        button = QPushButton(_context_button_label(match.result_type))
        if match.result_type == "eoat":
            button.clicked.connect(lambda _checked=False, value=match.key: page.controller.open_eoat(value))
        elif match.result_type == "machine":
            button.clicked.connect(lambda _checked=False, value=match.key: page.controller.open_machine(value))
        else:
            button.clicked.connect(lambda _checked=False, value=match.key: page.controller.open_tool(value))
        card.layout.addWidget(action_row(button))
        layout.addWidget(card)
    return section


def _context_button_label(result_type: str) -> str:
    if result_type == "machine":
        return "Open Machine Profile"
    if result_type == "tool":
        return "Open Tool Profile"
    return "Open EOAT Profile"


class EOATListTile(QWidget):
    def __init__(
        self,
        eoat: EOATRecord,
        *,
        compact: bool = False,
        compare_checked: bool = False,
        compare_callback=None,
        pinned: bool = False,
        recent: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("ListTile")
        self._height = 114 if compact else 148
        self.setMinimumHeight(self._height)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 12)
        layout.setSpacing(5 if compact else 7)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel(eoat.eoat_id)
        title.setObjectName("TileTitle")
        title.setWordWrap(False)
        title.setToolTip(eoat.eoat_id)
        header.addWidget(title, 1)
        health = eoat_relationship_health(eoat)
        header.addWidget(badge(health_label(health), health_badge_kind(health)))
        if compare_callback is not None:
            compare = QCheckBox("Compare")
            compare.setToolTip("Add this EOAT to compare mode.")
            compare.setChecked(compare_checked)
            compare.toggled.connect(compare_callback)
            header.addWidget(compare)
        if pinned:
            header.addWidget(badge("Pinned", "count"))
        elif recent:
            header.addWidget(badge("Recent", "ghost"))
        header.addWidget(badge(f"{eoat.documentation.score}% docs", _score_kind(eoat.documentation.score)))
        if eoat.warning_count:
            header.addWidget(badge(str(eoat.warning_count), "warn"))
        layout.addLayout(header)

        subtitle = QLabel(_eoat_tile_subtitle(eoat))
        subtitle.setObjectName("TileSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(5)
        meta.addWidget(badge(eoat.eoat_type or "Type missing", "outline"))
        meta.addWidget(badge(eoat.status or "Status missing", "good" if "active" in eoat.status.casefold() else "neutral"))
        meta.addStretch(1)
        layout.addLayout(meta)

        if not compact:
            machines = [f"M{machine}" for machine in eoat.machines[:4]]
            if len(eoat.machines) > 4:
                machines.append(f"+{len(eoat.machines) - 4}")
            machine_row = QHBoxLayout()
            machine_row.setContentsMargins(0, 0, 0, 0)
            machine_label = QLabel("Machines")
            machine_label.setObjectName("TileMeta")
            machine_row.addWidget(machine_label)
            machine_row.addWidget(_chip_group(machines, kind="primary", empty="No machines", per_row=6, limit=5), 1)
            layout.addLayout(machine_row)

    def sizeHint(self) -> QSize:
        return QSize(330, self._height)


class MachineListTile(QWidget):
    def __init__(
        self,
        machine: MachineRecord,
        *,
        compact: bool = False,
        compare_checked: bool = False,
        compare_callback=None,
        pinned: bool = False,
        recent: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("ListTile")
        self._height = 112 if compact else 148
        self.setMinimumHeight(self._height)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 12)
        layout.setSpacing(5 if compact else 7)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel(f"Machine {machine.machine}")
        title.setObjectName("TileTitle")
        title.setToolTip(machine.machine)
        header.addWidget(title, 1)
        health = machine_relationship_health(machine)
        header.addWidget(badge(health_label(health), health_badge_kind(health)))
        if compare_callback is not None:
            compare = QCheckBox("Compare")
            compare.setToolTip("Add this machine to compare mode.")
            compare.setChecked(compare_checked)
            compare.toggled.connect(compare_callback)
            header.addWidget(compare)
        if pinned:
            header.addWidget(badge("Pinned", "count"))
        elif recent:
            header.addWidget(badge("Recent", "ghost"))
        if machine.warning_count:
            header.addWidget(badge(str(machine.warning_count), "warn"))
        layout.addLayout(header)

        subtitle = QLabel(machine.robot_type or machine.robot_model or "Robot info missing")
        subtitle.setObjectName("TileSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(5)
        meta.addWidget(badge(f"{len(machine.compatible_eoats)} EOATs", "primary"))
        meta.addWidget(badge(f"{len(machine.compatible_tools)} tools", "outline"))
        meta.addWidget(badge(f"{machine.documentation_score}% docs", _score_kind(machine.documentation_score)))
        meta.addStretch(1)
        layout.addLayout(meta)

        if not compact and machine.compatible_eoats:
            layout.addWidget(_chip_group(machine.compatible_eoats[:4], kind="success", per_row=4, limit=4))

    def sizeHint(self) -> QSize:
        return QSize(320, self._height)


class ToolListTile(QWidget):
    def __init__(
        self,
        tool: ToolRecord,
        *,
        compact: bool = False,
        compare_checked: bool = False,
        compare_callback=None,
        recent: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("ListTile")
        self._height = 130 if compact else 166
        self.setMinimumHeight(self._height)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 14)
        layout.setSpacing(7 if compact else 9)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel(f"Tool {tool.tool}")
        title.setObjectName("TileTitle")
        title.setToolTip(tool.tool)
        header.addWidget(title, 1)
        health = tool_relationship_health(tool)
        header.addWidget(badge(health_label(health), health_badge_kind(health)))
        if compare_callback is not None:
            compare = QCheckBox("Compare")
            compare.setToolTip("Add this tool to compare mode.")
            compare.setChecked(compare_checked)
            compare.toggled.connect(compare_callback)
            header.addWidget(compare)
        if recent:
            header.addWidget(badge("Recent", "ghost"))
        if tool.warning_count:
            header.addWidget(badge(str(tool.warning_count), "warn"))
        layout.addLayout(header)

        subtitle = QLabel(tool.part_description or tool.part_family or ", ".join(tool.parts[:3]) or "No part description")
        subtitle.setObjectName("TileSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(5)
        meta.addWidget(badge(f"{len(tool.compatible_machines)} machines", "primary"))
        meta.addWidget(badge("Linked EOATs" if tool.compatible_eoats else "Missing EOAT Link", "good" if tool.compatible_eoats else "bad"))
        meta.addWidget(badge(f"{tool.warning_count} warnings", "warn" if tool.warning_count else "good"))
        meta.addStretch(1)
        layout.addLayout(meta)

        if not compact:
            layout.addWidget(_chip_group(tool.compatible_eoats[:4], kind="success", empty="No linked EOATs", per_row=4, limit=4))
            layout.addSpacing(2)

    def sizeHint(self) -> QSize:
        return QSize(360, self._height)


class _SetupPacketRecordSelector(QFrame):
    def __init__(self, title: str, placeholder: str, rows_callback, selected_callback, health_callback=None, parent=None):
        super().__init__(parent)
        self.rows_callback = rows_callback
        self.selected_callback = selected_callback
        self.health_callback = health_callback
        self.records = ()
        self.setObjectName("DetailCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)
        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        layout.addWidget(title_label)
        self.search = QLineEdit()
        self.search.setObjectName("ModernSearchBar")
        self.search.setPlaceholderText(placeholder)
        self.search.textChanged.connect(lambda: self.refresh(""))
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName("CardList")
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(self._selected)
        self.list.itemActivated.connect(self._selected)
        layout.addWidget(self.list, 1)

    def refresh(self, selected_id: str, *, selected_record=None) -> None:
        query = self.search.text().strip().casefold()
        scroll_value = self.list.verticalScrollBar().value()
        self.records = tuple(self.rows_callback())
        record_list = list(self.records)
        selected_key = selected_id.casefold() if selected_id else ""
        selected_in_rows = bool(selected_key and any(self._key(record).casefold() == selected_key for record in record_list))
        if selected_record is not None and selected_key and not selected_in_rows:
            record_list.insert(0, selected_record)
        self.list.blockSignals(True)
        self.list.clear()
        selected_item: QListWidgetItem | None = None
        for record in record_list:
            title = self._title(record)
            subtitle = self._subtitle(record)
            haystack = f"{title} {subtitle} {' '.join(self._aliases(record))}".casefold()
            selected = bool(selected_id and self._key(record).casefold() == selected_id.casefold())
            incompatible_selected = selected and not selected_in_rows
            if query and query not in haystack and not selected:
                continue
            status = "Selected - " if selected else ""
            suffix = "\nNot compatible with current filters; manual override required." if incompatible_selected else ""
            item = QListWidgetItem(f"{status}{title}\n{subtitle}{suffix}")
            item.setToolTip(subtitle)
            item.setData(Qt.ItemDataRole.UserRole, record)
            item.setSizeHint(QSize(0, 74))
            self._style_item(item, record, selected=selected, incompatible=incompatible_selected)
            self.list.addItem(item)
            if selected:
                selected_item = item
        if not self.list.count():
            empty = QListWidgetItem("No compatible choices found")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            empty.setSizeHint(QSize(0, 52))
            self.list.addItem(empty)
        elif selected_item is not None:
            selected_item.setSelected(True)
        self.list.blockSignals(False)
        self.list.verticalScrollBar().setValue(scroll_value)
        QTimer.singleShot(0, lambda value=scroll_value: self.list.verticalScrollBar().setValue(value))

    def _selected(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        record = item.data(Qt.ItemDataRole.UserRole)
        if record is not None:
            self.selected_callback(record)

    def _title(self, record) -> str:
        if isinstance(record, MachineRecord):
            return f"Machine {record.machine}"
        if isinstance(record, ToolRecord):
            return f"Tool {record.tool}"
        if isinstance(record, EOATRecord):
            return record.eoat_id
        return str(record)

    def _subtitle(self, record) -> str:
        if isinstance(record, MachineRecord):
            warning = " | Warning" if record.warning_count else ""
            return f"{record.robot_type or record.robot_model or 'Robot info missing'} | {len(record.compatible_tools)} tools | {len(record.compatible_eoats)} EOATs{warning}"
        if isinstance(record, ToolRecord):
            warning = " | Warning" if record.warning_count else ""
            return f"{record.part_description or record.part_family or 'Description missing'} | {len(record.compatible_machines)} machines | {len(record.compatible_eoats)} EOATs{warning}"
        if isinstance(record, EOATRecord):
            warning = " | Warning" if record.warning_count else ""
            return f"{record.eoat_type or 'Type missing'} / {record.status or 'Status missing'} | Docs {record.documentation.score}% | Photos {record.photo_count}{warning}"
        return ""

    def _aliases(self, record) -> tuple[str, ...]:
        values = []
        for attr in ("compatible_tools", "compatible_eoats", "compatible_machines", "tools", "machines", "parts", "molds"):
            values.extend(getattr(record, attr, ()) or ())
        return tuple(str(value) for value in values)

    def _key(self, record) -> str:
        if isinstance(record, MachineRecord):
            return record.machine
        if isinstance(record, ToolRecord):
            return record.tool
        if isinstance(record, EOATRecord):
            return record.eoat_id
        return str(record)

    def _style_item(self, item: QListWidgetItem, record, *, selected: bool, incompatible: bool) -> None:
        health = RelationshipHealth.INVALID if incompatible else (
            self.health_callback(record) if callable(self.health_callback) else RelationshipHealth.UNKNOWN
        )
        background, foreground = _health_item_colors(health, selected=selected)
        item.setData(Qt.ItemDataRole.BackgroundRole, background)
        item.setData(Qt.ItemDataRole.ForegroundRole, foreground)


class _SetupPacketPdfViewerDialog(QDialog):
    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.setObjectName("SetupPacketPdfViewerDialog")
        self.setWindowTitle(f"Changeover Packet - {self.path.name}")
        self.resize(1280, 840)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.viewer = _SetupPacketPdfViewer(self, show_toolbar=False)
        self.viewer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.viewer_toolbar = QWidget()
        self.viewer_toolbar.setFixedHeight(42)
        self.viewer_toolbar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        toolbar = QHBoxLayout(self.viewer_toolbar)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)
        self.viewer_prev_button = QPushButton("Previous")
        self.viewer_prev_button.clicked.connect(self.viewer.previous_page)
        self.viewer_next_button = QPushButton("Next")
        self.viewer_next_button.clicked.connect(self.viewer.next_page)
        self.viewer_zoom_out_button = QPushButton("Zoom Out")
        self.viewer_zoom_out_button.clicked.connect(self.viewer.zoom_out)
        self.viewer_zoom_in_button = QPushButton("Zoom In")
        self.viewer_zoom_in_button.clicked.connect(self.viewer.zoom_in)
        self.viewer_fit_width_button = QPushButton("Fit Width")
        self.viewer_fit_width_button.clicked.connect(self.viewer.fit_width)
        self.viewer_fit_page_button = QPushButton("Fit Page")
        self.viewer_fit_page_button.clicked.connect(self.viewer.fit_page)
        self.viewer_print_button = QPushButton("Print")
        self.viewer_print_button.clicked.connect(self.viewer.print_pdf)
        open_button = QPushButton("Open")
        open_button.clicked.connect(lambda: open_path(self.path))
        folder_button = QPushButton("Folder")
        folder_button.clicked.connect(lambda: open_path(self.path.parent))
        copy_button = QPushButton("Copy Path")
        copy_button.clicked.connect(self.copy_path)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        for button in (
            self.viewer_prev_button,
            self.viewer_next_button,
            self.viewer_zoom_out_button,
            self.viewer_zoom_in_button,
            self.viewer_fit_width_button,
            self.viewer_fit_page_button,
            self.viewer_print_button,
            open_button,
            folder_button,
            copy_button,
            close_button,
        ):
            toolbar.addWidget(button)
        toolbar.addWidget(self.viewer.page_label)
        toolbar.addStretch(1)
        layout.addWidget(self.viewer_toolbar)

        self.viewer_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.viewer_splitter.setObjectName("AtlasMainSplitter")
        self.viewer_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.viewer_splitter.setMinimumHeight(560)
        self.metadata_sidebar = SecondaryCard("Changeover Packet", "PDF details and actions")
        self.metadata_sidebar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.metadata_sidebar.setMinimumWidth(280)
        self.metadata_sidebar.setMaximumWidth(340)
        self.metadata_sidebar.layout.addWidget(key_value_grid(_setup_packet_pdf_metadata_rows(self.path)))
        filename_label = QLabel(_short_label(self.path.name, 64))
        filename_label.setObjectName("MutedText")
        filename_label.setWordWrap(True)
        filename_label.setToolTip(str(self.path))
        self.metadata_sidebar.layout.addWidget(filename_label)
        self.metadata_sidebar.layout.addStretch(1)
        self.viewer_splitter.addWidget(self.metadata_sidebar)
        self.viewer_splitter.addWidget(self.viewer)
        self.viewer_splitter.setSizes([310, 970])
        layout.addWidget(self.viewer_splitter, 1)
        if self.viewer.document is not None:
            self.viewer.document.pageCountChanged.connect(lambda *_args: self._sync_toolbar_controls())
        self.viewer.load_pdf(self.path)
        self._sync_toolbar_controls()

    def copy_path(self) -> None:
        QApplication.clipboard().setText(str(self.path))

    def _sync_toolbar_controls(self) -> None:
        can_view = self.viewer.view is not None and self.viewer.document is not None and self.viewer.document.pageCount() > 0
        for button in (
            self.viewer_prev_button,
            self.viewer_next_button,
            self.viewer_zoom_out_button,
            self.viewer_zoom_in_button,
            self.viewer_fit_width_button,
            self.viewer_fit_page_button,
            self.viewer_print_button,
        ):
            button.setEnabled(can_view)

    def closeEvent(self, event) -> None:
        self.viewer.close_document()
        super().closeEvent(event)


class _SetupPacketPdfViewer(QFrame):
    def __init__(self, parent=None, *, show_toolbar: bool = True):
        super().__init__(parent)
        self.path: Path | None = None
        self.document = QPdfDocument(self) if QPdfDocument is not None else None
        self.setObjectName("DetailCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        self.prev_button = QPushButton("Previous", self)
        self.prev_button.clicked.connect(self.previous_page)
        self.next_button = QPushButton("Next", self)
        self.next_button.clicked.connect(self.next_page)
        self.page_label = QLabel("Page - / -")
        self.page_label.setObjectName("MetricLabel")
        self.page_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.zoom_out_button = QPushButton("Zoom Out", self)
        self.zoom_out_button.clicked.connect(self.zoom_out)
        self.zoom_in_button = QPushButton("Zoom In", self)
        self.zoom_in_button.clicked.connect(self.zoom_in)
        self.fit_width_button = QPushButton("Fit Width", self)
        self.fit_width_button.clicked.connect(self.fit_width)
        self.fit_page_button = QPushButton("Fit Page", self)
        self.fit_page_button.clicked.connect(self.fit_page)
        self.print_button = QPushButton("Print", self)
        self.print_button.clicked.connect(self.print_pdf)
        if show_toolbar:
            for button in (
                self.prev_button,
                self.next_button,
                self.zoom_out_button,
                self.zoom_in_button,
                self.fit_width_button,
                self.fit_page_button,
                self.print_button,
            ):
                controls.addWidget(button)
            controls.addWidget(self.page_label)
            controls.addStretch(1)
            layout.addLayout(controls)

        self.message = QLabel("")
        self.message.setObjectName("MutedText")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        self.view = QPdfView(self) if QPdfView is not None else None
        if self.view is not None and self.document is not None:
            self.view.setDocument(self.document)
            self.view.setPageMode(QPdfView.PageMode.MultiPage)
            self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self.view.setMinimumHeight(360)
            self.document.pageCountChanged.connect(lambda *_args: self._sync_page_label())
            self.view.pageNavigator().currentPageChanged.connect(lambda *_args: self._sync_page_label())
            layout.addWidget(self.view, 1)
            self.message.setText("No changeover packet generated yet. Generate a packet to preview it here.")
        else:
            self.view = None
            self.message.setText("Embedded PDF viewer is unavailable in this build. Use Open PDF or Open Folder.")
            self.setMinimumHeight(160)
        self._sync_controls(False)

    def load_pdf(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.view is None or self.document is None:
            self.message.setText("Embedded PDF viewer is unavailable in this build. Use Open PDF or Open Folder.")
            self.message.setVisible(True)
            self._sync_controls(False)
            return
        if not self.path.exists():
            self.message.setText(f"PDF file not found: {self.path}")
            self.message.setVisible(True)
            self._sync_controls(False)
            return
        status = self.document.load(str(self.path))
        if status == QPdfDocument.Error.None_ or self.document.pageCount() > 0:
            self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self.message.setText("")
            self.message.setVisible(False)
            self._sync_controls(True)
            self._sync_page_label()
            return
        self.message.setText("Atlas could not load this PDF in the embedded viewer. Use Open PDF or Open Folder.")
        self.message.setVisible(True)
        self._sync_controls(False)

    def close_document(self) -> None:
        if self.document is not None:
            try:
                self.document.close()
            except RuntimeError:
                pass
        self._sync_controls(False)

    def previous_page(self) -> None:
        if self.view is None or self.document is None:
            return
        navigator = self.view.pageNavigator()
        page = max(0, navigator.currentPage() - 1)
        navigator.jump(page, QPointF(0, 0))
        self._sync_page_label()

    def next_page(self) -> None:
        if self.view is None or self.document is None:
            return
        navigator = self.view.pageNavigator()
        page = min(max(0, self.document.pageCount() - 1), navigator.currentPage() + 1)
        navigator.jump(page, QPointF(0, 0))
        self._sync_page_label()

    def zoom_in(self) -> None:
        if self.view is None:
            return
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(min(5.0, self.view.zoomFactor() * 1.2))

    def zoom_out(self) -> None:
        if self.view is None:
            return
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(max(0.2, self.view.zoomFactor() / 1.2))

    def fit_width(self) -> None:
        if self.view is not None:
            self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    def fit_page(self) -> None:
        if self.view is not None:
            self.view.setZoomMode(QPdfView.ZoomMode.FitInView)

    def print_pdf(self) -> None:
        if self.path:
            open_path(self.path)

    def _sync_page_label(self) -> None:
        try:
            page_count = 0 if self.document is None else self.document.pageCount()
        except RuntimeError:
            page_count = 0
        if self.view is None or self.document is None or page_count <= 0:
            self.page_label.setText("Page - / -")
            return
        current = max(0, self.view.pageNavigator().currentPage()) + 1
        self.page_label.setText(f"Page {current} / {page_count}")

    def _sync_controls(self, enabled: bool) -> None:
        for button in (
            self.prev_button,
            self.next_button,
            self.zoom_out_button,
            self.zoom_in_button,
            self.fit_width_button,
            self.fit_page_button,
            self.print_button,
        ):
            button.setEnabled(enabled)


class _PreviousPacketRow(QWidget):
    def __init__(self, path: Path, page: SetupPacketPage, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.page = page
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)
        metadata = _setup_packet_metadata(self.path)
        title = QLabel(_setup_packet_setup_line(self.path, metadata=metadata))
        title.setObjectName("TileTitle")
        title.setToolTip(str(self.path))
        title.setWordWrap(True)
        layout.addWidget(title)

        chip_row = QHBoxLayout()
        chip_row.setContentsMargins(0, 0, 0, 0)
        chip_row.setSpacing(6)
        type_chip = badge(str(metadata.get("packet_type") or "Changeover Packet"), "info")
        compat = str(metadata.get("compatibility_status") or "-")
        compat_chip = badge(compat, _compatibility_chip_kind(compat))
        chip_row.addWidget(type_chip)
        chip_row.addWidget(compat_chip)
        chip_row.addStretch(1)
        layout.addLayout(chip_row)

        meta = QLabel(f"{_setup_packet_generated_time(self.path, metadata)} | {_format_file_size(self.path)}")
        meta.setObjectName("MutedText")
        meta.setWordWrap(True)
        layout.addWidget(meta)
        filename = QLabel(_short_label(self.path.name, 62))
        filename.setObjectName("MutedText")
        filename.setWordWrap(True)
        filename.setToolTip(str(self.path))
        layout.addWidget(filename)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(6)
        view_button = QPushButton("View")
        view_button.setToolTip("View this packet inside Atlas.")
        view_button.clicked.connect(lambda: page.view_packet_in_app(self.path))
        open_button = QPushButton("Open")
        open_button.setToolTip("Open this packet in the default PDF viewer.")
        open_button.clicked.connect(lambda: open_path(self.path))
        folder_button = QPushButton("Folder")
        folder_button.setToolTip("Open this packet's folder.")
        folder_button.clicked.connect(lambda: open_path(self.path.parent))
        buttons.addWidget(view_button)
        buttons.addWidget(open_button)
        buttons.addWidget(folder_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def sizeHint(self) -> QSize:
        return QSize(340, 138)


@dataclass(frozen=True)
class PhotoPixmapLoadResult:
    pixmap: QPixmap
    state: str
    message: str = ""
    detail: str = ""


class _PhotoStageLabel(QLabel):
    def __init__(self, toggle_callback, parent=None):
        super().__init__(parent)
        self._toggle_callback = toggle_callback

    def mouseDoubleClickEvent(self, event) -> None:
        self._toggle_callback()
        event.accept()


class _PhotoFilmstrip(QScrollArea):
    def __init__(self, wheel_callback, parent=None):
        super().__init__(parent)
        self._wheel_callback = wheel_callback

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta:
            self._wheel_callback(-1 if delta > 0 else 1)
            event.accept()
            return
        super().wheelEvent(event)


class _PhotoThumbLabel(QLabel):
    def __init__(self, photo, index: int, select_callback, parent=None):
        super().__init__(parent)
        self.photo = photo
        self.index = index
        self._select_callback = select_callback
        self.setObjectName("PhotoViewerThumb")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setText(photo.filename or Path(photo.path).name or "Photo")
        self.setToolTip(photo.path)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(14)
        self._shadow.setOffset(0, 4)
        self._shadow.setColor(QColor(0, 0, 0, 155))
        self.setGraphicsEffect(self._shadow)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._select_callback(self.index)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def set_selected_state(self, selected: bool, distance: int) -> None:
        self.setProperty("selected", selected)
        if selected:
            size = QSize(132, 92)
            self._shadow.setBlurRadius(24)
        elif distance == 1:
            size = QSize(108, 76)
            self._shadow.setBlurRadius(16)
        else:
            size = QSize(92, 66)
            self._shadow.setBlurRadius(10)
        self.setFixedSize(size)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_result(self, result: AsyncPhotoLoadResult) -> None:
        if result.image.isNull():
            self.setText(Path(result.path).name or result.message or "Photo")
            return
        pixmap = QPixmap.fromImage(result.image)
        self.setText("")
        self.setPixmap(
            pixmap.scaled(
                max(20, self.width() - 10),
                max(20, self.height() - 10),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class PhotoCarouselDialog(QDialog):
    SUPPORTED_SUFFIXES = SUPPORTED_IMAGE_SUFFIXES

    def __init__(self, eoat: EOATRecord, *, prefetch: bool = True, parent=None):
        super().__init__(parent)
        self.eoat = eoat
        self.prefetch = prefetch
        self.photos = [photo for photo in _combined_photos(eoat) if Path(photo.path).suffix.casefold() in self.SUPPORTED_SUFFIXES]
        self.index = 0
        self.fit_mode = "fit"
        self.zoom = 1.0
        self.manager = _photo_manager_for_parent(parent, self)
        self._results: dict[int, AsyncPhotoLoadResult] = {}
        self._thumb_results: dict[int, AsyncPhotoLoadResult] = {}
        self._request_indexes: dict[str, int] = {}
        self._thumb_request_indexes: dict[str, int] = {}
        self._current_request_id = ""
        self._animate_next_render = True
        self.setObjectName("PhotoViewerDialog")
        self.setWindowTitle(f"Photos - {eoat.eoat_id}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        self.setSizeGripEnabled(True)
        self.setModal(True)
        self.resize(1080, 760)
        self.setMinimumSize(760, 520)
        self.manager.image_ready.connect(self._photo_ready)
        self.manager.update_selected_photo_context(eoat, reason="Carousel preload: current EOAT photo set")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title = QLabel(eoat.eoat_id)
        title.setObjectName("PhotoViewerTitle")
        self.filename_label = QLabel()
        self.filename_label.setObjectName("PhotoViewerMeta")
        self.filename_label.setWordWrap(True)
        title_block.addWidget(title)
        title_block.addWidget(self.filename_label)
        self.count_label = QLabel()
        self.count_label.setObjectName("PhotoViewerCount")
        self.view_button = QToolButton()
        self.view_button.setText("View")
        self.view_button.setObjectName("PhotoViewerToolButton")
        self.view_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.view_button.setMenu(self._view_menu())
        self.maximize_button = QPushButton("Maximize")
        self.maximize_button.setObjectName("PhotoViewerButton")
        self.maximize_button.clicked.connect(self.toggle_maximize_restore)
        close_button = QPushButton("Close")
        close_button.setObjectName("PhotoViewerCloseButton")
        close_button.clicked.connect(self.close)
        header.addLayout(title_block, 1)
        header.addWidget(self.count_label)
        header.addWidget(self.view_button)
        header.addWidget(self.maximize_button)
        header.addWidget(close_button)
        layout.addLayout(header)

        self.stage = QFrame()
        self.stage.setObjectName("PhotoViewerStage")
        stage_layout = QVBoxLayout(self.stage)
        stage_layout.setContentsMargins(8, 8, 8, 8)
        self.image_label = _PhotoStageLabel(self.toggle_fit_actual)
        self.image_label.setObjectName("PhotoViewerImage")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(620, 360)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._opacity_effect = QGraphicsOpacityEffect(self.image_label)
        self._opacity_effect.setOpacity(1.0)
        self.image_label.setGraphicsEffect(self._opacity_effect)
        self._fade_animation = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_animation.setDuration(170)
        self._fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        stage_layout.addWidget(self.image_label, 1)
        layout.addWidget(self.stage, 1)

        self.filmstrip = _PhotoFilmstrip(lambda step: self.next_photo() if step > 0 else self.previous_photo())
        self.filmstrip.setObjectName("PhotoViewerFilmstrip")
        self.filmstrip.setWidgetResizable(True)
        self.filmstrip.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.filmstrip.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.thumb_container = QWidget()
        self.thumb_layout = QHBoxLayout(self.thumb_container)
        self.thumb_layout.setContentsMargins(8, 8, 8, 8)
        self.thumb_layout.setSpacing(0)
        self.thumbnails: list[_PhotoThumbLabel] = []
        for index, photo in enumerate(self.photos):
            thumb = _PhotoThumbLabel(photo, index, self.select_photo)
            self.thumbnails.append(thumb)
            self.thumb_layout.addWidget(thumb)
        self.thumb_layout.addStretch(1)
        self.filmstrip.setWidget(self.thumb_container)
        layout.addWidget(self.filmstrip)

        secondary_actions = QHBoxLayout()
        secondary_actions.setContentsMargins(0, 0, 0, 0)
        self.folder_button = QPushButton("Open Folder")
        self.folder_button.setObjectName("PhotoViewerSecondaryButton")
        self.folder_button.clicked.connect(self.open_folder)
        self.external_button = QPushButton("Open Externally")
        self.external_button.setObjectName("PhotoViewerSecondaryButton")
        self.external_button.clicked.connect(self.open_current_external)
        secondary_actions.addStretch(1)
        secondary_actions.addWidget(self.folder_button)
        secondary_actions.addWidget(self.external_button)
        layout.addLayout(secondary_actions)
        self._show_photo()
        self._queue_thumbnails()

    def _view_menu(self):
        menu = self.view_button.menu() if hasattr(self, "view_button") else None
        if menu is None:
            from PySide6.QtWidgets import QMenu

            menu = QMenu(self)
        for label, callback in [
            ("Fit", lambda: self.set_fit_mode("fit")),
            ("Fill", lambda: self.set_fit_mode("fill")),
            ("Actual Size", lambda: self.set_fit_mode("actual")),
            ("Zoom In", lambda: self.adjust_zoom(1.18)),
            ("Zoom Out", lambda: self.adjust_zoom(0.85)),
            ("Reset Zoom", self.reset_zoom),
        ]:
            action = QAction(label, self)
            action.triggered.connect(lambda _checked=False, callback=callback: callback())
            menu.addAction(action)
        return menu

    def closeEvent(self, event) -> None:
        try:
            self.manager.image_ready.disconnect(self._photo_ready)
        except (RuntimeError, TypeError):
            pass
        for request_id in [*self._request_indexes, *self._thumb_request_indexes]:
            self.manager.cancel_request(request_id)
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Left:
            self.previous_photo()
            return
        if event.key() == Qt.Key.Key_Right:
            self.next_photo()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_current_pixmap()

    def previous_photo(self) -> None:
        if self.photos:
            self.select_photo((self.index - 1) % len(self.photos))

    def next_photo(self) -> None:
        if self.photos:
            self.select_photo((self.index + 1) % len(self.photos))

    def select_photo(self, index: int) -> None:
        if not self.photos or index == self.index:
            return
        self.manager.mark_user_activity()
        self.index = max(0, min(index, len(self.photos) - 1))
        self._animate_next_render = True
        self._show_photo()

    def toggle_maximize_restore(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self.maximize_button.setText("Maximize")
        else:
            self.showMaximized()
            self.maximize_button.setText("Restore")

    def toggle_fit_actual(self) -> None:
        self.set_fit_mode("actual" if self.fit_mode != "actual" else "fit")

    def set_fit_mode(self, mode: str) -> None:
        self.fit_mode = mode
        if mode != "actual":
            self.zoom = 1.0
        self._render_current_pixmap()

    def adjust_zoom(self, factor: float) -> None:
        self.zoom = max(0.1, min(6.0, self.zoom * factor))
        self.fit_mode = "actual"
        self._render_current_pixmap()

    def reset_zoom(self) -> None:
        self.zoom = 1.0
        self.fit_mode = "fit"
        self._render_current_pixmap()

    def open_folder(self) -> None:
        if self.eoat.photos.folder_path:
            open_path(self.eoat.photos.folder_path)

    def open_current_external(self) -> None:
        if self.photos:
            open_path(self.photos[self.index].path)

    def _show_photo(self) -> None:
        if not self.photos:
            self.count_label.setText("0 / 0")
            self.filename_label.setText("No photos linked.")
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("No photos linked for this EOAT.")
            self.external_button.setEnabled(False)
            self.folder_button.setEnabled(bool(self.eoat.photos.folder_path))
            return
        photo = self.photos[self.index]
        self.count_label.setText(f"{self.index + 1} / {len(self.photos)}")
        category = f"  /  {photo.category}" if photo.category else ""
        self.filename_label.setText(f"{photo.filename or Path(photo.path).name}{category}")
        self.filename_label.setToolTip(photo.path)
        self.external_button.setEnabled(bool(photo.path))
        self.folder_button.setEnabled(bool(self.eoat.photos.folder_path))
        self._queue_photo(self.index, priority=0)
        self._prefetch_photo_set()
        self._update_thumbnails()
        self._render_current_pixmap()

    @Slot(str, object)
    def _photo_ready(self, request_id: str, result: AsyncPhotoLoadResult) -> None:
        thumb_index = self._thumb_request_indexes.pop(request_id, None)
        if thumb_index is not None:
            self._thumb_results[thumb_index] = result
            if 0 <= thumb_index < len(self.thumbnails):
                with perf_timer(
                    getattr(self.manager, "project_root", ""),
                    "photo.thumbnail.display",
                    details={
                        "ui_sensitive": "image_display",
                        "path": result.path,
                        "request_id": request_id,
                        "thumb_index": thumb_index,
                        "state": result.state,
                    },
                    source="atlas_pages",
                    page_tool="photos",
                ):
                    self.thumbnails[thumb_index].set_result(result)
            return
        index = self._request_indexes.pop(request_id, None)
        if index is None:
            return
        self._results[index] = result
        if index == self.index and request_id == self._current_request_id:
            self._render_current_pixmap()

    def _queue_photo(self, index: int, *, priority: int) -> None:
        if index in self._results:
            return
        photo = self.photos[index]
        request_id = f"{id(self)}:full:{index}:{priority}:{time.perf_counter_ns()}"
        self._request_indexes[request_id] = index
        if priority == 0:
            self._current_request_id = request_id
        self.manager.request_image(
            photo.path,
            request_id=request_id,
            requested_size=self.image_label.size(),
            priority=priority,
            reason="Carousel preload: adjacent image" if priority == 1 else "Carousel preload: current EOAT photo set",
        )

    def _queue_thumbnail(self, index: int) -> None:
        if index in self._thumb_results or not (0 <= index < len(self.photos)):
            return
        photo = self.photos[index]
        request_id = f"{id(self)}:thumb:{index}:{time.perf_counter_ns()}"
        self._thumb_request_indexes[request_id] = index
        self.manager.request_image(
            photo.path,
            request_id=request_id,
            requested_size=THUMB_PRELOAD_SIZE,
            priority=0,
            reason="Carousel thumbnail",
        )

    def _queue_thumbnails(self) -> None:
        for index in range(len(self.photos)):
            self._queue_thumbnail(index)

    def _prefetch_photo_set(self) -> None:
        if not self.prefetch or len(self.photos) <= 1:
            return
        self._queue_photo((self.index - 1) % len(self.photos), priority=1)
        self._queue_photo((self.index + 1) % len(self.photos), priority=1)
        for offset in range(2, min(len(self.photos), 6)):
            self._queue_photo((self.index + offset) % len(self.photos), priority=2)

    def _update_thumbnails(self) -> None:
        if not self.thumbnails:
            return
        for thumb in self.thumbnails:
            distance = min(abs(thumb.index - self.index), len(self.photos) - abs(thumb.index - self.index))
            thumb.set_selected_state(thumb.index == self.index, distance)
            if thumb.index in self._thumb_results:
                thumb.set_result(self._thumb_results[thumb.index])
        current = self.thumbnails[self.index]
        self.filmstrip.ensureWidgetVisible(current, 80, 0)

    def _render_current_pixmap(self) -> None:
        if not self.photos:
            return
        result = self._results.get(self.index)
        if result is None:
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("Loading image...")
            return
        if result.image.isNull():
            detail = f"\n\n{result.detail}" if result.detail and getattr(self.controller_settings_debug(), "show_advanced_diagnostics", False) else ""
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(f"{result.message or result.state}{detail}")
            return
        with perf_timer(
            getattr(self.manager, "project_root", ""),
            "photo.full_image.display",
            details={
                "ui_sensitive": "image_display",
                "path": result.path,
                "photo_index": self.index,
                "fit_mode": self.fit_mode,
            },
            source="atlas_pages",
            page_tool="photos",
        ):
            self.image_label.setText("")
            pixmap = QPixmap.fromImage(result.image)
            size = self.image_label.size()
            if self.fit_mode == "actual":
                target_width = max(24, int(pixmap.width() * self.zoom))
                target_height = max(24, int(pixmap.height() * self.zoom))
                aspect_mode = Qt.AspectRatioMode.KeepAspectRatio
            else:
                target_width = max(120, size.width() - 18)
                target_height = max(120, size.height() - 18)
                aspect_mode = Qt.AspectRatioMode.KeepAspectRatioByExpanding if self.fit_mode == "fill" else Qt.AspectRatioMode.KeepAspectRatio
            self.image_label.setPixmap(
                pixmap.scaled(
                    target_width,
                    target_height,
                    aspect_mode,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        log_perf_marker(
            getattr(self.manager, "project_root", ""),
            "photo.full_image.display_ready",
            details={"path": result.path, "photo_index": self.index, "fit_mode": self.fit_mode},
            source="atlas_pages",
            page_tool="photos",
        )
        if self._animate_next_render:
            self._animate_next_render = False
            self._fade_animation.stop()
            self._opacity_effect.setOpacity(0.35)
            self._fade_animation.setStartValue(0.35)
            self._fade_animation.setEndValue(1.0)
            self._fade_animation.start()

    def controller_settings_debug(self):
        parent = self.parent()
        controller = getattr(parent, "controller", None)
        return getattr(controller, "settings", None)


def _photo_manager_for_parent(parent, fallback_parent) -> PhotoLoadManager:
    controller = getattr(parent, "controller", None)
    manager = getattr(controller, "photo_loader", None)
    if isinstance(manager, PhotoLoadManager):
        return manager
    return PhotoLoadManager(fallback_parent)


def _load_photo_pixmap(path: str, *, project_root: str = "") -> PhotoPixmapLoadResult:
    result = decode_photo_image(path)
    return PhotoPixmapLoadResult(
        pixmap=QPixmap.fromImage(result.image) if not result.image.isNull() else QPixmap(),
        state=result.state,
        message=result.message,
        detail=result.detail,
    )


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        child_layout = item.layout()
        if child_layout is not None:
            _clear_layout(child_layout)
            child_layout.setParent(None)
            child_layout.deleteLater()
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setGraphicsEffect(None)
            widget.setParent(None)
            widget.deleteLater()


def _compact_packet_missing(items: tuple[str, ...]) -> str:
    if not items:
        return "None indexed"
    visible = "; ".join(_short_label(item, 64) for item in items[:2])
    if len(items) > 2:
        visible += f"; +{len(items) - 2} more"
    return visible


def _setup_packet_prefill_note(context_label: str) -> str:
    folded = str(context_label or "").casefold()
    if not folded or folded in {"atlas", "sidebar", "command palette"}:
        return ""
    if "what do i need" in folded or "recommend" in folded:
        return "Prefilled from Recommendation"
    if "machine" in folded:
        return "Prefilled from Machine Profile"
    if "tool" in folded:
        return "Prefilled from Tool Search"
    if "eoat" in folded:
        return "Prefilled from EOAT Profile"
    return f"Prefilled from {context_label}"


def _setup_packet_pdf_info(path: Path, *, context=None) -> str:
    metadata = _setup_packet_metadata(path)
    machine = getattr(context, "machine_id", "") or metadata.get("machine") or "-"
    tool = getattr(context, "tool_id", "") or metadata.get("tool") or "-"
    eoat = getattr(context, "eoat_id", "") or metadata.get("eoat") or "-"
    packet_type = getattr(context, "packet_type_label", "") or metadata.get("packet_type") or "Changeover Packet"
    photo_mode = getattr(context, "photo_inclusion_label", "") or metadata.get("photo_inclusion") or "-"
    status = getattr(getattr(context, "validation", None), "status", "") or metadata.get("compatibility_status") or "-"
    override = getattr(getattr(context, "validation", None), "manual_override_used", None)
    if override is None:
        override = metadata.get("manual_override_used", False)
    return "\n".join(
        [
            f"Filename: {path.name}",
            f"Generated: {_setup_packet_generated_time(path, metadata)}",
            f"Setup: Machine {machine} | Tool {tool} | EOAT {eoat}",
            f"Packet type: {packet_type}",
            f"Photo inclusion: {photo_mode}",
            f"Fit Check: {status} | Manual override: {'Yes' if override else 'No'}",
            f"File size: {_format_file_size(path)}",
        ]
    )


def _setup_packet_pdf_row_summary(path: Path) -> str:
    parsed = _setup_packet_metadata(path)
    setup = (
        f"Machine {parsed.get('machine', '-')} | Tool {parsed.get('tool', '-')} | EOAT {parsed.get('eoat', '-')}"
        if parsed
        else "Setup details not parsed from filename"
    )
    packet_type = parsed.get("packet_type", "Changeover Packet")
    return f"{_setup_packet_generated_time(path, parsed)} | {setup} | {packet_type} | {_format_file_size(path)}"


def _setup_packet_setup_line(path: Path, *, metadata: dict[str, object] | None = None) -> str:
    parsed = metadata or _setup_packet_metadata(path)
    machine = parsed.get("machine")
    tool = parsed.get("tool")
    eoat = parsed.get("eoat")
    if machine or tool or eoat:
        return f"Machine {machine or '-'} | Tool {tool or '-'} | EOAT {eoat or '-'}"
    return _short_label(path.stem.replace("_", " "), 72)


def _compatibility_chip_kind(status: str) -> str:
    folded = str(status or "").casefold()
    if "manual" in folded or "not confirmed" in folded:
        return "bad"
    if "missing" in folded or "partial" in folded:
        return "warn"
    if "confirmed" in folded:
        return "good"
    return "info"


def _set_chip_kind(label: QLabel, kind: str) -> None:
    object_names = {
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
    label.setObjectName(object_names.get(kind, "NeutralChip"))
    label.style().unpolish(label)
    label.style().polish(label)


def _setup_packet_pdf_metadata_rows(path: Path) -> list[tuple[str, str]]:
    metadata = _setup_packet_metadata(path)
    return [
        ("Generated", _setup_packet_generated_time(path, metadata)),
        ("Machine", metadata.get("machine", "-")),
        ("Tool", metadata.get("tool", "-")),
        ("EOAT", metadata.get("eoat", "-")),
        ("Packet type", metadata.get("packet_type", "Changeover Packet")),
        ("Photo inclusion", metadata.get("photo_inclusion", "-")),
        ("Fit Check", metadata.get("compatibility_status", "-")),
        ("Manual override", "Yes" if metadata.get("manual_override_used") else "No"),
        ("File size", _format_file_size(path)),
    ]


def _setup_packet_metadata(path: Path) -> dict[str, object]:
    metadata = _load_setup_packet_sidecar(path)
    parsed = _parse_setup_packet_filename(path)
    merged = {**parsed, **metadata}
    if "generated_timestamp" in merged and "stamp" not in merged:
        merged["stamp"] = str(merged["generated_timestamp"])
    return merged


def _setup_packet_sidecar_path(path: Path) -> Path:
    return path.with_suffix(".json")


def _load_setup_packet_sidecar(path: Path) -> dict[str, object]:
    sidecar = _setup_packet_sidecar_path(path)
    try:
        raw = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_setup_packet_sidecar(path: Path, context) -> None:
    data = {
        "pdf_filename": path.name,
        "generated_timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "generated_at": context.generated_at,
        "machine": context.machine_id,
        "tool": context.tool_id,
        "eoat": context.eoat_id,
        "packet_type": context.packet_type_label,
        "photo_inclusion": context.photo_inclusion_label,
        "compatibility_status": context.validation.status,
        "manual_override_used": context.validation.manual_override_used,
        "source_summary": [f"{label}: {message}" for label, message, _path in context.source_files],
    }
    try:
        _setup_packet_sidecar_path(path).write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        return


def _parse_setup_packet_filename(path: Path) -> dict[str, str]:
    match = re.match(
        r"^EOAT_Setup_Packet__Tool_(?P<tool>.+?)__Machine_(?P<machine>.+?)__EOAT_(?P<eoat>.+?)__(?P<stamp>\d{8}_\d{4,6})\.pdf$",
        path.name,
    )
    if match:
        return match.groupdict()
    match = re.match(
        r"^Setup_Packet_Machine_(?P<machine>.+?)_Tool_(?P<tool>.+?)_EOAT_(?P<eoat>.+?)_(?P<stamp>\d{8}_\d{6})\.pdf$",
        path.name,
    )
    return match.groupdict() if match else {}


def _setup_packet_generated_time(path: Path, parsed: dict[str, object] | None = None) -> str:
    stamp = str((parsed or {}).get("stamp", ""))
    generated = str((parsed or {}).get("generated_timestamp", ""))
    if generated and not stamp:
        stamp = generated
    if stamp:
        time_part = stamp.split("_", 1)[1] if "_" in stamp else ""
        formats = ("%Y%m%d_%H%M",) if len(time_part) == 4 else ("%Y%m%d_%H%M%S", "%Y%m%d_%H%M")
        for fmt in formats:
            try:
                return datetime.strptime(stamp, fmt).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return "-"


def _format_file_size(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return "-"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _finalize_scroll_panel(scroll_area: QScrollArea, panel: QWidget, layout: QLayout) -> None:
    layout.invalidate()
    panel.adjustSize()
    panel.updateGeometry()
    panel.update()
    scroll_area.verticalScrollBar().setValue(0)
    scroll_area.horizontalScrollBar().setValue(0)
    scroll_area.viewport().update()


def _group_container(title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout]:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    title_label = QLabel(title)
    title_label.setObjectName("CardTitle")
    layout.addWidget(title_label)
    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("MutedText")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)
    return container, layout


class InstallPacketDialog(QDialog):
    def __init__(self, bundle: AtlasDataBundle, packet, parent=None):
        super().__init__(parent)
        self.bundle = bundle
        self.packet = packet
        self.export_path: Path | None = None
        self.setObjectName("InstallPacketDialog")
        self.setWindowTitle(packet.title)
        self.resize(900, 720)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = ProfileHeaderCard(packet.title, packet.subtitle, eyebrow="Install Packet")
        header.layout.addWidget(_chip_group(packet.summary_lines, kind="info", per_row=3, limit=8))
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)
        for section in packet.sections:
            card = PrimaryCard(section.title)
            card.layout.addWidget(key_value_grid(list(section.rows)))
            body_layout.addWidget(card)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        export_button = QPushButton("Export")
        export_button.setObjectName("PrimaryButton")
        export_button.clicked.connect(self.export)
        copy_button = QPushButton("Copy Summary")
        copy_button.clicked.connect(self.copy_summary)
        folder_button = QPushButton("Open Export Folder")
        folder_button.clicked.connect(lambda: open_path(atlas_export_dir(self.bundle.project_root)))
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(action_row(export_button, copy_button, folder_button, close_button))

    def export(self) -> None:
        self.export_path = export_install_packet(self.bundle, self.packet)
        self._status(f"Exported install packet: {self.export_path}")

    def copy_summary(self) -> None:
        QApplication.clipboard().setText(self.packet.markdown())
        self._status("Copied install packet summary.")

    def _status(self, message: str) -> None:
        controller = getattr(self.parent(), "controller", None)
        if controller is not None and hasattr(controller, "show_status"):
            controller.show_status(message)


class QRLabelPreviewDialog(QDialog):
    def __init__(self, bundle: AtlasDataBundle, eoat: EOATRecord, settings, parent=None):
        super().__init__(parent)
        self.bundle = bundle
        self.eoat = eoat
        self.settings = settings
        self.payload = build_eoat_qr_payload(eoat, mode=settings.qr_payload_mode)
        self.output_path: Path | None = None
        self.setObjectName("QRLabelPreviewDialog")
        self.setWindowTitle(f"QR Label - {eoat.eoat_id}")
        self.resize(860, 680)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        header = ProfileHeaderCard(f"QR Label: {eoat.eoat_id}", "Preview the exact encoded payload before exporting the label.", eyebrow="QR Codes")
        warning = qr_payload_warning(
            self.payload,
            mode=settings.qr_payload_mode,
            error_correction=settings.qr_error_correction,
        )
        header.layout.addWidget(
            _chip_group(
                [
                    f"{_qr_mode_display(settings.qr_payload_mode)} mode",
                    f"{len(self.payload)} payload chars",
                    f"{_qr_error_display(settings.qr_error_correction)} error correction",
                    f"{settings.qr_default_label_size.title()} label",
                    f"Min QR {recommended_qr_print_size(self.payload, error_correction=settings.qr_error_correction)}",
                    warning,
                ],
                kind="warn" if warning else "info",
                per_row=2,
                limit=6,
            )
        )
        validation_errors = validate_eoat_qr_payload(self.payload, mode=settings.qr_payload_mode, eoat_id=eoat.eoat_id)
        if validation_errors:
            header.layout.addWidget(_chip_group(validation_errors, kind="bad", per_row=1, limit=4))
        layout.addWidget(header)

        body = QHBoxLayout()
        self.preview_label = QLabel("QR label preview appears after Save / Export.")
        self.preview_label.setObjectName("PhotoThumb")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(420, 300)
        body.addWidget(self.preview_label, 1)

        payload_card = DetailCard("QR Payload", "Plain-text content stored inside the QR code.")
        self.payload_text = QTextEdit()
        self.payload_text.setReadOnly(True)
        self.payload_text.setPlainText(self.payload)
        self.payload_text.setMinimumHeight(210)
        self.payload_text.setToolTip("This is the exact text encoded in the QR code.")
        payload_card.layout.addWidget(self.payload_text)
        body.addWidget(payload_card, 1)
        layout.addLayout(body, 1)

        save_button = QPushButton("Save / Export")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self.generate)
        folder_button = QPushButton("Open Folder")
        folder_button.clicked.connect(self.open_folder)
        copy_button = QPushButton("Copy QR Payload")
        copy_button.clicked.connect(self.copy_payload)
        decode_button = QPushButton("Decode Generated QR")
        decode_button.clicked.connect(self.decode_generated_qr)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(action_row(save_button, folder_button, copy_button, decode_button, close_button))
        if not getattr(settings, "qr_show_payload_preview_before_export", True):
            self.generate()

    def generate(self) -> None:
        try:
            self.output_path = export_eoat_qr_label(
                self.bundle,
                self.eoat,
                payload_mode=self.settings.qr_payload_mode,
                error_correction=self.settings.qr_error_correction,
                label_size=self.settings.qr_default_label_size,
            )
        except (RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "QR Label", str(exc))
            return
        pixmap = QPixmap(str(self.output_path))
        if not pixmap.isNull():
            self.preview_label.setPixmap(
                pixmap.scaled(420, 300, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
            self.preview_label.setToolTip(str(self.output_path))
        self._status(f"Generated QR label: {self.output_path}")

    def open_folder(self) -> None:
        if self.output_path is not None:
            open_path(self.output_path.parent)
        else:
            open_path(atlas_export_dir(self.bundle.project_root) / "QR_Labels")

    def copy_payload(self) -> None:
        QApplication.clipboard().setText(self.payload)
        self._status("Copied QR payload.")

    def decode_generated_qr(self) -> None:
        if self.output_path is None:
            QMessageBox.information(self, "Decode QR", "Save / Export the label before decoding the generated QR image.")
            return
        decoded = decode_qr_payload_from_image(self.output_path)
        if decoded.payload == self.payload:
            QMessageBox.information(self, "Decode QR", "Decoded payload matches the preview exactly.")
            self._status("Decoded generated QR payload matches preview.")
            return
        QMessageBox.warning(
            self,
            "Decode QR",
            decoded.message or f"Decoded payload did not match preview.\nDecoded: {decoded.payload or '(empty)'}",
        )

    def _status(self, message: str) -> None:
        controller = getattr(self.parent(), "controller", None)
        if controller is not None and hasattr(controller, "show_status"):
            controller.show_status(message)


class CompareDialog(QDialog):
    def __init__(self, title: str, rows: list[dict[str, str]], columns: list[str], parent=None):
        super().__init__(parent)
        self.title_text = title
        self.rows = rows
        self.columns = columns
        self.setObjectName("CompareDialog")
        self.setWindowTitle(title)
        self.setSizeGripEnabled(True)
        self.resize(1080, 720)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        header = ProfileHeaderCard(title, "Grouped field comparison with visible difference badges.", eyebrow="Compare")
        header.layout.addWidget(_chip_group(columns, kind="info", per_row=4, limit=8))
        layout.addWidget(header)

        stats = _compare_stats(rows)
        summary = QWidget()
        summary_layout = QGridLayout(summary)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(8)
        for index, (label, value, kind) in enumerate(
            [
                ("Same fields", stats["same"], "good"),
                ("Different fields", stats["different"], "warn" if stats["different"] else "good"),
                ("Warning differences", stats["warnings"], "warn" if stats["warnings"] else "good"),
                ("Fit Check differences", stats["compatibility"], "warn" if stats["compatibility"] else "good"),
            ]
        ):
            summary_layout.addWidget(CompactStatCard(label, str(value), kind=kind), 0, index)
        layout.addWidget(summary)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        for category, category_rows in _group_compare_rows(rows):
            card = DetailCard(category or "Comparison", "Different rows are highlighted with status badges.")
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(7)
            header_labels = ["Field", *columns, "Difference"]
            for column_index, label in enumerate(header_labels):
                header_label = QLabel(label)
                header_label.setObjectName("MetricLabel")
                grid.addWidget(header_label, 0, column_index)
            for row_index, row in enumerate(category_rows, start=1):
                _add_compare_row(grid, row_index, row, columns)
            grid.setColumnStretch(1, 1)
            card.layout.addLayout(grid)
            content_layout.addWidget(card)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        self.table = QTableWidget()
        self.table.setObjectName("CompareHiddenTable")
        fill_table(self.table, rows, ["Category", "Field", *columns, "Difference"])
        self.table.hide()

        copy_button = QPushButton("Copy Comparison")
        copy_button.clicked.connect(self.copy_comparison)
        export_button = QPushButton("Export Comparison")
        export_button.clicked.connect(self.export_comparison)
        export_button.setEnabled(_compare_export_root(self) is not None)
        open_a = QPushButton(_open_compare_label(title, 0))
        open_a.setEnabled(len(columns) >= 1)
        open_a.clicked.connect(lambda: self.open_compared_record(0))
        open_b = QPushButton(_open_compare_label(title, 1))
        open_b.setEnabled(len(columns) >= 2)
        open_b.clicked.connect(lambda: self.open_compared_record(1))
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(action_row(close_button, copy_button, export_button, open_a, open_b))

    def copy_comparison(self) -> None:
        QApplication.clipboard().setText(_compare_text(self.title_text, self.rows, self.columns))

    def export_comparison(self) -> None:
        project_root = _compare_export_root(self)
        if project_root is None:
            return
        path = export_compare_summary(project_root, self.title_text, self.rows, self.columns)
        parent = self.parent()
        controller = getattr(parent, "controller", None)
        if controller is not None and hasattr(controller, "show_status"):
            controller.show_status(f"Exported comparison: {path}")

    def open_compared_record(self, index: int) -> None:
        if index >= len(self.columns):
            return
        parent = self.parent()
        controller = getattr(parent, "controller", None)
        if controller is None:
            return
        value = self.columns[index]
        target = value.replace("Tool ", "", 1).replace("Machine ", "", 1).strip()
        if "tool" in self.title_text.casefold() and hasattr(controller, "open_tool"):
            controller.open_tool(target)
        elif "machine" in self.title_text.casefold() and hasattr(controller, "open_machine"):
            controller.open_machine(target)
        elif hasattr(controller, "open_eoat"):
            controller.open_eoat(target)


def _compare_stats(rows: list[dict[str, str]]) -> dict[str, int]:
    stats = {"same": 0, "different": 0, "warnings": 0, "compatibility": 0}
    for row in rows:
        difference = row.get("Difference", "Same")
        if difference == "Same":
            stats["same"] += 1
            continue
        stats["different"] += 1
        category = row.get("Category", "").casefold()
        if "warning" in category:
            stats["warnings"] += 1
        if "compat" in category:
            stats["compatibility"] += 1
    return stats


def _group_compare_rows(rows: list[dict[str, str]]) -> list[tuple[str, list[dict[str, str]]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    order: list[str] = []
    for row in rows:
        category = row.get("Category", "Comparison")
        if category not in grouped:
            grouped[category] = []
            order.append(category)
        grouped[category].append(row)
    return [(category, grouped[category]) for category in order]


def _add_compare_row(grid: QGridLayout, row_index: int, row: dict[str, str], columns: list[str]) -> None:
    field = QLabel(row.get("Field", "-"))
    field.setObjectName("BodyText")
    field.setWordWrap(True)
    grid.addWidget(field, row_index, 0)
    quiet = row.get("Difference") == "Same"
    for column_index, column in enumerate(columns, start=1):
        value = QLabel(row.get(column, "-") or "-")
        value.setObjectName("MutedText" if quiet else "BodyText")
        value.setWordWrap(True)
        value.setToolTip(row.get(column, ""))
        grid.addWidget(value, row_index, column_index)
    difference = row.get("Difference", "Same") or "Same"
    grid.addWidget(badge(difference, _compare_status_kind(difference)), row_index, len(columns) + 1)


def _compare_status_kind(status: str) -> str:
    folded = status.casefold()
    if "same" in folded:
        return "good"
    if "missing" in folded or "warning" in folded:
        return "warn"
    return "bad"


def _compare_text(title: str, rows: list[dict[str, str]], columns: list[str]) -> str:
    lines = [title, ""]
    for category, category_rows in _group_compare_rows(rows):
        lines.extend([category, "-" * len(category)])
        for row in category_rows:
            values = " | ".join(f"{column}: {row.get(column, '-') or '-'}" for column in columns)
            lines.append(f"{row.get('Field', '-')}: {values} [{row.get('Difference', 'Same') or 'Same'}]")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _compare_export_root(dialog: CompareDialog) -> str | None:
    parent = dialog.parent()
    bundle = getattr(parent, "bundle", None)
    if bundle is None:
        controller = getattr(parent, "controller", None)
        bundle = getattr(controller, "bundle", None)
    return getattr(bundle, "project_root", None)


def _open_compare_label(title: str, index: int) -> str:
    suffix = "A" if index == 0 else "B"
    folded = title.casefold()
    if "tool" in folded:
        return f"Open Tool {suffix}"
    if "machine" in folded:
        return f"Open Machine {suffix}"
    return f"Open EOAT {suffix}"



PAGE_KEY_LABELS = {
    "home": "Home / Command Deck",
    "what": "What Do I Need?",
    "setup_packet": "Changeover Packet Builder",
    "eoats": "EOAT Profiles",
    "machines": "Machine Profiles",
    "tools": "Tool / Mold / Part",
    "matrix": "Fit Check",
    "overview": "Analytics Dashboard",
    "photos": "Photos",
    "standards": "Standards & Work Instructions",
    "pm": "PM / Inspection",
    "library": "Information Library",
    "reports": "Reports & Handoff",
    "diagnostics": "Settings / Diagnostics",
}


def _settings_combo(labels: list[str]) -> QComboBox:
    combo = QComboBox()
    combo.addItems(labels)
    combo.setMinimumWidth(150)
    combo.setMaximumWidth(320)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return combo


def _collapsible_card(title: str, subtitle: str, *, checked: bool = False) -> tuple[QWidget, QWidget]:
    section = AccordionSection(title, subtitle, expanded=checked)
    return section, section.body


def _add_settings_rows(grid: QGridLayout, rows: list[tuple[str, QWidget]]) -> None:
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(8)
    for index, (label, widget) in enumerate(rows):
        label_widget = QLabel(label)
        label_widget.setObjectName("MetricLabel")
        grid.addWidget(label_widget, index // 2 * 2, (index % 2) * 2)
        grid.addWidget(widget, index // 2 * 2 + 1, (index % 2) * 2)
    for column in range(4):
        grid.setColumnStretch(column, 1 if column % 2 else 0)


def _settings_check(tooltip: str) -> QCheckBox:
    checkbox = QCheckBox("Enabled")
    checkbox.setToolTip(tooltip)
    checkbox.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return checkbox


def _theme_value(label: str) -> str:
    folded = label.casefold()
    if "dark" in folded:
        return "dark"
    if "system" in folded:
        return "system"
    return "light"


def _color_scheme_value(label: str) -> str:
    folded = label.casefold()
    if "nolato" in folded:
        return "nolato_logo"
    if "graphite" in folded:
        return "industrial_graphite"
    if "aurora" in folded:
        return "aurora_tech"
    return "atlas_blue"


def _photo_preload_value(label: str) -> str:
    folded = label.casefold()
    if "off" in folded:
        return "off"
    if "aggressive" in folded:
        return "aggressive"
    if "balanced" in folded:
        return "balanced"
    return "conservative"


def _photo_behavior_value(label: str) -> str:
    folded = label.casefold()
    if "folder" in folded:
        return "open_folder"
    if "external" in folded:
        return "external"
    return "in_app"


def _qr_payload_value(label: str) -> str:
    folded = label.casefold()
    if "deep" in folded:
        return "deep_link"
    if "json" in folded:
        return "json"
    if "full" in folded:
        return "full"
    return "compact"


def _qr_mode_display(mode: str) -> str:
    folded = str(mode or "compact").casefold().replace("-", "_").replace(" ", "_")
    if folded in {"deep_link", "deeplink", "atlas_deep_link"}:
        return "Atlas Deep Link"
    if folded in {"json", "json_record"}:
        return "JSON Record"
    if folded == "full":
        return "Full Offline Record"
    return "Compact Human-Readable Text"


def _setup_packet_type_value(label: str) -> str:
    folded = label.casefold()
    if "verification" in folded:
        return "setup_verification"
    if "maintenance" in folded or "pm" in folded:
        return "maintenance_pm"
    if "documentation" in folded:
        return "documentation_review"
    return "standard_changeover"


def _setup_packet_type_display(value: str) -> str:
    folded = str(value or "").casefold()
    if "verification" in folded:
        return "Setup Verification Packet"
    if "maintenance" in folded or folded == "pm":
        return "Maintenance / PM Packet"
    if "documentation" in folded:
        return "Documentation Review Packet"
    return "Standard Changeover Packet"


def _setup_packet_photo_value(label: str) -> str:
    folded = label.casefold()
    if "no" in folded:
        return "none"
    if "all" in folded:
        return "all"
    return "key"


def _setup_packet_photo_display(value: str) -> str:
    folded = str(value or "").casefold()
    if folded in {"none", "no_photos"}:
        return "No photos"
    if folded in {"all", "all_photos"}:
        return "All photos"
    return "Key photos only"


def _setup_packet_open_value(label: str) -> str:
    folded = label.casefold()
    if "external" in folded:
        return "external_pdf"
    if "folder" in folded:
        return "open_folder"
    if "app" in folded:
        return "in_app"
    return "ask_each_time"


def _setup_packet_open_display(value: str) -> str:
    folded = str(value or "").casefold()
    if "external" in folded:
        return "External PDF viewer"
    if "folder" in folded:
        return "Open folder"
    if "app" in folded:
        return "In app"
    return "Ask each time"


def _qr_error_value(label: str) -> str:
    folded = label.casefold()
    if folded.startswith("l"):
        return "low"
    if folded.startswith("m"):
        return "medium"
    if folded.startswith("q"):
        return "quartile"
    return "high"


def _qr_error_display(value: str) -> str:
    folded = str(value or "high").casefold()
    if folded.startswith("l"):
        return "Low"
    if folded.startswith("m"):
        return "Medium"
    if folded.startswith("q"):
        return "Quartile"
    return "High"


def _page_key_for_label(label: str) -> str:
    for key, value in PAGE_KEY_LABELS.items():
        if value == label:
            return key
    return "home"


def _label_for_page_key(key: str) -> str:
    return PAGE_KEY_LABELS.get(key, PAGE_KEY_LABELS["home"])


def _eoat_list_label(eoat: EOATRecord) -> str:
    tools = ", ".join(eoat.tools[:2]) or "No tool"
    machines = ", ".join(eoat.machines[:3]) or "No machine"
    return f"{eoat.eoat_id}\n{tools} -> {machines}\n{eoat.eoat_type or 'Type missing'} | {eoat.documentation.score}% docs | {eoat.warning_count} warnings"


def _eoat_tile_subtitle(eoat: EOATRecord) -> str:
    tools = ", ".join(f"Tool {tool}" for tool in eoat.tools[:2]) if eoat.tools else "Tool missing"
    descriptor = _first_present(eoat.part_description, eoat.part_family, eoat.eoat_type, "No part description")
    return f"{tools} - {_short_label(descriptor, 58)}"


def _machine_list_label(machine: MachineRecord) -> str:
    robot = machine.robot_type or machine.robot_model or "Robot info missing"
    eoats = ", ".join(machine.compatible_eoats[:3]) or "No compatible EOATs"
    return f"Machine {machine.machine}\n{robot}\n{len(machine.compatible_eoats)} EOATs | {len(machine.compatible_tools)} tools | {eoats}"


def _sectioned_eoats(rows: list[EOATRecord], settings) -> list[tuple[str, list[EOATRecord]]]:
    return _sectioned_records(
        rows,
        pinned=settings.pinned_eoats,
        recent=settings.recent_eoats,
        key=lambda record: normalized_eoat_key(record.eoat_id),
        normalize=normalized_eoat_key,
        labels=("Pinned", "Recently Viewed", "All EOATs"),
    )


def _sectioned_machines(rows: list[MachineRecord], settings) -> list[tuple[str, list[MachineRecord]]]:
    return _sectioned_records(
        rows,
        pinned=settings.pinned_machines,
        recent=settings.recent_machines,
        key=lambda record: normalized_machine_key(record.machine),
        normalize=normalized_machine_key,
        labels=("Pinned", "Recently Viewed", "All Machines"),
    )


def _sectioned_tools(rows: list[ToolRecord], settings) -> list[tuple[str, list[ToolRecord]]]:
    return _sectioned_records(
        rows,
        pinned=settings.pinned_tools,
        recent=settings.recent_tools,
        key=lambda record: normalized_tool_key(record.tool),
        normalize=normalized_tool_key,
        labels=("Pinned", "Recently Viewed", "All Tools"),
    )


def _tool_navigation_sections(rows: list[ToolRecord], settings) -> list[tuple[str, list[ToolRecord]]]:
    by_key = {normalized_tool_key(tool.tool): tool for tool in rows}
    recent = [
        by_key[key]
        for key in _normalized_keys(getattr(settings, "recent_tools", ()), normalized_tool_key)
        if key in by_key
    ]
    sections: list[tuple[str, list[ToolRecord]]] = []
    if recent:
        sections.append(("Recently Viewed / Selected", recent))
    sections.append(("All Tools", rows))
    machines = sorted({machine for tool in rows for machine in tool.compatible_machines}, key=_natural_sort_key)
    for machine in machines:
        sections.append((f"By Machine - Machine {machine}", [tool for tool in rows if machine in tool.compatible_machines]))
    sections.extend(
        [
            ("By EOAT Link Status - Linked EOATs", [tool for tool in rows if not _tool_missing_eoat_link(tool)]),
            ("By EOAT Link Status - Missing EOAT Link", [tool for tool in rows if _tool_missing_eoat_link(tool)]),
            ("By Warning Status - No warnings", [tool for tool in rows if not tool.warning_count]),
            ("By Warning Status - Has warnings", [tool for tool in rows if tool.warning_count]),
        ]
    )
    for source in sorted({tool.source or "Atlas cached index" for tool in rows}, key=str.casefold):
        sections.append((f"By Source - {source}", [tool for tool in rows if (tool.source or "Atlas cached index") == source]))
    return sections


def _tool_missing_eoat_link(tool: ToolRecord) -> bool:
    return not bool(tool.compatible_eoats)


def _exact_machine_filter_key(query: str) -> str:
    text = str(query or "").strip()
    if re.fullmatch(r"[1-9]\d*", text):
        return normalized_machine_key(text)
    match = re.fullmatch(r"(?:machine|press|m|p)\s*[-#:]*\s*(\d+)", text, flags=re.IGNORECASE)
    return normalized_machine_key(match.group(1)) if match else ""


def _tool_search_rank(tool: ToolRecord, query: str) -> int:
    text = re.sub(r"^(tool|mold|part)\s*[-#:]*\s*", "", str(query or "").strip(), flags=re.IGNORECASE).strip()
    if not text:
        return 1
    query_key = normalized_tool_key(text)
    identifiers = [tool.tool, *tool.molds, *tool.parts]
    identifier_keys = [normalized_tool_key(value) for value in identifiers if normalized_tool_key(value)]
    if query_key and any(query_key == value for value in identifier_keys):
        return 100
    if query_key and any(value.startswith(query_key) for value in identifier_keys):
        return 85
    haystack = " ".join(
        [
            tool.tool,
            f"Tool {tool.tool}",
            tool.part_description,
            tool.part_family,
            " ".join(tool.parts),
            " ".join(tool.molds),
            " ".join(tool.compatible_eoats),
            " ".join(tool.compatible_machines),
        ]
    ).casefold()
    if text.isdigit() and len(text) <= 3:
        return 0
    return 40 if str(query or "").strip().casefold() in haystack or text.casefold() in haystack else 0


def _eoat_search_rank(eoat: EOATRecord, query: str) -> int:
    text = re.sub(r"^eoat\s*[-#:]*\s*", "", str(query or "").strip(), flags=re.IGNORECASE).strip()
    if not text:
        return 1
    query_key = normalized_eoat_key(text)
    eoat_key = normalized_eoat_key(eoat.eoat_id)
    if query_key and query_key == eoat_key:
        return 100
    suffix = _eoat_numeric_suffix(eoat.eoat_id)
    if text.isdigit() and suffix and int(text) == int(suffix):
        return 95 if len(text) == len(suffix) else 90
    haystack = " ".join(
        [
            eoat.eoat_id,
            eoat.eoat_type,
            eoat.status,
            " ".join(eoat.tools),
            " ".join(eoat.machines),
            eoat.part_description,
            eoat.part_family,
        ]
    ).casefold()
    return 40 if str(query or "").strip().casefold() in haystack or text.casefold() in haystack else 0


def _eoat_numeric_suffix(value: str) -> str:
    match = re.search(r"(\d{1,4})$", normalized_eoat_key(value))
    return f"{int(match.group(1)):04d}" if match else ""


def _health_item_colors(health: RelationshipHealth, *, selected: bool = False) -> tuple[QColor, QColor]:
    if selected:
        return QColor("#dbeafe"), QColor("#172033")
    return {
        RelationshipHealth.VERIFIED: (QColor("#ecfdf3"), QColor("#087f5b")),
        RelationshipHealth.REVIEW: (QColor("#fff7e6"), QColor("#9a5a00")),
        RelationshipHealth.MISSING: (QColor("#fff1f1"), QColor("#a61b1b")),
        RelationshipHealth.INVALID: (QColor("#fee2e2"), QColor("#991b1b")),
        RelationshipHealth.UNKNOWN: (QColor("#eef4fb"), QColor("#3d5a78")),
    }.get(health, (QColor("#eef4fb"), QColor("#3d5a78")))


def build_analytics_snapshot(bundle: AtlasDataBundle) -> dict[str, object]:
    doc_scores = [eoat.documentation.score for eoat in bundle.eoats]
    avg_docs = round(sum(doc_scores) / max(len(doc_scores), 1))
    doc_bins = {label: 0 for label in ("0-49%", "50-74%", "75-89%", "90-100%")}
    for score in doc_scores:
        doc_bins[_doc_bucket(score)] += 1
    eoat_type_counts = Counter(_eoat_type_bucket(eoat.eoat_type) for eoat in bundle.eoats)
    eoat_status_counts = Counter(_eoat_status_bucket(eoat.status) for eoat in bundle.eoats)
    photo_by_type: dict[str, list[int]] = {}
    for eoat in bundle.eoats:
        photo_by_type.setdefault(_eoat_type_bucket(eoat.eoat_type), []).append(eoat.photo_count)
    photo_coverage_by_type = {
        key: round(sum(values) / max(len(values), 1), 1)
        for key, values in sorted(photo_by_type.items(), key=lambda item: item[0])
    }
    warnings_by_category = Counter(_warning_category(warning) for warning in _all_atlas_warnings(bundle))
    for category in ("Fit Check", "EOAT Inventory", "Machine / Robot", "Press Capacity", "Photos", "Documentation"):
        warnings_by_category.setdefault(category, 0)
    top_warning_machines = {
        f"Machine {machine.machine}": machine.warning_count
        for machine in sorted(bundle.machines, key=lambda item: (-item.warning_count, _natural_sort_key(item.machine)))[:10]
        if machine.warning_count
    }
    tools_missing_eoat = [tool for tool in bundle.tools if not tool.compatible_eoats]
    tools_missing_chart = {
        tool.tool: max(1, len(tool.compatible_machines))
        for tool in sorted(tools_missing_eoat, key=lambda item: (-len(item.compatible_machines), item.tool.casefold()))[:10]
    }
    standards_summary = Counter({"OK": 0, "Review": 0, "Missing": 0})
    for eoat in bundle.eoats:
        if not eoat.standards:
            standards_summary["Missing"] += 1
            continue
        statuses = [_standard_status_for_eoat(standard, eoat)[0].casefold() for standard in eoat.standards]
        if any("missing" in status for status in statuses):
            standards_summary["Missing"] += 1
        elif any("review" in status for status in statuses):
            standards_summary["Review"] += 1
        else:
            standards_summary["OK"] += 1
    highest_warning_records = _highest_warning_records(bundle)
    machine_health_tiles = tuple(
        (machine.machine, machine_relationship_health(machine), machine.warning_count)
        for machine in sorted(bundle.machines, key=lambda item: _natural_sort_key(item.machine))
    )
    coverage_metrics = {
        "eoat_coverage": len([eoat for eoat in bundle.eoats if eoat.tools or eoat.machines]),
        "eoat_total": len(bundle.eoats),
        "machine_coverage": len([machine for machine in bundle.machines if machine.compatible_eoats or machine.compatible_tools]),
        "machine_total": len(bundle.machines),
        "tool_coverage": len([tool for tool in bundle.tools if tool.compatible_eoats or tool.compatible_machines]),
        "tool_total": len(bundle.tools),
        "average_documentation": avg_docs,
        "eoats_missing_photos": len([eoat for eoat in bundle.eoats if eoat.photo_count <= 0]),
        "tools_missing_validated_eoat": len(tools_missing_eoat),
        "machines_needing_review": len([machine for machine in bundle.machines if machine_relationship_health(machine) != RelationshipHealth.VERIFIED]),
        "highest_warning_records": len(highest_warning_records),
    }
    return {
        "coverage_metrics": coverage_metrics,
        "documentation_bins": doc_bins,
        "eoat_type_counts": dict(eoat_type_counts),
        "eoat_status_counts": dict(eoat_status_counts),
        "photo_coverage_by_type": photo_coverage_by_type,
        "warnings_by_category": dict(warnings_by_category),
        "top_warning_machines": top_warning_machines,
        "tools_missing_validated_eoat": tools_missing_chart,
        "standards_compliance_summary": dict(standards_summary),
        "machine_health_tiles": machine_health_tiles,
        "highest_warning_records": tuple(highest_warning_records),
    }


def _analytics_metric_cards(snapshot: dict[str, object]) -> list[QWidget]:
    metrics = snapshot["coverage_metrics"]
    return [
        MetricCard("EOAT Coverage", f"{metrics['eoat_coverage']} / {metrics['eoat_total']}", "Records with tool or machine links", kind="primary"),
        MetricCard("Machine Coverage", f"{metrics['machine_coverage']} / {metrics['machine_total']}", "Machines with EOAT/tool links", kind="primary"),
        MetricCard("Tool Coverage", f"{metrics['tool_coverage']} / {metrics['tool_total']}", "Tools with EOAT or machine links", kind="primary"),
        MetricCard("Avg Documentation Score", f"{metrics['average_documentation']}%", "EOAT profile completeness", kind="good" if metrics["average_documentation"] >= 80 else "warn"),
        MetricCard("EOATs Missing Photos", str(metrics["eoats_missing_photos"]), "Photo evidence gaps", kind="bad" if metrics["eoats_missing_photos"] else "good"),
        MetricCard("Tools Missing Validated EOAT", str(metrics["tools_missing_validated_eoat"]), "Tool records with no EOAT link", kind="bad" if metrics["tools_missing_validated_eoat"] else "good"),
        MetricCard("Machines Needing Review", str(metrics["machines_needing_review"]), "Missing/review health state", kind="warn" if metrics["machines_needing_review"] else "good"),
        MetricCard("Highest Warning Records", str(metrics["highest_warning_records"]), "Records listed below", kind="warn" if metrics["highest_warning_records"] else "good"),
    ]


def _qt_bar_chart(values: dict[str, int | float], *, axis_title: str = "Count") -> QWidget:
    if not values or QChart is None or QChartView is None or QBarSeries is None or QBarSet is None:
        return EmptyStateWidget("No chart data", "Atlas did not find rows for this chart.")
    ordered = list(values.items())
    bar_set = QBarSet(axis_title)
    for _label, value in ordered:
        bar_set.append(float(value))
    bar_set.setColor(QColor("#2f80ed"))
    series = QBarSeries()
    series.append(bar_set)
    chart = _base_chart()
    chart.addSeries(series)
    axis_x = QBarCategoryAxis()
    axis_x.append([str(label) for label, _value in ordered])
    axis_y = QValueAxis()
    axis_y.setRange(0, max(float(value) for _label, value in ordered) * 1.15 or 1)
    axis_y.setTitleText(axis_title)
    chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
    chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
    series.attachAxis(axis_x)
    series.attachAxis(axis_y)
    return _chart_view(chart)


def _qt_horizontal_bar_chart(values: dict[str, int | float], *, axis_title: str = "Count", limit: int = 10) -> QWidget:
    if not values or QChart is None or QChartView is None or QHorizontalBarSeries is None or QBarSet is None:
        return EmptyStateWidget("No chart data", "Atlas did not find rows for this chart.")
    ordered = sorted(values.items(), key=lambda item: (-float(item[1]), str(item[0]).casefold()))[:limit]
    bar_set = QBarSet(axis_title)
    for _label, value in ordered:
        bar_set.append(float(value))
    bar_set.setColor(QColor("#4f78a3"))
    series = QHorizontalBarSeries()
    series.append(bar_set)
    chart = _base_chart()
    chart.addSeries(series)
    axis_y = QBarCategoryAxis()
    axis_y.append([_short_label(str(label), 22) for label, _value in ordered])
    axis_x = QValueAxis()
    axis_x.setRange(0, max(float(value) for _label, value in ordered) * 1.15 or 1)
    axis_x.setTitleText(axis_title)
    chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
    chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
    series.attachAxis(axis_y)
    series.attachAxis(axis_x)
    return _chart_view(chart)


def _qt_donut_chart(values: dict[str, int | float]) -> QWidget:
    nonzero = {label: value for label, value in values.items() if float(value)}
    if not nonzero or QChart is None or QChartView is None or QPieSeries is None:
        return EmptyStateWidget("No chart data", "Atlas did not find rows for this chart.")
    series = QPieSeries()
    series.setHoleSize(0.42)
    colors = ["#2f80ed", "#087f5b", "#f59e0b", "#dc2626", "#7c6ee6", "#3d6f8f"]
    for index, (label, value) in enumerate(sorted(nonzero.items(), key=lambda item: (-float(item[1]), str(item[0]).casefold()))):
        slice_item = series.append(f"{label} ({value:g})", float(value))
        slice_item.setBrush(QColor(colors[index % len(colors)]))
        slice_item.setLabelVisible(True)
    chart = _base_chart()
    chart.addSeries(series)
    chart.legend().setVisible(True)
    chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
    return _chart_view(chart)


def _base_chart():
    chart = QChart()
    chart.setBackgroundBrush(QColor("#ffffff"))
    chart.setPlotAreaBackgroundBrush(QColor("#ffffff"))
    chart.setPlotAreaBackgroundVisible(True)
    chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
    chart.legend().setVisible(False)
    chart.setMargins(QMargins(4, 4, 4, 4))
    return chart


def _chart_view(chart) -> QWidget:
    view = QChartView(chart)
    view.setRenderHint(QPainter.RenderHint.Antialiasing)
    view.setMinimumHeight(220)
    view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return view


def _machine_health_grid(rows: tuple[tuple[str, RelationshipHealth, int], ...]) -> QWidget:
    widget = QWidget()
    layout = QGridLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(6)
    layout.setVerticalSpacing(6)
    if not rows:
        layout.addWidget(EmptyStateWidget("No machine data", "Atlas has not indexed machine records yet."))
        return widget
    columns = 12
    for index, (machine, health, warning_count) in enumerate(rows[:240]):
        label = QLabel(str(machine))
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setObjectName("MachineHealthTile")
        background, foreground = _health_item_colors(health)
        label.setStyleSheet(
            f"background:{background.name()}; color:{foreground.name()}; border:1px solid {foreground.name()}; border-radius:6px; padding:5px; font-weight:800;"
        )
        label.setToolTip(f"Machine {machine}: {health_label(health)} | {warning_count} warning(s)")
        layout.addWidget(label, index // columns, index % columns)
    return widget


def _doc_bucket(score: int) -> str:
    if score >= 90:
        return "90-100%"
    if score >= 75:
        return "75-89%"
    if score >= 50:
        return "50-74%"
    return "0-49%"


def _eoat_type_bucket(value: str) -> str:
    text = str(value or "").casefold()
    if "hybrid" in text:
        return "Hybrid"
    if "grip" in text or "mechanical" in text:
        return "Mechanical / Gripper"
    if "vacuum" in text or "cup" in text:
        return "Vacuum"
    return "Miscellaneous"


def _eoat_status_bucket(value: str) -> str:
    text = str(value or "").casefold()
    if any(token in text for token in ("complete", "ready", "active", "audited")):
        return "Complete"
    if any(token in text for token in ("progress", "pilot", "candidate")):
        return "In Progress"
    if any(token in text for token in ("review", "follow", "maybe", "cleanup")):
        return "Review"
    return "Missing"


def _warning_category(warning: WarningItem) -> str:
    text = f"{warning.source} {warning.title}".casefold()
    if "photo" in text:
        return "Photos"
    if "doc" in text or "field" in text:
        return "Documentation"
    if "press" in text or "capacity" in text:
        return "Press Capacity"
    if "inventory" in text or "tracker" in text or "eoat" in text:
        return "EOAT Inventory"
    if "machine" in text or "robot" in text:
        return "Machine / Robot"
    if "tool" in text or "compat" in text:
        return "Fit Check"
    return "Documentation"


def _all_atlas_warnings(bundle: AtlasDataBundle) -> list[WarningItem]:
    warnings = list(bundle.warnings)
    for eoat in bundle.eoats:
        warnings.extend(eoat.warnings)
    for machine in bundle.machines:
        warnings.extend(machine.warnings)
    for tool in bundle.tools:
        warnings.extend(tool.warnings)
    return warnings


def _highest_warning_records(bundle: AtlasDataBundle) -> list[str]:
    rows: list[tuple[int, str]] = []
    rows.extend((eoat.warning_count, f"{eoat.eoat_id}: {eoat.warning_count}") for eoat in bundle.eoats if eoat.warning_count)
    rows.extend((machine.warning_count, f"Machine {machine.machine}: {machine.warning_count}") for machine in bundle.machines if machine.warning_count)
    rows.extend((tool.warning_count, f"Tool {tool.tool}: {tool.warning_count}") for tool in bundle.tools if tool.warning_count)
    return [label for _count, label in sorted(rows, key=lambda item: (-item[0], item[1].casefold()))[:18]]


def _current_record_value(controller, record_type: str) -> str:
    pages = getattr(controller, "pages", {})
    if record_type == "machine":
        record = getattr(pages.get("machines"), "current", None)
        return getattr(record, "machine", "") or ""
    if record_type == "tool":
        record = getattr(pages.get("tools"), "current_tool", None)
        return getattr(record, "tool", "") or ""
    if record_type == "eoat":
        record = getattr(pages.get("eoats"), "current", None)
        return getattr(record, "eoat_id", "") or ""
    return ""


def _sectioned_records(rows, *, pinned, recent, key, normalize, labels: tuple[str, str, str]):
    by_key = {key(record): record for record in rows}
    pinned_rows = [by_key[item_key] for item_key in _normalized_keys(pinned, normalize) if item_key in by_key]
    pinned_keys = {key(record) for record in pinned_rows}
    recent_rows = [
        by_key[item_key]
        for item_key in _normalized_keys(recent, normalize)
        if item_key in by_key and item_key not in pinned_keys
    ]
    used = pinned_keys | {key(record) for record in recent_rows}
    all_rows = [record for record in rows if key(record) not in used]
    return [(labels[0], pinned_rows), (labels[1], recent_rows), (labels[2], all_rows)]


def _normalized_keys(values, normalize) -> list[str]:
    return [normalize(value) for value in values if normalize(value)]


def _contains_id(values, target: str) -> bool:
    folded = str(target or "").casefold()
    return bool(folded and any(str(value).casefold() == folded for value in values))


def _relationship_map_card(title: str, subtitle: str = "") -> CompatibilityCard:
    return CompatibilityCard(title, subtitle or "Compact relationship map from cached Atlas indexes.")


def _flow_arrow() -> QLabel:
    label = QLabel("->")
    label.setObjectName("MutedText")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def _eoat_relationship_map(eoat: EOATRecord) -> QWidget:
    card = _relationship_map_card("Relationship Map", "Tool -> EOAT -> Machine with evidence nodes.")
    health = eoat_relationship_health(eoat)
    card.layout.addWidget(badge(f"Relationship health: {health_label(health)}", health_badge_kind(health)))
    for tool in list(eoat.tools[:3]) or [""]:
        card.layout.addWidget(CompatibilityPathWidget(tool, eoat.eoat_id, eoat.machines[:8]))
    if len(eoat.tools) > 3:
        card.layout.addWidget(badge(f"+{len(eoat.tools) - 3} more tool(s)", "count"))
    card.layout.addWidget(
        _labeled_chips(
            "Robot / evidence",
            [
                _first_present(", ".join(eoat.robot_models), ", ".join(eoat.robot_types), "Robot info missing"),
                f"{eoat.photo_count} photo(s)",
                f"{len(eoat.standards)} applicable standards",
            ],
            kind="outline",
            per_row=3,
        )
    )
    if not eoat.tools or not eoat.machines:
        card.layout.addWidget(_chip_group(["Missing compatibility link"], kind="warn", per_row=3))
    return card


def _machine_relationship_map(machine: MachineRecord) -> QWidget:
    card = _relationship_map_card("Relationship Map", "Machine -> compatible EOATs -> tools.")
    health = machine_relationship_health(machine)
    card.layout.addWidget(badge(f"Relationship health: {health_label(health)}", health_badge_kind(health)))
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.addWidget(badge(f"Machine {machine.machine}", health_badge_kind(health)))
    layout.addWidget(_relationship_arrow())
    layout.addWidget(_chip_group(machine.compatible_eoats, kind="primary", empty="No compatible EOATs", per_row=4, limit=8))
    layout.addWidget(_relationship_arrow())
    layout.addWidget(_chip_group(machine.compatible_tools, kind="outline", empty="No linked tools", per_row=4, limit=8))
    layout.addStretch(1)
    card.layout.addWidget(row)
    card.layout.addWidget(
        _labeled_chips(
            "Robot context",
            [_first_present(machine.robot_type, machine.robot_model, "Robot info missing"), machine.controller],
            kind="outline",
            per_row=3,
        )
    )
    return card


def _tool_relationship_map(tool: ToolRecord) -> QWidget:
    card = _relationship_map_card("Relationship Map", "Tool -> EOAT -> machine summary.")
    health = tool_relationship_health(tool)
    card.layout.addWidget(badge(f"Relationship health: {health_label(health)}", health_badge_kind(health)))
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.addWidget(badge(f"Tool {tool.tool}", health_badge_kind(health)))
    layout.addWidget(_relationship_arrow())
    layout.addWidget(_chip_group(tool.compatible_eoats, kind="primary", empty="Missing EOAT link", per_row=4, limit=8))
    layout.addWidget(_relationship_arrow())
    layout.addWidget(_chip_group(tool.compatible_machines, kind="outline", empty="No linked machines", per_row=4, limit=8))
    layout.addStretch(1)
    card.layout.addWidget(row)
    if not tool.compatible_eoats:
        card.layout.addWidget(_chip_group(["No linked EOAT"], kind="bad", per_row=3))
    return card


def _eoat_compare_rows(records: list[EOATRecord]) -> list[dict[str, str]]:
    specs = [
        ("Identity", "EOAT ID", lambda item: item.eoat_id),
        ("Identity", "Type", lambda item: item.eoat_type),
        ("Identity", "Status", lambda item: item.status),
        ("Fit Check", "Compatible tools", lambda item: _join_values(item.tools)),
        ("Fit Check", "Compatible machines", lambda item: _join_values(item.machines)),
        ("Fit Check", "Robot / machine compatibility", lambda item: _join_values((*item.robot_types, *item.robot_models))),
        ("Readiness", "Documentation score", lambda item: f"{item.documentation.score}%"),
        ("Readiness", "Photo count", lambda item: str(item.photo_count)),
        ("Readiness", "Missing photo categories", lambda item: _join_values(item.photos.missing_categories)),
        ("Warnings", "Warnings", lambda item: str(item.warning_count)),
        ("Warnings", "Known issues", lambda item: item.known_issues),
        ("Setup", "Connection type", lambda item: item.connection_type),
        ("Setup", "Pneumatic / vacuum", lambda item: _first_present(item.vacuum_info, item.pressure_info)),
        ("Setup", "Gripper info", lambda item: item.gripper_info),
        ("Setup", "Sensor info", lambda item: item.sensor_info),
        ("References", "Standards references", lambda item: _join_values(standard.title for standard in item.standards)),
    ]
    return _compare_rows(records, [record.eoat_id for record in records], specs)


def _machine_compare_rows(records: list[MachineRecord]) -> list[dict[str, str]]:
    specs = [
        ("Identity", "Machine number", lambda item: item.machine),
        ("Robot", "Robot type", lambda item: item.robot_type),
        ("Robot", "Robot model / controller", lambda item: _first_present(item.robot_model, item.controller)),
        ("Fit Check", "Compatible EOATs", lambda item: _join_values(item.compatible_eoats)),
        ("Fit Check", "Compatible tools", lambda item: _join_values(item.compatible_tools)),
        ("Readiness", "Documentation score", lambda item: f"{item.documentation_score}%"),
        ("Warnings", "Warnings", lambda item: str(item.warning_count)),
        ("Context", "Current EOAT", lambda item: item.current_eoat),
    ]
    return _compare_rows(records, [f"Machine {record.machine}" for record in records], specs)


def _tool_compare_rows(records: list[ToolRecord]) -> list[dict[str, str]]:
    specs = [
        ("Identity", "Tool number", lambda item: item.tool),
        ("Identity", "Part description", lambda item: _first_present(item.part_description, item.part_family)),
        ("Fit Check", "Compatible EOATs", lambda item: _join_values(item.compatible_eoats)),
        ("Fit Check", "Compatible machines", lambda item: _join_values(item.compatible_machines)),
        ("Source", "Source", lambda item: item.source),
        ("Warnings", "Warnings", lambda item: str(item.warning_count)),
    ]
    return _compare_rows(records, [f"Tool {record.tool}" for record in records], specs)


def _relationship_arrow() -> QLabel:
    arrow = QLabel("->")
    arrow.setObjectName("MicroText")
    arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return arrow


def _compare_rows(records, columns: list[str], specs) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for category, field, getter in specs:
        values = [_short_compare_value(getter(record)) for record in records]
        non_empty = {value for value in values if value}
        if len(set(values)) <= 1:
            difference = "Same"
        elif len(non_empty) != len(values):
            difference = "Missing"
        elif "warning" in category.casefold():
            difference = "Warning"
        else:
            difference = "Different"
        row = {"Category": category, "Field": field, "Difference": difference}
        for column, value in zip(columns, values, strict=False):
            row[column] = value
        rows.append(row)
    return rows


def _join_values(values) -> str:
    return ", ".join(str(value).strip() for value in values if str(value).strip())


def _short_compare_value(value) -> str:
    text = str(value or "").strip()
    return text if len(text) <= 160 else f"{text[:157]}..."


def _tool_card(tool, controller, page: ToolSearchPage | None = None) -> QWidget:
    card = ToolCompatibilityCard(f"Tool {tool.tool}", tool.part_description or tool.part_family or ", ".join(tool.parts[:3]) or "No part description")
    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    if page is not None:
        compare = QCheckBox("Compare")
        compare.setToolTip("Add this tool to compare mode.")
        compare.setChecked(normalized_tool_key(tool.tool) in page.compare_keys)
        compare.toggled.connect(lambda checked, tool_id=tool.tool: page.set_compare_selected(tool_id, checked))
        header.addWidget(compare)
    header.addWidget(badge("Compatible" if tool.compatible_eoats else "Review", "success" if tool.compatible_eoats else "warning"))
    header.addWidget(badge(tool.source or "Atlas source", "outline"))
    settings = getattr(controller, "settings", None)
    if settings is not None and _contains_id(getattr(settings, "recent_tools", ()), tool.tool):
        header.addWidget(badge("Recent", "ghost"))
    is_pinned = getattr(controller, "is_pinned", lambda _item_type, _key: False)
    if is_pinned("tool", tool.tool):
        header.addWidget(badge("Pinned", "count"))
    if tool.warning_count:
        header.addWidget(badge(f"{tool.warning_count} warning(s)", "warn"))
    header.addStretch(1)
    card.layout.addLayout(header)
    card.layout.addWidget(CompatibilityPathWidget(tool.tool, ", ".join(tool.compatible_eoats[:3]), tool.compatible_machines[:8]))
    card.layout.addWidget(_labeled_chips("Compatible EOATs", tool.compatible_eoats, empty="No linked EOATs", per_row=6))
    card.layout.addWidget(_labeled_chips("Compatible Machines", tool.compatible_machines, empty="No linked machines", per_row=6))
    card.layout.addWidget(_tool_relationship_map(tool))
    buttons = []
    if tool.compatible_eoats:
        eoat_button = QPushButton("Open EOAT")
        eoat_button.clicked.connect(
            lambda _checked=False, eoat_id=tool.compatible_eoats[0], selected_tool=tool: (
                page.mark_tool_viewed(selected_tool) if page is not None else None,
                controller.open_eoat(eoat_id),
            )
        )
        buttons.append(eoat_button)
    if buttons:
        card.layout.addWidget(action_row(*buttons))
    return card


PHOTO_LIBRARY_REQUIRED_CATEGORIES = (
    "00_Overall",
    "01_Front_View",
    "02_Side_View",
    "03_Vacuum_Cups_Grippers",
)


def _photo_record_matches(eoat: EOATRecord, query: str, mode_label: str) -> bool:
    folded_query = str(query or "").strip().casefold()
    folded_mode = str(mode_label or "all").casefold()
    categories = _photo_categories_for_eoat(eoat)
    if "has photos" in folded_mode and eoat.photo_count <= 0:
        return False
    if "missing folder" in folded_mode and eoat.photos.folder_exists:
        return False
    if "missing categories" in folded_mode and not eoat.photos.missing_categories:
        return False
    if "by tool" in folded_mode and folded_query:
        return any(folded_query in tool.casefold() for tool in eoat.tools)
    if "by machine" in folded_mode and folded_query:
        return any(folded_query in machine.casefold() for machine in eoat.machines)
    if "photo category" in folded_mode and folded_query:
        return any(folded_query in category.casefold() for category in categories)
    if not folded_query:
        return True
    haystack = " ".join(
        [
            eoat.eoat_id,
            " ".join(eoat.tools),
            " ".join(eoat.machines),
            eoat.photos.folder_path,
            " ".join(categories),
        ]
    ).casefold()
    return folded_query in haystack


def _photo_leaf_tooltip(eoat: EOATRecord) -> str:
    missing = ", ".join(eoat.photos.missing_categories) or "No required category gaps"
    return "\n".join(
        [
            eoat.eoat_id,
            f"Photos: {eoat.photo_count}",
            f"Folder: {'found' if eoat.photos.folder_exists else 'missing'}",
            f"Missing categories: {missing}",
        ]
    )


def _photo_library_categories(records: list[EOATRecord]) -> list[str]:
    categories = set(PHOTO_LIBRARY_REQUIRED_CATEGORIES)
    for eoat in records:
        categories.update(_photo_categories_for_eoat(eoat))
        categories.update(eoat.photos.missing_categories)
    return sorted((category for category in categories if category), key=_natural_sort_key)


def _photo_categories_for_eoat(eoat: EOATRecord) -> tuple[str, ...]:
    categories = {
        photo.category
        for photo in (*eoat.photos.photos, *eoat.photos.indexed_photos)
        if str(photo.category or "").strip()
    }
    categories.update(eoat.photos.missing_categories)
    return tuple(sorted(categories, key=_natural_sort_key))


def _photo_detail_hero(eoat: EOATRecord) -> QWidget:
    section = ProfileHeaderCard(eoat.eoat_id, _first_present(eoat.part_description, eoat.part_family, "EOAT photo set"), eyebrow="Photo Library")
    section.layout.addWidget(
        _chip_group(
            [
                f"{eoat.photo_count} photo(s)",
                "Folder found" if eoat.photos.folder_exists else "Folder missing",
                f"{len(eoat.photos.missing_categories)} missing category(s)",
            ],
            kind="good" if eoat.photo_count and not eoat.photos.missing_categories else "warn",
            per_row=3,
        )
    )
    section.layout.addWidget(_labeled_chips("Tools", eoat.tools, empty="No linked tools", per_row=6))
    section.layout.addWidget(_labeled_chips("Machines", eoat.machines, empty="No linked machines", per_row=6))
    if eoat.photos.missing_categories:
        section.layout.addWidget(_labeled_chips("Missing Categories", eoat.photos.missing_categories, kind="warn", per_row=4))
    else:
        section.layout.addWidget(_chip_group(["All required photo categories covered"], kind="good", per_row=3))
    folder = QLabel(_short_path(eoat.photos.folder_path) if eoat.photos.folder_path else "No photo folder linked.")
    folder.setObjectName("MicroText")
    folder.setWordWrap(True)
    folder.setToolTip(eoat.photos.folder_path)
    section.layout.addWidget(folder)
    return section


def _photo_detail_actions(eoat: EOATRecord, page: PhotosPage) -> QWidget:
    card = DetailCard("Photo Actions", "Open the async viewer or jump to related Atlas context.")
    view_button = QPushButton("View Photos")
    view_button.setObjectName("PrimaryButton")
    view_button.setEnabled(eoat.photo_count > 0)
    view_button.clicked.connect(lambda _checked=False, record=eoat: page.view_photos(record))
    folder_button = QPushButton("Open Photo Folder")
    folder_button.setEnabled(bool(eoat.photos.folder_path))
    folder_button.clicked.connect(page.open_folder)
    profile_button = QPushButton("Open EOAT Profile")
    profile_button.clicked.connect(page.open_profile)
    copy_button = QPushButton("Copy Folder Path")
    copy_button.setEnabled(bool(eoat.photos.folder_path))
    copy_button.clicked.connect(page.copy_folder_path)
    card.layout.addWidget(action_row(view_button, folder_button, profile_button, copy_button))
    return card


def _photo_category_checklist(eoat: EOATRecord) -> QWidget:
    widget = QWidget()
    layout = QGridLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(10)
    layout.setVerticalSpacing(7)
    present = {
        photo.category
        for photo in (*eoat.photos.photos, *eoat.photos.indexed_photos)
        if str(photo.category or "").strip()
    }
    categories = list(PHOTO_LIBRARY_REQUIRED_CATEGORIES)
    for category in _photo_categories_for_eoat(eoat):
        if category not in categories:
            categories.append(category)
    for row, category in enumerate(categories):
        status = "Missing" if category in eoat.photos.missing_categories else ("Found" if category in present else "Optional")
        kind = "warn" if status == "Missing" else ("good" if status == "Found" else "outline")
        layout.addWidget(badge(status, kind), row, 0)
        label = QLabel(category)
        label.setObjectName("BodyText")
        label.setToolTip(category)
        layout.addWidget(label, row, 1)
    layout.setColumnStretch(1, 1)
    return widget


def _natural_sort_key(value: str):
    text = str(value or "")
    chunks = []
    current = ""
    digit_mode = None
    for char in text:
        is_digit = char.isdigit()
        if digit_mode is None or is_digit == digit_mode:
            current += char
        else:
            chunks.append((0, int(current)) if digit_mode else (1, current.casefold()))
            current = char
        digit_mode = is_digit
    if current:
        chunks.append((0, int(current)) if digit_mode else (1, current.casefold()))
    return chunks


def _photo_folder_card(eoat: EOATRecord, page: PhotosPage) -> QWidget:
    card = PhotoGalleryCard(eoat.eoat_id, "Photo summary. Images load only when the carousel is opened.")
    top = QHBoxLayout()
    top.setContentsMargins(0, 0, 0, 0)
    top.addWidget(badge(f"{eoat.photo_count} photo(s)", "good" if eoat.photo_count else "warn"))
    top.addWidget(badge("Folder found" if eoat.photos.folder_exists else "Folder missing", "good" if eoat.photos.folder_exists else "bad"))
    top.addWidget(badge(f"{len(eoat.photos.missing_categories)} missing category(s)", "warn" if eoat.photos.missing_categories else "good"))
    top.addStretch(1)
    card.layout.addLayout(top)
    card.layout.addWidget(_labeled_chips("Tools", eoat.tools, empty="No linked tools", per_row=6))
    card.layout.addWidget(_labeled_chips("Machines", eoat.machines, empty="No linked machines", per_row=6))
    if eoat.photos.missing_categories:
        card.layout.addWidget(_labeled_chips("Missing categories", eoat.photos.missing_categories, kind="warn", per_row=5))
    else:
        card.layout.addWidget(badge("No required photo category gaps detected", "good"))
    folder_label = QLabel(_short_path(eoat.photos.folder_path) if eoat.photos.folder_path else "No photo folder linked.")
    folder_label.setObjectName("MicroText")
    folder_label.setToolTip(eoat.photos.folder_path)
    folder_label.setWordWrap(True)
    card.layout.addWidget(folder_label)
    buttons = []
    view_button = QPushButton("View Photos")
    view_button.setObjectName("PrimaryButton")
    view_button.clicked.connect(lambda _checked=False, record=eoat: page.view_photos(record))
    buttons.append(view_button)
    if eoat.photos.folder_path:
        button = QPushButton("Open Photo Folder")
        button.clicked.connect(lambda _checked=False, path=eoat.photos.folder_path: open_path(path))
        buttons.append(button)
    card.layout.addWidget(action_row(*buttons))
    return card


def _standard_card(standard) -> QWidget:
    bundle = AtlasDataBundle(project_root="", loaded_at="", standards=(standard,))
    return _standard_document_card(_standard_document_from_reference(standard, priority=0), bundle)


def _standards_documents(bundle: AtlasDataBundle) -> list[dict]:
    documents: list[dict] = []
    seen_paths: set[str] = set()
    for standard in bundle.standards:
        if standard.path:
            path = Path(standard.path)
            if not path.exists():
                continue
            seen_paths.add(_document_path_key(path))
        documents.append(_standard_document_from_reference(standard, priority=10))
    for path in _live_standards_document_paths(bundle):
        key = _document_path_key(path)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        documents.append(_standard_document_from_reference(_standard_reference_from_path(path), priority=12))
    export_root = Path(bundle.project_root) / "06_Final_Handoff" / "Atlas_Exports"
    if export_root.exists():
        for path in sorted(export_root.rglob("*"))[:300]:
            if path.is_file() and path.suffix.casefold() in {".pdf", ".md", ".csv", ".xlsx", ".docx"}:
                documents.append(_standard_document_from_path(path, "Generated Reports", priority=40))
    return documents


def _live_standards_document_paths(bundle: AtlasDataBundle) -> list[Path]:
    if not bundle.project_root:
        return []
    paths = resolve_project_paths(bundle.project_root)
    folders = [
        paths.standards,
        paths.work_instructions,
        Path(bundle.project_root) / "Project_Help_Documents",
        Path(bundle.project_root) / "output" / "documents",
        Path(bundle.project_root) / "output" / "pdf",
    ]
    documents: list[Path] = []
    for folder in folders:
        if not folder.exists():
            continue
        try:
            documents.extend(
                path
                for path in folder.rglob("*")
                if path.is_file() and path.suffix.casefold() in STANDARD_EXTENSIONS and not path.name.startswith("~$")
            )
        except OSError:
            continue
    return sorted(documents, key=lambda path: str(path).casefold())


def _standard_reference_from_path(path: Path) -> StandardReference:
    title = path.stem.replace("_", " ").replace("-", " ").strip().title() or path.name
    folded = path.name.casefold().replace("_", " ").replace("-", " ")
    snippet = (
        "Primary EOAT standardization guidance. Open the source document for full design and documentation rules."
        if "eoat standardization" in folded
        else _document_preview(path, limit=320)
    )
    return StandardReference(title=title, path=str(path), category="", snippet=snippet)


def _document_path_key(path: str | Path) -> str:
    try:
        return str(Path(path).resolve(strict=False)).casefold()
    except OSError:
        return str(path).casefold()


def _standard_document_from_reference(standard: StandardReference, *, priority: int) -> dict:
    path = Path(standard.path) if standard.path else Path()
    doc_type, status = _classify_document(standard.title, standard.category, path)
    document = {
        "title": standard.title or path.stem or "Untitled standard",
        "type": doc_type,
        "status": status,
        "modified": _format_modified(_file_mtime(path)) if standard.path else "Not available",
        "modified_sort": _file_mtime(path),
        "path": standard.path,
        "raw_preview": standard.snippet or _document_preview(path, limit=1200),
        "tags": _document_tags(standard.title, standard.category, path),
        "priority": priority + _document_priority(doc_type, status, path),
        "is_blank": status in {"Blank", "Template", "Archived"} or _looks_blank_document(path),
    }
    document["snippet"] = build_document_preview(document)
    return document


def _standard_document_from_path(path: Path, doc_type: str, *, priority: int) -> dict:
    status = "Generated"
    if _looks_blank_document(path):
        status = "Blank"
    document = {
        "title": path.stem.replace("_", " ").replace("-", " ").title(),
        "type": doc_type,
        "status": status,
        "modified": _format_modified(_file_mtime(path)),
        "modified_sort": _file_mtime(path),
        "path": str(path),
        "raw_preview": _document_preview(path, limit=1600),
        "tags": _document_tags(path.stem, doc_type, path),
        "priority": priority + _document_priority(doc_type, status, path),
        "is_blank": status == "Blank",
    }
    document["snippet"] = build_document_preview(document)
    return document


def _standard_document_card(document: dict, bundle: AtlasDataBundle) -> QWidget:
    suffix = Path(str(document.get("path") or "")).suffix.upper().lstrip(".") or "DOC"
    related = _related_records_for_document(document, bundle)
    buttons = []
    path_text = document.get("path", "")
    if path_text:
        open_button = QPushButton("Open Document")
        open_button.setObjectName("PrimaryButton")
        open_button.clicked.connect(lambda _checked=False, path=path_text: open_path(path))
        buttons.append(open_button)
        folder_button = QPushButton("Open Folder")
        folder_button.clicked.connect(lambda _checked=False, path=path_text: open_path(Path(path).parent))
        buttons.append(folder_button)
    details_button = QPushButton("Details")
    details_button.clicked.connect(lambda _checked=False, doc=document, data=bundle: _show_document_details(doc, data))
    buttons.append(details_button)
    metadata = [
        document.get("modified", "Not available"),
        f"{len(related)} related record(s)" if related else "No related records indexed",
    ]
    return DocumentCard(
        category=document["type"],
        title=document["title"],
        description=_document_purpose(document),
        badges=[(document["status"], _document_status_kind(document["status"])), (suffix, "outline")],
        metadata=metadata,
        preview=document["snippet"] or "Open the source document for full details.",
        path_label=shorten_path(document.get("path", "")),
        full_path=document.get("path", ""),
        tags=document["tags"],
        actions=buttons,
    )


def _standards_summary_grid(documents: list[dict]) -> QWidget:
    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(10)
    counts = Counter(document["type"] for document in documents)
    status_counts = Counter(document["status"] for document in documents)
    cards = [
        MetricCard("Controlled Standards", str(counts.get("Controlled Standards", 0)), "Approved standards and reference rules", kind="primary"),
        MetricCard("Work Instructions", str(counts.get("Work Instructions", 0)), "Procedure and how-to documents", kind="primary"),
        MetricCard("PM / Inspection", str(counts.get("PM / Inspection Checklists", 0)), "Checklists and maintenance guidance", kind="primary"),
        MetricCard("Generated Reports", str(counts.get("Generated Reports", 0)), "Useful generated evidence reports", kind="primary"),
        MetricCard("Templates Hidden", str(status_counts.get("Template", 0)), "Hidden until Show templates is enabled", kind="warn" if status_counts.get("Template", 0) else "good"),
        MetricCard("Blank/Empty Hidden", str(status_counts.get("Blank", 0)), "Hidden until blank documents are enabled", kind="warn" if status_counts.get("Blank", 0) else "good"),
    ]
    for index, card in enumerate(cards):
        grid.addWidget(card, index // 3, index % 3)
    wrapper = QWidget()
    wrapper.setLayout(grid)
    return wrapper


def _sort_documents(documents: list[dict], sort_label: str) -> list[dict]:
    folded = str(sort_label or "").casefold()
    if "modified" in folded:
        return sorted(documents, key=lambda item: (-float(item.get("modified_sort") or 0), item["title"].casefold()))
    if "type" in folded:
        return sorted(documents, key=lambda item: (item["type"].casefold(), item["status"].casefold(), item["title"].casefold()))
    if "title" in folded:
        return sorted(documents, key=lambda item: item["title"].casefold())
    return sorted(documents, key=lambda item: (item["priority"], item["type"].casefold(), item["title"].casefold()))


def _document_purpose(document: dict) -> str:
    text = " ".join([document.get("title", ""), document.get("type", ""), " ".join(document.get("tags", ()))])
    folded = text.casefold()
    if "pm" in folded or "inspection" in folded:
        return "Inspection or maintenance reference for EOAT readiness."
    if "generated" in folded or "report" in folded:
        return "Generated Atlas evidence for review, export, or handoff."
    if "work instruction" in folded:
        return "Procedure document for repeatable EOAT work."
    return "Controlled reference for EOAT design, documentation, or setup review."


def _show_document_details(document: dict, bundle: AtlasDataBundle) -> None:
    dialog = QDialog()
    dialog.setWindowTitle(f"Document Details - {document.get('title', 'Document')}")
    dialog.resize(760, 620)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)
    layout.addWidget(PageHeader(document.get("title", "Document"), _document_purpose(document)))
    layout.addWidget(
        key_value_grid(
            [
                ("Type/category", document.get("type", "")),
                ("Status", document.get("status", "")),
                ("Last modified", document.get("modified", "")),
                ("Source path", document.get("path", "") or "Not indexed"),
                ("Tags", ", ".join(document.get("tags", ()))),
                ("Related records", ", ".join(_related_records_for_document(document, bundle)) or "None indexed"),
            ]
        )
    )
    preview = QTextEdit()
    preview.setReadOnly(True)
    preview.setPlainText(build_document_detail_preview(document))
    layout.addWidget(preview, 1)
    buttons = []
    path_text = document.get("path", "")
    if path_text:
        open_button = QPushButton("Open Document")
        open_button.setObjectName("PrimaryButton")
        open_button.clicked.connect(lambda _checked=False, path=path_text: open_path(path))
        folder_button = QPushButton("Open Folder")
        folder_button.clicked.connect(lambda _checked=False, path=path_text: open_path(Path(path).parent))
        buttons.extend([open_button, folder_button])
    close_button = QPushButton("Close")
    close_button.clicked.connect(dialog.accept)
    buttons.append(close_button)
    layout.addWidget(action_row(*buttons))
    dialog.exec()


def _classify_document(title: str, category: str, path: Path) -> tuple[str, str]:
    text = " ".join([title, category, str(path)]).casefold()
    if "archive" in text or "old" in path.parts:
        return "Archived / Blank Templates", "Archived"
    if "template" in text or "draft" in text:
        return "Templates", "Template"
    if "work instruction" in text or "wi" in text:
        return "Work Instructions", "Draft" if "draft" in text else "Controlled"
    if "pm" in text or "inspection" in text or "checklist" in text:
        return "PM / Inspection Checklists", "Controlled"
    if "report" in text or "generated" in text:
        return "Generated Reports", "Generated"
    return "Controlled Standards", "Controlled"


def _document_status_kind(status: str) -> str:
    return {
        "Controlled": "verified",
        "Draft": "review",
        "Template": "unknown",
        "Generated": "unknown",
        "Blank": "missing",
        "Archived": "unknown",
    }.get(status, "unknown")


def _document_priority(doc_type: str, status: str, path: Path) -> int:
    if status in {"Blank", "Archived"}:
        return 90
    if status == "Template":
        return 70
    if doc_type == "Controlled Standards":
        return 0
    if doc_type == "Work Instructions":
        return 5
    if doc_type == "PM / Inspection Checklists":
        return 10
    if doc_type == "Generated Reports":
        return 25
    return 50


def _document_tags(title: str, category: str, path: Path) -> tuple[str, ...]:
    text = " ".join([title, category, path.name]).casefold()
    tags = []
    for label, keywords in [
        ("vacuum", ("vacuum", "cup")),
        ("tubing/routing", ("tube", "tubing", "routing", "pneumatic")),
        ("sensors", ("sensor", "part-present")),
        ("quick disconnects", ("quick", "disconnect", "m12")),
        ("fasteners/hardware", ("fastener", "hardware", "mount")),
        ("safety", ("safety", "guard", "risk")),
        ("documentation/CAD/BOM/revision", ("document", "cad", "bom", "revision")),
        ("PM checklist", ("pm", "maintenance", "inspection", "checklist")),
        ("process binder information", ("process", "binder")),
    ]:
        if any(keyword in text for keyword in keywords):
            tags.append(label)
    return tuple(dict.fromkeys([*tags, path.suffix.upper().lstrip(".") or "DOC"]))


def build_document_preview(document: dict, *, limit: int = 220) -> str:
    if document.get("is_blank") or document.get("status") in {"Blank", "Template"}:
        return "Blank template" if document.get("status") == "Blank" else "Template document"
    raw = str(document.get("raw_preview") or document.get("snippet") or "")
    generated = _generated_report_summary(raw)
    if generated:
        return _short_label(generated, limit)
    cleaned = _clean_preview_text(raw)
    return _short_label(cleaned, limit) if cleaned else ""


def build_document_detail_preview(document: dict) -> str:
    raw = str(document.get("raw_preview") or document.get("snippet") or "")
    cleaned = _clean_preview_text(raw, keep_headers=True)
    if cleaned:
        return cleaned
    return build_document_preview(document, limit=500) or "No text preview is available for this document type."


def shorten_path(path: str | Path, *, limit: int = 72) -> str:
    if not path:
        return "No source path indexed"
    target = Path(str(path))
    label = f"{target.parent.name}\\{target.name}" if target.parent.name else target.name
    return _short_label(label, limit)


def _document_preview(path: Path, *, limit: int = 220) -> str:
    if not path or not path.exists() or path.suffix.casefold() not in {".md", ".txt", ".csv"}:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")[: max(limit * 6, 1200)]
    except OSError:
        return ""
    return _short_label(_clean_preview_text(text), limit)


def _looks_blank_document(path: Path) -> bool:
    if not path or not path.exists():
        return False
    text = path.name.casefold()
    if any(token in text for token in ("blank", "empty", "template")):
        return True
    try:
        if path.stat().st_size == 0:
            return True
    except OSError:
        return False
    preview = _document_preview(path, limit=700).casefold()
    return bool(preview and any(token in preview for token in ("no data yet", "0 scanned", "zero scanned records", "template placeholder")))


def _clean_preview_text(text: str, *, keep_headers: bool = False) -> str:
    lines = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not keep_headers and line.startswith("#"):
            continue
        if re.fullmatch(r"[\|\-\:\s]+", line):
            continue
        if "|" in line:
            cells = [cell.strip(" *`") for cell in line.strip("|").split("|") if cell.strip(" *`")]
            if cells:
                line = ": ".join(cells[:2]) if len(cells) == 2 else ", ".join(cells[:4])
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"[*_`]+", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return " ".join(lines)


def _generated_report_summary(text: str) -> str:
    cleaned = _clean_preview_text(text)
    folded = f"{text or ''} {cleaned}".casefold()
    if not folded:
        return ""
    if "no data yet" in folded or "0 scanned" in folded or "zero scanned" in folded:
        return "Generated report has no scanned data yet."
    values = {}
    patterns = {
        "eoats": r"(\d+)\s+eoats?\s+(?:scanned|reviewed|records?)",
        "gaps": r"(\d+)\s+(?:documentation\s+)?gaps?",
        "critical": r"(\d+)\s+critical\s+gaps?",
        "important": r"(\d+)\s+(?:important|warning)\s+gaps?",
        "audits": r"(\d+)\s+audits?\s+scored",
        "average": r"average(?:\s+compliance)?\s+score[:\s]+(\d+)",
        "failed": r"failed\s+standards?[:\s]+(\d+)",
        "follow_up": r"follow[- ]?up\s+items?[:\s]+(\d+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, folded)
        if match:
            values[key] = match.group(1)
    table_patterns = {
        "eoats": r"eoats?\s+scanned[:\s]+(\d+)",
        "gaps": r"documentation\s+gaps?[:\s]+(\d+)",
        "critical": r"critical\s+gaps?[:\s]+(\d+)",
        "important": r"important\s+gaps?[:\s]+(\d+)",
        "audits": r"audits?\s+scored[:\s]+(\d+)",
        "average": r"average(?:\s+compliance)?\s+score[:\s]+(\d+)",
        "failed": r"failed\s+standards?[:\s]+(\d+)",
        "follow_up": r"follow[- ]?up\s+items?[:\s]+(\d+)",
    }
    for key, pattern in table_patterns.items():
        match = re.search(pattern, folded)
        if match:
            values[key] = match.group(1)
    if {"audits", "average", "failed"} & values.keys():
        pieces = []
        if values.get("audits"):
            pieces.append(f"{values['audits']} audits scored")
        if values.get("average"):
            pieces.append(f"average compliance score {values['average']}%")
        if values.get("failed"):
            pieces.append(f"{values['failed']} failed standards")
        if values.get("follow_up"):
            pieces.append(f"{values['follow_up']} follow-up items")
        return ". ".join(pieces) + "."
    if {"eoats", "gaps", "critical", "important"} & values.keys():
        pieces = []
        if values.get("eoats"):
            pieces.append(f"{values['eoats']} EOATs scanned")
        if values.get("gaps"):
            pieces.append(f"{values['gaps']} documentation gaps")
        if values.get("critical"):
            pieces.append(f"{values['critical']} critical gaps")
        if values.get("important"):
            pieces.append(f"{values['important']} important gaps")
        return ". ".join(pieces) + "."
    return ""


def _related_records_for_document(document: dict, bundle: AtlasDataBundle) -> tuple[str, ...]:
    text = " ".join([document.get("title", ""), document.get("snippet", ""), document.get("path", "")]).casefold()
    related = []
    for eoat in bundle.eoats:
        if eoat.eoat_id and eoat.eoat_id.casefold() in text:
            related.append(eoat.eoat_id)
    for machine in bundle.machines:
        if machine.machine and f"machine {machine.machine}".casefold() in text:
            related.append(f"Machine {machine.machine}")
    for tool in bundle.tools:
        if tool.tool and tool.tool.casefold() in text:
            related.append(f"Tool {tool.tool}")
    return tuple(dict.fromkeys(related[:12]))


def _build_information_entries(bundle: AtlasDataBundle | None) -> list[InformationLibraryEntry]:
    return build_information_entries(bundle)


def _static_information_entries() -> list[InformationLibraryEntry]:
    return seed_information_entries()
    topics = [
        (
            ("Atlas App Help", "Home / Command Deck"),
            "Home / Command Deck",
            "Use the Command Deck for instant lookup, page navigation, source status, and high-level Atlas metrics.",
            "The home page is the fast starting point. Its search sends known tool, machine, EOAT, part, robot, or keyword text into the recommendation engine. Quick actions jump to the major read-only pages, while source chips show whether the cached data was built from available workbooks, photo folders, and standards.",
            ("home", "search", "metrics"),
        ),
        (
            ("Atlas App Help", "What Do I Need?"),
            "What Do I Need?",
            "Enter any known identifier to get the best EOAT recommendation, ranked backups, warnings, and install checklist.",
            "This page uses cached normalized indexes and in-memory recommendation data. Open EOAT Profile, View Photos, Open Related Tool, and Open Related Machine actions jump directly into the full profile pages without rescanning Excel.",
            ("recommendation", "eoat", "install"),
        ),
        (
            ("Atlas App Help", "EOAT Profiles"),
            "EOAT Profiles",
            "EOAT profiles show compatibility, readiness, photo coverage, warnings, and quiet technical detail cards.",
            "Start with the profile header to answer what the EOAT is, what tools it supports, what machines it can run on, and whether documentation/photos/warnings need attention before staging.",
            ("profile", "readiness", "warnings"),
        ),
        (
            ("Atlas App Help", "Machine Profiles"),
            "Machine Profiles",
            "Machine profiles focus on machine number, robot context, compatible EOATs/tools, and actionable warnings.",
            "Use the compatibility chips to confirm machine support. Robot type, model, controller, and documentation score stay in supporting detail so the primary compatibility answer remains obvious.",
            ("machine", "robot", "compatibility"),
        ),
        (
            ("Atlas App Help", "Tool / Mold / Part"),
            "Tool / Mold / Part",
            "Search tools, molds, parts, and descriptions to see compatible EOATs and machines.",
            "Tool cards show a compact Tool -> EOAT -> Machine flow. Use the single global What Do I Need action when you want a recommendation for the selected/searched tool.",
            ("tool", "mold", "part"),
        ),
        (
            ("Atlas App Help", "Fit Check"),
            "Fit Check",
            "The matrix is the dense sortable view for EOAT-machine-tool relationships.",
            "Use it when you need comparison or export-friendly rows. The matrix is intentionally denser than profile pages and is wrapped in a dedicated data panel so it does not compete visually with dashboard profiles.",
            ("matrix", "export", "dense data"),
        ),
        (
            ("Atlas App Help", "Analytics Dashboard"),
            "Analytics Dashboard",
            "Analytics Dashboard summarizes coverage, documentation, photos, warnings, and standards compliance.",
            "Use the dashboard cards and charts first, then inspect the affected profiles when planning cleanup or validating coverage before handoff.",
            ("coverage", "heatmap", "dashboard"),
        ),
        (
            ("Atlas App Help", "Photos"),
            "Photos",
            "Photo cards summarize counts, folder status, and missing categories. Images load in the carousel on demand.",
            "Atlas avoids loading every photo while browsing. Click View Photos to load one image at a time in-app, or use Open Photo Folder/Open Externally for source-folder inspection.",
            ("photos", "carousel", "lazy loading"),
        ),
        (
            ("Atlas App Help", "Standards & Work Instructions"),
            "Standards & Work Instructions",
            "Standards & Work Instructions lists controlled standards, work instructions, checklists, and useful generated reports.",
            "Likely EOAT standardization documents placed in the project root are safely copied into 03_Standards without overwriting existing files, then indexed as high-priority references.",
            ("standards", "documents", "read-only"),
        ),
        (
            ("Atlas App Help", "PM / Inspection"),
            "PM / Inspection",
            "PM / Inspection groups weekly, monthly, and pre-install checks into checklist cards.",
            "Review cups/grippers, tubing, cable routing, quick disconnects, sensors, hardware, photo evidence, and warnings before staging or maintaining EOATs.",
            ("pm", "inspection", "maintenance"),
        ),
        (
            ("Atlas App Help", "Reports & Handoff"),
            "Reports & Handoff",
            "Reports create timestamped read-only exports for compatibility, documentation gaps, and photo coverage.",
            "Exports are generated from the cached Atlas bundle and do not modify source workbooks, photos, or standard documents.",
            ("reports", "exports", "read-only"),
        ),
        (
            ("Atlas App Help", "Settings / Diagnostics"),
            "Settings / Diagnostics",
            "Settings control theme mode, color scheme, startup page, photo viewer behavior, density, diagnostics, and auto-refresh.",
            "Preferences are stored in the user settings file. They apply immediately where practical and never get written into source workbooks or photo folders.",
            ("settings", "theme", "diagnostics"),
        ),
        (
            ("EOAT Standards", "Design Guidelines"),
            "EOAT standardization documents",
            "EOAT standards define preferred design, documentation, and inspection expectations.",
            "Treat the main standardization document as a primary reference. It should influence EOAT construction fields, warnings, documentation requirements, photos, PM checks, and troubleshooting guidance.",
            ("standardization", "design", "requirements"),
        ),
        (
            ("EOAT Standards", "Vacuum Standards"),
            "Vacuum standards",
            "Vacuum guidance covers cups, circuits, pressure/vacuum notes, and failure-prone wear items.",
            "When a profile has vacuum info missing or photos do not show cups/circuits, the readiness score and warning cards should prompt a source-data or photo cleanup check.",
            ("vacuum", "cups", "readiness"),
        ),
        (
            ("EOAT Standards", "Pneumatic Tubing / Routing"),
            "Pneumatic tubing / routing",
            "Tubing guidance focuses on routing, strain relief, kinks, pinch points, and clear connection documentation.",
            "Missing tubing notes, pneumatic photos, or unclear routing can affect install confidence and maintenance repeatability.",
            ("pneumatics", "tubing", "routing"),
        ),
        (
            ("EOAT Standards", "Sensors"),
            "Sensor standards",
            "Sensor guidance covers confirmation signals, wiring/cable routing, labels, and machine/robot integration context.",
            "Missing sensor information can cause uncertain compatibility and should be resolved from EOAT Inventory, Robot Info, or standards documentation.",
            ("sensors", "signals", "robot"),
        ),
        (
            ("EOAT Standards", "Quick Disconnects"),
            "Quick disconnects",
            "Quick disconnect guidance helps users verify connections before install and during PM.",
            "If connection type is missing, use the EOAT profile warnings and photo folder to decide whether the source workbook or photo documentation needs cleanup.",
            ("quick disconnects", "connections", "install"),
        ),
        (
            ("EOAT Standards", "Grippers"),
            "Gripper standards",
            "Gripper guidance covers wear, mounting, adjustability, confirmation, and spare/replacement visibility.",
            "Profiles with gripper info missing should be treated as review-needed until source rows or photos confirm the configuration.",
            ("grippers", "mechanical", "inspection"),
        ),
        (
            ("EOAT Standards", "Mounting Hardware"),
            "Mounting hardware",
            "Mounting guidance covers stable EOAT connection, fastener visibility, torque/condition checks, and repeatable setup.",
            "Missing hardware photos or construction notes can affect setup quality, so Atlas surfaces those as readiness and warning context.",
            ("mounting", "hardware", "setup"),
        ),
        (
            ("EOAT Standards", "Fasteners"),
            "Fasteners",
            "Fastener checks support PM and pre-install inspection for loose, missing, damaged, or inconsistent hardware.",
            "Use PM checklist guidance with photos and known issues to decide whether a standard update or source-data fix is needed.",
            ("fasteners", "pm", "inspection"),
        ),
        (
            ("EOAT Standards", "Weight Reduction"),
            "Weight reduction",
            "Weight and construction guidance helps confirm EOATs are appropriate for robot capacity and repeated handling.",
            "Atlas does not invent performance data; when weight or construction notes are missing, it should present review guidance rather than false confidence.",
            ("weight", "construction", "robot"),
        ),
        (
            ("EOAT Standards", "Safety"),
            "Safety",
            "Safety references should guide pre-install review, missing documentation warnings, and troubleshooting.",
            "Warning cards are designed to make safety-relevant data gaps obvious without burying them in a spreadsheet-like detail dump.",
            ("safety", "warnings", "install"),
        ),
        (
            ("EOAT Standards", "Documentation Requirements"),
            "Documentation requirements",
            "Documentation score considers identity, type/status, compatibility, robot/pneumatic/sensor context, photos, and standards references.",
            "A low score is a cleanup signal. It does not always block use, but it means the user should review warnings before relying on the EOAT for a machine/tool setup.",
            ("documentation", "score", "gaps"),
        ),
        (
            ("Fit Check Logic", "Tool-to-Machine Fit Check"),
            "Tool-to-machine compatibility",
            "Atlas uses Press Capacity/tool-machine rows and normalized tool keys to connect tools to machines.",
            "Tool lookups should use cached dictionaries, not workbook rescans. Missing tool-machine links usually point to Press Capacity source gaps or normalization mismatches.",
            ("tool", "machine", "press capacity"),
        ),
        (
            ("Fit Check Logic", "EOAT-to-Tool Fit Check"),
            "EOAT-to-tool compatibility",
            "EOAT-to-tool links come from EOAT inventory/audit rows and normalized tool numbers.",
            "If an EOAT appears compatible with a tool but not a machine, check whether the tool exists in Press Capacity and whether the machine source data is available.",
            ("eoat", "tool", "indexes"),
        ),
        (
            ("Fit Check Logic", "Off-Machine EOAT Audits"),
            "Off-machine EOAT audits",
            "Off-machine audits may provide EOAT identity, condition, photos, and documentation context even before full compatibility is known.",
            "Use warnings and detail metadata to distinguish documented off-machine evidence from confirmed machine/tool compatibility.",
            ("audit", "off-machine", "photos"),
        ),
        (
            ("Fit Check Logic", "Fit Check Rows"),
            "Fit Check rows",
            "Dense compatibility rows are generated from cached Atlas bundle data for matrix and export workflows.",
            "The matrix is best for auditing many relationships at once; profile cards are best for answering a specific install question quickly.",
            ("matrix", "rows", "export"),
        ),
        (
            ("Fit Check Logic", "Confidence / Warnings"),
            "Fit Check confidence / warnings",
            "High confidence usually means tool, EOAT, and machine links exist with useful robot/documentation context.",
            "Partial compatibility is still useful, but warning chips tell the user what is missing and where to look before staging.",
            ("confidence", "warnings", "compatibility"),
        ),
        (
            ("Photos / Documentation", "Photo Folder Structure"),
            "Photo folder structure",
            "Photo folders are indexed once at refresh time and linked to EOAT IDs/tool context through normalized folder/file names.",
            "Atlas should not re-index photos on every search. Folder paths stay read-only and are opened externally only when the user chooses to inspect them.",
            ("photos", "folders", "indexes"),
        ),
        (
            ("Photos / Documentation", "Required Photo Categories"),
            "Required photo categories",
            "Front, rear/side, connection, pneumatic/vacuum/gripper, sensor, and overall context photos help make EOAT profiles usable.",
            "Missing category chips identify what a future audit/photo pass should capture so the profile is useful within seconds.",
            ("photo categories", "documentation", "audit"),
        ),
        (
            ("Photos / Documentation", "Missing Photo Categories"),
            "Missing photo categories",
            "Missing categories are shown as warning chips, not silent omissions.",
            "Use them as a photography checklist during EOAT standardization work; they do not modify or rename existing source files.",
            ("missing photos", "warnings", "cleanup"),
        ),
        (
            ("Photos / Documentation", "Photo Viewer"),
            "Photo viewer",
            "The in-app carousel loads the current image, keeps aspect ratio, and provides Open Folder/Open Externally fallbacks.",
            "HEIC/HEIF previews require Qt support or Pillow plus pillow-heif. If preview support is unavailable, Atlas shows a clear message instead of a blank panel.",
            ("photo viewer", "heic", "carousel"),
        ),
        (
            ("Photos / Documentation", "External Folder Handling"),
            "External folder handling",
            "Open Folder and Open Externally are user-triggered actions for inspecting original project files.",
            "Atlas remains read-only for source photo folders. Settings can require confirmation before opening external files or folders.",
            ("external files", "read-only", "settings"),
        ),
        (
            ("PM / Inspection", "Weekly Checks"),
            "Weekly checks",
            "Weekly inspection should catch wear, looseness, damaged cups/grippers, tubing issues, and signal/connection problems.",
            "Use EOAT warnings and photo coverage as the quick context for what to inspect before running production.",
            ("weekly", "pm", "inspection"),
        ),
        (
            ("PM / Inspection", "Monthly Checks"),
            "Monthly checks",
            "Monthly inspection should review documentation, repeated issues, spare parts/BOM context, and photo currency.",
            "Low documentation scores and repeated warnings are signals that a monthly cleanup or standards review may be needed.",
            ("monthly", "documentation", "pm"),
        ),
        (
            ("PM / Inspection", "Vacuum Cups"),
            "Vacuum cups",
            "Vacuum cups should be reviewed for wear, cracks, missing parts, or poor placement.",
            "Photo categories and vacuum notes help confirm whether cups are documented well enough for repeatable setup.",
            ("vacuum", "cups", "wear"),
        ),
        (
            ("PM / Inspection", "Tubing"),
            "Tubing",
            "Tubing checks should look for kinks, rub points, pinch hazards, unsecured routing, and unclear connection paths.",
            "Missing tubing notes in a profile should prompt review of photos or source workbook fields.",
            ("tubing", "routing", "pm"),
        ),
        (
            ("PM / Inspection", "Cable Management"),
            "Cable management",
            "Cable and sensor routing should be checked for strain, pinch points, labels, and confirmation reliability.",
            "Atlas surfaces sensor/cable context through technical details and warnings where source fields are missing.",
            ("cables", "sensors", "routing"),
        ),
        (
            ("Reports & Handoff", "EOAT Summary"),
            "EOAT summary export",
            "EOAT summary exports package the selected EOAT profile context for offline review.",
            "Exports are generated from loaded cached data and should reflect the same warnings, compatibility, photos, and documentation status shown in the UI.",
            ("eoat export", "summary", "reports"),
        ),
        (
            ("Reports & Handoff", "Machine Summary"),
            "Machine summary export",
            "Machine summary exports focus on robot context, compatible EOATs/tools, and warnings.",
            "Use this when sharing machine-specific setup or cleanup context without sending users into the full app.",
            ("machine export", "robot", "reports"),
        ),
        (
            ("Reports & Handoff", "Tool Summary"),
            "Tool summary export",
            "Tool summary exports help communicate which EOATs and machines are linked to a tool/mold/part search.",
            "Tool summaries are useful when validating compatibility coverage or planning standards cleanup around a tooling family.",
            ("tool export", "compatibility", "reports"),
        ),
        (
            ("Reports & Handoff", "Project Reports"),
            "Project reports",
            "Project-level reports provide compatibility, documentation gap, and photo coverage views.",
            "They are best used for handoff, cleanup planning, and source-data review rather than day-to-day EOAT selection.",
            ("project reports", "handoff", "coverage"),
        ),
        (
            ("Troubleshooting", "Photo Not Displaying"),
            "Photo not displaying",
            "If a photo is detected but not visible, the decoder likely cannot load the format or the file is corrupt/missing.",
            "Use the viewer message first. HEIC/HEIF previews need Qt support or Pillow with pillow-heif; Open Externally and Open Folder remain available as fallbacks.",
            ("photos", "heic", "troubleshooting"),
        ),
        (
            ("Troubleshooting", "Slow Loading"),
            "Slow loading",
            "Atlas should load workbooks, photo indexes, and standards at refresh/startup, then use cached lookup indexes for normal searches.",
            "Use Settings / Diagnostics performance cards to identify workbook load time, photo index time, cache build time, and search/lookup timings.",
            ("performance", "cache", "diagnostics"),
        ),
        (
            ("Troubleshooting", "No Fit Check Match Found"),
            "No Fit Check match found",
            "No compatibility usually means an identifier was missing, normalized differently, or absent from the source relationship tables.",
            "Check Tool #, EOAT ID, machine number, Press Capacity rows, Robot Info, and source EOAT Inventory fields.",
            ("compatibility", "missing data", "tool"),
        ),
        (
            ("Troubleshooting", "Search Not Finding Expected Item"),
            "Search not finding expected item",
            "Search uses normalized in-memory keys and text fields from the loaded Atlas bundle.",
            "If a source workbook changed, use Refresh Data. If the value is still missing, review the source row and normalization of EOAT ID, Tool #, Machine #, part, and robot fields.",
            ("search", "refresh", "normalization"),
        ),
        (
            ("Settings", "Theme"),
            "Theme mode",
            "Theme mode controls light, dark, or system/default behavior.",
            "Light remains the default for screenshots and most floor use. Dark mode is available for lower-glare viewing and uses the same Atlas design tokens.",
            ("theme", "light", "dark"),
        ),
        (
            ("Settings", "Color Scheme"),
            "Color scheme",
            "Color scheme controls the accent palette independently from light/dark mode.",
            "Atlas Blue is the default. Nolato Logo uses red as a controlled accent with charcoal anchors and neutral surfaces, without turning the whole app red.",
            ("color scheme", "nolato", "settings"),
        ),
        (
            ("Settings", "Photo Viewer Settings"),
            "Photo viewer settings",
            "Photo viewer behavior can open photos in-app, open the folder, or use the external viewer.",
            "Lazy previews and carousel prefetch settings keep browsing fast while still allowing smoother next/previous navigation when enabled.",
            ("photo viewer", "settings", "prefetch"),
        ),
        (
            ("Settings", "Density / Compact Mode"),
            "Density / compact mode",
            "Density settings tune how compact selector tiles and cards feel.",
            "Compact mode is useful on smaller screens or when scanning long EOAT/machine lists. Comfortable mode prioritizes readability.",
            ("density", "compact", "lists"),
        ),
        (
            ("Settings", "Diagnostics"),
            "Diagnostics",
            "Advanced diagnostics show dense source tables and raw performance counters.",
            "Hide diagnostics for a cleaner operator-style view; enable them when investigating source paths, refresh behavior, or performance timings.",
            ("diagnostics", "performance", "settings"),
        ),
    ]
    now = time.time()
    return [
        InformationLibraryEntry(
            entry_id=_entry_id_from_parts(*path, title),
            title=title,
            category=path[0],
            summary=summary,
            body=body,
            source="Atlas App Help",
            source_section=path[-1],
            tags=tags,
            tree_path=path,
            related=tuple(part for part in path if part != path[0]),
            indexed_at=now,
        )
        for path, title, summary, body, tags in topics
    ]


def _standard_information_entries(standard: StandardReference) -> list[InformationLibraryEntry]:
    path = Path(standard.path) if standard.path else Path()
    title = standard.title or (path.stem if standard.path else "Indexed standard")
    summary = standard.snippet or "Indexed standards document available from the project standards library."
    source = LibrarySource(
        source_type=title or "EOAT Standard Design Guidelines",
        document_name=title or "EOAT Standard Design Guidelines",
        section=standard.category or "Standards & Work Instructions",
        file_path=standard.path,
        modified=_file_mtime(path) if standard.path else 0.0,
    )
    return [
        InformationLibraryEntry(
            entry_id=_entry_id_from_parts("source-document", title, standard.path),
            entry_type="source_document",
            category="Source Document References",
            title=f"Source: {title}",
            summary=summary,
            key_takeaway="Open the source document when the library summary is not enough for an engineering decision.",
            sections=(
                InformationSection("What It Contains", (summary,)),
                InformationSection("How Atlas Uses It", ("Adds source-aware reference entries and links EOAT profiles to likely standards context.",)),
                InformationSection("When To Open It", ("Open before changing a standard, resolving a disputed interpretation, or preparing a handoff packet.",)),
            ),
            tags=("source", "standard", path.suffix.upper().lstrip(".") or "DOC"),
            related_pages=("Standards & Work Instructions", "Information Library"),
            source=source,
            tree_path=("Source Document References", "Indexed Standards", title),
            indexed_at=time.time(),
        )
    ]
    path = Path(standard.path)
    category = _standard_information_category(standard)
    suffix = path.suffix.upper().lstrip(".") or "DOC"
    tags = tuple(tag for tag in (standard.category, suffix, "standard", "read-only") if tag)
    title = standard.title or path.stem or "Untitled standard"
    summary = standard.snippet or "Open the source document for full guidance."
    tree_path = _standard_tree_path(standard, category)
    primary = InformationLibraryEntry(
        entry_id=_entry_id_from_parts(*tree_path, title, str(path)),
        title=standard.title or path.stem or "Untitled standard",
        category=category,
        summary=summary,
        body=_standard_information_body(title, summary, standard),
        source=path.name or standard.path,
        path=standard.path,
        source_section=standard.category or category,
        tags=tags,
        tree_path=tree_path,
        related=("Documentation requirements", "Fit Check confidence", "Photo documentation rules"),
        modified=_file_mtime(path),
        indexed_at=time.time(),
    )
    return [primary, *_text_document_section_entries(primary)]


def _standard_information_category(standard: StandardReference) -> str:
    category = (standard.category or "").casefold()
    title = (standard.title or "").casefold()
    if "eoat standard" in category or "standardization" in title or "eoat standard" in title:
        return "EOAT Standards"
    if "pm" in category or "maintenance" in category:
        return "PM / Inspection"
    if "sensor" in category:
        return "Sensors"
    if "vacuum" in category:
        return "Pneumatics / Vacuum / Grippers"
    if "quick" in category or "disconnect" in category:
        return "Quick Disconnects"
    if "documentation" in category:
        return "Documentation Requirements"
    return "EOAT Standards"


def _standard_tree_path(standard: StandardReference, category: str) -> tuple[str, ...]:
    folded = " ".join([standard.category, standard.title]).casefold()
    if "vacuum" in folded:
        return ("EOAT Standards", "Vacuum Standards")
    if "pneumatic" in folded or "tubing" in folded:
        return ("EOAT Standards", "Pneumatic Tubing / Routing")
    if "sensor" in folded:
        return ("EOAT Standards", "Sensors")
    if "quick" in folded or "disconnect" in folded:
        return ("EOAT Standards", "Quick Disconnects")
    if "gripper" in folded:
        return ("EOAT Standards", "Grippers")
    if "pm" in folded or "inspection" in folded or "maintenance" in folded:
        return ("PM / Inspection", "Monthly Checks")
    if "document" in folded or "standardization" in folded or "standard" in folded:
        return ("EOAT Standards", "Design Guidelines")
    if category == "Documentation Requirements":
        return ("EOAT Standards", "Documentation Requirements")
    return ("EOAT Standards", "Design Guidelines")


def _standard_information_body(title: str, summary: str, standard: StandardReference) -> str:
    return "\n\n".join(
        [
            f"Rule / standard: {summary}",
            "Purpose: Give EOAT users a reliable reference for design, documentation, inspection, and setup decisions without digging through project folders.",
            "When it applies: Review this standard when an EOAT profile shows missing construction, pneumatic/vacuum/gripper, sensor, photo, compatibility, or documentation fields.",
            "Related Atlas areas: EOAT profile readiness, Standards & Work Instructions, Information Library, PM / Inspection, photo category warnings, and compatibility confidence warnings.",
            f"Source: {standard.path or standard.title}",
        ]
    )


def _text_document_section_entries(primary: InformationLibraryEntry) -> list[InformationLibraryEntry]:
    path = Path(primary.path)
    if path.suffix.casefold() not in {".md", ".txt"}:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    sections = _split_text_sections(text)
    entries = []
    for index, (section_title, content) in enumerate(sections[:80], start=1):
        if len(content.strip()) < 24:
            continue
        title = section_title or f"{primary.title} section {index}"
        summary = _short_label(" ".join(content.split()), 240)
        body = "\n\n".join(
            [
                content.strip(),
                "What this means: Use this source section as standards context when reviewing EOAT readiness, warnings, photos, and compatibility details.",
                f"Related source document: {primary.source}",
            ]
        )
        entries.append(
            replace(
                primary,
                entry_id=_entry_id_from_parts(primary.entry_id, str(index), title),
                title=title,
                summary=summary,
                body=body,
                source_section=section_title or primary.source_section,
                tags=(*primary.tags, "source section"),
            )
        )
    return entries


def _split_text_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        is_heading = line.startswith("#") or (line and len(line) < 90 and line.endswith(":"))
        if is_heading and current_lines:
            sections.append((current_title, current_lines))
            current_lines = []
        if is_heading:
            current_title = line.lstrip("#").strip().rstrip(":") or current_title
        else:
            current_lines.append(raw_line)
    if current_lines:
        sections.append((current_title, current_lines))
    return [(title, "\n".join(lines).strip()) for title, lines in sections if "\n".join(lines).strip()]


def _warning_information_entry(warning, *, title_prefix: str = "") -> InformationLibraryEntry:
    title = f"{title_prefix}: {warning.title}" if title_prefix else (warning.title or "Atlas warning")
    symptom = warning.message or warning.title or "Atlas warning generated from source validation."
    source_name = warning.source or "Atlas internal reference"
    return InformationLibraryEntry(
        entry_id=_entry_id_from_parts("warning", title, source_name, warning.related_eoat_id, warning.machine, warning.tool),
        entry_type="troubleshooting",
        category="Troubleshooting",
        title=title,
        summary=symptom,
        key_takeaway=warning.suggested_fix or "Repair the source condition named by the warning, then refresh Atlas.",
        sections=(
            InformationSection("Symptom", (symptom,)),
            InformationSection(
                "Likely Causes",
                (warning.why_it_matters or "A source value, path, or relationship did not pass Atlas validation.",),
            ),
            InformationSection("Checks To Run", ("Open the related profile or Settings source status.", "Check the source named in metadata.")),
            InformationSection("Fix Steps", (warning.suggested_fix or "Repair the source data and refresh Atlas.",)),
        ),
        tags=tuple(
            value
            for value in (warning.severity, warning.source, warning.related_eoat_id, warning.machine, warning.tool)
            if value
        ),
        related_fields=tuple(value for value in (warning.related_eoat_id, warning.machine, warning.tool) if value),
        related_pages=("EOAT Profiles", "Machine Profiles", "Settings / Diagnostics"),
        source=LibrarySource(source_type=source_name, document_name=source_name),
        tree_path=("Troubleshooting", "Live Atlas Warnings", warning.title or title),
        indexed_at=time.time(),
    )
    title = f"{title_prefix}: {warning.title}" if title_prefix else warning.title
    pieces = [warning.message, warning.why_it_matters, warning.suggested_fix]
    summary = " ".join(piece for piece in pieces if piece) or "Review source data for this warning."
    body = "\n\n".join(
        [
            f"Issue: {warning.message or warning.title}",
            f"Why it matters: {warning.why_it_matters or 'This can affect search, compatibility confidence, install readiness, or standards cleanup.'}",
            f"Suggested fix: {warning.suggested_fix or 'Review the source workbook, Robot Info, photo index, or standards reference connected to this warning.'}",
            f"Related EOAT: {warning.related_eoat_id or title_prefix or '-'}",
            f"Related machine/tool: {warning.machine or '-'} / {warning.tool or '-'}",
        ]
    )
    tags = tuple(
        value
        for value in (
            warning.severity,
            warning.source,
            warning.related_eoat_id,
            warning.machine,
            warning.tool,
        )
        if value
    )
    return InformationLibraryEntry(
        entry_id=_entry_id_from_parts("warning", title, warning.source, warning.related_eoat_id, warning.machine, warning.tool),
        title=title or "Atlas warning",
        category="Troubleshooting",
        summary=summary,
        body=body,
        source=warning.source or "Atlas data checks",
        tags=tags,
        tree_path=("Troubleshooting", "Missing Source Files" if "missing" in summary.casefold() else "No Fit Check Match Found"),
        related=("Documentation requirements", "Fit Check confidence", "Source status"),
        indexed_at=time.time(),
    )


def _information_score(entry: InformationLibraryEntry, query: str) -> int:
    return information_score(entry, query)


def _information_card(entry: InformationLibraryEntry) -> QWidget:
    card = DetailCard(entry.title, entry.summary, eyebrow=entry_type_label(entry.entry_type))
    card.layout.addWidget(
        _chip_group([entry.category, entry.source.source_type, *entry.tags[:5]], kind="outline", per_row=5, limit=8)
    )
    source = entry.path or entry.source.document_name
    source_label = QLabel(_short_path(source) if entry.path else source)
    source_label.setObjectName("MicroText")
    source_label.setWordWrap(True)
    source_label.setToolTip(source)
    card.layout.addWidget(source_label)
    buttons = []
    if entry.source.file_exists:
        open_button = QPushButton("Open Source Document")
        open_button.clicked.connect(lambda _checked=False, path=entry.path: open_path(path))
        buttons.append(open_button)
    copy_button = QPushButton("Copy Summary")
    copy_button.clicked.connect(lambda _checked=False, text=f"{entry.title}\n\n{entry.summary}": QApplication.clipboard().setText(text))
    buttons.append(copy_button)
    card.layout.addWidget(action_row(*buttons))
    return card


def _library_tree_path_for_entry(entry: InformationLibraryEntry) -> tuple[str, ...]:
    parts = [part.strip() for part in (entry.tree_path or (entry.category,)) if str(part).strip()]
    collapsed: list[str] = []
    for part in parts:
        if collapsed and collapsed[-1].casefold() == part.casefold():
            continue
        collapsed.append(part)
    if collapsed and collapsed[-1].casefold() == entry.title.casefold():
        collapsed.pop()
    return tuple(collapsed)


def _information_section_block(title: str, text: str | tuple[str, ...] | list[str]) -> QWidget:
    block = QWidget()
    layout = QVBoxLayout(block)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(3)
    title_label = QLabel(title)
    title_label.setObjectName("DetailTitle")
    body = QLabel(_information_text(text))
    body.setObjectName("BodyText")
    body.setWordWrap(True)
    layout.addWidget(title_label)
    layout.addWidget(body)
    return block


def _information_text(text: str | tuple[str, ...] | list[str]) -> str:
    if isinstance(text, tuple | list):
        items = [str(item).strip() for item in text if str(item).strip()]
        if not items:
            return "Not applicable"
        if len(items) == 1:
            return items[0]
        return "\n".join(f"- {item}" for item in items)
    return str(text or "Not applicable")


def _information_list_block(items: tuple[str, ...] | list[str]) -> QWidget:
    return _information_section_block("Review", tuple(items))


def _information_example_block(example) -> QWidget:
    block = DetailCard(example.title)
    if example.inputs:
        block.layout.addWidget(_information_section_block("Input", example.inputs))
    if example.logic:
        block.layout.addWidget(_information_section_block("Logic", example.logic))
    if example.outputs:
        block.layout.addWidget(_information_section_block("Output", example.outputs))
    return block


def _information_detail_sections(entry: InformationLibraryEntry) -> list[tuple[str, str]]:
    return [(section.title, _information_text(section.items)) for section in entry.sections]


def _app_help_detail_sections(entry: InformationLibraryEntry) -> list[tuple[str, str]]:
    title = entry.title
    related_pages = _related_pages_text(entry, "Home / Command Deck, What Do I Need?, Settings / Diagnostics")
    return [
        ("What this page does", entry.summary),
        ("When to use it", _app_help_when_to_use(title)),
        ("How to use it", _app_help_how_to_use(title)),
        ("What the results mean", _app_help_results_meaning(title)),
        ("Related actions", _related_actions_for_entry(entry)),
        ("Common troubleshooting notes", _troubleshooting_note_for_entry(entry)),
        ("Related Atlas pages/features", related_pages),
    ]


def _standard_detail_sections(entry: InformationLibraryEntry) -> list[tuple[str, str]]:
    title_text = f"{entry.title} {entry.summary} {' '.join(entry.tags)}".casefold()
    topic = _standard_topic(title_text)
    return [
        ("Standard / Rule", entry.summary or f"Use {entry.title} as a read-only EOAT standards reference."),
        ("What it means", _standard_meaning(topic, entry)),
        ("Why it matters", _standard_why(topic)),
        ("What to check in the EOAT audit", _standard_checks(topic)),
        ("Related fields/pages", _standard_related_fields(topic)),
        ("Common warning signs", _standard_warning_signs(topic)),
        ("Source", entry.path or entry.source.document_name or "Atlas standards index"),
    ]


def _warning_detail_sections(entry: InformationLibraryEntry) -> list[tuple[str, str]]:
    return [
        ("Issue", entry.summary),
        ("Why it matters", _extract_body_value(entry.body, "Why it matters") or "This can affect search, compatibility confidence, install readiness, or standards cleanup."),
        ("Suggested fix", _extract_body_value(entry.body, "Suggested fix") or "Review the source workbook, standards reference, photo folder, or Atlas warning context."),
        ("Related standard", "Documentation Requirements and Fit Check Confidence are the usual first standards to review."),
        ("Related source workbook/report", entry.path or entry.source.document_name or "Atlas data checks"),
        ("Related Atlas page", _related_pages_text(entry, "Information Library, EOAT Profiles, Machine Profiles, Settings / Diagnostics")),
    ]


def _general_detail_sections(entry: InformationLibraryEntry) -> list[tuple[str, str]]:
    return [
        ("Summary", entry.summary),
        ("Practical explanation", entry.body or "Use this reference to understand the selected Atlas information item."),
        ("When this applies", "Use this when the selected topic appears in an EOAT profile, machine profile, standards document, report, or troubleshooting workflow."),
        ("Why it matters", "Clear reference context helps users make fast read-only decisions without guessing from workbook rows."),
        ("Related Atlas pages/features", _related_pages_text(entry, "Information Library")),
        ("Source", entry.path or entry.source.document_name or "Atlas generated guidance"),
    ]


def _standard_topic(text: str) -> str:
    if "tubing" in text or "pneumatic" in text or "routing" in text:
        return "tubing"
    if "vacuum" in text or "cup" in text:
        return "vacuum"
    if "sensor" in text or "signal" in text:
        return "sensors"
    if "quick" in text or "disconnect" in text or "connection" in text:
        return "disconnects"
    if "gripper" in text:
        return "grippers"
    if "mount" in text or "hardware" in text or "fastener" in text:
        return "hardware"
    if "photo" in text:
        return "photos"
    if "document" in text or "score" in text:
        return "documentation"
    return "general"


def _standard_meaning(topic: str, entry: InformationLibraryEntry) -> str:
    meanings = {
        "tubing": "Tubing should be secured, readable, and able to move through robot motion without kinking, rubbing, pinching, or pulling on fittings.",
        "vacuum": "Vacuum cups and circuits should be visible, documented, and inspected for wear, leaks, cracked cups, missing fittings, and unclear circuit routing.",
        "sensors": "Sensors and confirmation signals should be identified clearly enough that setup and troubleshooting can verify the EOAT state quickly.",
        "disconnects": "Quick disconnects and connection types should be documented so the correct pneumatic/electrical setup can be confirmed before install.",
        "grippers": "Gripper style, contact points, wear items, and adjustment context should be visible in source fields or photos.",
        "hardware": "Mounting hardware and fasteners should be secure, visible, and consistent with the EOAT setup so repeat installs are reliable.",
        "photos": "Required photo categories should make the EOAT understandable without opening the source folder first.",
        "documentation": "Required fields should be complete enough for Atlas to answer identity, compatibility, readiness, and warning questions quickly.",
    }
    return meanings.get(topic, entry.body or "Use this standard as practical context for EOAT design, documentation, inspection, and setup decisions.")


def _standard_why(topic: str) -> str:
    reasons = {
        "tubing": "Poor routing can cause vacuum or pressure loss, intermittent failures, premature tubing wear, and setup delays.",
        "vacuum": "Vacuum issues are common install and handling failure points, so missing or unclear vacuum context lowers readiness confidence.",
        "sensors": "Unclear sensor information can cause false ready states, missed part confirmation, and harder machine troubleshooting.",
        "disconnects": "Incorrect or undocumented connections create setup mistakes and slow changeovers.",
        "grippers": "Gripper wear or undocumented contact points can affect part handling and repeatability.",
        "hardware": "Loose or undocumented hardware can create safety, reliability, and setup-repeatability risks.",
        "photos": "Good photos reduce guessing and make profiles useful within seconds.",
        "documentation": "Missing fields reduce lookup quality and make compatibility answers harder to trust.",
    }
    return reasons.get(topic, "A clear standard reduces setup uncertainty, improves PM consistency, and supports faster EOAT reuse.")


def _standard_checks(topic: str) -> str:
    checks = {
        "tubing": "Check wrist rotation, C-flip motion, strain relief, bend radius, rubbing points, pinch points, heat exposure, and quick-disconnect routing.",
        "vacuum": "Check cup condition, circuit routing, fittings, vacuum notes, pressure notes, missing category photos, and known handling issues.",
        "sensors": "Check sensor type, wiring/cable routing, confirmation logic, robot/machine context, and sensor photo categories.",
        "disconnects": "Check connection type, fitting condition, labels, routing, matching machine/robot context, and install notes.",
        "grippers": "Check gripper type, jaw/contact condition, adjustment points, spare/wear parts, and photos showing contact areas.",
        "hardware": "Check mounting bolts, brackets, missing fasteners, loose hardware, witness marks, and photos of the EOAT mount.",
        "photos": "Check overall, front, side/rear, connection, pneumatic/vacuum/gripper, and sensor photo categories.",
        "documentation": "Check EOAT ID, Tool #, machine compatibility, EOAT type/status, robot info, pneumatic/vacuum/gripper info, sensors, photos, and warnings.",
    }
    return checks.get(topic, "Check the related EOAT profile fields, warning cards, photos, and source standards before relying on the item.")


def _standard_related_fields(topic: str) -> str:
    fields = {
        "tubing": "Fields/pages: Tubing Notes, Vacuum Info, Pressure Info, Connection Type, EOAT Profiles, Photos, PM / Inspection.",
        "vacuum": "Fields/pages: Vacuum Info, Pressure Info, Gripper Info, Known Issues, EOAT Profiles, Photos, PM / Inspection.",
        "sensors": "Fields/pages: Sensor Info, Robot Info, Machine Profiles, EOAT Profiles, Photos, PM / Inspection.",
        "disconnects": "Fields/pages: Connection Type, Robot Info, Machine Profiles, EOAT Profiles, Photos.",
        "grippers": "Fields/pages: EOAT Type, Gripper Info, Known Issues, EOAT Profiles, Photos, PM / Inspection.",
        "hardware": "Fields/pages: EOAT Construction/Type, Install Notes, Known Issues, Photos, PM / Inspection.",
        "photos": "Fields/pages: Photo folder, missing photo categories, EOAT Profiles, Photos page, Standards & Work Instructions.",
        "documentation": "Fields/pages: EOAT ID, Tool #, Machine #, EOAT Type, Status, Robot Info, Documentation Score, Warnings.",
    }
    return fields.get(topic, "Fields/pages: EOAT Profiles, Machine Profiles, Photos, Standards & Work Instructions, Information Library.")


def _standard_warning_signs(topic: str) -> str:
    warnings = {
        "tubing": "Missing tubing notes, unclear photo coverage, visible kinks/rub points, or repeated vacuum/pressure warnings.",
        "vacuum": "No vacuum notes, missing cup photos, low photo count, known handling issues, or low documentation score.",
        "sensors": "Missing sensor info, missing robot info, no sensor photos, or uncertain machine compatibility.",
        "disconnects": "Missing connection type, unclear fittings, missing machine/robot context, or setup notes that conflict.",
        "grippers": "Missing gripper info, poor contact photos, known issues, or no wear/inspection context.",
        "hardware": "Missing mounting photos, loose/missing fastener notes, known install issues, or low readiness score.",
        "photos": "Folder missing, zero photos, missing required categories, or photos that do not show connections/circuits.",
        "documentation": "Critical missing fields, no tool/machine links, missing Robot Info, or low documentation score.",
    }
    return warnings.get(topic, "Watch for missing fields, low documentation score, missing photos, and compatibility uncertainty.")


def _app_help_when_to_use(title: str) -> str:
    folded = title.casefold()
    if "what do i need" in folded:
        return "Use it when you know any tool, machine, EOAT ID, part, mold, robot type, or keyword and need the best install recommendation."
    if "eoat" in folded and "profile" in folded:
        return "Use it when you need to inspect one EOAT's compatibility, readiness, photos, warnings, and technical context."
    if "machine" in folded:
        return "Use it when you need robot context and the EOATs/tools that can run on a machine."
    if "photo" in folded:
        return "Use it when you need photo coverage, missing categories, folder status, or in-app carousel viewing."
    if "settings" in folded:
        return "Use it when changing theme, color scheme, startup behavior, photo loading behavior, or diagnostics visibility."
    return "Use it when the page directly answers the identifier, compatibility, photo, standards, report, or diagnostics question in front of you."


def _app_help_how_to_use(title: str) -> str:
    folded = title.casefold()
    if "what do i need" in folded:
        return "Type the known identifier, review the best recommendation first, then use profile actions to open EOAT, photos, tool, or machine context."
    if "profile" in folded:
        return "Filter the left selector, choose a record, and scan the header, compatibility, readiness, photo, warning, and detail sections in order."
    if "matrix" in folded:
        return "Pick the matrix mode, filter by identifier, sort rows, and export only when dense comparison is useful."
    if "settings" in folded:
        return "Change one setting at a time; preferences persist per user and apply immediately where practical."
    return "Use the search/filter controls first, then open the relevant card, profile, source document, or export action."


def _app_help_results_meaning(title: str) -> str:
    folded = title.casefold()
    if "what do i need" in folded:
        return "Scores rank fit and readiness; warnings and missing photos tell you what to check before staging."
    if "photo" in folded:
        return "Photo counts and category chips show coverage; viewer failures explain decode/support issues and keep external-open options available."
    if "settings" in folded:
        return "Settings affect Atlas presentation and photo loading behavior only; they do not modify source workbooks or photo folders."
    return "Atlas shows cached source evidence with provenance, warnings, and refresh timing so the user can judge confidence."


def _related_actions_for_entry(entry: InformationLibraryEntry) -> str:
    folded = entry.title.casefold()
    if "photo" in folded:
        return "View Photos, Open Photo Folder, Open Externally, Clear Photo Cache, adjust Photo Preload Mode."
    if "what do i need" in folded:
        return "Open EOAT Profile, View Photos, Open Related Tool, Open Related Machine, Export Recommendation."
    if "settings" in folded:
        return "Change Theme Mode, Color Scheme, Photo Preload Mode, Clear Photo Cache, Refresh Data."
    if "report" in folded or "export" in folded:
        return "Export compatibility, documentation, photo coverage, EOAT, machine, or recommendation summaries."
    return "Open the most relevant profile, inspect the warning source, open the named standard, or refresh the cache after source repair."


def _troubleshooting_note_for_entry(entry: InformationLibraryEntry) -> str:
    folded = f"{entry.title} {entry.summary}".casefold()
    if "photo" in folded or "heic" in folded:
        return "If a preview fails, use the in-view message first. HEIC/HEIF may require Pillow plus pillow-heif; Open Folder and Open Externally remain available."
    if "compat" in folded or "search" in folded:
        return "If a result is missing, refresh data and check normalized EOAT ID, Tool #, Machine #, Robot Info, and Press Capacity rows."
    return "If the information looks stale, use Refresh Data and verify the relevant source workbook, standards folder, or photo folder exists."


def _related_pages_text(entry: InformationLibraryEntry, fallback: str) -> str:
    if entry.related:
        return ", ".join(entry.related)
    if entry.tree_path:
        return ", ".join(entry.tree_path)
    return fallback


def _extract_body_value(body: str, label: str) -> str:
    prefix = f"{label}:"
    for line in body.splitlines():
        if line.strip().casefold().startswith(prefix.casefold()):
            return line.split(":", 1)[1].strip()
    return ""


def _entry_id_from_parts(*parts: str) -> str:
    raw = "|".join(str(part) for part in parts if str(part).strip())
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in raw)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:140] or "library-entry"


def _tree_label_parts(path: tuple[str, ...]) -> list[str]:
    return [part for part in path if part]


def _format_modified(value: float) -> str:
    if not value:
        return "Not applicable"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(value))


def _information_reference_text(entry: InformationLibraryEntry) -> str:
    pieces = [
        entry.title,
        "",
        entry.summary,
        "",
        f"Entry type: {entry_type_label(entry.entry_type)}",
        f"Key takeaway: {entry.key_takeaway}",
        "",
        entry.body,
        "",
        f"Category: {entry.category}",
        f"Tree path: {' / '.join(entry.tree_path) or entry.category}",
        f"Source type: {entry.source.source_type}",
        f"Source document: {entry.source.document_name}",
        f"Source section: {entry.source.section_label}",
        f"File: {entry.source.file_label}",
        f"Last modified: {entry.source.modified_label}",
    ]
    if entry.tags:
        pieces.append(f"Tags: {', '.join(entry.tags)}")
    return "\n".join(piece for piece in pieces if piece is not None)


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _machine_hero_section(machine: MachineRecord) -> QWidget:
    section = ProfileHeaderCard(f"Machine {machine.machine}", machine.robot_type or machine.robot_model or "Robot info missing", eyebrow="Machine Profile")
    chips = [
        f"{len(machine.compatible_eoats)} compatible EOAT(s)",
        f"{len(machine.compatible_tools)} compatible tool(s)",
        f"{machine.documentation_score}% documentation",
        f"{machine.warning_count} warning(s)",
    ]
    if machine.current_eoat:
        chips.insert(0, f"Current EOAT {machine.current_eoat}")
    section.layout.addWidget(
        _chip_group(
            chips,
            kind="info",
            per_row=4,
        )
    )
    return section


def _machine_compatibility_section(machine: MachineRecord) -> QWidget:
    section = CompatibilityCard("Fit Check", "Machine relationships from Atlas cached indexes.")
    section.layout.addWidget(_labeled_chips("Compatible EOATs", machine.compatible_eoats, empty="No linked EOATs", per_row=6))
    section.layout.addWidget(_labeled_chips("Compatible Tools", machine.compatible_tools, empty="No linked tools", per_row=6))
    section.layout.addWidget(_labeled_chips("Compatible Parts", machine.compatible_parts[:24], empty="No linked parts", per_row=4))
    return section


def _machine_technical_section(machine: MachineRecord) -> QWidget:
    section = DetailCard("Machine / Robot Info", "Reference metadata kept quieter than compatibility and warnings.")
    section.layout.addWidget(
        key_value_grid(
            [
                ("Machine", machine.machine),
                ("Robot Type", machine.robot_type),
                ("Robot Model", machine.robot_model),
                ("Controller", machine.controller),
                ("Documentation", f"{machine.documentation_score}%"),
            ]
        )
    )
    return section


def _machine_warnings_section(machine: MachineRecord) -> QWidget:
    if not machine.warnings:
        return SuccessCard("No machine warnings", "Atlas did not find open machine data gaps for this record.")
    section, section_layout = _group_container("Warnings / Data Gaps", "Action items that can affect machine compatibility confidence.")
    for warning in machine.warnings[:10]:
        section_layout.addWidget(
            _warning_block(
                warning.title,
                warning.message,
                warning.why_it_matters or "This can affect machine compatibility confidence.",
                warning.suggested_fix or "Review Robot Info or source workbook data.",
                _warning_kind(warning.severity),
            )
        )
    return section


def _tool_hero_section(tool: ToolRecord) -> QWidget:
    subtitle = tool.part_description or tool.part_family or ", ".join(tool.parts[:4]) or "No part description recorded"
    section = ProfileHeaderCard(f"Tool {tool.tool}", subtitle, eyebrow="Tool / Mold / Part")
    section.layout.addWidget(
        _chip_group(
            [
                f"{len(tool.compatible_machines)} compatible machine(s)",
                f"{len(tool.compatible_eoats)} compatible EOAT(s)",
                f"{tool.warning_count} warning(s)",
                tool.source or "Atlas cached index",
            ],
            kind="info",
            per_row=4,
        )
    )
    return section


def _tool_compatibility_section(tool: ToolRecord) -> QWidget:
    section = CompatibilityCard("Fit Check", "Cached Tool -> EOAT -> Machine relationships.")
    section.layout.addWidget(_labeled_chips("Compatible EOATs", tool.compatible_eoats, empty="Missing EOAT link", per_row=6))
    section.layout.addWidget(_labeled_chips("Compatible Machines", tool.compatible_machines, empty="No linked machines", per_row=6))
    section.layout.addWidget(_labeled_chips("Parts / molds", (*tool.parts[:12], *tool.molds[:8]), empty="No part or mold metadata", per_row=4))
    return section


def _tool_source_section(tool: ToolRecord) -> QWidget:
    section = DetailCard("Source Metadata", "Reference fields from cached Atlas source indexes.")
    section.layout.addWidget(
        key_value_grid(
            [
                ("Tool number", tool.tool),
                ("Part description", tool.part_description),
                ("Part family", tool.part_family),
                ("Molds", ", ".join(tool.molds)),
                ("Source", tool.source or "Atlas cached index"),
                ("Source rows", str(len(tool.source_rows))),
            ]
        )
    )
    return section


def _tool_warning_section(tool: ToolRecord) -> QWidget:
    if not tool.warnings:
        return SuccessCard("No tool warnings", "Atlas did not find open tool compatibility warnings for this record.")
    section, section_layout = _group_container("Warnings / Actions", "Review compatibility gaps before using this tool.")
    for warning in tool.warnings[:10]:
        section_layout.addWidget(
            _warning_block(
                warning.title,
                warning.message,
                warning.why_it_matters or "This can affect tool-to-EOAT or tool-to-machine compatibility confidence.",
                warning.suggested_fix or "Review Press Capacity, EOAT Tracker, or source compatibility rows.",
                _warning_kind(warning.severity),
            )
        )
    return section


def _tool_action_section(tool: ToolRecord, page: ToolSearchPage) -> QWidget:
    section = DetailCard("Tool Actions", "Jump to linked records or create a focused summary.")
    buttons = []
    recommendation = QPushButton("Run What Do I Need?")
    recommendation.setObjectName("PrimaryButton")
    recommendation.clicked.connect(page.run_current_recommendation)
    buttons.append(recommendation)
    eoat_button = QPushButton("Open Compatible EOAT Profile")
    eoat_button.setEnabled(bool(tool.compatible_eoats))
    eoat_button.clicked.connect(page.open_related_eoat)
    buttons.append(eoat_button)
    machine_button = QPushButton("Open Compatible Machine Profile")
    machine_button.setEnabled(bool(tool.compatible_machines))
    machine_button.clicked.connect(page.open_related_machine)
    buttons.append(machine_button)
    compare_button = QPushButton("Remove from Compare" if normalized_tool_key(tool.tool) in page.compare_keys else "Add to Compare")
    compare_button.clicked.connect(page.toggle_compare_current)
    buttons.append(compare_button)
    export_button = QPushButton("Export Tool Summary")
    export_button.clicked.connect(page.export_current_tool)
    buttons.append(export_button)
    packet_button = QPushButton("Changeover Packet")
    packet_button.clicked.connect(page.generate_install_packet)
    buttons.append(packet_button)
    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(8)
    for index, button in enumerate(buttons):
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        grid.addWidget(button, index // 3, index % 3)
    for column in range(3):
        grid.setColumnStretch(column, 1)
    section.layout.addLayout(grid)
    return section


def _eoat_hero_section(eoat: EOATRecord) -> QWidget:
    section = ProfileHeaderCard(eoat.eoat_id, _first_present(eoat.part_description, eoat.part_family, "Engineering profile"), eyebrow="EOAT Profile")
    section.layout.addWidget(
        _chip_group(
            [
                eoat.eoat_type or "Type missing",
                eoat.status or "Status missing",
                _compatibility_status(eoat)[0],
            ],
            kind="info",
            per_row=3,
        )
    )

    metrics = QWidget()
    grid = QGridLayout(metrics)
    grid.setContentsMargins(0, 2, 0, 0)
    grid.setSpacing(8)
    values = [
        ("Documentation", f"{eoat.documentation.score}%", eoat.documentation.status_label),
        ("Photos", str(eoat.photo_count), "Linked images"),
        ("Warnings", str(eoat.warning_count), "Open data gaps"),
    ]
    for index, (label, value, note) in enumerate(values):
        grid.addWidget(_profile_metric(label, value, note), 0, index)
    section.layout.addWidget(metrics)
    section.layout.addWidget(_labeled_chips("Main compatible Tool #s", eoat.tools, empty="No linked tools", per_row=6))
    section.layout.addWidget(_labeled_chips("Main compatible Machines", eoat.machines, empty="No linked machines", per_row=6))
    return section


def _profile_metric(label: str, value: str, note: str) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(1)
    value_label = QLabel(value)
    value_label.setObjectName("ProfileMetricValue")
    label_text = QLabel(label)
    label_text.setObjectName("ProfileMetricLabel")
    note_text = QLabel(note)
    note_text.setObjectName("MutedText")
    note_text.setWordWrap(True)
    layout.addWidget(value_label)
    layout.addWidget(label_text)
    layout.addWidget(note_text)
    return widget


def _eoat_compatibility_section(eoat: EOATRecord) -> QWidget:
    section = CompatibilityCard("Fit Check", "Tool -> EOAT -> Machine relationships.")
    status_text, status_kind = _compatibility_status(eoat)
    section.layout.addWidget(_chip_group([status_text], kind=status_kind, per_row=3))
    if not eoat.tools:
        section.layout.addWidget(_chip_group(["Missing tool compatibility"], kind="bad", per_row=3))
    if not eoat.machines:
        section.layout.addWidget(_chip_group(["Missing machine compatibility"], kind="bad", per_row=3))
    if not eoat.robot_types and not eoat.robot_models:
        section.layout.addWidget(_chip_group(["Missing robot info"], kind="warn", per_row=3))

    tools = list(eoat.tools[:5]) or ["Missing Tool #"]
    machines = list(eoat.machines[:8])
    for tool in tools:
        section.layout.addWidget(CompatibilityPathWidget("" if tool == "Missing Tool #" else tool, eoat.eoat_id, machines))
    if len(eoat.tools) > 5:
        section.layout.addWidget(badge(f"+{len(eoat.tools) - 5} more tools", "info"))
    return section


def _eoat_readiness_section(eoat: EOATRecord) -> QWidget:
    items = _readiness_items(eoat)
    score = round(sum(item["points"] for item in items) / max(len(items), 1) * 100)
    return ReadinessScoreWidget(score, _readiness_summary(score), items)


def _eoat_photo_section(eoat: EOATRecord) -> QWidget:
    section = PhotoGalleryCard("Photo Evidence", "Lazy thumbnail strip and missing-category signal.")
    photos = _combined_photos(eoat)
    section.layout.addWidget(
        _chip_group(
            [f"{eoat.photo_count} linked photo(s)", f"Folder: {'found' if eoat.photos.folder_exists else 'missing'}"],
            kind="good" if eoat.photo_count else "warn",
            per_row=3,
        )
    )
    if eoat.photos.missing_categories:
        section.layout.addWidget(
            _labeled_chips("Missing photo categories", eoat.photos.missing_categories, kind="warn", per_row=4)
        )
    else:
        section.layout.addWidget(_chip_group(["No required photo category gaps detected"], kind="good", per_row=3))

    strip = QWidget()
    row = QHBoxLayout(strip)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(PhotoStripWidget([photo.path for photo in photos], max_items=8, thumb_size=(118, 88)))
    section.layout.addWidget(strip)
    return section


def _eoat_applicable_standards_section(eoat: EOATRecord) -> QWidget:
    count = len(eoat.standards)
    section = SecondaryCard(f"Applicable Standards ({count})", "Standards inferred from EOAT type, documentation, photos, and indexed references.")
    section.layout.addWidget(badge(f"Standards: {count}", "unknown" if count == 0 else "review"))
    toggle = QToolButton()
    toggle.setText("Show applicable standards")
    toggle.setCheckable(True)
    toggle.setChecked(False)
    toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    body = QWidget()
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 0, 0)
    body_layout.setSpacing(8)
    if not eoat.standards:
        body_layout.addWidget(EmptyStateWidget("No applicable standards indexed", "Atlas did not find a standards document tied to this EOAT."))
    for standard in eoat.standards:
        card = DetailCard(standard.title or "Untitled standard", standard.category or "Uncategorized")
        status, kind = _standard_status_for_eoat(standard, eoat)
        rows = [
            ("Standard name", standard.title),
            ("Category", standard.category or "Uncategorized"),
            ("Why it applies", _standard_applies_reason(standard, eoat)),
            ("Status for this EOAT", status),
            ("Source document/report path", standard.path or "Not indexed"),
        ]
        card.layout.addWidget(badge(status, kind))
        card.layout.addWidget(key_value_grid(rows))
        body_layout.addWidget(card)
    body.setVisible(False)
    toggle.toggled.connect(body.setVisible)
    section.layout.addWidget(toggle)
    section.layout.addWidget(body)
    return section


def _standard_status_for_eoat(standard: StandardReference, eoat: EOATRecord) -> tuple[str, str]:
    folded = f"{standard.title} {standard.category}".casefold()
    if "photo" in folded or "documentation" in folded:
        if eoat.photo_count <= 0:
            return "Missing photos", "missing"
        if eoat.documentation.score < 75:
            return "Review", "review"
    if eoat.documentation.score < 50:
        return "Review", "review"
    return "OK", "verified"


def _standard_applies_reason(standard: StandardReference, eoat: EOATRecord) -> str:
    folded = f"{standard.title} {standard.category}".casefold()
    eoat_text = " ".join(
        [
            eoat.eoat_type,
            eoat.vacuum_info,
            eoat.pressure_info,
            eoat.gripper_info,
            eoat.sensor_info,
            eoat.connection_type,
            eoat.tubing_notes,
        ]
    ).casefold()
    if "tube" in folded or "routing" in folded or "pneumatic" in folded:
        return "Applies because EOAT uses pneumatic lines or tubing/routing information."
    if "vacuum" in folded or "cup" in folded:
        return "Applies because EOAT type or notes indicate vacuum/cup handling."
    if "disconnect" in folded or "quick" in folded:
        return "Applies because EOAT has pneumatic/electrical disconnect context."
    if "sensor" in folded:
        return "Applies because EOAT has sensor or part-present context."
    if "pm" in folded or "inspection" in folded or "maintenance" in folded:
        return "Applies to all active EOATs for recurring inspection and maintenance readiness."
    if "doc" in folded or "standard" in folded:
        return "Applies to all EOATs as documentation, CAD/BOM, photo, and revision guidance."
    if any(token in eoat_text for token in ("vacuum", "pneumatic", "sensor", "disconnect", "gripper")):
        return "Applies because this EOAT has matching technical context in its profile."
    return "Applies as a general EOAT design, setup, documentation, or inspection reference."


def _eoat_technical_details(eoat: EOATRecord, *, columns: int = 1) -> QWidget:
    container = QWidget()
    layout = QGridLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    groups = [
        (
            "Tool / Part Info",
            "Tooling",
            [
                ("Tools", ", ".join(eoat.tools)),
                ("Molds", ", ".join(eoat.molds)),
                ("Parts", ", ".join(eoat.parts)),
                ("Part Family", eoat.part_family),
                ("Part Description", eoat.part_description),
            ],
        ),
        (
            "Machine / Robot Info",
            "Robot",
            [
                ("Machines", ", ".join(eoat.machines)),
                ("Robot Types", ", ".join(eoat.robot_types)),
                ("Robot Models", ", ".join(eoat.robot_models)),
                ("Connection", eoat.connection_type),
            ],
        ),
        (
            "EOAT Construction / Type",
            "Build",
            [
                ("EOAT Type", eoat.eoat_type),
                ("Status", eoat.status),
                ("Install Notes", eoat.install_notes),
                ("Known Issues", eoat.known_issues),
            ],
        ),
        (
            "Pneumatic / Vacuum / Gripper Info",
            "Pneumatics",
            [
                ("Vacuum", eoat.vacuum_info),
                ("Pressure", eoat.pressure_info),
                ("Gripper", eoat.gripper_info),
                ("Tubing Notes", eoat.tubing_notes),
            ],
        ),
        (
            "Sensors",
            "Signals",
            [
                ("Sensor Info", eoat.sensor_info),
            ],
        ),
        (
            "Documentation / Photos",
            "Evidence",
            [
                ("Documentation", f"{eoat.documentation.score}% - {eoat.documentation.status_label}"),
                ("Present Fields", ", ".join(eoat.documentation.present_fields[:12])),
                ("Missing Fields", ", ".join(eoat.documentation.missing_fields[:12])),
                ("Photo Folder", eoat.photos.folder_path),
                ("Applicable Standards", ", ".join(standard.title for standard in eoat.standards[:6])),
            ],
        ),
        (
            "Warnings / Data Gaps",
            "Review",
            [
                ("Open Warnings", str(eoat.warning_count)),
                ("Critical Missing Fields", ", ".join(eoat.documentation.critical_missing_fields)),
                ("Missing Photo Categories", ", ".join(eoat.photos.missing_categories)),
            ],
        ),
    ]
    column_count = max(1, min(2, columns))
    for index, (title, marker, values) in enumerate(groups):
        layout.addWidget(_detail_card(title, values, marker), index // column_count, index % column_count)
    for column in range(column_count):
        layout.setColumnStretch(column, 1)
    return container


def _eoat_warnings_section(eoat: EOATRecord) -> QWidget:
    if not eoat.warnings and not eoat.documentation.critical_missing_fields:
        return SuccessCard("No open EOAT warnings", "Documentation and compatibility checks did not find urgent gaps.")
    section, section_layout = _group_container("Warnings / Data Gaps", "Action items are separated from reference details.")
    for field in eoat.documentation.critical_missing_fields:
        section_layout.addWidget(
            _warning_block(
                "Critical documentation missing",
                f"{field} is not filled in.",
                "This can lower install confidence and make future lookup/reuse less reliable.",
                "Update the EOAT master tracker or audit row with this field.",
                "bad",
            )
        )
    for warning in eoat.warnings[:10]:
        section_layout.addWidget(
            _warning_block(
                warning.title,
                warning.message,
                warning.why_it_matters or "This can affect compatibility confidence, search quality, or install readiness.",
                warning.suggested_fix or "Review the source workbook, photo index, or EOAT Command Center record.",
                _warning_kind(warning.severity),
            )
        )
    if len(eoat.warnings) > 10:
        section_layout.addWidget(badge(f"+{len(eoat.warnings) - 10} more warnings", "warn"))
    return section


def _detail_card(title: str, values: list[tuple[str, str]], marker: str = "") -> QWidget:
    section = DetailCard(title, eyebrow=marker)
    section.layout.addWidget(_detail_value_grid(values))
    return section


def _detail_value_grid(values: list[tuple[str, str]]) -> QWidget:
    widget = QWidget()
    layout = QGridLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(14)
    layout.setVerticalSpacing(8)
    for row, (key, value) in enumerate(values):
        key_label = QLabel(key)
        key_label.setObjectName("MetricLabel")
        key_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(key_label, row, 0)
        layout.addWidget(_detail_value_widget(key, value), row, 1)
    layout.setColumnStretch(1, 1)
    return widget


def _detail_value_widget(key: str, value: str) -> QWidget:
    text = str(value or "").strip()
    folded_key = key.casefold()
    if not text:
        return badge("Not recorded", "warn" if "missing" in folded_key or "warning" in folded_key else "ghost")
    if folded_key in {
        "tools",
        "molds",
        "parts",
        "machines",
        "robot types",
        "robot models",
        "present fields",
        "missing fields",
        "critical missing fields",
        "missing photo categories",
        "applicable standards",
    }:
        kind = "warn" if "missing" in folded_key or "critical" in folded_key else ("primary" if "machine" in folded_key else "outline")
        return _chip_group(_split_values(text), kind=kind, empty="Not recorded", per_row=2, limit=8)
    if folded_key == "documentation":
        score_text = text.split("%", 1)[0]
        kind = _score_kind(int(score_text)) if score_text.isdigit() else "outline"
        return badge(text, kind)
    if folded_key == "status" or folded_key == "eoat type":
        return badge(text, "outline")
    label = QLabel(_short_path(text) if "folder" in folded_key or "path" in folded_key else text)
    label.setObjectName("BodyText")
    label.setWordWrap(True)
    label.setToolTip(text)
    return label


def _warning_block(title: str, what: str, why: str, fix: str, kind: str) -> QWidget:
    block = WarningCard(title or "Warning", severity="bad" if kind == "bad" else "warn")
    block.layout.addWidget(badge(kind.upper(), kind))
    block.layout.addWidget(
        key_value_grid(
            [
                ("What is missing", what),
                ("Why it matters", why),
            ]
        )
    )
    action = QLabel(fix)
    action.setObjectName("ActionText")
    action.setWordWrap(True)
    block.layout.addWidget(action)
    return block


def _labeled_chips(title: str, values, *, kind: str = "info", empty: str = "-", per_row: int = 4) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    label = QLabel(title)
    label.setObjectName("MetricLabel")
    layout.addWidget(label)
    layout.addWidget(_chip_group(values, kind=kind, empty=empty, per_row=per_row))
    return widget


def _checklist_row(marker: str, text: str, *, kind: str = "primary") -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.addWidget(badge(marker, "count"))
    body = QLabel(text)
    body.setObjectName("BodyText")
    body.setWordWrap(True)
    layout.addWidget(body, 1)
    layout.addWidget(badge("check", kind))
    return row


def _chip_group(values, *, kind: str = "info", empty: str = "-", per_row: int = 4, limit: int = 18) -> QWidget:
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
        chip = badge(_short_label(text), chip_kind)
        chip.setToolTip(text)
        layout.addWidget(chip, index // per_row, index % per_row)
    if len(items) > limit:
        index = len(visible)
        layout.addWidget(badge(f"+{len(items) - limit} more", "info"), index // per_row, index % per_row)
    layout.setColumnStretch(per_row, 1)
    return widget


def _readiness_items(eoat: EOATRecord) -> list[dict[str, object]]:
    doc_score = eoat.documentation.score
    doc_kind = _score_kind(doc_score)
    doc_points = 1.0 if doc_score >= 80 else (0.5 if doc_score >= 50 else 0.0)
    warnings_kind = "good" if eoat.warning_count == 0 else ("warn" if eoat.warning_count < 3 else "bad")
    return [
        {
            "name": "Photos present",
            "status": "OK" if eoat.photo_count else "Missing",
            "kind": "good" if eoat.photo_count else "bad",
            "detail": f"{eoat.photo_count} linked photo(s)",
            "points": 1.0 if eoat.photo_count else 0.0,
        },
        {
            "name": "Documentation score",
            "status": f"{doc_score}%",
            "kind": doc_kind,
            "detail": eoat.documentation.status_label,
            "points": doc_points,
        },
        {
            "name": "Machine compatibility",
            "status": "OK" if eoat.machines else "Missing",
            "kind": "good" if eoat.machines else "bad",
            "detail": ", ".join(eoat.machines[:6]) or "No compatible machines linked",
            "points": 1.0 if eoat.machines else 0.0,
        },
        {
            "name": "Robot info",
            "status": "OK" if eoat.robot_types or eoat.robot_models else "Review",
            "kind": "good" if eoat.robot_types or eoat.robot_models else "warn",
            "detail": ", ".join((*eoat.robot_types, *eoat.robot_models)) or "Robot type/model not linked",
            "points": 1.0 if eoat.robot_types or eoat.robot_models else 0.5,
        },
        {
            "name": "Standards references",
            "status": "OK" if eoat.standards else "Review",
            "kind": "good" if eoat.standards else "warn",
            "detail": f"{len(eoat.standards)} applicable standard(s)",
            "points": 1.0 if eoat.standards else 0.5,
        },
        {
            "name": "Warnings",
            "status": "OK" if eoat.warning_count == 0 else str(eoat.warning_count),
            "kind": warnings_kind,
            "detail": "No open warnings" if eoat.warning_count == 0 else "Review warning cards below",
            "points": 1.0 if eoat.warning_count == 0 else (0.5 if eoat.warning_count < 3 else 0.0),
        },
    ]


def _combined_photos(eoat: EOATRecord) -> list:
    photos = []
    seen = set()
    for photo in (*eoat.photos.photos, *eoat.photos.indexed_photos):
        if photo.path and photo.path not in seen:
            photos.append(photo)
            seen.add(photo.path)
    return photos


def _compatibility_status(eoat: EOATRecord) -> tuple[str, str]:
    if eoat.tools and eoat.machines:
        return "High-confidence compatibility", "good"
    if eoat.tools or eoat.machines:
        return "Partial compatibility", "warn"
    return "Fit Check missing", "bad"


def _score_kind(score: int) -> str:
    if score >= 80:
        return "good"
    if score >= 50:
        return "warn"
    return "bad"


def _warning_kind(severity: str) -> str:
    lowered = severity.casefold()
    if "error" in lowered or "critical" in lowered:
        return "bad"
    if "warn" in lowered:
        return "warn"
    return "info"


def _readiness_summary(score: int) -> str:
    if score >= 80:
        return "Ready for normal pre-install review."
    if score >= 50:
        return "Usable, but check the yellow items before install."
    return "Needs data cleanup before confident reuse."


def _first_present(*values: str) -> str:
    return next((value for value in values if value), "")


def _short_label(value: str, limit: int = 34) -> str:
    return value if len(value) <= limit else f"{value[: limit - 3]}..."


def _split_values(value: str) -> list[str]:
    return [piece.strip() for piece in value.replace(";", ",").split(",") if piece.strip()]


def _short_path(value: str, *, keep_parts: int = 3) -> str:
    if not value:
        return ""
    path = Path(value)
    parts = path.parts
    if len(parts) <= keep_parts:
        return value
    return str(Path("...").joinpath(*parts[-keep_parts:]))


def _machine_profile_text(machine: MachineRecord | None) -> str:
    if machine is None:
        return ""
    lines = [
        f"Machine: {machine.machine}",
        f"Robot Type: {machine.robot_type or '-'}",
        f"Robot Model/Controller: {machine.robot_model or '-'}",
        f"Current/known EOAT: {machine.current_eoat or '-'}",
        f"Compatible EOATs: {', '.join(machine.compatible_eoats) or '-'}",
        f"Compatible Tools: {', '.join(machine.compatible_tools) or '-'}",
        f"Compatible Parts: {', '.join(machine.compatible_parts[:20]) or '-'}",
        f"Documentation score: {machine.documentation_score}%",
    ]
    if machine.warnings:
        lines.extend(["", "Warnings:", *[f"- {warning.title}: {warning.message}" for warning in machine.warnings]])
    return "\n".join(lines)


def _warning_row(warning, *, fallback_eoat: str = "") -> dict[str, str]:
    return {
        "Severity": warning.severity,
        "What": f"{warning.title}: {warning.message}",
        "Why it matters": warning.why_it_matters or "This can affect search, compatibility confidence, or install readiness.",
        "Suggested fix": warning.suggested_fix or "Review in EOAT Command Center.",
        "EOAT": warning.related_eoat_id or fallback_eoat,
        "Machine": warning.machine,
        "Tool": warning.tool,
        "Source": warning.source,
    }


def _selected_row(table: QTableWidget) -> dict | None:
    selected = table.selectedItems()
    if not selected:
        return None
    data = selected[0].data(Qt.ItemDataRole.UserRole)
    return data if isinstance(data, dict) else None


def _find_eoat(bundle: AtlasDataBundle | None, eoat_id: str) -> EOATRecord | None:
    if bundle is None:
        return None
    key = normalized_eoat_key(eoat_id)
    return next((record for record in bundle.eoats if normalized_eoat_key(record.eoat_id) == key), None)


def _find_machine(bundle: AtlasDataBundle | None, machine: str) -> MachineRecord | None:
    if bundle is None:
        return None
    key = normalized_machine_key(machine)
    return next((record for record in bundle.machines if normalized_machine_key(record.machine) == key), None)


def _find_tool(bundle: AtlasDataBundle | None, tool: str) -> ToolRecord | None:
    if bundle is None:
        return None
    key = normalized_tool_key(tool)
    return next((record for record in bundle.tools if normalized_tool_key(record.tool) == key), None)


__all__ = [
    "DiagnosticsPage",
    "EOATBrowserPage",
    "HomePage",
    "InformationLibraryPage",
    "MachineBrowserPage",
    "MatrixPage",
    "OverviewPage",
    "PMInspectionPage",
    "PhotosPage",
    "ReportsPage",
    "StandardsPage",
    "ToolSearchPage",
    "WhatNeedPage",
]
