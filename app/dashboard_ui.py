from __future__ import annotations

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QBrush, QColor, QFont
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QProgressBar, QStackedWidget, QSplitter, QTreeWidget, QTreeWidgetItem, QWidget
except ImportError:  # pragma: no cover
    Qt = QBrush = QColor = QFont = QApplication = QLabel = QMainWindow = QProgressBar = QStackedWidget = QSplitter = QTreeWidget = QTreeWidgetItem = QWidget = None

from core.config import load_config, save_config
from core.constants import APP_NAME
from .task_runner import get_task_manager
from .theme import app_stylesheet, theme_tokens
from .navigation import NAV_SECTIONS
from .ui_constants import DEFAULT_WINDOW_HEIGHT, DEFAULT_WINDOW_WIDTH, MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, SIDEBAR_WIDTH
from .pages.audit import AuditPage
from .pages.audit_progress import AuditProgressPage
from .pages.bom_spares import BomSparesPage
from .pages.fmea import FmeaPage
from .pages.handoff import HandoffPage
from .pages.home import HomePage
from .pages.issue_analysis import IssueAnalysisPage
from .pages.kpi_dashboard import KpiDashboardPage
from .pages.photos import PhotosPage
from .pages.pilot_candidates import PilotCandidatesPage
from .pages.pm_checklists import PmChecklistsPage
from .pages.reports import ReportsPage
from .pages.schedule import SchedulePage
from .pages.settings import SettingsPage
from .pages.standards_docs import StandardsDocsPage
from .pages.tool_registry import ToolRegistryPage
from .pages.workbook_health import WorkbookHealthPage


class DashboardWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.setWindowTitle(APP_NAME)
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.task_manager = get_task_manager()

        self.nav = QTreeWidget()
        self.nav.setObjectName("SidebarNav")
        self.nav.setHeaderHidden(True)
        self.nav.setIndentation(12)
        self.nav.setRootIsDecorated(False)
        self.nav.setMinimumWidth(SIDEBAR_WIDTH)
        self.nav.setMaximumWidth(SIDEBAR_WIDTH + 45)
        self.stack = QStackedWidget()
        self.stack.setObjectName("ContentStack")
        self.pages: dict[str, object] = {}
        self.page_indexes: dict[str, int] = {}
        self.page_factories = self._build_page_factories()
        for section in NAV_SECTIONS:
            header = QTreeWidgetItem([section.label])
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            header.setData(0, Qt.ItemDataRole.UserRole, "")
            header_font = QFont()
            header_font.setBold(True)
            header_font.setPointSize(8)
            header.setFont(0, header_font)
            header.setForeground(0, QBrush(QColor(theme_tokens(self.config.theme)["sidebar_group_text"])))
            self.nav.addTopLevelItem(header)
            header.setExpanded(True)
            for item in section.items:
                child = QTreeWidgetItem([item.label])
                child.setData(0, Qt.ItemDataRole.UserRole, item.page_key)
                header.addChild(child)
                self.page_indexes[item.page_key] = self.stack.count()
                placeholder = QLabel(f"Loading {item.label}...")
                placeholder.setWordWrap(True)
                self.stack.addWidget(placeholder)

        splitter = QSplitter()
        splitter.setObjectName("MainSplitter")
        splitter.addWidget(self.nav)
        splitter.addWidget(self.stack)
        splitter.setSizes([SIDEBAR_WIDTH, DEFAULT_WINDOW_WIDTH - SIDEBAR_WIDTH])
        self.setCentralWidget(splitter)
        self.task_progress = QProgressBar()
        self.task_progress.setMaximumWidth(140)
        self.task_progress.setRange(0, 0)
        self.task_progress.hide()
        self.statusBar().showMessage("Ready")
        self.statusBar().addPermanentWidget(self.task_progress)
        self.task_manager.task_started.connect(self._task_started)
        self.task_manager.task_finished.connect(self._task_finished)
        self.task_manager.task_rejected.connect(self._task_rejected)
        self.nav.currentItemChanged.connect(self._show_page_from_item)
        self._show_page("home")
        self._select_nav_item("home")

    def _build_page_factories(self) -> dict[str, object]:
        return {
            "home": lambda: self._create_home_page(),
            "schedule": lambda: SchedulePage(self.config),
            "audit": lambda: AuditPage(self.config),
            "photos": lambda: PhotosPage(self.config),
            "workbook_health": lambda: WorkbookHealthPage(self.config),
            "audit_progress": lambda: AuditProgressPage(self.config),
            "issue_analysis": lambda: IssueAnalysisPage(self.config),
            "fmea": lambda: FmeaPage(self.config),
            "pilot_candidates": lambda: PilotCandidatesPage(self.config),
            "kpi_dashboard": lambda: KpiDashboardPage(self.config),
            "standards_docs": lambda: StandardsDocsPage(self.config),
            "pm_checklists": lambda: PmChecklistsPage(self.config),
            "bom_spares": lambda: BomSparesPage(self.config),
            "reports": lambda: ReportsPage(self.config),
            "tool_registry": lambda: ToolRegistryPage(),
            "handoff": lambda: HandoffPage(self.config),
            "settings": lambda: self._create_settings_page(),
        }

    def _create_home_page(self):
        home = HomePage(self.config)
        home.project_root_changed.connect(self._project_root_changed)
        home.navigate_requested.connect(self._navigate_to_page)
        return home

    def _create_settings_page(self):
        settings = SettingsPage(self.config)
        settings.settings_saved.connect(self._settings_saved)
        settings.theme_changed.connect(self.apply_theme)
        return settings

    def _project_root_changed(self, _project_root: str) -> None:
        save_config(self.config)

    def _settings_saved(self) -> None:
        home = self.pages.get("home")
        if home is not None:
            home.refresh_status()

    def apply_theme(self, theme: str) -> None:
        self.config.theme = theme
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(app_stylesheet(theme))
        colors = theme_tokens(theme)
        for top_index in range(self.nav.topLevelItemCount()):
            header = self.nav.topLevelItem(top_index)
            header.setForeground(0, QBrush(QColor(colors["sidebar_group_text"])))

    def _task_started(self, request) -> None:
        self.task_progress.show()
        self.statusBar().showMessage(f"Running: {request.name}...")

    def _task_finished(self, result) -> None:
        self.task_progress.hide()
        status = "Completed" if result.ok else "Failed"
        self.statusBar().showMessage(f"{status}: {result.name} - {result.message}", 9000)

    def _task_rejected(self, result) -> None:
        self.task_progress.hide()
        self.statusBar().showMessage(result.message, 9000)

    def _show_page_from_item(self, current, _previous=None) -> None:
        if current is None:
            return
        page_key = current.data(0, Qt.ItemDataRole.UserRole)
        if page_key:
            self._show_page(str(page_key))

    def _show_page(self, page_key: str) -> None:
        index = self.page_indexes[page_key]
        if page_key not in self.pages:
            page = self.page_factories[page_key]()
            old = self.stack.widget(index)
            self.stack.removeWidget(old)
            old.deleteLater()
            self.stack.insertWidget(index, page)
            self.pages[page_key] = page
        self.stack.setCurrentIndex(index)

    def _navigate_to_page(self, page_key: str) -> None:
        self._select_nav_item(page_key)
        self._show_page(page_key)

    def _select_nav_item(self, page_key: str) -> None:
        for top_index in range(self.nav.topLevelItemCount()):
            header = self.nav.topLevelItem(top_index)
            for child_index in range(header.childCount()):
                child = header.child(child_index)
                if child.data(0, Qt.ItemDataRole.UserRole) == page_key:
                    self.nav.setCurrentItem(child)
                    return
