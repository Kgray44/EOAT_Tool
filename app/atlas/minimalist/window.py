from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QStackedWidget

from core.atlas_data_loader import load_atlas_data
from core.atlas_models import AtlasDataBundle
from core.atlas_recommendations import recommend_for_query
from core.atlas_utils import normalized_eoat_key, normalized_machine_key, normalized_tool_key
from core.config import UserConfig
from core.performance import perf_timer

from ..settings import AtlasSettings, save_atlas_settings
from .data import infer_search_kind, page_label, record_recent_search, with_front
from .home import AtlasMinimalistHomePage
from .library import AtlasMinimalistLibraryPage


class MinimalistAtlasLoadWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, project_root: str, *, force_refresh: bool = False, exclude_unaudited_tools: bool = True):
        super().__init__()
        self.project_root = project_root
        self.force_refresh = force_refresh
        self.exclude_unaudited_tools = exclude_unaudited_tools

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit("Loading Atlas data...")
            bundle = load_atlas_data(
                self.project_root,
                force_refresh=self.force_refresh,
                exclude_unaudited_tools=self.exclude_unaudited_tools,
            )
            self.finished.emit(bundle)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MinimalistAtlasWindow(QMainWindow):
    data_ready = Signal(object)
    data_failed = Signal(str)
    loading_progress = Signal(str)

    def __init__(self, config: UserConfig, *, auto_refresh: bool = True, settings: AtlasSettings | None = None):
        super().__init__()
        self.config = config
        self.settings = (settings or AtlasSettings()).normalized()
        self.bundle: AtlasDataBundle | None = None
        self.current_page_key = "minimalist_home"
        self.pages = {}
        self._load_thread: QThread | None = None
        self._load_worker: MinimalistAtlasLoadWorker | None = None
        self.setWindowTitle("EOAT Atlas - Minimalist")
        self.resize(1536, 1024)
        self.setMinimumSize(1100, 700)

        self.stack = QStackedWidget()
        self.home_page = AtlasMinimalistHomePage(self)
        self.library_page = AtlasMinimalistLibraryPage(self)
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.library_page)
        self.pages = {"minimalist_home": self.home_page, "home": self.home_page, "library": self.library_page}
        self.setCentralWidget(self.stack)
        self.command_palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self.command_palette_shortcut.activated.connect(self._context_search_shortcut)

        if auto_refresh:
            self.refresh_data(force=False)

    def refresh_data(self, *, force: bool) -> None:
        if self._load_thread is not None and self._load_thread.isRunning():
            self.show_status("Atlas data refresh is already running.")
            return
        self.home_page.set_bundle(None)
        self.library_page.set_bundle(None)
        self.loading_progress.emit("Loading Atlas data...")
        self._load_thread = QThread(self)
        self._load_worker = MinimalistAtlasLoadWorker(
            self.config.project_root,
            force_refresh=force,
            exclude_unaudited_tools=self.settings.exclude_unaudited_tools,
        )
        self._load_worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.progress.connect(self.loading_progress.emit)
        self._load_worker.finished.connect(self._data_loaded)
        self._load_worker.failed.connect(self._data_failed)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.failed.connect(self._load_thread.quit)
        self._load_thread.finished.connect(self._load_worker.deleteLater)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.finished.connect(self._clear_worker_refs)
        self._load_thread.start()

    @Slot(object)
    def _data_loaded(self, bundle: AtlasDataBundle) -> None:
        self.bundle = bundle
        self.home_page.set_bundle(bundle)
        self.library_page.set_bundle(bundle)
        self.show_status(f"Loaded {len(bundle.eoats)} EOATs, {len(bundle.machines)} machines, {len(bundle.tools)} tools.")
        self.data_ready.emit(bundle)

    @Slot(str)
    def _data_failed(self, message: str) -> None:
        self.show_status(f"Atlas data load failed: {message}")
        self.data_failed.emit(message)

    @Slot()
    def _clear_worker_refs(self) -> None:
        self._load_thread = None
        self._load_worker = None

    def show_page(self, key: str) -> None:
        with perf_timer(
            self.config.project_root,
            f"navigation.show_page.{key}",
            details={"target_page": key, "current_page": self.current_page_key, "bundle_loaded": self.bundle is not None},
            source="minimalist_window",
            page_tool="navigation",
        ):
            normalized = "minimalist_home" if key in {"home", "minimalist_home"} else str(key or "minimalist_home")
            self.current_page_key = normalized
            if normalized == "minimalist_home":
                self.stack.setCurrentWidget(self.home_page)
                self.home_page.page_shown()
                self.home_page.shell.set_active_nav(normalized)
                return
            if normalized == "library":
                self.stack.setCurrentWidget(self.library_page)
                self.library_page.page_shown()
                self.library_page.shell.set_active_nav(normalized)
                return
            self.show_status(f"{page_label(normalized)} is not implemented in the minimalist UI yet.")

    def open_recommendation(self, query: str, *, kind: str = "", record_search: bool = True) -> None:
        query = str(query or "").strip()
        if not query:
            self.show_status("Enter a tool, mold, part, machine, EOAT, or description to search.")
            return
        if record_search:
            self.record_minimalist_search(query, kind=kind, update=False)
        if self.bundle is None:
            if record_search:
                self._refresh_recent_searches()
            self.show_status("Atlas data is still loading.")
            return
        result = recommend_for_query(self.bundle, query)
        if result.matches:
            first = result.matches[0]
            if record_search:
                self.record_minimalist_search(query, kind=self._result_type_label(first.result_type), update=False)
            self._record_match_recent(first.result_type, first.key)
        if record_search:
            self._refresh_recent_searches()
        message = result.summary
        if result.best is not None:
            machines = ", ".join(result.best.machines[:4]) or "no machines indexed"
            message = f"{result.summary} Score {result.best.score}. Machines: {machines}."
        self.show_status(message)

    def open_eoat(self, eoat_id: str) -> None:
        with perf_timer(
            self.config.project_root,
            "record.open_request.eoat",
            details={"record_type": "eoat", "record_id": eoat_id},
            source="minimalist_window",
            page_tool="navigation",
        ):
            value = str(eoat_id or "").strip()
            if not value:
                return
            self.record_recent("eoat", value)
            record = self._find_eoat(value)
            if record is None:
                self.open_recommendation(value)
                return
            self.show_page("library")
            self.library_page.select_entity("eoat", record.eoat_id)
            tools = ", ".join(record.tools[:3]) or "no linked tools"
            machines = ", ".join(record.machines[:4]) or "no linked machines"
            self.show_status(f"{record.eoat_id}: {record.eoat_type or 'EOAT'} | Tools: {tools} | Machines: {machines}.")

    def open_machine(self, machine: str) -> None:
        with perf_timer(
            self.config.project_root,
            "record.open_request.machine",
            details={"record_type": "machine", "record_id": machine},
            source="minimalist_window",
            page_tool="navigation",
        ):
            value = str(machine or "").strip()
            if not value:
                return
            self.record_recent("machine", value)
            record = self._find_machine(value)
            if record is None:
                self.open_recommendation(value)
                return
            self.show_page("library")
            self.library_page.select_entity("machine", record.machine)
            eoats = ", ".join(record.compatible_eoats[:4]) or "no compatible EOATs indexed"
            self.show_status(f"Machine {record.machine}: {record.robot_type or record.robot_model or 'robot info missing'} | EOATs: {eoats}.")

    def open_tool(self, tool: str) -> None:
        with perf_timer(
            self.config.project_root,
            "record.open_request.tool",
            details={"record_type": "tool", "record_id": tool},
            source="minimalist_window",
            page_tool="navigation",
        ):
            value = str(tool or "").strip()
            if not value:
                return
            self.record_recent("tool", value)
            record = self._find_tool(value)
            if record is None:
                self.open_recommendation(value)
                return
            self.show_page("library")
            self.library_page.select_entity("tool", record.tool)
            eoats = ", ".join(record.compatible_eoats[:4]) or "no validated EOATs indexed"
            machines = ", ".join(record.compatible_machines[:4]) or "no machines indexed"
            self.show_status(f"Tool {record.tool}: EOATs: {eoats} | Machines: {machines}.")

    def open_setup_packet(self, **_kwargs) -> None:
        self.show_page("setup_packet")

    def open_photos(self, _eoat_id: str = "") -> None:
        self.show_page("photos")

    def generate_install_packet_current_context(self) -> None:
        self.show_page("setup_packet")

    def make_qr_for_current_eoat(self) -> None:
        self.show_status("QR label generation is not implemented in the minimalist UI yet.")

    def open_compare(self, item_type: str) -> None:
        self.show_status(f"{item_type.title()} compare is not implemented in the minimalist UI yet.")

    def toggle_dark_mode(self) -> None:
        self.show_status("The minimalist UI is a fixed dark design option for now.")

    def show_status(self, message: str) -> None:
        active = self.stack.currentWidget() if hasattr(self, "stack") else self.home_page
        toast = getattr(active, "show_toast", None)
        if callable(toast):
            toast(message)
            return
        self.home_page.show_toast(message)

    def record_minimalist_search(self, query: str, *, kind: str = "", update: bool = True) -> None:
        text = str(query or "").strip()
        if not text:
            return
        resolved_kind = kind.strip() or infer_search_kind(text, self.bundle)
        record_recent_search(text, kind=resolved_kind, bundle=self.bundle)
        if update:
            self._refresh_recent_searches()

    def record_recent(self, item_type: str, key: str) -> None:
        text = str(key or "").strip()
        if not text:
            return
        attr = {
            "eoat": "recent_eoats",
            "machine": "recent_machines",
            "tool": "recent_tools",
        }.get(item_type)
        if not attr:
            return
        values = with_front(getattr(self.settings, attr), text, limit=12)
        if values == getattr(self.settings, attr):
            return
        self.settings = replace(self.settings, **{attr: values}).normalized()
        save_atlas_settings(self.settings)
        self.home_page.set_bundle(self.bundle)

    def is_pinned(self, _item_type: str, _key: str) -> bool:
        return False

    def _record_match_recent(self, result_type: str, key: str) -> None:
        if result_type == "eoat":
            self.record_recent("eoat", key)
        elif result_type == "machine":
            self.record_recent("machine", key)
        elif result_type == "tool":
            self.record_recent("tool", key)

    def _refresh_recent_searches(self) -> None:
        self.home_page.home_content.card.refresh_recent_searches()
        self.home_page.shell.search_overlay.refresh_results()
        self.library_page.shell.search_overlay.refresh_results()

    def _context_search_shortcut(self) -> None:
        if self.current_page_key == "library":
            self.library_page.focus_library_search()
            return
        self.stack.currentWidget().open_search_overlay()

    def _result_type_label(self, result_type: str) -> str:
        return {
            "eoat": "EOAT",
            "machine": "Machine",
            "tool": "Tool / Mold",
            "part": "Part",
        }.get(str(result_type or "").casefold(), "Search")

    def _find_eoat(self, value: str):
        if self.bundle is None:
            return None
        key = normalized_eoat_key(value)
        return next((record for record in self.bundle.eoats if normalized_eoat_key(record.eoat_id) == key), None)

    def _find_machine(self, value: str):
        if self.bundle is None:
            return None
        key = normalized_machine_key(value)
        return next((record for record in self.bundle.machines if normalized_machine_key(record.machine) == key), None)

    def _find_tool(self, value: str):
        if self.bundle is None:
            return None
        key = normalized_tool_key(value)
        return next((record for record in self.bundle.tools if normalized_tool_key(record.tool) == key), None)

    def closeEvent(self, event) -> None:
        self.home_page.shell.remove_app_event_filter()
        self.library_page.shell.remove_app_event_filter()
        if self._load_thread is not None and self._load_thread.isRunning():
            self._load_thread.quit()
            self._load_thread.wait(3000)
        super().closeEvent(event)


__all__ = ["MinimalistAtlasWindow"]
