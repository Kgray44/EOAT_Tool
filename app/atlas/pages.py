from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
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
    QSplitter,
    QTableWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.atlas_exports import (
    export_compatibility_matrix,
    export_documentation_gap_report,
    export_eoat_summary,
    export_machine_summary,
    export_photo_coverage_report,
    export_recommendation_summary,
)
from core.atlas_models import AtlasDataBundle, EOATRecord, MachineRecord, RecommendationResult, StandardReference
from core.atlas_recommendations import recommend_for_query
from core.atlas_utils import normalized_eoat_key, normalized_machine_key
from core.compatibility_engine import compatibility_matrix_rows
from core.openers import open_path
from core.performance import log_performance_event

from .widgets import (
    AtlasHero,
    ChecklistCard,
    CompactStatCard,
    CompatibilityCard,
    CompatibilityPathWidget,
    DenseDataPanel,
    DetailCard,
    EmptyStateWidget,
    EOATProfileCard,
    ExportActionCard,
    FeatureActionCard,
    InfoPanel,
    MachineProfileCard,
    MiniProgressBar,
    ModernSearchBar,
    PhotoGalleryCard,
    PhotoStripWidget,
    PrimaryCard,
    ProfileHeaderCard,
    ReadinessScoreWidget,
    SecondaryCard,
    SuccessCard,
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
            ("Compatibility Matrix", "Dense EOAT, machine, and tool links.", "matrix", "Matrix"),
            ("View Standards", "Setup, PM, and documentation library.", "standards", "Library"),
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
        copy_button = QPushButton("Copy Recommendation")
        copy_button.clicked.connect(self.copy_result)
        export_button = QPushButton("Export Summary")
        export_button.clicked.connect(self.export_result)
        layout.addWidget(action_row(open_button, copy_button, export_button))
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
            if candidate.reasons:
                card.layout.addWidget(_labeled_chips("Why", candidate.reasons[:4], kind="info", per_row=2))
            card.layout.addWidget(_recommendation_action_row(candidate, self, primary=False))
            candidate_layout.addWidget(card)
        if not self.result.candidates:
            candidate_layout.addWidget(EmptyStateWidget("No candidates found", "Try a different tool, machine, or EOAT identifier."))
        self.result_layout.addWidget(candidate_section)
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("EOAT Browser", "Search EOATs, review profile details, photos, warnings, and install context."))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by EOAT ID, tool, machine, type, status, part, or warning")
        self.filter.textChanged.connect(self.refresh)
        layout.addWidget(self.filter)
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
        folder_button = QPushButton("Open Photos")
        folder_button.clicked.connect(self.open_photos)
        export_button = QPushButton("Export EOAT Summary")
        export_button.clicked.connect(self.export_current)
        machine_button = QPushButton("Open Machine Profile")
        machine_button.clicked.connect(self.open_related_machine)
        tool_button = QPushButton("Open Tool Lookup")
        tool_button.clicked.connect(self.open_related_tool)
        what_button = QPushButton("What Do I Need?")
        what_button.clicked.connect(self.open_recommendation)
        layout.addWidget(action_row(copy_button, folder_button, export_button, machine_button, tool_button, what_button))
        self._show_detail(None)

    def refresh(self) -> None:
        if self.bundle is None:
            return
        query = self.filter.text().strip().casefold()
        rows = []
        self._records_by_key = {}
        for eoat in self.bundle.eoats:
            self._records_by_key[normalized_eoat_key(eoat.eoat_id)] = eoat
            haystack = " ".join(
                [eoat.eoat_id, eoat.eoat_type, eoat.status, " ".join(eoat.tools), " ".join(eoat.machines), eoat.part_description]
            ).casefold()
            if query and query not in haystack:
                continue
            rows.append(eoat)
        self.list.blockSignals(True)
        self.list.clear()
        for eoat in rows[:200]:
            tile = EOATListTile(eoat, compact=self.controller.settings.compact_list_mode)
            item = QListWidgetItem()
            item.setSizeHint(tile.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, eoat)
            self.list.addItem(item)
            self.list.setItemWidget(item, tile)
        if len(rows) > 200:
            item = QListWidgetItem(f"Showing first 200 of {len(rows)} matches. Refine the search to narrow results.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        self.list.blockSignals(False)
        if rows:
            target = normalized_eoat_key(self.current.eoat_id) if self.current else normalized_eoat_key(rows[0].eoat_id)
            selected_row = 0
            for index, eoat in enumerate(rows[:200]):
                if normalized_eoat_key(eoat.eoat_id) == target:
                    selected_row = index
                    break
            self.list.setCurrentRow(selected_row)
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
                self._show_detail(record)

    def _show_detail(self, eoat: EOATRecord | None) -> None:
        self.current = eoat
        self._render_eoat_profile(eoat)

    def open_photos(self) -> None:
        if self.current and self.current.photos.folder_path:
            open_path(self.current.photos.folder_path)

    def export_current(self) -> None:
        bundle = self.require_bundle()
        if bundle and self.current:
            path = export_eoat_summary(bundle, self.current)
            self.controller.show_status(f"Exported EOAT summary: {path}")

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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Machine Browser", "Find machine EOAT compatibility, robot context, and warning status."))
        self.filter = ModernSearchBar("Filter by machine, robot, tool, EOAT, or part")
        self.filter.textChanged.connect(self.refresh)
        layout.addWidget(self.filter)
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
        export_button = QPushButton("Export Machine Summary")
        export_button.clicked.connect(self.export_current)
        matrix_button = QPushButton("Open Matrix")
        matrix_button.clicked.connect(lambda: self.controller.show_page("matrix"))
        layout.addWidget(action_row(eoat_button, matrix_button, export_button))
        self._show_detail(None)

    def refresh(self) -> None:
        if self.bundle is None:
            return
        query = self.filter.text().strip().casefold()
        rows = []
        self._records_by_key = {}
        for machine in self.bundle.machines:
            self._records_by_key[normalized_machine_key(machine.machine)] = machine
            haystack = " ".join(
                [machine.machine, machine.robot_type, machine.robot_model, " ".join(machine.compatible_eoats), " ".join(machine.compatible_tools)]
            ).casefold()
            if query and query not in haystack:
                continue
            rows.append(machine)
        self.list.blockSignals(True)
        self.list.clear()
        for machine in rows[:200]:
            tile = MachineListTile(machine, compact=self.controller.settings.compact_list_mode)
            item = QListWidgetItem()
            item.setSizeHint(tile.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, machine)
            self.list.addItem(item)
            self.list.setItemWidget(item, tile)
        if len(rows) > 200:
            item = QListWidgetItem(f"Showing first 200 of {len(rows)} matches. Refine the search to narrow results.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        self.list.blockSignals(False)
        if rows:
            target = normalized_machine_key(self.current.machine) if self.current else normalized_machine_key(rows[0].machine)
            selected_row = 0
            for index, machine in enumerate(rows[:200]):
                if normalized_machine_key(machine.machine) == target:
                    selected_row = index
                    break
            self.list.setCurrentRow(selected_row)
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
                self._show_detail(record)

    def _show_detail(self, machine: MachineRecord | None) -> None:
        self.current = machine
        self._render_machine_profile(machine)

    def export_current(self) -> None:
        bundle = self.require_bundle()
        if bundle and self.current:
            path = export_machine_summary(bundle, self.current)
            self.controller.show_status(f"Exported machine summary: {path}")

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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Tool / Mold / Part Search", "Find compatible EOATs and machines from tool, mold, part number, or description."))
        self.search = ModernSearchBar("Search tool, mold, part number, or description")
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
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
        layout.addWidget(self.scroll, 1)
        recommend_button = QPushButton("Run What Do I Need?")
        recommend_button.setObjectName("PrimaryButton")
        recommend_button.clicked.connect(lambda: self.controller.open_recommendation(self.search.text().strip()))
        layout.addWidget(action_row(recommend_button))

    def refresh(self) -> None:
        if self.bundle is None:
            return
        query = self.search.text().strip().casefold()
        _clear_layout(self.card_layout)
        matches = []
        for tool in self.bundle.tools:
            haystack = " ".join(
                [
                    tool.tool,
                    f"Tool {tool.tool}",
                    tool.part_description,
                    tool.part_family,
                    " ".join(tool.parts),
                    " ".join(tool.compatible_eoats),
                ]
            ).casefold()
            if query and query not in haystack:
                continue
            matches.append(tool)
        for tool in matches[:120]:
            self.card_layout.addWidget(_tool_card(tool, self.controller))
        if not matches:
            self.card_layout.addWidget(EmptyStateWidget("No matching tools", "Try a tool number, mold number, part description, or EOAT ID."))
        elif len(matches) > 120:
            self.card_layout.addWidget(EmptyStateWidget("More matches available", f"Showing first 120 of {len(matches)}. Refine the search to narrow results."))
        self.card_layout.addStretch(1)


class MatrixPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Compatibility Matrix", "Sortable, filterable compatibility views."))
        controls = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["eoat_machine", "tool_eoat", "tool_machine"])
        self.mode.currentTextChanged.connect(self.refresh)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter matrix")
        self.filter.textChanged.connect(self.refresh)
        export_button = QPushButton("Export CSV")
        export_button.clicked.connect(self.export_csv)
        controls.addWidget(self.mode)
        controls.addWidget(self.filter, 1)
        controls.addWidget(export_button)
        panel = DenseDataPanel("Compatibility Rows", "Dense matrix view for sorting, filtering, and export.")
        panel.layout.addLayout(controls)
        self.table = QTableWidget()
        panel.layout.addWidget(self.table, 1)
        layout.addWidget(panel, 1)

    def refresh(self) -> None:
        if self.bundle is None:
            return
        rows = compatibility_matrix_rows(self.bundle, mode=self.mode.currentText())
        query = self.filter.text().strip().casefold()
        if query:
            rows = [row for row in rows if query in " ".join(str(value) for value in row.values()).casefold()]
        columns = list(rows[0].keys()) if rows else ["EOAT", "Machine", "Status"]
        fill_table(self.table, rows, columns)

    def export_csv(self) -> None:
        bundle = self.require_bundle()
        if bundle:
            path = export_compatibility_matrix(bundle, mode=self.mode.currentText())
            self.controller.show_status(f"Exported matrix: {path}")


class OverviewPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Overall Maps", "Machine grid, documentation heatmap, and compatibility coverage."))
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
        metrics = self.bundle.metrics
        metric_grid = QGridLayout()
        metric_cards = [
            CompactStatCard("EOAT coverage", str(metrics.get("eoats_documented", len(self.bundle.eoats))), "Documented EOAT records"),
            CompactStatCard("Machine coverage", str(metrics.get("machines_covered", len(self.bundle.machines))), "Machines with Atlas context"),
            CompactStatCard("Tool coverage", str(metrics.get("tools_covered", len(self.bundle.tools))), "Tools linked or inferred"),
            CompactStatCard("Documentation avg.", f"{metrics.get('documentation_average', 0)}%", "EOAT profile completeness"),
        ]
        for index, card in enumerate(metric_cards):
            metric_grid.addWidget(card, index // 4, index % 4)
        self.content_layout.addLayout(metric_grid)

        machines, machines_layout = _group_container(
            "Machine Coverage Map",
            "Tiles signal compatibility coverage and warning state at a glance.",
        )
        machine_grid = QGridLayout()
        machine_grid.setContentsMargins(0, 0, 0, 0)
        machine_grid.setSpacing(8)
        for index, machine in enumerate(self.bundle.machines[:36]):
            card = MachineProfileCard(f"Machine {machine.machine}", machine.robot_type or machine.robot_model or "Robot info missing")
            card.layout.addWidget(badge("OK" if machine.compatible_eoats else "Review", "success" if machine.compatible_eoats else "warning"))
            card.layout.addWidget(badge(f"{len(machine.compatible_eoats)} EOAT(s)", "info"))
            card.layout.addWidget(badge(f"{len(machine.compatible_tools)} tool(s)", "info"))
            if machine.warning_count:
                card.layout.addWidget(badge(f"{machine.warning_count} warning(s)", "warn"))
            machine_grid.addWidget(card, index // 4, index % 4)
        machines_layout.addLayout(machine_grid)
        self.content_layout.addWidget(machines)

        docs, docs_layout = _group_container("Documentation Heatmap", "Lowest-scoring EOAT documentation records appear first.")
        doc_grid = QGridLayout()
        doc_grid.setContentsMargins(0, 0, 0, 0)
        doc_grid.setSpacing(8)
        for index, eoat in enumerate(sorted(self.bundle.eoats, key=lambda item: item.documentation.score)[:48]):
            card = EOATProfileCard(eoat.eoat_id)
            card.layout.addWidget(badge(f"{eoat.documentation.score}% docs", _score_kind(eoat.documentation.score)))
            card.layout.addWidget(MiniProgressBar(eoat.documentation.score, kind=_score_kind(eoat.documentation.score)))
            card.layout.addWidget(badge(f"{eoat.photo_count} photo(s)", "good" if eoat.photo_count else "warn"))
            doc_grid.addWidget(card, index // 4, index % 4)
        docs_layout.addLayout(doc_grid)
        self.content_layout.addWidget(docs)
        self.content_layout.addStretch(1)


class PhotosPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.current: EOATRecord | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Photos", "Browse linked EOAT photos without moving or renaming source files."))
        self.filter = ModernSearchBar("Filter by EOAT, tool, machine, or category")
        self.filter.textChanged.connect(self.refresh)
        layout.addWidget(self.filter)
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
        layout.addWidget(self.scroll, 1)

    def refresh(self) -> None:
        if self.bundle is None:
            return
        query = self.filter.text().strip().casefold()
        _clear_layout(self.card_layout)
        matches = []
        for eoat in self.bundle.eoats:
            haystack = " ".join([eoat.eoat_id, " ".join(eoat.tools), " ".join(eoat.machines), eoat.photos.folder_path]).casefold()
            if query and query not in haystack:
                continue
            matches.append(eoat)
        for eoat in matches[:80]:
            self.card_layout.addWidget(_photo_folder_card(eoat, self))
        if not matches:
            self.card_layout.addWidget(EmptyStateWidget("No photo folders matched", "Try an EOAT ID, tool number, machine number, or folder keyword."))
        elif len(matches) > 80:
            self.card_layout.addWidget(EmptyStateWidget("More photo folders available", f"Showing first 80 of {len(matches)}. Refine the search to narrow results."))
        self.card_layout.addStretch(1)

    def open_folder(self) -> None:
        if self.current and self.current.photos.folder_path:
            open_path(self.current.photos.folder_path)

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


class StandardsPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Standards", "Open and search available EOAT standardization documents."))
        self.filter = ModernSearchBar("Search vacuum, tubing, sensors, quick disconnects, PM, documentation")
        self.filter.textChanged.connect(self.refresh)
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
        layout.addWidget(self.filter)
        layout.addWidget(self.scroll, 1)

    def refresh(self) -> None:
        if self.bundle is None:
            return
        query = self.filter.text().strip().casefold()
        _clear_layout(self.card_layout)
        matches = []
        for standard in self.bundle.standards:
            haystack = " ".join([standard.title, standard.category, standard.snippet, standard.path]).casefold()
            if query and query not in haystack:
                continue
            matches.append(standard)
        grouped: dict[str, list] = {}
        for standard in matches:
            grouped.setdefault(standard.category or "Uncategorized", []).append(standard)
        for category, standards in sorted(grouped.items(), key=lambda item: item[0].casefold()):
            self.card_layout.addWidget(InfoPanel(category, f"{len(standards)} document(s)"))
            for standard in standards:
                self.card_layout.addWidget(_standard_card(standard))
        if not matches:
            self.card_layout.addWidget(EmptyStateWidget("No standards matched", "Try a category, document title, or keyword."))
        self.card_layout.addStretch(1)

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


@dataclass(frozen=True)
class InformationLibraryEntry:
    entry_id: str
    title: str
    category: str
    summary: str
    body: str
    source: str = "Atlas"
    path: str = ""
    source_section: str = ""
    tags: tuple[str, ...] = ()
    tree_path: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    modified: float = 0.0
    indexed_at: float = 0.0


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
        self.search = ModernSearchBar("Search title, body, tags, source file, or tree path")
        self.search.textChanged.connect(self.refresh)
        self.category = QComboBox()
        self.category.currentTextChanged.connect(self.refresh)
        self.sort = QComboBox()
        self.sort.addItems(["Relevance", "Category", "Source document", "Title", "Last modified"])
        self.sort.currentTextChanged.connect(self.refresh)
        controls.addWidget(self.search, 1)
        controls.addWidget(self.category)
        controls.addWidget(self.sort)
        layout.addLayout(controls)

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
        self._sync_categories()
        self.refresh()

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
        category = self.category.currentText()
        scored = []
        for entry in self.entries:
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
            scored.sort(key=lambda item: (item[1].source.casefold(), item[1].title.casefold()))
        elif sort_mode == "Title":
            scored.sort(key=lambda item: item[1].title.casefold())
        elif sort_mode == "Last modified":
            scored.sort(key=lambda item: (-item[1].modified, item[1].title.casefold()))
        else:
            scored.sort(key=lambda item: (-item[0], item[1].category.casefold(), item[1].title.casefold()))
        self.filtered_entries = [entry for _score, entry in scored]
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
            path_parts = tuple(part for part in (entry.tree_path or (entry.category,)) if part)
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
            leaf = QTreeWidgetItem([entry.title])
            leaf.setData(0, Qt.ItemDataRole.UserRole, entry.entry_id)
            leaf.setToolTip(0, entry.summary)
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
        header = ProfileHeaderCard(entry.title, entry.summary, eyebrow=entry.category)
        header.layout.addWidget(
            _chip_group(
                [entry.category, *_tree_label_parts(entry.tree_path)[1:4], *entry.tags[:4]],
                kind="info",
                per_row=4,
                limit=8,
            )
        )
        self.detail_layout.addWidget(header)

        body = PrimaryCard("Reference Detail", "Expanded guidance for the selected information item.", eyebrow="Details")
        body_label = QLabel(entry.body or entry.summary)
        body_label.setObjectName("BodyText")
        body_label.setWordWrap(True)
        body.layout.addWidget(body_label)
        self.detail_layout.addWidget(body)

        if entry.related:
            related = SecondaryCard("Related References", "Nearby topics from the same standards/help area.")
            related.layout.addWidget(_chip_group(entry.related, kind="outline", per_row=4, limit=12))
            self.detail_layout.addWidget(related)

        metadata = InfoPanel("Source Metadata", "Reference provenance and indexing details.")
        metadata.layout.addWidget(
            key_value_grid(
                [
                    ("Tree path", " / ".join(entry.tree_path) or entry.category),
                    ("Source", entry.source or "Atlas generated guidance"),
                    ("Source section", entry.source_section or "-"),
                    ("File", _short_path(entry.path) if entry.path else "-"),
                    ("Last modified", _format_modified(entry.modified)),
                    ("Indexed", _format_modified(entry.indexed_at)),
                ]
            )
        )
        self.detail_layout.addWidget(metadata)

        buttons = []
        if entry.path:
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
        layout.addWidget(page_title("Reports / Export", "Timestamped Atlas exports. Source workbooks and photos are not modified."))
        grid = QGridLayout()
        grid.setSpacing(10)
        cards = [
            (
                "Compatibility Matrix CSV",
                "Export EOAT-machine-tool compatibility rows for dense comparison or offline review.",
                lambda: export_compatibility_matrix(self.bundle),
            ),
            (
                "Documentation Gap Report",
                "Export action-oriented missing data, warning, and readiness items.",
                lambda: export_documentation_gap_report(self.bundle),
            ),
            (
                "Photo Coverage Report",
                "Export linked photo counts, missing categories, and source folder status.",
                lambda: export_photo_coverage_report(self.bundle),
            ),
        ]
        for index, (title, description, callback) in enumerate(cards):
            card = ExportActionCard(title, description, "Export")
            card.button.clicked.connect(lambda _checked=False, callback=callback: self._run_export(callback))
            grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(grid)
        layout.addStretch(1)

    def _run_export(self, callback) -> None:
        if self.require_bundle() is None:
            return
        path = callback()
        self.controller.show_status(f"Exported: {path}")


class DiagnosticsPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(18, 18, 18, 18)
        outer_layout.addWidget(page_title("Settings / Diagnostics", "Path status, refresh controls, and Atlas performance timings."))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.scroll.setWidget(content)
        outer_layout.addWidget(self.scroll, 1)

        settings_card = PrimaryCard("Atlas Settings", "Editable preferences are stored per user and do not touch source workbooks or photo folders.")
        settings_card.setMinimumHeight(280)
        settings_grid = QGridLayout()
        settings_grid.setContentsMargins(0, 0, 0, 0)
        settings_grid.setHorizontalSpacing(12)
        settings_grid.setVerticalSpacing(8)
        self.theme_combo = _settings_combo(["Light", "Dark", "System/default"])
        self.color_scheme_combo = _settings_combo(["Atlas Blue", "Nolato Logo"])
        self.startup_combo = _settings_combo(
            [
                "Home / Command Deck",
                "What Do I Need?",
                "EOAT Search / Profiles",
                "Machine Search / Profiles",
                "Tool / Mold / Part Search",
                "Compatibility Matrix",
                "Overall Maps",
                "Photos",
                "Standards",
                "PM / Inspection",
                "Information Library",
                "Reports / Export",
                "Settings / Diagnostics",
            ]
        )
        self.search_mode_combo = _settings_combo(["Smart", "EOAT", "Machine", "Tool"])
        self.photo_behavior_combo = _settings_combo(["Open in app", "Open folder", "Open external viewer"])
        self.card_density_combo = _settings_combo(["Comfortable", "Compact"])
        self.lazy_previews_check = _settings_check("Enable optional cheap/cached photo previews on summary cards.")
        self.prefetch_check = _settings_check("Load the previous and next carousel images in memory for smoother navigation.")
        self.advanced_check = _settings_check("Show dense source and raw performance diagnostics tables.")
        self.compact_list_check = _settings_check("Use shorter EOAT and machine selector tiles.")
        self.open_after_export_check = _settings_check("Open the export folder after report generation when practical.")
        self.confirm_external_check = _settings_check("Ask before opening folders or files outside Atlas.")
        self.auto_refresh_check = _settings_check("Refresh Atlas data automatically when the app starts.")
        settings_widgets = [
            ("Theme mode", self.theme_combo),
            ("Color scheme", self.color_scheme_combo),
            ("Startup page", self.startup_combo),
            ("Default search mode", self.search_mode_combo),
            ("Photo viewer behavior", self.photo_behavior_combo),
            ("Card density", self.card_density_combo),
            ("Photo loading", self.lazy_previews_check),
            ("Carousel", self.prefetch_check),
            ("Diagnostics", self.advanced_check),
            ("List density", self.compact_list_check),
            ("Exports", self.open_after_export_check),
            ("External files", self.confirm_external_check),
            ("Startup refresh", self.auto_refresh_check),
        ]
        for index, (label, widget) in enumerate(settings_widgets):
            label_widget = QLabel(label)
            label_widget.setObjectName("MetricLabel")
            settings_grid.addWidget(label_widget, index // 2, (index % 2) * 2)
            settings_grid.addWidget(widget, index // 2, (index % 2) * 2 + 1)
        settings_body = QWidget()
        settings_body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        settings_body.setMinimumHeight(205)
        settings_body.setLayout(settings_grid)
        settings_card.layout.addWidget(settings_body)
        layout.addWidget(settings_card)

        control_card = InfoPanel("Data Refresh", "Manual refresh rebuilds cached Atlas data without modifying source files.")
        refresh_button = QPushButton("Refresh Data")
        refresh_button.setObjectName("PrimaryButton")
        refresh_button.clicked.connect(lambda: self.controller.refresh_data(force=True))
        note = QLabel("Atlas is read-only. Refresh rebuilds the in-memory cache/indexes from the configured sources.")
        note.setObjectName("BodyText")
        note.setWordWrap(True)
        control_card.layout.addWidget(note)
        control_card.layout.addWidget(refresh_button)
        layout.addWidget(control_card)
        self.source_card = InfoPanel("Source Status", "Required and optional source availability.")
        self.source_grid = QGridLayout()
        self.source_grid.setContentsMargins(0, 0, 0, 0)
        self.source_grid.setSpacing(8)
        self.source_card.layout.addLayout(self.source_grid)
        layout.addWidget(self.source_card)
        self.perf_card = SecondaryCard("Performance Timings", "Compact developer diagnostics for slow-operation triage.")
        self.perf_grid = QGridLayout()
        self.perf_grid.setContentsMargins(0, 0, 0, 0)
        self.perf_grid.setSpacing(8)
        self.perf_card.layout.addLayout(self.perf_grid)
        layout.addWidget(self.perf_card)
        self.sources = QTableWidget()
        self.metrics = QTableWidget()
        self.source_panel = DenseDataPanel("Source Path Details", "Compact reference table for configured Atlas source paths.")
        self.source_panel.layout.addWidget(self.sources, 1)
        layout.addWidget(self.source_panel, 1)
        self.metrics_panel = DenseDataPanel("Raw Performance Diagnostics", "Developer timings and cache counters.")
        self.metrics_panel.layout.addWidget(self.metrics, 1)
        layout.addWidget(self.metrics_panel, 1)
        self._wire_settings_controls()
        self._sync_settings_controls()

    def refresh(self) -> None:
        if self.bundle is None:
            return
        _clear_layout(self.source_grid)
        for index, source in enumerate(self.bundle.source_statuses):
            chip = badge(f"{source.label}: {'Ready' if source.available else 'Missing'}", "good" if source.available else "warn")
            chip.setToolTip(f"{source.message}\n{source.path}")
            self.source_grid.addWidget(chip, index // 3, index % 3)
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
        self._apply_diagnostics_visibility()

    def _wire_settings_controls(self) -> None:
        self.theme_combo.currentTextChanged.connect(lambda: self._save_setting(theme=_theme_value(self.theme_combo.currentText())))
        self.color_scheme_combo.currentTextChanged.connect(
            lambda: self._save_setting(color_scheme=_color_scheme_value(self.color_scheme_combo.currentText()))
        )
        self.startup_combo.currentTextChanged.connect(lambda: self._save_setting(startup_page=_page_key_for_label(self.startup_combo.currentText())))
        self.search_mode_combo.currentTextChanged.connect(lambda: self._save_setting(default_search_mode=self.search_mode_combo.currentText().casefold()))
        self.photo_behavior_combo.currentTextChanged.connect(lambda: self._save_setting(photo_viewer_behavior=_photo_behavior_value(self.photo_behavior_combo.currentText())))
        self.card_density_combo.currentTextChanged.connect(lambda: self._save_setting(card_density=self.card_density_combo.currentText().casefold()))
        self.lazy_previews_check.toggled.connect(lambda value: self._save_setting(lazy_photo_previews=value))
        self.prefetch_check.toggled.connect(lambda value: self._save_setting(carousel_prefetch=value))
        self.advanced_check.toggled.connect(lambda value: self._save_setting(show_advanced_diagnostics=value))
        self.compact_list_check.toggled.connect(lambda value: self._save_setting(compact_list_mode=value))
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
            self.card_density_combo,
            self.lazy_previews_check,
            self.prefetch_check,
            self.advanced_check,
            self.compact_list_check,
            self.open_after_export_check,
            self.confirm_external_check,
            self.auto_refresh_check,
        ]
        for control in controls:
            control.blockSignals(True)
        self.theme_combo.setCurrentText({"light": "Light", "dark": "Dark", "system": "System/default"}.get(settings.theme, "Light"))
        self.color_scheme_combo.setCurrentText({"atlas_blue": "Atlas Blue", "nolato_logo": "Nolato Logo"}.get(settings.color_scheme, "Atlas Blue"))
        self.startup_combo.setCurrentText(_label_for_page_key(settings.startup_page))
        self.search_mode_combo.setCurrentText(settings.default_search_mode.upper() if settings.default_search_mode == "eoat" else settings.default_search_mode.title())
        self.photo_behavior_combo.setCurrentText(
            {"in_app": "Open in app", "open_folder": "Open folder", "external": "Open external viewer"}.get(
                settings.photo_viewer_behavior, "Open in app"
            )
        )
        self.card_density_combo.setCurrentText(settings.card_density.title())
        self.lazy_previews_check.setChecked(settings.lazy_photo_previews)
        self.prefetch_check.setChecked(settings.carousel_prefetch)
        self.advanced_check.setChecked(settings.show_advanced_diagnostics)
        self.compact_list_check.setChecked(settings.compact_list_mode)
        self.open_after_export_check.setChecked(settings.open_after_export)
        self.confirm_external_check.setChecked(settings.confirm_external_open)
        self.auto_refresh_check.setChecked(settings.auto_refresh_on_startup)
        for control in controls:
            control.blockSignals(False)

    def _save_setting(self, **changes) -> None:
        self.controller.update_settings(replace(self.controller.settings, **changes))

    def _apply_diagnostics_visibility(self) -> None:
        show = bool(self.controller.settings.show_advanced_diagnostics)
        self.source_panel.setVisible(show)
        self.metrics_panel.setVisible(show)


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
        lines.extend(["", "Ranking reasons:", *[f"- {reason}" for reason in result.best.reasons]])
    lines.extend(["", "Before install:", *[f"{index}. {item}" for index, item in enumerate(result.install_checklist, start=1)]])
    if result.warnings:
        lines.extend(["", "Warnings:", *[f"- {warning.title}: {warning.message}" for warning in result.warnings]])
    if len(result.candidates) > 1:
        lines.extend(["", "Backup EOATs:", *[f"- {candidate.eoat_id}: {candidate.summary}" for candidate in result.candidates[1:]]])
    return "\n".join(lines)


def _recommendation_action_row(candidate, page: WhatNeedPage, *, primary: bool) -> QWidget:
    buttons = []
    eoat_button = QPushButton("Open EOAT Profile")
    if primary:
        eoat_button.setObjectName("PrimaryButton")
    eoat_button.clicked.connect(lambda _checked=False, eoat_id=candidate.eoat_id: page.controller.open_eoat(eoat_id))
    buttons.append(eoat_button)

    photos_button = QPushButton("View Photos")
    if primary:
        photos_button.setObjectName("HeroSecondaryButton")
    photos_button.clicked.connect(lambda _checked=False, eoat_id=candidate.eoat_id: page.open_photos_for(eoat_id))
    buttons.append(photos_button)

    if candidate.tools:
        tool_button = QPushButton("Open Related Tool" if primary else "Open Tool")
        if primary:
            tool_button.setObjectName("HeroSecondaryButton")
        tool_button.clicked.connect(lambda _checked=False, tool=candidate.tools[0]: page.open_tool_value(tool))
        buttons.append(tool_button)

    if candidate.machines:
        machine_button = QPushButton("Open Related Machine" if primary else "Open Machine")
        if primary:
            machine_button.setObjectName("HeroSecondaryButton")
        machine_button.clicked.connect(lambda _checked=False, machine=candidate.machines[0]: page.open_machine_value(machine))
        buttons.append(machine_button)

    if primary:
        export_button = QPushButton("Export Recommendation")
        export_button.setObjectName("HeroSecondaryButton")
        export_button.clicked.connect(page.export_result)
        buttons.append(export_button)

    return action_row(*buttons)


class EOATListTile(QWidget):
    def __init__(self, eoat: EOATRecord, *, compact: bool = False, parent=None):
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
    def __init__(self, machine: MachineRecord, *, compact: bool = False, parent=None):
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


@dataclass(frozen=True)
class PhotoLoadResult:
    pixmap: QPixmap
    state: str
    message: str = ""
    detail: str = ""


class PhotoCarouselDialog(QDialog):
    SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

    def __init__(self, eoat: EOATRecord, *, prefetch: bool = True, parent=None):
        super().__init__(parent)
        self.eoat = eoat
        self.prefetch = prefetch
        self.photos = [photo for photo in _combined_photos(eoat) if Path(photo.path).suffix.casefold() in self.SUPPORTED_SUFFIXES]
        self.index = 0
        self.fit_mode = "fit"
        self.zoom = 1.0
        self._prefetched: dict[int, PhotoLoadResult] = {}
        self.setObjectName("PhotoViewerDialog")
        self.setWindowTitle(f"Photos - {eoat.eoat_id}")
        self.setModal(True)
        self.resize(980, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel(eoat.eoat_id)
        title.setObjectName("PhotoViewerTitle")
        self.count_label = QLabel()
        self.count_label.setObjectName("PhotoViewerMeta")
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        header.addWidget(title, 1)
        header.addWidget(self.count_label)
        header.addWidget(close_button)
        layout.addLayout(header)

        self.image_label = QLabel()
        self.image_label.setObjectName("PhotoViewerImage")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(640, 420)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.image_label, 1)

        self.filename_label = QLabel()
        self.filename_label.setObjectName("PhotoViewerMeta")
        self.filename_label.setWordWrap(True)
        layout.addWidget(self.filename_label)

        view_controls = QHBoxLayout()
        view_controls.setContentsMargins(0, 0, 0, 0)
        fit_button = QPushButton("Fit")
        fit_button.clicked.connect(lambda: self.set_fit_mode("fit"))
        fill_button = QPushButton("Fill")
        fill_button.clicked.connect(lambda: self.set_fit_mode("fill"))
        actual_button = QPushButton("Actual Size")
        actual_button.clicked.connect(lambda: self.set_fit_mode("actual"))
        zoom_out = QPushButton("Zoom -")
        zoom_out.clicked.connect(lambda: self.adjust_zoom(0.85))
        zoom_in = QPushButton("Zoom +")
        zoom_in.clicked.connect(lambda: self.adjust_zoom(1.18))
        reset_zoom = QPushButton("Reset Zoom")
        reset_zoom.clicked.connect(self.reset_zoom)
        view_controls.addWidget(fit_button)
        view_controls.addWidget(fill_button)
        view_controls.addWidget(actual_button)
        view_controls.addStretch(1)
        view_controls.addWidget(zoom_out)
        view_controls.addWidget(zoom_in)
        view_controls.addWidget(reset_zoom)
        layout.addLayout(view_controls)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        self.previous_button = QPushButton("Previous")
        self.previous_button.clicked.connect(self.previous_photo)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.next_photo)
        self.folder_button = QPushButton("Open Folder")
        self.folder_button.clicked.connect(self.open_folder)
        self.external_button = QPushButton("Open Externally")
        self.external_button.clicked.connect(self.open_current_external)
        controls.addWidget(self.previous_button)
        controls.addWidget(self.next_button)
        controls.addStretch(1)
        controls.addWidget(self.folder_button)
        controls.addWidget(self.external_button)
        layout.addLayout(controls)
        self._show_photo()

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
        if not self.photos:
            return
        self.index = (self.index - 1) % len(self.photos)
        self._show_photo()

    def next_photo(self) -> None:
        if not self.photos:
            return
        self.index = (self.index + 1) % len(self.photos)
        self._show_photo()

    def set_fit_mode(self, mode: str) -> None:
        self.fit_mode = mode
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
            self.previous_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self.external_button.setEnabled(False)
            self.folder_button.setEnabled(bool(self.eoat.photos.folder_path))
            return
        photo = self.photos[self.index]
        self.count_label.setText(f"{self.index + 1} / {len(self.photos)}")
        category = f" - {photo.category}" if photo.category else ""
        self.filename_label.setText(f"{photo.filename or Path(photo.path).name}{category}")
        self.filename_label.setToolTip(photo.path)
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText("Loading...")
        QApplication.processEvents()
        self._render_current_pixmap()
        self.previous_button.setEnabled(len(self.photos) > 1)
        self.next_button.setEnabled(len(self.photos) > 1)
        self.external_button.setEnabled(Path(photo.path).exists())
        self.folder_button.setEnabled(bool(self.eoat.photos.folder_path))
        if self.prefetch and len(self.photos) > 1:
            self._pixmap_for_index((self.index - 1) % len(self.photos))
            self._pixmap_for_index((self.index + 1) % len(self.photos))

    def _render_current_pixmap(self) -> None:
        if not self.photos:
            return
        result = self._pixmap_for_index(self.index)
        if result.pixmap.isNull():
            detail = f"\n\n{result.detail}" if result.detail and getattr(self.controller_settings_debug(), "show_advanced_diagnostics", False) else ""
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(f"{result.message or result.state}{detail}")
            return
        self.image_label.setText("")
        size = self.image_label.size()
        if self.fit_mode == "actual":
            target_width = max(24, int(result.pixmap.width() * self.zoom))
            target_height = max(24, int(result.pixmap.height() * self.zoom))
            aspect_mode = Qt.AspectRatioMode.KeepAspectRatio
        else:
            target_width = max(120, size.width() - 18)
            target_height = max(120, size.height() - 18)
            aspect_mode = Qt.AspectRatioMode.KeepAspectRatioByExpanding if self.fit_mode == "fill" else Qt.AspectRatioMode.KeepAspectRatio
        self.image_label.setPixmap(
            result.pixmap.scaled(
                target_width,
                target_height,
                aspect_mode,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def controller_settings_debug(self):
        parent = self.parent()
        controller = getattr(parent, "controller", None)
        return getattr(controller, "settings", None)

    def _pixmap_for_index(self, index: int) -> PhotoLoadResult:
        if index not in self._prefetched:
            parent = self.parent()
            bundle = getattr(parent, "bundle", None)
            project_root = getattr(bundle, "project_root", "")
            self._prefetched[index] = _load_photo_pixmap(self.photos[index].path, project_root=project_root)
        return self._prefetched[index]


def _load_photo_pixmap(path: str, *, project_root: str = "") -> PhotoLoadResult:
    started = time.perf_counter()
    target = Path(path)
    pixmap = QPixmap()
    suffix = target.suffix.casefold()
    detail = ""
    result: PhotoLoadResult | None = None
    try:
        if not path or not target.exists():
            result = PhotoLoadResult(pixmap, "file_missing", "File missing. Use Open Folder to inspect the source location.", str(target))
            return result
        if suffix not in PhotoCarouselDialog.SUPPORTED_SUFFIXES:
            result = PhotoLoadResult(
                pixmap,
                "unsupported_format",
                f"Unsupported image format {suffix or '(none)'}. Use Open Externally or Open Folder.",
                str(target),
            )
            return result

        qt_pixmap = QPixmap(str(target))
        if not qt_pixmap.isNull():
            result = PhotoLoadResult(qt_pixmap, "loaded")
            return result

        if suffix in {".heic", ".heif"}:
            try:
                import pillow_heif  # type: ignore[import-not-found]

                pillow_heif.register_heif_opener()
            except ImportError as exc:
                detail = str(exc)
                message = "HEIC preview support is not installed. Use Open Externally or Open Folder."
                LOGGER.warning("Atlas photo preview missing HEIC support for %s: %s", target, exc)
                result = PhotoLoadResult(pixmap, "unsupported_format", message, detail)
                return result

        try:
            result = PhotoLoadResult(_load_pixmap_with_pillow(target), "loaded")
            return result
        except ImportError as exc:
            detail = str(exc)
            message = "Image preview decoder is not installed. Use Open Externally or Open Folder."
            LOGGER.warning("Atlas photo preview missing Pillow decoder for %s: %s", target, exc)
            result = PhotoLoadResult(pixmap, "unsupported_format", message, detail)
            return result
        except Exception as exc:
            detail = repr(exc)
            message = f"Decode failed for {target.name}. Use Open Externally or Open Folder."
            LOGGER.warning("Atlas photo preview decode failed for %s: %s", target, exc)
            result = PhotoLoadResult(pixmap, "decode_failed", message, detail)
            return result
    finally:
        if project_root:
            result_state = result.state if result is not None else "checked"
            log_performance_event(
                project_root,
                "atlas.photo_preview_load",
                time.perf_counter() - started,
                success=result_state == "loaded",
                source="atlas",
                page_tool="photos",
                details={"path": target.name, "state": result_state, "detail": detail},
                error_count=0 if result_state == "loaded" else 1,
            )


def _load_pixmap_with_pillow(path: Path) -> QPixmap:
    from PIL import Image, ImageOps

    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA")
        else:
            image = image.convert("RGBA")
        image.thumbnail((5000, 5000))
        width, height = image.size
        data = image.tobytes("raw", "RGBA")
    qimage = QImage(data, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimage)


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


PAGE_KEY_LABELS = {
    "home": "Home / Command Deck",
    "what": "What Do I Need?",
    "eoats": "EOAT Search / Profiles",
    "machines": "Machine Search / Profiles",
    "tools": "Tool / Mold / Part Search",
    "matrix": "Compatibility Matrix",
    "overview": "Overall Maps",
    "photos": "Photos",
    "standards": "Standards",
    "pm": "PM / Inspection",
    "library": "Information Library",
    "reports": "Reports / Export",
    "diagnostics": "Settings / Diagnostics",
}


def _settings_combo(labels: list[str]) -> QComboBox:
    combo = QComboBox()
    combo.addItems(labels)
    combo.setMinimumWidth(150)
    combo.setMaximumWidth(320)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return combo


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
    return "atlas_blue"


def _photo_behavior_value(label: str) -> str:
    folded = label.casefold()
    if "folder" in folded:
        return "open_folder"
    if "external" in folded:
        return "external"
    return "in_app"


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


def _tool_card(tool, controller) -> QWidget:
    card = ToolCompatibilityCard(f"Tool {tool.tool}", tool.part_description or tool.part_family or ", ".join(tool.parts[:3]) or "No part description")
    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.addWidget(badge("Compatible" if tool.compatible_eoats else "Review", "success" if tool.compatible_eoats else "warning"))
    header.addWidget(badge(tool.source or "Atlas source", "outline"))
    if tool.warning_count:
        header.addWidget(badge(f"{tool.warning_count} warning(s)", "warn"))
    header.addStretch(1)
    card.layout.addLayout(header)
    card.layout.addWidget(CompatibilityPathWidget(tool.tool, ", ".join(tool.compatible_eoats[:3]), tool.compatible_machines[:8]))
    card.layout.addWidget(_labeled_chips("Compatible EOATs", tool.compatible_eoats, empty="No linked EOATs", per_row=6))
    card.layout.addWidget(_labeled_chips("Compatible Machines", tool.compatible_machines, empty="No linked machines", per_row=6))
    buttons = []
    if tool.compatible_eoats:
        eoat_button = QPushButton("Open EOAT")
        eoat_button.clicked.connect(lambda _checked=False, eoat_id=tool.compatible_eoats[0]: controller.open_eoat(eoat_id))
        buttons.append(eoat_button)
    if buttons:
        card.layout.addWidget(action_row(*buttons))
    return card


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
    suffix = Path(str(standard.path)).suffix.upper().lstrip(".") or "DOC"
    card = DetailCard(standard.title or "Untitled standard", standard.snippet, eyebrow=standard.category or "Document")
    card.layout.addWidget(_chip_group([standard.category or "Document", suffix, "Read-only"], kind="outline", per_row=4))
    path_label = QLabel(standard.path)
    path_label.setObjectName("MicroText")
    path_label.setWordWrap(True)
    card.layout.addWidget(path_label)
    button = QPushButton("Open Document")
    button.clicked.connect(lambda _checked=False, path=standard.path: open_path(path))
    card.layout.addWidget(action_row(button))
    return card


def _build_information_entries(bundle: AtlasDataBundle | None) -> list[InformationLibraryEntry]:
    if bundle is None:
        return []
    entries = list(_static_information_entries())
    for standard in bundle.standards:
        entries.extend(_standard_information_entries(standard))
    for warning in bundle.warnings:
        entries.append(_warning_information_entry(warning))
    for eoat in bundle.eoats:
        for warning in eoat.warnings[:3]:
            entries.append(_warning_information_entry(warning, title_prefix=eoat.eoat_id))
    return [replace(entry, entry_id=f"{index:04d}-{entry.entry_id}") for index, entry in enumerate(entries, start=1)]


def _static_information_entries() -> list[InformationLibraryEntry]:
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
            ("Atlas App Help", "Tool / Mold / Part Search"),
            "Tool / Mold / Part Search",
            "Search tools, molds, parts, and descriptions to see compatible EOATs and machines.",
            "Tool cards show a compact Tool -> EOAT -> Machine flow. Use the single global What Do I Need action when you want a recommendation for the selected/searched tool.",
            ("tool", "mold", "part"),
        ),
        (
            ("Atlas App Help", "Compatibility Matrix"),
            "Compatibility Matrix",
            "The matrix is the dense sortable view for EOAT-machine-tool relationships.",
            "Use it when you need comparison or export-friendly rows. The matrix is intentionally denser than profile pages and is wrapped in a dedicated data panel so it does not compete visually with dashboard profiles.",
            ("matrix", "export", "dense data"),
        ),
        (
            ("Atlas App Help", "Overall Maps"),
            "Overall Maps",
            "Overall Maps summarize machine coverage and EOAT documentation heatmap status.",
            "Use the summary cards first, then inspect machine tiles or low-scoring EOAT tiles when planning cleanup or validating coverage before handoff.",
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
            ("Atlas App Help", "Standards Library"),
            "Standards Library",
            "The Standards Library lists EOAT standardization documents and opens the source files read-only.",
            "Likely EOAT standardization documents placed in the project root are safely copied into 03_Standards without overwriting existing files, then indexed as high-priority standards.",
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
            ("Atlas App Help", "Reports / Export"),
            "Reports / Export",
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
            ("Compatibility Logic", "Tool-to-Machine Compatibility"),
            "Tool-to-machine compatibility",
            "Atlas uses Press Capacity/tool-machine rows and normalized tool keys to connect tools to machines.",
            "Tool lookups should use cached dictionaries, not workbook rescans. Missing tool-machine links usually point to Press Capacity source gaps or normalization mismatches.",
            ("tool", "machine", "press capacity"),
        ),
        (
            ("Compatibility Logic", "EOAT-to-Tool Compatibility"),
            "EOAT-to-tool compatibility",
            "EOAT-to-tool links come from EOAT inventory/audit rows and normalized tool numbers.",
            "If an EOAT appears compatible with a tool but not a machine, check whether the tool exists in Press Capacity and whether the machine source data is available.",
            ("eoat", "tool", "indexes"),
        ),
        (
            ("Compatibility Logic", "Off-Machine EOAT Audits"),
            "Off-machine EOAT audits",
            "Off-machine audits may provide EOAT identity, condition, photos, and documentation context even before full compatibility is known.",
            "Use warnings and detail metadata to distinguish documented off-machine evidence from confirmed machine/tool compatibility.",
            ("audit", "off-machine", "photos"),
        ),
        (
            ("Compatibility Logic", "Compatibility Rows"),
            "Compatibility rows",
            "Dense compatibility rows are generated from cached Atlas bundle data for matrix and export workflows.",
            "The matrix is best for auditing many relationships at once; profile cards are best for answering a specific install question quickly.",
            ("matrix", "rows", "export"),
        ),
        (
            ("Compatibility Logic", "Confidence / Warnings"),
            "Compatibility confidence / warnings",
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
            ("Reports / Exports", "EOAT Summary"),
            "EOAT summary export",
            "EOAT summary exports package the selected EOAT profile context for offline review.",
            "Exports are generated from loaded cached data and should reflect the same warnings, compatibility, photos, and documentation status shown in the UI.",
            ("eoat export", "summary", "reports"),
        ),
        (
            ("Reports / Exports", "Machine Summary"),
            "Machine summary export",
            "Machine summary exports focus on robot context, compatible EOATs/tools, and warnings.",
            "Use this when sharing machine-specific setup or cleanup context without sending users into the full app.",
            ("machine export", "robot", "reports"),
        ),
        (
            ("Reports / Exports", "Tool Summary"),
            "Tool summary export",
            "Tool summary exports help communicate which EOATs and machines are linked to a tool/mold/part search.",
            "Tool summaries are useful when validating compatibility coverage or planning standards cleanup around a tooling family.",
            ("tool export", "compatibility", "reports"),
        ),
        (
            ("Reports / Exports", "Project Reports"),
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
            ("Troubleshooting", "No Compatibility Found"),
            "No compatibility found",
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
        related=("Documentation requirements", "Compatibility confidence", "Photo documentation rules"),
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
            "Related Atlas areas: EOAT profile readiness, Standards Library, Information Library, PM / Inspection, photo category warnings, and compatibility confidence warnings.",
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
        tree_path=("Troubleshooting", "Missing Source Files" if "missing" in summary.casefold() else "No Compatibility Found"),
        related=("Documentation requirements", "Compatibility confidence", "Source status"),
        indexed_at=time.time(),
    )


def _information_score(entry: InformationLibraryEntry, query: str) -> int:
    terms = [term.casefold() for term in query.split() if term.strip()]
    if not terms:
        return 1
    haystack = " ".join(
        [
            entry.title,
            entry.category,
            entry.summary,
            entry.body,
            entry.source,
            entry.path,
            entry.source_section,
            " ".join(entry.tags),
            " ".join(entry.tree_path),
        ]
    ).casefold()
    score = 0
    for term in terms:
        if term in haystack:
            score += 4 if term in entry.title.casefold() else (2 if term in entry.summary.casefold() else 1)
    return score


def _information_card(entry: InformationLibraryEntry) -> QWidget:
    card = DetailCard(entry.title, entry.summary, eyebrow=entry.category)
    card.layout.addWidget(_chip_group([entry.category, *entry.tags[:5]], kind="outline", per_row=5, limit=6))
    source = entry.path or entry.source
    source_label = QLabel(_short_path(source) if source else "Atlas generated guidance")
    source_label.setObjectName("MicroText")
    source_label.setWordWrap(True)
    source_label.setToolTip(source)
    card.layout.addWidget(source_label)
    buttons = []
    if entry.path:
        open_button = QPushButton("Open Source Document")
        open_button.clicked.connect(lambda _checked=False, path=entry.path: open_path(path))
        buttons.append(open_button)
    copy_button = QPushButton("Copy Summary")
    copy_button.clicked.connect(lambda _checked=False, text=f"{entry.title}\n\n{entry.summary}": QApplication.clipboard().setText(text))
    buttons.append(copy_button)
    card.layout.addWidget(action_row(*buttons))
    return card


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
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(value))


def _information_reference_text(entry: InformationLibraryEntry) -> str:
    pieces = [
        entry.title,
        "",
        entry.summary,
        "",
        entry.body,
        "",
        f"Category: {entry.category}",
        f"Tree path: {' / '.join(entry.tree_path) or entry.category}",
        f"Source: {entry.source}",
    ]
    if entry.path:
        pieces.append(f"Path: {entry.path}")
    if entry.source_section:
        pieces.append(f"Section: {entry.source_section}")
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
    section = CompatibilityCard("Compatibility", "Machine relationships from Atlas cached indexes.")
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
    section = CompatibilityCard("Compatibility", "Tool -> EOAT -> Machine relationships.")
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
                ("Standards", ", ".join(standard.title for standard in eoat.standards[:6])),
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
        "standards",
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
    return "Compatibility missing", "bad"


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
