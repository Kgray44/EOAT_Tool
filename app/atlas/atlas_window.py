from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.atlas_data_loader import load_atlas_data
from core.atlas_models import AtlasDataBundle
from core.config import UserConfig

from .assets import ATLAS_LOGO_PATH
from .command_palette import AtlasCommandPalette
from .pages import (
    DiagnosticsPage,
    EOATBrowserPage,
    HomePage,
    InformationLibraryPage,
    MachineBrowserPage,
    MatrixPage,
    OverviewPage,
    PhotosPage,
    PMInspectionPage,
    ReportsPage,
    SetupPacketPage,
    StandardsPage,
    ToolSearchPage,
    WhatNeedPage,
)
from .photo_loader import PhotoLoadManager
from .settings import AtlasSettings, load_atlas_settings, save_atlas_settings
from .styles import atlas_stylesheet


class AtlasLoadWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, project_root: str, *, force_refresh: bool = False):
        super().__init__()
        self.project_root = project_root
        self.force_refresh = force_refresh

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit("Loading workbooks and indexes...")
            bundle = load_atlas_data(self.project_root, force_refresh=self.force_refresh)
            self.finished.emit(bundle)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class AtlasWindow(QMainWindow):
    data_ready = Signal(object)
    data_failed = Signal(str)
    loading_progress = Signal(str)

    def __init__(self, config: UserConfig, *, auto_refresh: bool = True, settings: AtlasSettings | None = None):
        super().__init__()
        self.config = config
        self.settings = (settings or load_atlas_settings()).normalized()
        self.bundle: AtlasDataBundle | None = None
        self.current_page_key = ""
        self.photo_loader = PhotoLoadManager(self, max_memory_mb=self.settings.photo_cache_limit_mb)
        self.photo_loader.set_ui_ready_for_preload(False, reason="Paused: app loading")
        self.photo_loader.set_preload_mode(self.settings.photo_preload_mode)
        self._photo_preload_ready_scheduled = False
        self._load_thread: QThread | None = None
        self._load_worker: AtlasLoadWorker | None = None
        self.setWindowTitle("EOAT Atlas")
        if ATLAS_LOGO_PATH.exists():
            self.setWindowIcon(QIcon(str(ATLAS_LOGO_PATH)))
        self.resize(1380, 860)
        self.setMinimumSize(1100, 700)
        self.sidebar = QWidget()
        self.sidebar.setObjectName("AtlasSidebarPanel")
        self.sidebar.setFixedWidth(230)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_layout.setSpacing(12)
        header = QFrame()
        header.setObjectName("AtlasSidebarHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(10, 10, 10, 10)
        header_layout.setSpacing(5)
        logo = QLabel()
        logo.setObjectName("AtlasSidebarLogo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(ATLAS_LOGO_PATH))
        if not pixmap.isNull():
            logo.setPixmap(
                pixmap.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            logo.setText("EOAT")
        name = QLabel("EOAT Atlas")
        name.setObjectName("AtlasSidebarTitle")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(logo)
        header_layout.addWidget(name)
        sidebar_layout.addWidget(header)
        self.command_palette_button = QPushButton("Command Palette  Ctrl+K")
        self.command_palette_button.setObjectName("AtlasNavItem")
        self.command_palette_button.clicked.connect(self.open_command_palette)
        sidebar_layout.addWidget(self.command_palette_button)

        nav_scroll = QScrollArea()
        nav_scroll.setObjectName("AtlasSidebarScroll")
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_content = QWidget()
        nav_layout = QVBoxLayout(nav_content)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)
        self.nav_items: dict[str, QPushButton] = {}
        for section, items in NAV_SECTIONS:
            section_label = QLabel(section)
            section_label.setObjectName("AtlasNavSectionLabel")
            nav_layout.addWidget(section_label)
            for key, label in items:
                button = QPushButton(label)
                button.setObjectName("AtlasNavItem")
                button.setCheckable(True)
                button.clicked.connect(lambda _checked=False, key=key: self.show_page(key))
                self.nav_items[key] = button
                nav_layout.addWidget(button)
        nav_layout.addStretch(1)
        nav_scroll.setWidget(nav_content)
        sidebar_layout.addWidget(nav_scroll, 1)
        self.stack = QStackedWidget()
        self.pages = self._create_pages()
        for key, label in PAGE_LABELS:
            self.stack.addWidget(self.pages[key])
        splitter = QSplitter()
        splitter.setObjectName("AtlasMainSplitter")
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.stack)
        splitter.setSizes([230, 1150])
        self.setCentralWidget(splitter)
        self.status_label = QLabel("Starting EOAT Atlas...")
        self.statusBar().addPermanentWidget(self.status_label)
        self.command_palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self.command_palette_shortcut.activated.connect(self.open_command_palette)
        self.apply_settings(save=False, notify_pages=False)
        self.show_page(self.settings.startup_page)
        if auto_refresh:
            self.refresh_data(force=False)

    def _create_pages(self) -> dict[str, QWidget]:
        return {
            "home": HomePage(self),
            "what": WhatNeedPage(self),
            "setup_packet": SetupPacketPage(self),
            "eoats": EOATBrowserPage(self),
            "machines": MachineBrowserPage(self),
            "tools": ToolSearchPage(self),
            "matrix": MatrixPage(self),
            "overview": OverviewPage(self),
            "photos": PhotosPage(self),
            "standards": StandardsPage(self),
            "pm": PMInspectionPage(self),
            "library": InformationLibraryPage(self),
            "reports": ReportsPage(self),
            "diagnostics": DiagnosticsPage(self),
        }

    def show_page(self, key: str) -> None:
        keys = [item_key for item_key, _label in PAGE_LABELS]
        if key in keys:
            self.photo_loader.mark_user_activity()
            self.current_page_key = key
            self.stack.setCurrentIndex(keys.index(key))
            for item_key, button in self.nav_items.items():
                button.setChecked(item_key == key)
            page = self.pages.get(key)
            if hasattr(page, "page_shown"):
                page.page_shown()

    def open_recommendation(self, query: str) -> None:
        self.show_page("what")
        page = self.pages["what"]
        if hasattr(page, "run_query"):
            page.run_query(query)

    def open_eoat(self, eoat_id: str) -> None:
        self.record_recent("eoat", eoat_id)
        self.show_page("eoats")
        page = self.pages["eoats"]
        if hasattr(page, "open_record"):
            page.open_record(eoat_id)

    def open_machine(self, machine: str) -> None:
        self.record_recent("machine", machine)
        self.show_page("machines")
        page = self.pages["machines"]
        if hasattr(page, "open_record"):
            page.open_record(machine)

    def open_tool(self, tool: str) -> None:
        self.record_recent("tool", tool)
        self.show_page("tools")
        page = self.pages["tools"]
        if hasattr(page, "open_record"):
            page.open_record(tool)
            return
        search = getattr(page, "search", None)
        if search is not None:
            search.setText(tool)

    def open_setup_packet(
        self,
        *,
        machine: str = "",
        tool: str = "",
        eoat: str = "",
        recommendation=None,
        context_label: str = "Atlas",
    ) -> None:
        self.show_page("setup_packet")
        page = self.pages.get("setup_packet")
        if hasattr(page, "prefill_context"):
            page.prefill_context(
                machine_id=machine,
                tool_id=tool,
                eoat_id=eoat,
                recommendation=recommendation,
                context_label=context_label,
            )

    def open_photos(self, eoat_id: str) -> None:
        self.show_page("photos")
        page = self.pages["photos"]
        if hasattr(page, "open_record"):
            page.open_record(eoat_id)
            return
        search = getattr(page, "filter", None)
        if search is not None:
            search.setText(eoat_id)

    def show_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 9000)

    def update_settings(self, settings: AtlasSettings) -> None:
        self.settings = settings.normalized()
        self.apply_settings(save=True)

    def update_setup_packet_settings(self, settings: AtlasSettings) -> None:
        self.settings = settings.normalized()
        save_atlas_settings(self.settings)
        self.show_status("Changeover Packet settings saved.")

    def apply_settings(self, *, save: bool = False, notify_pages: bool = True) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(atlas_stylesheet(self.settings.effective_theme, self.settings.color_scheme))
        self.photo_loader.set_preload_mode(self.settings.photo_preload_mode)
        self.photo_loader.set_cache_limit_mb(self.settings.photo_cache_limit_mb)
        self.command_palette_shortcut.setEnabled(bool(self.settings.command_palette_enabled))
        self.command_palette_button.setVisible(bool(self.settings.command_palette_enabled))
        if save:
            save_atlas_settings(self.settings)
            self.show_status("Atlas settings saved.")
        if notify_pages:
            for page in self.pages.values():
                if hasattr(page, "settings_changed"):
                    page.settings_changed()

    def open_command_palette(self) -> None:
        if not self.settings.command_palette_enabled:
            self.show_status("Command palette is disabled in Settings.")
            return
        palette = AtlasCommandPalette(self, self)
        palette.open_with_query()
        palette.exec()

    def toggle_dark_mode(self) -> None:
        next_theme = "light" if self.settings.effective_theme == "dark" else "dark"
        self.update_settings(replace(self.settings, theme=next_theme))

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
        values = _with_front(getattr(self.settings, attr), text, limit=12)
        if values == getattr(self.settings, attr):
            return
        self.settings = replace(self.settings, **{attr: values}).normalized()
        save_atlas_settings(self.settings)

    def toggle_pin(self, item_type: str, key: str) -> bool:
        attr = {
            "eoat": "pinned_eoats",
            "machine": "pinned_machines",
            "tool": "pinned_tools",
        }.get(item_type)
        text = str(key or "").strip()
        if not attr or not text:
            return False
        current = tuple(getattr(self.settings, attr))
        folded = text.casefold()
        if any(item.casefold() == folded for item in current):
            values = tuple(item for item in current if item.casefold() != folded)
            pinned = False
        else:
            values = (text, *current)
            pinned = True
        self.update_settings(replace(self.settings, **{attr: values}))
        return pinned

    def is_pinned(self, item_type: str, key: str) -> bool:
        attr = {
            "eoat": "pinned_eoats",
            "machine": "pinned_machines",
            "tool": "pinned_tools",
        }.get(item_type)
        folded = str(key or "").strip().casefold()
        return bool(attr and folded and any(item.casefold() == folded for item in getattr(self.settings, attr)))

    def generate_install_packet_current_context(self) -> None:
        page = self.pages.get(self.current_page_key)
        handler = getattr(page, "generate_install_packet", None)
        if callable(handler):
            handler()
            return
        self.open_setup_packet(context_label="Command Palette")

    def make_qr_for_current_eoat(self) -> None:
        page = self.pages.get("eoats")
        handler = getattr(page, "make_qr_label", None)
        if self.current_page_key == "eoats" and callable(handler):
            handler()
            return
        self.show_status("Open an EOAT profile before generating a QR label.")

    def open_compare(self, item_type: str) -> None:
        page_key = {"eoat": "eoats", "machine": "machines", "tool": "tools"}.get(item_type)
        if not page_key:
            return
        page = self.pages.get(page_key)
        handler = getattr(page, "open_compare_selected", None)
        if callable(handler):
            if self.current_page_key != page_key:
                self.show_page(page_key)
            handler(allow_fallback=True)

    def refresh_data(self, *, force: bool) -> None:
        if self._load_thread is not None and self._load_thread.isRunning():
            self.show_status("Atlas data refresh is already running.")
            return
        self._photo_preload_ready_scheduled = False
        self.photo_loader.set_ui_ready_for_preload(
            False,
            reason="Paused: data refresh" if self.isVisible() else "Paused: app loading",
        )
        self.status_label.setText("Loading data...")
        self.loading_progress.emit("Loading data...")
        self.statusBar().showMessage("Refreshing Atlas data in the background...")
        self._load_thread = QThread(self)
        self._load_worker = AtlasLoadWorker(self.config.project_root, force_refresh=force)
        self._load_worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.progress.connect(self._on_load_progress)
        self._load_worker.finished.connect(self._data_loaded)
        self._load_worker.failed.connect(self._data_failed)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.failed.connect(self._load_thread.quit)
        self._load_thread.finished.connect(self._load_worker.deleteLater)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.finished.connect(self._clear_worker_refs)
        self._load_thread.start()

    @Slot(str)
    def _on_load_progress(self, message: str) -> None:
        self.status_label.setText(message)
        self.loading_progress.emit(message)

    @Slot(object)
    def _data_loaded(self, bundle: AtlasDataBundle) -> None:
        self.bundle = bundle
        self.photo_loader.set_photo_catalog(bundle)
        for page in self.pages.values():
            if hasattr(page, "set_bundle"):
                page.set_bundle(bundle)
        self.status_label.setText(f"Ready. Refreshed {bundle.loaded_at}")
        self.statusBar().showMessage(
            f"Loaded {len(bundle.eoats)} EOATs, {len(bundle.machines)} machines, {len(bundle.tools)} tools.",
            9000,
        )
        self.data_ready.emit(bundle)
        self._schedule_photo_preload_after_ui_ready()

    @Slot(str)
    def _data_failed(self, message: str) -> None:
        self.status_label.setText("Data load failed")
        self.statusBar().showMessage(f"Atlas data load failed: {message}", 12000)
        self.data_failed.emit(message)

    @Slot()
    def _clear_worker_refs(self) -> None:
        self._load_thread = None
        self._load_worker = None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_photo_preload_after_ui_ready()

    def _schedule_photo_preload_after_ui_ready(self) -> None:
        if self._photo_preload_ready_scheduled or self.bundle is None or not self.isVisible():
            return
        self._photo_preload_ready_scheduled = True
        QTimer.singleShot(1200, self._enable_photo_preload_if_ready)

    def _enable_photo_preload_if_ready(self) -> None:
        if self.bundle is None or not self.isVisible():
            self._photo_preload_ready_scheduled = False
            return
        self.photo_loader.set_ui_ready_for_preload(True, reason="Ready")

    def closeEvent(self, event) -> None:
        if self._load_thread is not None and self._load_thread.isRunning():
            self._load_thread.quit()
            self._load_thread.wait(3000)
        super().closeEvent(event)


