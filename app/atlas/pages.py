from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
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
    title: str
    category: str
    snippet: str
    source: str = "Atlas"
    path: str = ""
    tags: tuple[str, ...] = ()
    modified: float = 0.0


class InformationLibraryPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.entries: list[InformationLibraryEntry] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Information Library", "Search Atlas help, EOAT standards, compatibility rules, photos, PM guidance, and troubleshooting references."))
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        self.search = ModernSearchBar("Search standards, compatibility, photos, PM, settings, warnings, or exports")
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

    def set_bundle(self, bundle: AtlasDataBundle | None) -> None:
        self.bundle = bundle
        self.entries = _build_information_entries(bundle) if bundle is not None else []
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
        _clear_layout(self.card_layout)
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
        if scored:
            summary = InfoPanel("Library Results", f"{len(scored)} matching reference item(s). Search uses an in-memory index built at refresh time.")
            self.card_layout.addWidget(summary)
        for _score, entry in scored[:80]:
            self.card_layout.addWidget(_information_card(entry))
        if not scored:
            self.card_layout.addWidget(EmptyStateWidget("No library entries matched", "Try standards, photos, PM, compatibility, troubleshooting, settings, or an EOAT keyword."))
        elif len(scored) > 80:
            self.card_layout.addWidget(EmptyStateWidget("More results available", f"Showing first 80 of {len(scored)}. Refine the search to narrow results."))
        self.card_layout.addStretch(1)


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
            ("Theme", self.theme_combo),
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


