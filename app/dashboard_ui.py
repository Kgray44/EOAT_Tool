from __future__ import annotations

import inspect
import time

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QShortcut
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QMessageBox, QProgressBar, QStackedWidget, QSplitter, QTreeWidget, QTreeWidgetItem, QWidget
except ImportError:  # pragma: no cover
    Qt = QBrush = QColor = QFont = QKeySequence = QShortcut = QApplication = QLabel = QMainWindow = QMessageBox = QProgressBar = QStackedWidget = QSplitter = QTreeWidget = QTreeWidgetItem = QWidget = None

from core.openers import open_path
from core.config import load_config, save_config
from core.constants import APP_NAME
from core.performance import log_performance
from core.workbook_cache import invalidate_all_workbook_cache
from core.search import SearchResult
from .command_registry import build_dashboard_command_registry
from .event_bus import EVENT_ANY, EVENT_AUDIT_SAVED, EVENT_PROJECT_ROOT_CHANGED, EVENT_SETTINGS_CHANGED, AppEvent, get_event_bus
from .page_async import log_page_performance
from .page_registry import PAGE_SPECS, PageSpec, create_page
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
        self.event_bus = get_event_bus()
        self._unsubscribe_event_bus = self.event_bus.subscribe(EVENT_ANY, self._on_app_event)
        self._current_page_key: str | None = None
        self._suppress_nav_change = False
        self._last_project_root = self.config.project_root

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
        self.page_specs = {spec.key: spec for spec in PAGE_SPECS}
        self.page_factories = self._build_page_factories()
        self.command_registry = build_dashboard_command_registry(self)
        self.command_palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self.command_palette_shortcut.activated.connect(self.open_command_palette)
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
        return {spec.key: (lambda spec=spec: self._create_page_from_spec(spec)) for spec in PAGE_SPECS}

    def _create_page_from_spec(self, spec: PageSpec):
        page = create_page(spec, self.config)
        self._connect_page_signals(spec, page)
        return page

    def _connect_page_signals(self, spec: PageSpec, page) -> None:
        if spec.key == "home":
            if hasattr(page, "project_root_changed"):
                page.project_root_changed.connect(self._project_root_changed)
            if hasattr(page, "navigate_requested"):
                page.navigate_requested.connect(self._navigate_to_page)
        elif spec.key == "settings":
            if hasattr(page, "settings_saved"):
                page.settings_saved.connect(self._settings_saved)
            if hasattr(page, "theme_changed"):
                page.theme_changed.connect(self.apply_theme)

    def _project_root_changed(self, _project_root: str) -> None:
        save_config(self.config)
        self._publish_project_root_changed(_project_root, source="home")

    def _settings_saved(self) -> None:
        self.event_bus.emit(
            EVENT_SETTINGS_CHANGED,
            {"project_root": self.config.project_root, "theme": self.config.theme},
            source="settings",
        )
        if self.config.project_root != self._last_project_root:
            self._publish_project_root_changed(self.config.project_root, source="settings")

    def _publish_project_root_changed(self, project_root: str, *, source: str) -> None:
        old_project_root = self._last_project_root
        self._last_project_root = project_root
        invalidate_all_workbook_cache()
        for page in list(self.pages.values()):
            self._call_optional_page_hook(page, "on_project_root_changed", self.config)
        self.event_bus.emit(
            EVENT_PROJECT_ROOT_CHANGED,
            {"project_root": project_root, "old_project_root": old_project_root},
            source=source,
        )

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
        log_performance(
            self.config.project_root,
            f"task.{result.id}",
            result.duration_seconds,
            success=result.ok,
            source="task_runner",
            page_tool=result.name,
            details={"task_category": "dashboard", "message": result.message[:240]},
            warning_count=len(result.warnings),
            error_count=1 if result.error else 0,
        )

    def _task_rejected(self, result) -> None:
        self.task_progress.hide()
        self.statusBar().showMessage(result.message, 9000)

    def _show_page_from_item(self, current, _previous=None) -> None:
        if self._suppress_nav_change:
            return
        if current is None:
            return
        page_key = current.data(0, Qt.ItemDataRole.UserRole)
        if page_key:
            if not self._show_page(str(page_key)) and self._current_page_key:
                self._select_nav_item(self._current_page_key)

    def _show_page(self, page_key: str) -> bool:
        index = self.page_indexes[page_key]
        if self._current_page_key and self._current_page_key != page_key:
            current_page = self.pages.get(self._current_page_key)
            allowed, reason = self._page_can_close(current_page, destination_page=page_key)
            if not allowed:
                message = reason or "The current page is not ready to close."
                self.statusBar().showMessage(message, 9000)
                if QMessageBox is not None:
                    QMessageBox.warning(self, APP_NAME, message)
                return False

        created = False
        if page_key not in self.pages:
            shell_started = time.perf_counter()
            page = self.page_factories[page_key]()
            log_page_performance(
                self.config.project_root,
                page_key,
                "shell_create",
                time.perf_counter() - shell_started,
                details={"created": True},
            )
            old = self.stack.widget(index)
            self.stack.removeWidget(old)
            old.deleteLater()
            self.stack.insertWidget(index, page)
            self.pages[page_key] = page
            created = True
        previous_page = self.pages.get(self._current_page_key or "")
        if previous_page is not None and self._current_page_key != page_key:
            self._call_optional_page_hook(previous_page, "on_hide")
        page = self.pages[page_key]
        self.stack.setCurrentIndex(index)
        self._current_page_key = page_key
        handled_show = self._call_optional_page_hook(page, "on_show")
        if not created and not handled_show:
            self._refresh_page_on_show(self.page_specs[page_key], page)
        return True

    def _navigate_to_page(self, page_key: str) -> None:
        if self._show_page(page_key):
            self._select_nav_item(page_key)

    def navigate_to_page(self, page_key: str) -> None:
        self._navigate_to_page(page_key)

    def page(self, page_key: str):
        return self.pages.get(page_key)

    def show_page_message(self, page_key: str, message: str) -> None:
        page = self.pages.get(page_key)
        result_panel = getattr(page, "result_panel", None)
        if result_panel is not None and hasattr(result_panel, "show_text"):
            result_panel.show_text(message)
            return
        status_label = getattr(page, "status_label", None)
        if status_label is not None and hasattr(status_label, "setText"):
            status_label.setText(message)
            return
        self.statusBar().showMessage(message, 9000)

    def open_command_palette(self) -> None:
        from .widgets.command_palette import CommandPalette

        palette = CommandPalette(self.command_registry, self.config.project_root, self)
        palette.exec()

    def open_search_result(self, result: SearchResult | dict) -> bool:
        data = result.to_dict() if isinstance(result, SearchResult) else dict(result)
        action = str(data.get("action") or "")
        if action == "open_audit":
            self._navigate_to_page("audit")
            page = self.pages.get("audit")
            audit_id = str(data.get("audit_id") or "")
            if audit_id and hasattr(page, "load_existing_audit"):
                page.load_existing_audit(audit_id, loaded_message=f"Opened from global search: {audit_id}")
            field = str(data.get("field") or "")
            if field and hasattr(page, "focus_annotation_target"):
                page.focus_annotation_target({"audit_id": audit_id, "field_key": field, "field_label": field, "target_type": "audit_field"})
            return True
        if action == "open_press":
            self._navigate_to_page("press_view")
            page = self.pages.get("press_view")
            machine = str(data.get("machine") or "")
            if hasattr(page, "select_machine"):
                page.select_machine(machine)
            return True
        if action == "open_note":
            self._navigate_to_page("notes")
            page = self.pages.get("notes")
            note_id = str(data.get("target_id") or "")
            if note_id and hasattr(page, "select_note"):
                page.select_note(note_id)
            return True
        if action == "open_tag":
            self._navigate_to_page("tags")
            page = self.pages.get("tags")
            target_id = str(data.get("target_id") or "")
            if hasattr(page, "select_tag_or_assignment"):
                if str(data.get("result_id") or "").startswith("tag_assignment:"):
                    page.select_tag_or_assignment(assignment_id=target_id)
                else:
                    page.select_tag_or_assignment(tag_id=target_id)
            return True
        if action == "open_open_item":
            self._navigate_to_page("open_items")
            self.show_page_message("open_items", f"Opened Open Items from search: {data.get('title') or data.get('target_id') or ''}")
            return True
        if action == "open_validation":
            self._navigate_to_page("workbook_health")
            self.show_page_message("workbook_health", f"Opened Workbook Health from search: {data.get('title') or ''}")
            return True
        if action == "open_report":
            path = str(data.get("path") or "")
            if path:
                result_open = open_path(path)
                self.statusBar().showMessage(result_open.summary, 9000)
                return result_open.success
        if action == "open_photo":
            path = str(data.get("path") or "")
            if path:
                result_open = open_path(path)
                if result_open.success:
                    self.statusBar().showMessage(result_open.summary, 9000)
                    return True
            self._navigate_to_page("photos")
            self.show_page_message("photos", f"Opened Photos from search: {data.get('title') or ''}")
            return True
        return False

    def _refresh_page_on_show(self, spec: PageSpec, page) -> None:
        if spec.refresh_on_show:
            self._refresh_page(page)

    def _refresh_page(self, page) -> bool:
        for method_name in ("refresh_status", "refresh_metrics", "refresh", "refresh_data"):
            method = getattr(page, method_name, None)
            if callable(method):
                method()
                return True
        return False

    def _on_app_event(self, event: AppEvent) -> None:
        for page_key, page in list(self.pages.items()):
            spec = self.page_specs.get(page_key)
            if spec is None or event.event_type not in spec.listens_to:
                continue
            if event.source in {page_key, f"{page_key}_page"}:
                continue
            event_handler = getattr(page, "on_event", None)
            if callable(event_handler):
                try:
                    handled = event_handler(event)
                except Exception as exc:
                    self.statusBar().showMessage(f"{spec.label} event refresh failed: {exc}", 9000)
                    log_page_performance(
                        self.config.project_root,
                        page_key,
                        "event_refresh",
                        0.0,
                        success=False,
                        details={"event_type": event.event_type, "error": str(exc)},
                    )
                    continue
                if handled is not False:
                    continue
            if event.event_type == EVENT_AUDIT_SAVED and event.payload.get("refresh_mode") == "invalidate_only":
                continue
            self._refresh_page(page)

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
                    self._suppress_nav_change = True
                    try:
                        self.nav.setCurrentItem(child)
                    finally:
                        self._suppress_nav_change = False
                    return

    @staticmethod
    def _call_optional_page_hook(page, hook_name: str, *args):
        method = getattr(page, hook_name, None)
        if callable(method):
            return method(*args)
        return None

    @classmethod
    def _page_can_close(cls, page, destination_page: str | None = None) -> tuple[bool, str]:
        if page is None:
            return True, ""
        method = getattr(page, "can_close", None)
        if not callable(method):
            result = None
        else:
            try:
                parameters = inspect.signature(method).parameters
                result = method(destination_page) if parameters else method()
            except (TypeError, ValueError):
                result = method()
        if result is None:
            return True, ""
        if isinstance(result, tuple):
            allowed = bool(result[0]) if result else True
            reason = str(result[1]) if len(result) > 1 and result[1] is not None else ""
            return allowed, reason
        return bool(result), ""

    def closeEvent(self, event) -> None:
        for page in list(self.pages.values()):
            allowed, reason = self._page_can_close(page)
            if not allowed:
                message = reason or "A page is not ready to close."
                self.statusBar().showMessage(message, 9000)
                if QMessageBox is not None:
                    QMessageBox.warning(self, APP_NAME, message)
                event.ignore()
                return
        if self._unsubscribe_event_bus is not None:
            self._unsubscribe_event_bus()
            self._unsubscribe_event_bus = None
        super().closeEvent(event)
