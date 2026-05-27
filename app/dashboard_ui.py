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


class DashboardWindow(QMainWindow):
    def __init__(self, config=None):
        super().__init__()
        self.config = config or load_config()
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
            "schedule": lambda: self._create_config_page("schedule", self.config),
            "audit": lambda: self._create_config_page("audit", self.config),
            "notes": lambda: self._create_config_page("notes", self.config),
            "tags": lambda: self._create_config_page("tags", self.config),
            "photos": lambda: self._create_config_page("photos", self.config),
            "workbook_health": lambda: self._create_config_page("workbook_health", self.config),
            "audit_progress": lambda: self._create_config_page("audit_progress", self.config),
            "issue_analysis": lambda: self._create_config_page("issue_analysis", self.config),
            "fmea": lambda: self._create_config_page("fmea", self.config),
            "pilot_candidates": lambda: self._create_config_page("pilot_candidates", self.config),
            "kpi_dashboard": lambda: self._create_config_page("kpi_dashboard", self.config),
            "standards_docs": lambda: self._create_config_page("standards_docs", self.config),
            "pm_checklists": lambda: self._create_config_page("pm_checklists", self.config),
            "bom_spares": lambda: self._create_config_page("bom_spares", self.config),
            "reports": lambda: self._create_config_page("reports", self.config),
            "scheduled_reports": lambda: self._create_config_page("scheduled_reports", self.config),
            "tool_registry": lambda: self._create_config_page("tool_registry"),
            "handoff": lambda: self._create_config_page("handoff", self.config),
            "settings": lambda: self._create_settings_page(),
        }

    def _create_home_page(self):
        from .pages.home import HomePage

        home = HomePage(self.config)
        home.project_root_changed.connect(self._project_root_changed)
        home.navigate_requested.connect(self._navigate_to_page)
        return home

    def _create_config_page(self, page_key: str, *args):
        if page_key == "schedule":
            from .pages.schedule import SchedulePage as Page
        elif page_key == "audit":
            from .pages.audit import AuditPage as Page
        elif page_key == "notes":
            from .pages.notes import NotesPage as Page
        elif page_key == "tags":
            from .pages.tags import TagsPage as Page
        elif page_key == "photos":
            from .pages.photos import PhotosPage as Page
        elif page_key == "workbook_health":
            from .pages.workbook_health import WorkbookHealthPage as Page
        elif page_key == "audit_progress":
            from .pages.audit_progress import AuditProgressPage as Page
        elif page_key == "issue_analysis":
            from .pages.issue_analysis import IssueAnalysisPage as Page
        elif page_key == "fmea":
            from .pages.fmea import FmeaPage as Page
        elif page_key == "pilot_candidates":
            from .pages.pilot_candidates import PilotCandidatesPage as Page
        elif page_key == "kpi_dashboard":
            from .pages.kpi_dashboard import KpiDashboardPage as Page
        elif page_key == "standards_docs":
            from .pages.standards_docs import StandardsDocsPage as Page
        elif page_key == "pm_checklists":
            from .pages.pm_checklists import PmChecklistsPage as Page
        elif page_key == "bom_spares":
            from .pages.bom_spares import BomSparesPage as Page
        elif page_key == "reports":
            from .pages.reports import ReportsPage as Page
        elif page_key == "scheduled_reports":
            from .pages.scheduled_reports import ScheduledReportsPage as Page
        elif page_key == "tool_registry":
            from .pages.tool_registry import ToolRegistryPage as Page
        elif page_key == "handoff":
            from .pages.handoff import HandoffPage as Page
        else:
            raise KeyError(page_key)
        return Page(*args)

    def _create_settings_page(self):
        from .pages.settings import SettingsPage

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
        created = False
        if page_key not in self.pages:
            page = self.page_factories[page_key]()
            old = self.stack.widget(index)
            self.stack.removeWidget(old)
            old.deleteLater()
            self.stack.insertWidget(index, page)
            self.pages[page_key] = page
            created = True
        page = self.pages[page_key]
        self.stack.setCurrentIndex(index)
        if page_key == "audit_progress" and not created and hasattr(page, "refresh_metrics"):
            page.refresh_metrics()
        elif page_key in {"notes", "tags"} and not created and hasattr(page, "refresh"):
            page.refresh()

    def _navigate_to_page(self, page_key: str) -> None:
        self._select_nav_item(page_key)
        self._show_page(page_key)

    def open_annotation_target(self, target) -> bool:
        from .widgets.annotation_target_navigator import AnnotationTargetNavigator

        return AnnotationTargetNavigator(self).open_target(target)

    def open_annotation_targets(self, targets, *, title: str = "Select Target for Tag") -> bool:
        from .widgets.annotation_target_navigator import AnnotationTargetNavigator

        return AnnotationTargetNavigator(self).open_targets(list(targets), title=title)

    def open_annotation_tag(self, *, tag_id: str | None = None, assignment_id: str | None = None) -> bool:
        from .widgets.annotation_target_navigator import AnnotationTargetNavigator

        return AnnotationTargetNavigator(self).open_tag(tag_id=tag_id, assignment_id=assignment_id)

    def _select_nav_item(self, page_key: str) -> None:
        for top_index in range(self.nav.topLevelItemCount()):
            header = self.nav.topLevelItem(top_index)
            for child_index in range(header.childCount()):
                child = header.child(child_index)
                if child.data(0, Qt.ItemDataRole.UserRole) == page_key:
                    self.nav.setCurrentItem(child)
                    return