class PhotoCarouselDialog(QDialog):
    SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic"}

    def __init__(self, eoat: EOATRecord, *, prefetch: bool = True, parent=None):
        super().__init__(parent)
        self.eoat = eoat
        self.prefetch = prefetch
        self.photos = [photo for photo in _combined_photos(eoat) if Path(photo.path).suffix.casefold() in self.SUPPORTED_SUFFIXES]
        self.index = 0
        self._prefetched: dict[int, QPixmap] = {}
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

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        self.previous_button = QPushButton("Previous")
        self.previous_button.clicked.connect(self.previous_photo)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.next_photo)
        folder_button = QPushButton("Open Folder")
        folder_button.clicked.connect(self.open_folder)
        external_button = QPushButton("Open Externally")
        external_button.clicked.connect(self.open_current_external)
        controls.addWidget(self.previous_button)
        controls.addWidget(self.next_button)
        controls.addStretch(1)
        controls.addWidget(folder_button)
        controls.addWidget(external_button)
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
        self._show_photo()

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

    def open_folder(self) -> None:
        if self.eoat.photos.folder_path:
            open_path(self.eoat.photos.folder_path)

    def open_current_external(self) -> None:
        if self.photos:
            open_path(self.photos[self.index].path)

    def _show_photo(self) -> None:
        if not self.photos:
            self.count_label.setText("0 / 0")
            self.filename_label.setText("No previewable photos found.")
            self.image_label.setText("No previewable photos found.")
            return
        photo = self.photos[self.index]
        self.count_label.setText(f"{self.index + 1} / {len(self.photos)}")
        category = f" - {photo.category}" if photo.category else ""
        self.filename_label.setText(f"{photo.filename or Path(photo.path).name}{category}")
        self.filename_label.setToolTip(photo.path)
        pixmap = self._pixmap_for_index(self.index)
        if pixmap.isNull():
            self.image_label.setText(f"Could not preview {Path(photo.path).name}")
            self.image_label.setPixmap(QPixmap())
        else:
            size = self.image_label.size()
            self.image_label.setPixmap(
                pixmap.scaled(
                    max(120, size.width() - 18),
                    max(120, size.height() - 18),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self.previous_button.setEnabled(len(self.photos) > 1)
        self.next_button.setEnabled(len(self.photos) > 1)
        if self.prefetch and len(self.photos) > 1:
            self._pixmap_for_index((self.index - 1) % len(self.photos))
            self._pixmap_for_index((self.index + 1) % len(self.photos))

    def _pixmap_for_index(self, index: int) -> QPixmap:
        if index not in self._prefetched:
            self._prefetched[index] = QPixmap(self.photos[index].path)
        return self._prefetched[index]


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
        entries.append(_standard_information_entry(standard))
    for warning in bundle.warnings:
        entries.append(_warning_information_entry(warning))
    for eoat in bundle.eoats:
        for warning in eoat.warnings[:3]:
            entries.append(_warning_information_entry(warning, title_prefix=eoat.eoat_id))
    return entries


def _static_information_entries() -> list[InformationLibraryEntry]:
    return [
        InformationLibraryEntry(
            "What Do I Need? inputs",
            "App Help",
            "Enter a Tool #, Machine #, EOAT ID, part description, robot type, mold, or keyword to get a ranked EOAT recommendation with an install checklist.",
            tags=("recommendations", "search", "install"),
        ),
        InformationLibraryEntry(
            "Compatibility logic",
            "Compatibility",
            "Atlas combines EOAT Inventory rows, Press Capacity tool-to-machine relationships, Robot Info, and cached normalized indexes. Search does not rescan workbooks.",
            tags=("tool", "machine", "eoat", "indexes"),
        ),
        InformationLibraryEntry(
            "Photo documentation rules",
            "Photos",
            "Photo cards summarize folder status and missing categories. Open View Photos to load images in the carousel one at a time.",
            tags=("photos", "carousel", "lazy loading"),
        ),
        InformationLibraryEntry(
            "Documentation readiness",
            "Documentation Requirements",
            "Readiness is driven by photos present, documentation score, machine compatibility, robot info, standards references, and warning count.",
            tags=("readiness", "documentation", "warnings"),
        ),
        InformationLibraryEntry(
            "PM / Inspection guidance",
            "PM / Inspection",
            "Review cups/grippers, tubing and cable routing, quick disconnects, sensor confirmation, warning cards, and PM frequency before staging EOATs.",
            tags=("pm", "inspection", "maintenance"),
        ),
        InformationLibraryEntry(
            "Settings and diagnostics",
            "Settings",
            "Settings control theme, startup page, photo viewer behavior, lazy previews, diagnostics visibility, list density, export behavior, and auto-refresh on startup.",
            tags=("settings", "dark mode", "diagnostics"),
        ),
        InformationLibraryEntry(
            "Reports and exports",
            "Reports / Exports",
            "Atlas exports timestamped summaries under the project export folder and does not modify source workbooks or photo folders.",
            tags=("exports", "reports", "read-only"),
        ),
        InformationLibraryEntry(
            "Troubleshooting missing compatibility",
            "Troubleshooting",
            "If an EOAT has partial compatibility, check Tool # normalization, Press Capacity rows, machine fields, Robot Info, and source EOAT Inventory data.",
            tags=("troubleshooting", "compatibility", "missing data"),
        ),
    ]


def _standard_information_entry(standard: StandardReference) -> InformationLibraryEntry:
    path = Path(standard.path)
    category = _standard_information_category(standard)
    suffix = path.suffix.upper().lstrip(".") or "DOC"
    tags = tuple(tag for tag in (standard.category, suffix, "standard", "read-only") if tag)
    return InformationLibraryEntry(
        title=standard.title or path.stem or "Untitled standard",
        category=category,
        snippet=standard.snippet or "Open the source document for full guidance.",
        source=path.name or standard.path,
        path=standard.path,
        tags=tags,
        modified=_file_mtime(path),
    )


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


def _warning_information_entry(warning, *, title_prefix: str = "") -> InformationLibraryEntry:
    title = f"{title_prefix}: {warning.title}" if title_prefix else warning.title
    pieces = [warning.message, warning.why_it_matters, warning.suggested_fix]
    snippet = " ".join(piece for piece in pieces if piece) or "Review source data for this warning."
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
        title=title or "Atlas warning",
        category="Troubleshooting",
        snippet=snippet,
        source=warning.source or "Atlas data checks",
        tags=tags,
    )


def _information_score(entry: InformationLibraryEntry, query: str) -> int:
    terms = [term.casefold() for term in query.split() if term.strip()]
    if not terms:
        return 1
    haystack = " ".join([entry.title, entry.category, entry.snippet, entry.source, entry.path, " ".join(entry.tags)]).casefold()
    score = 0
    for term in terms:
        if term in haystack:
            score += 2 if term in entry.title.casefold() else 1
    return score


def _information_card(entry: InformationLibraryEntry) -> QWidget:
    card = DetailCard(entry.title, entry.snippet, eyebrow=entry.category)
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
    copy_button.clicked.connect(lambda _checked=False, text=f"{entry.title}\n\n{entry.snippet}": QApplication.clipboard().setText(text))
    buttons.append(copy_button)
    card.layout.addWidget(action_row(*buttons))
    return card


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
