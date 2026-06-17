from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTextEdit,
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
from core.atlas_models import AtlasDataBundle, EOATRecord, MachineRecord, RecommendationResult
from core.atlas_recommendations import recommend_for_query
from core.atlas_utils import normalized_eoat_key, normalized_machine_key
from core.compatibility_engine import compatibility_matrix_rows
from core.openers import open_path

from .widgets import MetricCard, action_row, fill_table, page_title, photo_thumb


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
        hero = QWidget()
        hero.setObjectName("AtlasHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(18, 16, 18, 16)
        title = QLabel("EOAT Atlas")
        title.setObjectName("HeroTitle")
        subtitle = QLabel("Search, understand, and install EOATs from the existing Command Center data.")
        subtitle.setObjectName("HeroSubtitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Enter Tool #, Machine #, EOAT ID, part name, robot type, or keyword")
        self.search.returnPressed.connect(self._run_search)
        what_button = QPushButton("What Do I Need?")
        what_button.setObjectName("PrimaryButton")
        what_button.clicked.connect(self._run_search)
        row = QHBoxLayout()
        row.addWidget(self.search, 1)
        row.addWidget(what_button)
        hero_layout.addWidget(title)
        hero_layout.addWidget(subtitle)
        hero_layout.addLayout(row)
        layout.addWidget(hero)

        quick = QHBoxLayout()
        for label, page in [
            ("Search EOAT", "eoats"),
            ("Search Machine", "machines"),
            ("Search Tool #", "tools"),
            ("Browse Photos", "photos"),
            ("Compatibility Matrix", "matrix"),
            ("View Standards", "standards"),
        ]:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, page=page: self.controller.show_page(page))
            quick.addWidget(button)
        layout.addLayout(quick)

        self.metrics = {
            "eoats": MetricCard("EOATs documented"),
            "machines": MetricCard("Machines covered"),
            "tools": MetricCard("Tools covered"),
            "photos": MetricCard("Photos linked"),
            "docs": MetricCard("Avg. documentation"),
            "warnings": MetricCard("Open warnings"),
        }
        metric_grid = QGridLayout()
        for index, card in enumerate(self.metrics.values()):
            metric_grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(metric_grid)

        self.status_table = QTableWidget()
        layout.addWidget(QLabel("Data sources"))
        layout.addWidget(self.status_table)
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
        rows = [
            {"Source": status.label, "Available": "Yes" if status.available else "No", "Path": status.path, "Message": status.message}
            for status in self.bundle.source_statuses
        ]
        fill_table(self.status_table, rows, ["Source", "Available", "Message", "Path"])

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
        self.input = QLineEdit()
        self.input.setPlaceholderText("Example: Tool 12345, Machine 14, P4-EOAT-0041, silicone OD")
        self.input.returnPressed.connect(self.run)
        run_button = QPushButton("Get Recommendation")
        run_button.setObjectName("PrimaryButton")
        run_button.clicked.connect(self.run)
        row.addWidget(self.input, 1)
        row.addWidget(run_button)
        layout.addLayout(row)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.candidates = QTableWidget()
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.output)
        splitter.addWidget(self.candidates)
        splitter.setSizes([340, 220])
        layout.addWidget(splitter, 1)
        open_button = QPushButton("Open EOAT Profile")
        open_button.clicked.connect(self.open_best)
        copy_button = QPushButton("Copy Recommendation")
        copy_button.clicked.connect(self.copy_result)
        export_button = QPushButton("Export Summary")
        export_button.clicked.connect(self.export_result)
        layout.addWidget(action_row(open_button, copy_button, export_button))

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
        self.output.setPlainText(_recommendation_text(self.result))
        rows = [
            {
                "Rank": candidate.rank,
                "EOAT": candidate.eoat_id,
                "Score": candidate.score,
                "Machines": ", ".join(candidate.machines),
                "Docs": f"{candidate.documentation_score}%",
                "Photos": candidate.photo_count,
                "Reasons": " ".join(candidate.reasons[:3]),
            }
            for candidate in self.result.candidates
        ]
        fill_table(self.candidates, rows, ["Rank", "EOAT", "Score", "Machines", "Docs", "Photos", "Reasons"])

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


class EOATBrowserPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.current: EOATRecord | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("EOAT Browser", "Search EOATs, review profile details, photos, warnings, and install context."))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by EOAT ID, tool, machine, type, status, part, or warning")
        self.filter.textChanged.connect(self.refresh)
        layout.addWidget(self.filter)
        splitter = QSplitter()
        self.table = QTableWidget()
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setSizes([720, 500])
        layout.addWidget(splitter, 1)
        copy_button = QPushButton("Copy EOAT ID")
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.current.eoat_id if self.current else ""))
        folder_button = QPushButton("Open Photos")
        folder_button.clicked.connect(self.open_photos)
        export_button = QPushButton("Export EOAT Summary")
        export_button.clicked.connect(self.export_current)
        layout.addWidget(action_row(copy_button, folder_button, export_button))

    def refresh(self) -> None:
        if self.bundle is None:
            return
        query = self.filter.text().strip().casefold()
        rows = []
        for eoat in self.bundle.eoats:
            haystack = " ".join(
                [eoat.eoat_id, eoat.eoat_type, eoat.status, " ".join(eoat.tools), " ".join(eoat.machines), eoat.part_description]
            ).casefold()
            if query and query not in haystack:
                continue
            rows.append(
                {
                    "EOAT": eoat.eoat_id,
                    "Tools": ", ".join(eoat.tools),
                    "Machines": ", ".join(eoat.machines),
                    "Type": eoat.eoat_type,
                    "Status": eoat.status,
                    "Docs": f"{eoat.documentation.score}%",
                    "Photos": eoat.photo_count,
                    "Warnings": eoat.warning_count,
                }
            )
        fill_table(self.table, rows, ["EOAT", "Tools", "Machines", "Type", "Status", "Docs", "Photos", "Warnings"])
        if rows and self.current is None:
            self.table.selectRow(0)

    def open_record(self, eoat_id: str) -> None:
        self.filter.setText(eoat_id)
        self.refresh()
        self._show_detail(_find_eoat(self.bundle, eoat_id) if self.bundle else None)

    def _selection_changed(self) -> None:
        row = _selected_row(self.table)
        if row:
            self._show_detail(_find_eoat(self.bundle, str(row.get("EOAT"))))

    def _show_detail(self, eoat: EOATRecord | None) -> None:
        self.current = eoat
        self.detail.setPlainText(_eoat_profile_text(eoat) if eoat else "Select an EOAT.")

    def open_photos(self) -> None:
        if self.current and self.current.photos.folder_path:
            open_path(self.current.photos.folder_path)

    def export_current(self) -> None:
        bundle = self.require_bundle()
        if bundle and self.current:
            path = export_eoat_summary(bundle, self.current)
            self.controller.show_status(f"Exported EOAT summary: {path}")


class MachineBrowserPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.current: MachineRecord | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Machine Browser", "Find machine EOAT compatibility, robot context, and warning status."))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by machine, robot, tool, EOAT, or part")
        self.filter.textChanged.connect(self.refresh)
        layout.addWidget(self.filter)
        splitter = QSplitter()
        self.table = QTableWidget()
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setSizes([700, 520])
        layout.addWidget(splitter, 1)
        export_button = QPushButton("Export Machine Summary")
        export_button.clicked.connect(self.export_current)
        matrix_button = QPushButton("Open Matrix")
        matrix_button.clicked.connect(lambda: self.controller.show_page("matrix"))
        layout.addWidget(action_row(matrix_button, export_button))

    def refresh(self) -> None:
        if self.bundle is None:
            return
        query = self.filter.text().strip().casefold()
        rows = []
        for machine in self.bundle.machines:
            haystack = " ".join(
                [machine.machine, machine.robot_type, machine.robot_model, " ".join(machine.compatible_eoats), " ".join(machine.compatible_tools)]
            ).casefold()
            if query and query not in haystack:
                continue
            rows.append(
                {
                    "Machine": machine.machine,
                    "Robot": machine.robot_type or machine.robot_model,
                    "EOATs": len(machine.compatible_eoats),
                    "Tools": len(machine.compatible_tools),
                    "Current EOAT": machine.current_eoat,
                    "Docs": f"{machine.documentation_score}%",
                    "Warnings": machine.warning_count,
                }
            )
        fill_table(self.table, rows, ["Machine", "Robot", "EOATs", "Tools", "Current EOAT", "Docs", "Warnings"])
        if rows and self.current is None:
            self.table.selectRow(0)

    def open_record(self, machine_id: str) -> None:
        self.filter.setText(machine_id)
        self.refresh()
        self._show_detail(_find_machine(self.bundle, machine_id) if self.bundle else None)

    def _selection_changed(self) -> None:
        row = _selected_row(self.table)
        if row:
            self._show_detail(_find_machine(self.bundle, str(row.get("Machine"))))

    def _show_detail(self, machine: MachineRecord | None) -> None:
        self.current = machine
        self.detail.setPlainText(_machine_profile_text(machine) if machine else "Select a machine.")

    def export_current(self) -> None:
        bundle = self.require_bundle()
        if bundle and self.current:
            path = export_machine_summary(bundle, self.current)
            self.controller.show_status(f"Exported machine summary: {path}")


class ToolSearchPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Tool / Mold / Part Search", "Find compatible EOATs and machines from tool, mold, part number, or description."))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search tool, mold, part number, or description")
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.table = QTableWidget()
        layout.addWidget(self.table, 1)
        recommend_button = QPushButton("Run What Do I Need?")
        recommend_button.setObjectName("PrimaryButton")
        recommend_button.clicked.connect(lambda: self.controller.open_recommendation(self.search.text().strip()))
        layout.addWidget(action_row(recommend_button))

    def refresh(self) -> None:
        if self.bundle is None:
            return
        query = self.search.text().strip().casefold()
        rows = []
        for tool in self.bundle.tools:
            haystack = " ".join([tool.tool, tool.part_description, tool.part_family, " ".join(tool.parts), " ".join(tool.compatible_eoats)]).casefold()
            if query and query not in haystack:
                continue
            rows.append(
                {
                    "Tool": tool.tool,
                    "Part": tool.part_description or ", ".join(tool.parts[:2]),
                    "EOATs": ", ".join(tool.compatible_eoats),
                    "Machines": ", ".join(tool.compatible_machines),
                    "Source": tool.source,
                    "Warnings": tool.warning_count,
                }
            )
        fill_table(self.table, rows, ["Tool", "Part", "EOATs", "Machines", "Source", "Warnings"])


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
        layout.addLayout(controls)
        self.table = QTableWidget()
        layout.addWidget(self.table, 1)

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
        self.summary = QTableWidget()
        self.docs = QTableWidget()
        layout.addWidget(QLabel("Machine Grid Map"))
        layout.addWidget(self.summary, 1)
        layout.addWidget(QLabel("Documentation Heatmap"))
        layout.addWidget(self.docs, 1)

    def refresh(self) -> None:
        if self.bundle is None:
            return
        machine_rows = [
            {
                "Machine": machine.machine,
                "Known EOAT": machine.current_eoat or ", ".join(machine.compatible_eoats[:2]),
                "Compatible EOATs": len(machine.compatible_eoats),
                "Documentation": f"{machine.documentation_score}%",
                "Status": "Warnings" if machine.warnings else "OK",
            }
            for machine in self.bundle.machines
        ]
        doc_rows = [
            {
                "EOAT": eoat.eoat_id,
                "Completeness": eoat.documentation.status_label,
                "Score": f"{eoat.documentation.score}%",
                "Photos": eoat.photo_count,
                "Compatibility": "Known" if eoat.machines else "Missing",
                "Warnings": eoat.warning_count,
            }
            for eoat in self.bundle.eoats
        ]
        fill_table(self.summary, machine_rows, ["Machine", "Known EOAT", "Compatible EOATs", "Documentation", "Status"])
        fill_table(self.docs, doc_rows, ["EOAT", "Completeness", "Score", "Photos", "Compatibility", "Warnings"])


class PhotosPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.current: EOATRecord | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Photos", "Browse linked EOAT photos without moving or renaming source files."))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by EOAT, tool, machine, or category")
        self.filter.textChanged.connect(self.refresh)
        layout.addWidget(self.filter)
        splitter = QSplitter()
        self.table = QTableWidget()
        self.table.itemSelectionChanged.connect(self._selection_changed)
        scroll = QScrollArea()
        self.thumb_widget = QWidget()
        self.thumb_layout = QGridLayout(self.thumb_widget)
        scroll.setWidget(self.thumb_widget)
        scroll.setWidgetResizable(True)
        splitter.addWidget(self.table)
        splitter.addWidget(scroll)
        splitter.setSizes([500, 700])
        layout.addWidget(splitter, 1)
        open_button = QPushButton("Open Folder")
        open_button.clicked.connect(self.open_folder)
        layout.addWidget(action_row(open_button))

    def refresh(self) -> None:
        if self.bundle is None:
            return
        query = self.filter.text().strip().casefold()
        rows = []
        for eoat in self.bundle.eoats:
            haystack = " ".join([eoat.eoat_id, " ".join(eoat.tools), " ".join(eoat.machines), eoat.photos.folder_path]).casefold()
            if query and query not in haystack:
                continue
            rows.append({"EOAT": eoat.eoat_id, "Photos": eoat.photo_count, "Folder": eoat.photos.folder_path, "Missing": ", ".join(eoat.photos.missing_categories)})
        fill_table(self.table, rows, ["EOAT", "Photos", "Missing", "Folder"])
        if rows and self.current is None:
            self.table.selectRow(0)

    def _selection_changed(self) -> None:
        row = _selected_row(self.table)
        if row:
            self.current = _find_eoat(self.bundle, str(row.get("EOAT")))
            self._render_thumbnails()

    def _render_thumbnails(self) -> None:
        while self.thumb_layout.count():
            item = self.thumb_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        if self.current is None:
            return
        photos = list((*self.current.photos.photos, *self.current.photos.indexed_photos))[:48]
        for index, photo in enumerate(photos):
            self.thumb_layout.addWidget(photo_thumb(photo.path), index // 4, index % 4)
        self.thumb_layout.setRowStretch((len(photos) // 4) + 1, 1)

    def open_folder(self) -> None:
        if self.current and self.current.photos.folder_path:
            open_path(self.current.photos.folder_path)


class StandardsPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Standards", "Open and search available EOAT standardization documents."))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Search vacuum, tubing, sensors, quick disconnects, PM, documentation")
        self.filter.textChanged.connect(self.refresh)
        self.table = QTableWidget()
        self.table.itemDoubleClicked.connect(lambda _item: self.open_selected())
        open_button = QPushButton("Open Document")
        open_button.clicked.connect(self.open_selected)
        layout.addWidget(self.filter)
        layout.addWidget(self.table, 1)
        layout.addWidget(action_row(open_button))

    def refresh(self) -> None:
        if self.bundle is None:
            return
        query = self.filter.text().strip().casefold()
        rows = []
        for standard in self.bundle.standards:
            haystack = " ".join([standard.title, standard.category, standard.snippet, standard.path]).casefold()
            if query and query not in haystack:
                continue
            rows.append({"Title": standard.title, "Category": standard.category, "Snippet": standard.snippet, "Path": standard.path})
        fill_table(self.table, rows, ["Title", "Category", "Snippet", "Path"])

    def open_selected(self) -> None:
        row = _selected_row(self.table)
        if row:
            open_path(str(row.get("Path")))


class PMInspectionPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("PM / Inspection", "Generated PM and pre-install guidance from loaded EOAT data."))
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)

    def refresh(self) -> None:
        if self.bundle is None:
            return
        missing_pm = [eoat.eoat_id for eoat in self.bundle.eoats if "Maintenance Frequency" in eoat.documentation.missing_fields]
        missing_pm_lines = [f"- {eoat_id}" for eoat_id in missing_pm[:80]] or ["No missing PM frequency fields found."]
        lines = [
            "EOAT PM Checklist",
            "",
            "Weekly inspection:",
            "1. Check cups/grippers for wear, cracks, looseness, or missing hardware.",
            "2. Inspect tubing and cable routing for pinch, rub, kink, or strain points.",
            "3. Verify quick disconnects, sensors, and confirmation signals before production.",
            "4. Review known issues for the EOAT and machine before install.",
            "",
            "Monthly inspection:",
            "1. Verify EOAT documentation, BOM/spare parts, and revision references.",
            "2. Review repeated wear/damage notes and update PM frequency if needed.",
            "3. Confirm photo evidence still represents current EOAT condition.",
            "",
            "EOATs missing PM info:",
            *missing_pm_lines,
        ]
        self.text.setPlainText("\n".join(lines))


class GapsPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Documentation Gaps", "Action-oriented warnings from Atlas data checks."))
        self.table = QTableWidget()
        layout.addWidget(self.table, 1)

    def refresh(self) -> None:
        if self.bundle is None:
            return
        rows = []
        for warning in self.bundle.warnings:
            rows.append(_warning_row(warning))
        for eoat in self.bundle.eoats:
            for warning in eoat.warnings:
                rows.append(_warning_row(warning, fallback_eoat=eoat.eoat_id))
        fill_table(self.table, rows, ["Severity", "What", "Why it matters", "Suggested fix", "EOAT", "Machine", "Tool", "Source"])


class ReportsPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Reports / Export", "Timestamped Atlas exports. Source workbooks and photos are not modified."))
        buttons = [
            ("Compatibility matrix CSV", lambda: export_compatibility_matrix(self.bundle)),
            ("Documentation gap report", lambda: export_documentation_gap_report(self.bundle)),
            ("Photo coverage report", lambda: export_photo_coverage_report(self.bundle)),
        ]
        for label, callback in buttons:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, callback=callback: self._run_export(callback))
            layout.addWidget(button)
        layout.addStretch(1)

    def _run_export(self, callback) -> None:
        if self.require_bundle() is None:
            return
        path = callback()
        self.controller.show_status(f"Exported: {path}")


class DiagnosticsPage(BaseAtlasPage):
    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(page_title("Settings / Diagnostics", "Path status, refresh controls, and Atlas performance timings."))
        refresh_button = QPushButton("Refresh Data")
        refresh_button.setObjectName("PrimaryButton")
        refresh_button.clicked.connect(lambda: self.controller.refresh_data(force=True))
        layout.addWidget(refresh_button)
        self.sources = QTableWidget()
        self.metrics = QTableWidget()
        layout.addWidget(QLabel("Source paths"))
        layout.addWidget(self.sources, 1)
        layout.addWidget(QLabel("Performance diagnostics"))
        layout.addWidget(self.metrics, 1)

    def refresh(self) -> None:
        if self.bundle is None:
            return
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


def _eoat_profile_text(eoat: EOATRecord | None) -> str:
    if eoat is None:
        return ""
    values = [
        ("EOAT ID", eoat.eoat_id),
        ("Status", eoat.status),
        ("EOAT Type", eoat.eoat_type),
        ("Tools", ", ".join(eoat.tools)),
        ("Machines", ", ".join(eoat.machines)),
        ("Part", eoat.part_description or eoat.part_family),
        ("Connection", eoat.connection_type),
        ("Robot", ", ".join(eoat.robot_types + eoat.robot_models)),
        ("Vacuum", eoat.vacuum_info),
        ("Pressure", eoat.pressure_info),
        ("Gripper", eoat.gripper_info),
        ("Sensors", eoat.sensor_info),
        ("Tubing Notes", eoat.tubing_notes),
        ("Documentation", f"{eoat.documentation.score}% - {eoat.documentation.status_label}"),
        ("Photos", f"{eoat.photo_count} linked; folder: {eoat.photos.folder_path}"),
        ("Known Issues", eoat.known_issues),
    ]
    lines = [f"{key}: {value or '-'}" for key, value in values]
    if eoat.warnings:
        lines.extend(["", "Warnings:", *[f"- {warning.title}: {warning.message}" for warning in eoat.warnings]])
    if eoat.standards:
        lines.extend(["", "Applicable Standards:", *[f"- {standard.title} ({standard.category})" for standard in eoat.standards[:8]]])
    return "\n".join(lines)


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
    "GapsPage",
    "HomePage",
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
