from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.atlas_data_loader import load_atlas_data
from core.atlas_models import AtlasDataBundle
from core.config import UserConfig

from .assets import ATLAS_LOGO_PATH
from .pages import (
    DiagnosticsPage,
    EOATBrowserPage,
    GapsPage,
    HomePage,
    MachineBrowserPage,
    MatrixPage,
    OverviewPage,
    PhotosPage,
    PMInspectionPage,
    ReportsPage,
    StandardsPage,
    ToolSearchPage,
    WhatNeedPage,
)


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

    def __init__(self, config: UserConfig, *, auto_refresh: bool = True):
        super().__init__()
        self.config = config
        self.bundle: AtlasDataBundle | None = None
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
        sidebar_layout.setContentsMargins(10, 12, 10, 10)
        sidebar_layout.setSpacing(8)
        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(ATLAS_LOGO_PATH))
        if not pixmap.isNull():
            logo.setPixmap(
                pixmap.scaled(86, 86, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            logo.setText("EOAT")
        name = QLabel("EOAT Atlas")
        name.setObjectName("AtlasSidebarTitle")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(logo)
        sidebar_layout.addWidget(name)
        self.nav = QListWidget()
        self.nav.setObjectName("AtlasSidebar")
        sidebar_layout.addWidget(self.nav, 1)
        self.stack = QStackedWidget()
        self.pages = self._create_pages()
        for key, label in PAGE_LABELS:
            item = QListWidgetItem(label)
            item.setData(256, key)
            self.nav.addItem(item)
            self.stack.addWidget(self.pages[key])
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        splitter = QSplitter()
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.stack)
        splitter.setSizes([230, 1150])
        self.setCentralWidget(splitter)
        self.status_label = QLabel("Starting EOAT Atlas...")
        self.statusBar().addPermanentWidget(self.status_label)
        self.nav.setCurrentRow(0)
        if auto_refresh:
            self.refresh_data(force=False)

    def _create_pages(self) -> dict[str, QWidget]:
        return {
            "home": HomePage(self),
            "what": WhatNeedPage(self),
            "eoats": EOATBrowserPage(self),
            "machines": MachineBrowserPage(self),
            "tools": ToolSearchPage(self),
            "matrix": MatrixPage(self),
            "overview": OverviewPage(self),
            "photos": PhotosPage(self),
            "standards": StandardsPage(self),
            "pm": PMInspectionPage(self),
            "gaps": GapsPage(self),
            "reports": ReportsPage(self),
            "diagnostics": DiagnosticsPage(self),
        }

    def show_page(self, key: str) -> None:
        keys = [item_key for item_key, _label in PAGE_LABELS]
        if key in keys:
            self.nav.setCurrentRow(keys.index(key))

    def open_recommendation(self, query: str) -> None:
        self.show_page("what")
        page = self.pages["what"]
        if hasattr(page, "run_query"):
            page.run_query(query)

    def open_eoat(self, eoat_id: str) -> None:
        self.show_page("eoats")
        page = self.pages["eoats"]
        if hasattr(page, "open_record"):
            page.open_record(eoat_id)

    def open_machine(self, machine: str) -> None:
        self.show_page("machines")
        page = self.pages["machines"]
        if hasattr(page, "open_record"):
            page.open_record(machine)

    def open_tool(self, tool: str) -> None:
        self.show_page("tools")
        page = self.pages["tools"]
        search = getattr(page, "search", None)
        if search is not None:
            search.setText(tool)

    def show_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 9000)

    def refresh_data(self, *, force: bool) -> None:
        if self._load_thread is not None and self._load_thread.isRunning():
            self.show_status("Atlas data refresh is already running.")
            return
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
        for page in self.pages.values():
            if hasattr(page, "set_bundle"):
                page.set_bundle(bundle)
        self.status_label.setText(f"Ready. Refreshed {bundle.loaded_at}")
        self.statusBar().showMessage(
            f"Loaded {len(bundle.eoats)} EOATs, {len(bundle.machines)} machines, {len(bundle.tools)} tools.",
            9000,
        )
        self.data_ready.emit(bundle)

    @Slot(str)
    def _data_failed(self, message: str) -> None:
        self.status_label.setText("Data load failed")
        self.statusBar().showMessage(f"Atlas data load failed: {message}", 12000)
        self.data_failed.emit(message)

    @Slot()
    def _clear_worker_refs(self) -> None:
        self._load_thread = None
        self._load_worker = None

    def closeEvent(self, event) -> None:
        if self._load_thread is not None and self._load_thread.isRunning():
            self._load_thread.quit()
            self._load_thread.wait(3000)
        super().closeEvent(event)


PAGE_LABELS = [
    ("home", "Home / Command Deck"),
    ("what", "What Do I Need?"),
    ("eoats", "EOAT Search / Profiles"),
    ("machines", "Machine Search / Profiles"),
    ("tools", "Tool / Mold / Part Search"),
    ("matrix", "Compatibility Matrix"),
    ("overview", "Overall Maps"),
    ("photos", "Photos"),
    ("standards", "Standards"),
    ("pm", "PM / Inspection"),
    ("gaps", "Documentation Gaps"),
    ("reports", "Reports / Export"),
    ("diagnostics", "Settings / Diagnostics"),
]


__all__ = ["AtlasWindow"]