def _with_front(values: tuple[str, ...], text: str, *, limit: int) -> tuple[str, ...]:
    folded = text.casefold()
    items = [text, *[item for item in values if item.casefold() != folded]]
    return tuple(items[:limit])


PAGE_LABELS = [
    ("home", "Home / Command Deck"),
    ("what", "What Do I Need?"),
    ("setup_packet", "Changeover Packet Builder"),
    ("eoats", "EOAT Profiles"),
    ("machines", "Machine Profiles"),
    ("tools", "Tool / Mold / Part"),
    ("matrix", "Compatibility Data Table"),
    ("overview", "Analytics Dashboard"),
    ("photos", "Photos"),
    ("standards", "Standards & Work Instructions"),
    ("pm", "PM / Inspection"),
    ("library", "Information Library"),
    ("reports", "Reports & Handoff"),
    ("diagnostics", "Settings / Diagnostics"),
]

NAV_SECTIONS = [
    (
        "Command",
        [
            ("home", "Home / Command Deck"),
            ("what", "What Do I Need?"),
            ("setup_packet", "Changeover Packet Builder"),
        ],
    ),
    (
        "Lookup",
        [
            ("eoats", "EOAT Profiles"),
            ("machines", "Machine Profiles"),
            ("tools", "Tool / Mold / Part"),
        ],
    ),
    (
        "Insights",
        [
            ("overview", "Analytics Dashboard"),
            ("photos", "Photos"),
            ("standards", "Standards & Work Instructions"),
            ("pm", "PM / Inspection"),
        ],
    ),
    (
        "System",
        [
            ("reports", "Reports & Handoff"),
            ("diagnostics", "Settings / Diagnostics"),
        ],
    ),
    (
        "Advanced",
        [
            ("matrix", "Compatibility Data Table"),
        ],
    ),
]


__all__ = ["AtlasWindow"]
