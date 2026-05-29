from __future__ import annotations

import time

try:
    from PySide6.QtWidgets import (
        QCheckBox,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QScrollArea,
        QSplitter,
        QTableWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QCheckBox = QGridLayout = QGroupBox = QHBoxLayout = QLabel = QPushButton = QScrollArea = QSplitter = QTableWidget = QTextEdit = QVBoxLayout = QWidget = None

from app.page_async import AsyncRefreshMixin, log_page_performance
from app.page_tasks import run_tool_background
from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from core.deliverable_check import run_final_deliverable_check
from core.final_handoff import build_final_handoff_package
from core.final_handoff_readiness import (
    build_final_handoff_readiness,
    export_deliverable_readiness,
    export_leadership_summary,
    export_open_items_carryover,
    export_technical_appendix,
)
from core.final_summary import generate_final_project_summary
from core.openers import open_path
from core.paths import resolve_project_paths
from core.presentation_export import export_presentation_assets
from core.project_backup import backup_project
from core.workflows import run_workflow

from .analysis_widgets import populate_table


class HandoffPage(AsyncRefreshMixin, QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._init_async_refresh("handoff")
        self._quiet_readiness_refresh = False
        layout = QVBoxLayout(self)
        heading = QLabel("Final Handoff")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self._deliverable_group())
        left_layout.addWidget(self._presentation_group())
        left_layout.addWidget(self._summary_group())
        left_layout.addWidget(self._handoff_group())
        left_layout.addWidget(self._release_group())
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        left_scroll.setWidget(left)
        splitter.addWidget(left_scroll)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Deliverable Status"))
        self.status_table = QTableWidget()
        right_layout.addWidget(self.status_table, stretch=2)
        self.result_panel = ToolRunPanel()
        right_layout.addWidget(self.result_panel, stretch=1)
        self.preview = ReportViewer()
        self.preview.setMaximumHeight(240)
        self.preview.setPlaceholderText("No final report selected yet. Run a handoff action to preview the generated index or report.")
        right_layout.addWidget(self.preview, stretch=2)
        splitter.addWidget(right)
        splitter.setSizes([430, 760])
        layout.addWidget(splitter, stretch=1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.on_show()

    def on_show(self) -> None:
        self.refresh_status()
        return True

    def _deliverable_group(self) -> QGroupBox:
        box = QGroupBox("Final Deliverable Status")
        layout = QVBoxLayout(box)
        row = QHBoxLayout()
        run = QPushButton("Run Final Deliverable Check")
        run.clicked.connect(self.run_deliverable_check)
        open_folder = QPushButton("Open Handoff Package Folder")
        open_folder.clicked.connect(lambda: self.open_folder("handoff"))
        refresh = QPushButton("Refresh Status")
        refresh.clicked.connect(lambda: self.refresh_status(force=True))
        row.addWidget(run)
        row.addWidget(open_folder)
        row.addWidget(refresh)
        layout.addLayout(row)
        return box

    def _presentation_group(self) -> QGroupBox:
        box = QGroupBox("Presentation Assets")
        layout = QHBoxLayout(box)
        button = QPushButton("Generate Presentation Assets")
        button.clicked.connect(self.generate_presentation_assets)
        open_folder = QPushButton("Open Presentation Assets Folder")
        open_folder.clicked.connect(lambda: self.open_folder("presentation"))
        layout.addWidget(button)
        layout.addWidget(open_folder)
        return box

    def _summary_group(self) -> QGroupBox:
        box = QGroupBox("Final Summary")
        layout = QVBoxLayout(box)
        self.summary_notes = QTextEdit()
        self.summary_notes.setPlaceholderText("Optional notes for the final project summary draft")
        self.summary_notes.setMaximumHeight(90)
        self.summary_docx = QCheckBox("Also create DOCX")
        row = QHBoxLayout()
        button = QPushButton("Generate Final Project Summary Draft")
        button.clicked.connect(self.generate_final_summary)
        open_folder = QPushButton("Open Final Report Folder")
        open_folder.clicked.connect(lambda: self.open_folder("final_report"))
        row.addWidget(button)
        row.addWidget(open_folder)
        export_row = QHBoxLayout()
        leadership = QPushButton("Export Leadership Summary")
        leadership.clicked.connect(self.export_leadership_summary)
        appendix = QPushButton("Export Technical Appendix")
        appendix.clicked.connect(self.export_technical_appendix)
        carryover = QPushButton("Export Open Items Carryover")
        carryover.clicked.connect(self.export_open_items_carryover)
        readiness = QPushButton("Export Readiness Checklist")
        readiness.clicked.connect(self.export_readiness_checklist)
        export_row.addWidget(leadership)
        export_row.addWidget(appendix)
        export_row.addWidget(carryover)
        export_row.addWidget(readiness)
        layout.addWidget(self.summary_notes)
        layout.addWidget(self.summary_docx)
        layout.addLayout(row)
        layout.addLayout(export_row)
        return box

    def _handoff_group(self) -> QGroupBox:
        box = QGroupBox("Handoff Package")
        layout = QVBoxLayout(box)
        options = QGridLayout()
        self.dry_run = QCheckBox("Dry run")
        self.dry_run.setChecked(True)
        self.include_daily = QCheckBox("Include daily reports")
        self.include_weekly = QCheckBox("Include weekly reports")
        self.include_weekly.setChecked(True)
        self.include_mentor = QCheckBox("Include mentor briefs")
        self.include_photos = QCheckBox("Include actual photo files")
        for index, widget in enumerate([self.dry_run, self.include_daily, self.include_weekly, self.include_mentor, self.include_photos]):
            options.addWidget(widget, index // 2, index % 2)
        layout.addLayout(options)
        row = QHBoxLayout()
        build = QPushButton("Build Final Handoff Package")
        build.clicked.connect(self.build_handoff_package)
        open_folder = QPushButton("Open Handoff Package Folder")
        open_folder.clicked.connect(lambda: self.open_folder("handoff"))
        row.addWidget(build)
        row.addWidget(open_folder)
        layout.addLayout(row)
        return box

    def _release_group(self) -> QGroupBox:
        box = QGroupBox("Release Safety")
        layout = QHBoxLayout(box)
        final_review = QPushButton("Run Final Review Workflow")
        final_review.clicked.connect(lambda: self._run_background("handoff_final_review", "Final Review Workflow", lambda: run_workflow(self.config.project_root, "final-review"), modifies_files=True))
        backup = QPushButton("Backup Workbook")
        backup.clicked.connect(lambda: self._run_background("handoff_backup_workbook", "Workbook Backup", lambda: backup_project(self.config.project_root, mode="workbook"), modifies_files=True, workbook_lock=True))
        light = QPushButton("Create Light Backup")
        light.clicked.connect(lambda: self._run_background("handoff_backup_light", "Light Project Backup", lambda: backup_project(self.config.project_root, mode="light"), modifies_files=True))
        layout.addWidget(final_review)
        layout.addWidget(backup)
        layout.addWidget(light)
        return box

    def refresh_status(self, *_args, force: bool = False, quiet: bool = False) -> bool:
        self._quiet_readiness_refresh = quiet
        return self._begin_background_refresh(
            task_id="handoff_readiness_refresh",
            name="Final Handoff Readiness Refresh",
            load=lambda: build_final_handoff_readiness(self.config.project_root),
            apply_result=self._apply_readiness_result,
            force=force,
            loading_text="" if quiet else "Loading final handoff readiness in background...",
        )

    def _apply_readiness_result(self, readiness, data_load_seconds: float) -> None:
        render_started = time.perf_counter()
        rows = [
            {
                "Deliverable": item.label,
                "Status": item.status,
                "Evidence": "; ".join(item.evidence[:2]),
                "Warnings": "; ".join(item.warnings),
                "Recommended Action": item.recommended_action,
            }
            for item in readiness.deliverables
        ]
        populate_table(self.status_table, rows, ["Deliverable", "Status", "Evidence", "Warnings", "Recommended Action"])
        render_seconds = time.perf_counter() - render_started
        log_page_performance(
            self.config.project_root,
            "handoff",
            "data_load",
            data_load_seconds,
            details={"row_count": len(rows)},
        )
        log_page_performance(
            self.config.project_root,
            "handoff",
            "table_render",
            render_seconds,
            details={"row_count": len(rows)},
        )
        if self._quiet_readiness_refresh:
            self._quiet_readiness_refresh = False
        else:
            self.result_panel.show_text(f"Loaded final handoff readiness in {data_load_seconds:.1f}s.")

    def _show_result(self, result) -> None:
        self.result_panel.show_result(result)
        if result.output_reports:
            self.preview.load_report_file(result.output_reports[0])
        self.refresh_status(force=True, quiet=True)

    def run_deliverable_check(self) -> None:
        self._run_background("handoff_deliverable_check", "Final Deliverable Check", lambda: run_final_deliverable_check(self.config.project_root), modifies_files=True)

    def generate_presentation_assets(self) -> None:
        self._run_background("handoff_presentation_assets", "Presentation Assets", lambda: export_presentation_assets(self.config.project_root, include_docx=False), modifies_files=True)

    def generate_final_summary(self) -> None:
        self._run_background(
            "handoff_final_summary",
            "Final Project Summary",
            lambda: generate_final_project_summary(
                    self.config.project_root,
                    include_docx=self.summary_docx.isChecked(),
                    notes=self.summary_notes.toPlainText(),
                ),
            modifies_files=True,
        )

    def export_leadership_summary(self) -> None:
        self._run_background("handoff_leadership_summary", "Leadership Summary Export", lambda: export_leadership_summary(self.config.project_root), modifies_files=True)

    def export_technical_appendix(self) -> None:
        self._run_background("handoff_technical_appendix", "Technical Appendix Export", lambda: export_technical_appendix(self.config.project_root), modifies_files=True)

    def export_open_items_carryover(self) -> None:
        self._run_background("handoff_open_items_carryover", "Open Items Carryover Export", lambda: export_open_items_carryover(self.config.project_root), modifies_files=True)

    def export_readiness_checklist(self) -> None:
        self._run_background("handoff_readiness_checklist", "Readiness Checklist Export", lambda: export_deliverable_readiness(self.config.project_root), modifies_files=True)

    def build_handoff_package(self) -> None:
        self._run_background(
            "handoff_build_package",
            "Final Handoff Package",
            lambda: build_final_handoff_package(
                    self.config.project_root,
                    include_daily_reports=self.include_daily.isChecked(),
                    include_weekly_reports=self.include_weekly.isChecked(),
                    include_mentor_briefs=self.include_mentor.isChecked(),
                    include_photo_files=self.include_photos.isChecked(),
                    dry_run=self.dry_run.isChecked(),
                ),
            modifies_files=not self.dry_run.isChecked(),
        )

    def open_folder(self, folder: str) -> None:
        paths = resolve_project_paths(self.config.project_root)
        lookup = {
            "handoff": paths.final_handoff,
            "presentation": paths.presentation_assets_root,
            "final_report": paths.final_report,
        }
        result = open_path(lookup[folder])
        if not result.success:
            self.result_panel.show_result(result)

    def _run_background(self, task_id: str, name: str, func, modifies_files: bool = False, workbook_lock: bool = False) -> None:
        run_tool_background(
            self.result_panel,
            task_id,
            name,
            func,
            self._show_result,
            modifies_files=modifies_files,
            workbook_lock=workbook_lock,
        )
