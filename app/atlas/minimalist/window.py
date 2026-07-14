from __future__ import annotations

import logging
import os
import re
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QWidget

from core.atlas_entity_search import (
    EntitySearchIndex,
    EntitySearchQueryResult,
    EntitySearchResult,
    normalize_entity_id,
    normalize_entity_type,
)
from core.atlas_models import AtlasDataBundle
from core.atlas_search import SearchResolution, normalize_search_term, resolve_search_query
from core.config import UserConfig
from core.logging import log_activity_event
from core.performance import perf_timer
from core.reporting.pdf_preview_session import cleanup_abandoned_preview_files

from ..page_transition import PageTransitionController
from ..settings import AtlasSettings, save_atlas_settings
from .data import (
    infer_search_kind,
    page_label,
    record_recent_entity_result,
    record_recent_search,
    remove_recent_entity,
    with_front,
)
from .fit_check import AtlasMinimalistFitCheckPage
from .home import AtlasMinimalistHomePage
from .library import AtlasMinimalistLibraryPage
from .packet_builder import AtlasMinimalistPacketBuilderPage
from .settings_store import load_settings as load_minimalist_settings
from .settings_store import save_settings as save_minimalist_settings
from .simple_pages import AtlasMinimalistSimplePage
from .theme import normalize_theme_preference, set_active_minimalist_theme

if TYPE_CHECKING:
    from core.packet_builder_packets import PacketSetup

LOGGER = logging.getLogger(__name__)


def normalized_eoat_key(value) -> str:
    return _normalized_lookup_key(value)


def normalized_tool_key(value) -> str:
    key = _normalized_lookup_key(value)
    return key[4:] if key.startswith("tool") and len(key) > 4 else key


def normalized_machine_key(value) -> str:
    key = _normalized_lookup_key(value)
    for prefix in ("machine", "press"):
        if key.startswith(prefix) and len(key) > len(prefix):
            return key[len(prefix) :]
    return key


def _normalized_lookup_key(value) -> str:
    if value is None:
        return ""
    text = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
    return re.sub(r"[^a-z0-9]+", "", text.strip().casefold())


class MinimalistAtlasLoadWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        project_root: str,
        *,
        force_refresh: bool = False,
        exclude_unaudited_tools: bool = True,
        source_paths: dict[str, str] | None = None,
    ):
        super().__init__()
        self.project_root = project_root
        self.force_refresh = force_refresh
        self.exclude_unaudited_tools = exclude_unaudited_tools
        self.source_paths = dict(source_paths or {})

    @Slot()
    def run(self) -> None:
        try:
            backend = os.getenv("EOAT_ATLAS_DATA_BACKEND", "mysql_api").strip().casefold()
            if backend == "mysql_api":
                from core.data_gateway import AtlasDataGateway

                gateway = AtlasDataGateway()
                try:
                    if self.force_refresh or not gateway.cache.path.exists():
                        self.progress.emit("Deep Refresh: rebuilding the disposable API cache...")
                        gateway.deep_refresh()
                    else:
                        self.progress.emit("Refreshing through the EOAT Atlas API...")
                        gateway.refresh()
                    bundle = gateway.load_bundle(self.project_root)
                    bundle.metrics["deep_refresh"] = bool(self.force_refresh)
                finally:
                    gateway.close()
            elif backend == "legacy":
                from core.atlas_data_loader import load_atlas_data

                self.progress.emit("Loading legacy workbook data (explicit legacy mode)...")
                bundle = load_atlas_data(
                    self.project_root,
                    force_refresh=self.force_refresh,
                    exclude_unaudited_tools=self.exclude_unaudited_tools,
                    source_paths=self.source_paths,
                )
            else:
                raise RuntimeError(f"Unsupported EOAT Atlas backend: {backend}")
            self.finished.emit(bundle)
        except Exception as exc:
            LOGGER.exception("Atlas data refresh failed")
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MinimalistAtlasWindow(QMainWindow):
    data_ready = Signal(object)
    data_failed = Signal(str)
    loading_progress = Signal(str)

    def __init__(self, config: UserConfig, *, auto_refresh: bool = True, settings: AtlasSettings | None = None):
        super().__init__()
        self.config = config
        self.settings = (settings or AtlasSettings()).normalized()
        self.minimalist_app_settings = load_minimalist_settings()
        self._minimalist_theme_preference = normalize_theme_preference(
            self.minimalist_app_settings.get("app", {}).get("theme") if isinstance(self.minimalist_app_settings, dict) else None
        )
        set_active_minimalist_theme(self._minimalist_theme_preference)
        self.bundle: AtlasDataBundle | None = None
        self._entity_search_index = EntitySearchIndex.empty()
        self.current_page_key = "minimalist_home"
        self.pages = {}
        self._load_thread: QThread | None = None
        self._load_worker: MinimalistAtlasLoadWorker | None = None
        self._refresh_in_progress = False
        self._bundle_before_refresh: AtlasDataBundle | None = None
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self.refresh_data)
        self._source_watch_timer = QTimer(self)
        self._source_watch_timer.timeout.connect(self._check_source_file_changes)
        self._source_file_signature: dict[str, float] = {}
        self._source_change_notified_signature: dict[str, float] = {}
        self._using_cached_data_fallback = False
        QTimer.singleShot(0, cleanup_abandoned_preview_files)
        self.setWindowTitle("EOAT Atlas")
        self.resize(1760, 1080)
        self.setMinimumSize(1280, 820)

        self.stack = QStackedWidget()
        self.stack.setObjectName("MinimalistAtlasPageStack")
        self.page_transition = PageTransitionController(self.stack, parent=self)
        self._apply_minimalist_behavior_settings()
        self.home_page = AtlasMinimalistHomePage(self)
        self.fit_check_page = AtlasMinimalistFitCheckPage(self)
        self.packet_builder_page = AtlasMinimalistPacketBuilderPage(self)
        self.library_page = AtlasMinimalistLibraryPage(self)
        self.standards_page = AtlasMinimalistSimplePage(
            self,
            page_key="standards",
            title="Standards & WI",
            subtitle="Standards and work instructions will be added later.",
            mode="standards",
        )
        self.settings_page = None
        self.data_health_page = AtlasMinimalistSimplePage(
            self,
            page_key="data_health",
            title="Data Health",
            subtitle="Data validation tools will be added later.",
            mode="data_health",
        )
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.fit_check_page)
        self.stack.addWidget(self.packet_builder_page)
        self.stack.addWidget(self.library_page)
        self.stack.addWidget(self.standards_page)
        self.stack.addWidget(self.data_health_page)
        self.pages = {
            "minimalist_home": self.home_page,
            "home": self.home_page,
            "fit_check": self.fit_check_page,
            "matrix": self.fit_check_page,
            "packet_builder": self.packet_builder_page,
            "setup_packet": self.packet_builder_page,
            "library": self.library_page,
            "standards": self.standards_page,
            "data_health": self.data_health_page,
        }
        self._apply_minimalist_theme_to_pages(self._minimalist_theme_preference)
        self.setCentralWidget(self.stack)
        self.command_palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self.command_palette_shortcut.activated.connect(self._context_search_shortcut)
        self.command_palette_meta_shortcut = QShortcut(QKeySequence("Meta+K"), self)
        self.command_palette_meta_shortcut.activated.connect(self._context_search_shortcut)
        self._record_diagnostic_timestamp("last_app_launch")
        if bool(self.minimalist_setting("validation.run_on_startup", True)):
            self._record_diagnostic_timestamp("last_validation")

        if auto_refresh:
            self.refresh_data()

    def preview_minimalist_theme(
        self,
        preference: str | None,
        *,
        accent: str | None = None,
        enhanced_small_text_contrast: bool | None = None,
    ) -> None:
        self._minimalist_theme_preference = normalize_theme_preference(preference)
        app_settings = self.minimalist_app_settings.get("app", {}) if isinstance(self.minimalist_app_settings, dict) else {}
        set_active_minimalist_theme(
            self._minimalist_theme_preference,
            accent=accent if accent is not None else app_settings.get("accent"),
            enhanced_small_text_contrast=(
                enhanced_small_text_contrast
                if enhanced_small_text_contrast is not None
                else app_settings.get("enhanced_small_text_contrast")
            ),
        )
        self._apply_minimalist_theme_to_pages(self._minimalist_theme_preference)

    def commit_minimalist_settings(self, settings: dict) -> None:
        self.minimalist_app_settings = deepcopy(settings)
        app_settings = self.minimalist_app_settings.get("app", {}) if isinstance(self.minimalist_app_settings, dict) else {}
        self.preview_minimalist_theme(
            app_settings.get("theme"),
            accent=app_settings.get("accent"),
            enhanced_small_text_contrast=app_settings.get("enhanced_small_text_contrast"),
        )
        self._apply_minimalist_behavior_settings()

    def _apply_minimalist_behavior_settings(self) -> None:
        app_settings = self.minimalist_app_settings.get("app", {}) if isinstance(self.minimalist_app_settings, dict) else {}
        loading_settings = self.minimalist_app_settings.get("data_loading", {}) if isinstance(self.minimalist_app_settings, dict) else {}
        reduced_motion = bool(app_settings.get("reduce_motion", False))
        animation_speed = str(app_settings.get("animation_speed", "smooth") or "smooth")
        self.page_transition.reduced_motion = reduced_motion or animation_speed == "reduced"
        durations = {
            "reduced": (120, 80),
            "standard": (220, 120),
            "smooth": (320, 160),
        }.get(animation_speed, (320, 160))
        self.page_transition.incoming_duration_ms = durations[0]
        self.page_transition.outgoing_duration_ms = durations[1]
        auto_refresh = bool(loading_settings.get("auto_refresh_enabled", False)) and not bool(loading_settings.get("manual_refresh_only", False))
        try:
            auto_refresh_minutes = int(loading_settings.get("auto_refresh_minutes", 15))
        except (TypeError, ValueError):
            auto_refresh_minutes = 15
        if auto_refresh:
            self._auto_refresh_timer.start(max(1, auto_refresh_minutes) * 60 * 1000)
        else:
            self._auto_refresh_timer.stop()
        mysql_api_mode = os.getenv("EOAT_ATLAS_DATA_BACKEND", "mysql_api").strip().casefold() == "mysql_api"
        if (
            not mysql_api_mode
            and bool(loading_settings.get("detect_file_changes", True))
            and not bool(loading_settings.get("manual_refresh_only", False))
        ):
            self._capture_source_file_signature()
            self._source_watch_timer.start(60_000)
        else:
            self._source_watch_timer.stop()

    def minimalist_setting(self, dotted_path: str, default=None):
        node = self.minimalist_app_settings if isinstance(self.minimalist_app_settings, dict) else {}
        for key in dotted_path.split("."):
            if not isinstance(node, dict):
                return default
            node = node.get(key)
        return default if node is None else node

    def _configured_source_paths(self) -> dict[str, str]:
        try:
            from core.globalization.config import load_or_create_global_config

            configured = load_or_create_global_config().source_paths()
        except Exception:
            configured = {}
        paths = self.minimalist_app_settings.get("paths", {}) if isinstance(self.minimalist_app_settings, dict) else {}
        if not isinstance(paths, dict):
            return configured
        configured.update({str(key): str(value) for key, value in paths.items() if str(value or "").strip()})
        return configured

    def _capture_source_file_signature(self) -> None:
        signatures: dict[str, float] = {}
        for key, value in self._configured_source_paths().items():
            path = Path(value).expanduser()
            if path.is_file():
                try:
                    signatures[key] = path.stat().st_mtime
                except OSError:
                    continue
        self._source_file_signature = signatures

    def _check_source_file_changes(self) -> None:
        if not bool(self.minimalist_setting("data_loading.detect_file_changes", True)):
            return
        current: dict[str, float] = {}
        changed: list[str] = []
        for key, value in self._configured_source_paths().items():
            path = Path(value).expanduser()
            if not path.is_file():
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            current[key] = mtime
            previous = self._source_file_signature.get(key)
            notified = self._source_change_notified_signature.get(key)
            if previous is not None and mtime != previous and notified != mtime:
                changed.append(key)
                self._source_change_notified_signature[key] = mtime
        if current:
            self._source_file_signature.update(current)
        if changed and bool(self.minimalist_setting("data_loading.warn_when_files_changed", True)):
            self.show_status("Source files changed since the last load. Run Deep Refresh when you are ready to rebuild the local cache.")

    def _apply_minimalist_theme_to_pages(self, preference: str | None) -> None:
        seen: set[int] = set()
        pages = getattr(self, "pages", {}) or {}
        for page in pages.values():
            if id(page) in seen:
                continue
            seen.add(id(page))
            shell = getattr(page, "shell", None)
            apply_shell = getattr(shell, "set_theme_preference", None)
            if callable(apply_shell):
                apply_shell(preference)
            for attr in ("home_content", "fit_content", "packet_content", "library_content", "simple_content", "settings_content"):
                content = getattr(page, attr, None)
                apply_content = getattr(content, "apply_theme_preference", None)
                if callable(apply_content):
                    apply_content(preference)

    def refresh_data(self, *, force: bool = False, deep_refresh: bool = False) -> None:
        deep = bool(deep_refresh or force)
        mysql_api_mode = os.getenv("EOAT_ATLAS_DATA_BACKEND", "mysql_api").strip().casefold() == "mysql_api"
        if self._refresh_in_progress or (self._load_thread is not None and self._load_thread.isRunning()):
            self.show_status("Atlas data refresh is already running.")
            return
        self._refresh_in_progress = True
        self._bundle_before_refresh = self.bundle
        self._entity_search_index = EntitySearchIndex.empty()
        try:
            self._apply_bundle_to_pages(None)
        except Exception as exc:
            LOGGER.exception("Could not prepare Atlas pages for data refresh")
            self._refresh_in_progress = False
            self._bundle_before_refresh = None
            self.show_status(f"Atlas data refresh could not start: {type(exc).__name__}: {exc}")
            return
        if deep and mysql_api_mode:
            self.loading_progress.emit("Deep Refresh: rebuilding the disposable API cache...")
            self.show_status("Deep Refresh started. EOAT Atlas is rebuilding its disposable cache from the API.")
        elif deep:
            self.loading_progress.emit("Deep Refresh: rebuilding the legacy cache from workbook...")
            self.show_status("Explicit legacy Deep Refresh started.")
        elif mysql_api_mode:
            self.loading_progress.emit("Refreshing through the EOAT Atlas API...")
            self.show_status("Refreshing EOAT Atlas from the server change feed and disposable cache.")
        else:
            self.loading_progress.emit("Refreshing from local cache...")
            self.show_status("Refreshing EOAT Atlas from the existing local cache.")
        self._load_thread = QThread(self)
        self._load_worker = MinimalistAtlasLoadWorker(
            self.config.project_root,
            force_refresh=deep,
            exclude_unaudited_tools=self.settings.exclude_unaudited_tools,
            source_paths=self._configured_source_paths(),
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

    def deep_refresh_data(self) -> None:
        self.refresh_data(deep_refresh=True)

    @Slot(object)
    def _data_loaded(self, bundle: AtlasDataBundle) -> None:
        self.bundle = bundle
        self._bundle_before_refresh = None
        self._using_cached_data_fallback = False
        with perf_timer(
            self.config.project_root,
            "search.index.build",
            details={
                "eoats": len(bundle.eoats),
                "tools": len(bundle.tools),
                "machines": len(bundle.machines),
                "loaded_at": bundle.loaded_at,
            },
            source="minimalist_search",
            page_tool="search",
        ):
            self._entity_search_index = EntitySearchIndex.build(bundle)
        self._apply_bundle_to_pages(bundle)
        deep_refresh = bool(getattr(bundle, "metrics", {}).get("deep_refresh"))
        action_label = "Deep Refresh complete." if deep_refresh else "Refresh complete."
        load_message = f"{action_label} Loaded {len(bundle.eoats)} EOATs, {len(bundle.machines)} machines, {len(bundle.tools)} tools."
        if bool(self.minimalist_setting("data_loading.show_last_refresh_timestamp", True)):
            load_message = f"{load_message} {datetime.now().strftime('%I:%M %p')}."
        self.show_status(load_message)
        if os.getenv("EOAT_ATLAS_DATA_BACKEND", "mysql_api").strip().casefold() != "mysql_api":
            self._capture_source_file_signature()
        self._record_diagnostic_timestamp("last_successful_data_load")
        self.data_ready.emit(bundle)

    @Slot(str)
    def _data_failed(self, message: str) -> None:
        fallback = self._bundle_before_refresh or self.bundle
        self._bundle_before_refresh = None
        if fallback is not None and bool(self.minimalist_setting("data_loading.cache_last_good_data", True)):
            self.bundle = fallback
            self._apply_bundle_to_pages(fallback)
            self._using_cached_data_fallback = True
            if bool(self.minimalist_setting("data_loading.show_cached_data_warning", True)):
                self.show_status("Atlas data refresh failed; the last successful local data remains available. You can try again.")
            self.data_ready.emit(fallback)
            return
        self.show_status("Atlas data refresh failed. Check the application log, then try again.")
        self.data_failed.emit(message)

    def _apply_bundle_to_pages(self, bundle: AtlasDataBundle | None) -> None:
        self.home_page.set_bundle(bundle)
        self.fit_check_page.set_bundle(bundle)
        self.packet_builder_page.set_bundle(bundle)
        self.library_page.set_bundle(bundle)
        self.standards_page.set_bundle(bundle)
        if self.settings_page is not None:
            self.settings_page.set_bundle(bundle)
        self.data_health_page.set_bundle(bundle)

    def _record_diagnostic_timestamp(self, key: str) -> None:
        if not bool(self.minimalist_setting("diagnostics.activity_log_enabled", True)):
            return
        settings = load_minimalist_settings()
        settings.setdefault("diagnostics", {})[key] = datetime.now().isoformat(timespec="seconds")
        try:
            save_minimalist_settings(settings)
        except OSError:
            LOGGER.debug("Could not persist minimalist diagnostic timestamp %s", key, exc_info=True)
            return
        self.minimalist_app_settings = settings

    @Slot()
    def _clear_worker_refs(self) -> None:
        self._refresh_in_progress = False
        self._load_thread = None
        self._load_worker = None

    def show_page(self, key: str) -> bool:
        with perf_timer(
            self.config.project_root,
            f"navigation.show_page.{key}",
            details={"target_page": key, "current_page": self.current_page_key, "bundle_loaded": self.bundle is not None},
            source="minimalist_window",
            page_tool="navigation",
        ):
            normalized = "minimalist_home" if key in {"home", "minimalist_home"} else str(key or "minimalist_home")
            if not self._confirm_current_page_navigation(normalized):
                return False
            self.close_all_search_overlays()
            if normalized == "minimalist_home":
                return self._activate_page(self.home_page, "minimalist_home", normalized)
            if normalized == "library":
                return self._activate_page(self.library_page, "library", normalized)
            if normalized in {"packet_builder", "setup_packet"}:
                if self._activate_page(self.fit_check_page, "fit_check", "fit_check"):
                    self.show_status("Setup Packets now generate from a valid Fit Check.")
                    return True
                return False
            if normalized in {"fit_check", "matrix"}:
                return self._activate_page(self.fit_check_page, "fit_check", "fit_check")
            if normalized == "standards":
                return self._activate_page(self.standards_page, "standards", "standards")
            if normalized in {"settings", "diagnostics"}:
                settings_page = self._ensure_settings_page()
                return self._activate_page(settings_page, "settings", "settings")
            if normalized == "data_health":
                return self._activate_page(self.data_health_page, "data_health", "data_health")
            self._set_active_back_to_library_visible(False, animated=False)
            self.close_all_search_overlays()
            self.show_status(f"{page_label(normalized)} is not implemented in the minimalist UI yet.")
            return False

    def _confirm_current_page_navigation(self, target_key: str) -> bool:
        target = "settings" if target_key in {"settings", "diagnostics"} else target_key
        if self.current_page_key != "settings" or target == "settings":
            return True
        confirmer = getattr(self.settings_page, "confirm_navigation_away", None)
        if callable(confirmer):
            return bool(confirmer())
        return True

    def _activate_page(self, page: QWidget, page_key: str, nav_key: str) -> bool:
        app_settings = self.minimalist_app_settings.get("app", {}) if isinstance(self.minimalist_app_settings, dict) else {}
        transitions_enabled = not bool(app_settings.get("reduce_motion", False)) and str(app_settings.get("animation_speed", "smooth")) != "reduced"
        previous_page_key = self.current_page_key
        if not self.page_transition.switch_to_widget(page, animated=bool(self.current_page_key) and transitions_enabled):
            return False
        if previous_page_key == "settings" and page_key != "settings":
            page_hidden = getattr(self.settings_page, "page_hidden", None)
            if callable(page_hidden):
                page_hidden()
        self.current_page_key = page_key
        if hasattr(page, "page_shown"):
            page.page_shown()
        shell = getattr(page, "shell", None)
        if shell is not None:
            shell.set_active_nav(nav_key)
        self.close_all_search_overlays()
        return True

    def _ensure_settings_page(self) -> QWidget:
        if self.settings_page is None:
            from .settings_page import AtlasMinimalistSettingsPage

            self.settings_page = AtlasMinimalistSettingsPage(self)
            self.settings_page.set_bundle(self.bundle)
            self.stack.addWidget(self.settings_page)
            self.pages["settings"] = self.settings_page
            self.pages["diagnostics"] = self.settings_page
            self._apply_minimalist_theme_to_pages(self._minimalist_theme_preference)
        return self.settings_page

    def open_recommendation(self, query: str, *, kind: str = "", record_search: bool = True) -> None:
        query = str(query or "").strip()
        if not query:
            self.show_status("Enter a tool, mold, part, machine, EOAT, or description to search.")
            return
        if self.bundle is None:
            self.show_status("Atlas data is still loading.")
            return
        from core.atlas_recommendations import recommend_for_query

        result = recommend_for_query(self.bundle, query)
        if result.matches:
            first = result.matches[0]
            if record_search and first.result_type in {"eoat", "machine", "tool", "part"}:
                self.record_minimalist_search(query, kind=self._result_type_label(first.result_type), update=False)
            self._record_match_recent(first.result_type, first.key)
        if record_search:
            self._refresh_recent_searches()
        message = result.summary
        if result.best is not None:
            machines = ", ".join(result.best.machines[:4]) or "no machines indexed"
            message = f"{result.summary} Score {result.best.score}. Machines: {machines}."
        self.show_status(message)

    def resolve_search_query(self, query: str) -> SearchResolution:
        return resolve_search_query(self.bundle, query)

    def entity_search_index(self) -> EntitySearchIndex:
        return self._entity_search_index

    def search_entities(self, query: str, *, limit: int = 30):
        text = str(query or "").strip()
        search_settings = self.minimalist_app_settings.get("search", {}) if isinstance(self.minimalist_app_settings, dict) else {}
        with perf_timer(
            self.config.project_root,
            "search.query.execute",
            details={
                "query_length": len(text),
                "index_items": len(self._entity_search_index.items),
                "limit": limit,
            },
            source="minimalist_search",
            page_tool="search",
        ):
            raw_result = self._entity_search_index.search(text, limit=max(limit, int(search_settings.get("recent_items_limit", 15) or 15)))
            allowed_types = {
                entity_type
                for entity_type, key in (
                    ("eoat", "include_eoats"),
                    ("tool", "include_tools"),
                    ("machine", "include_machines"),
                )
                if bool(search_settings.get(key, True))
            }
            results = [result for result in raw_result.results if result.entity_type in allowed_types]
            if not bool(search_settings.get("show_partial_matches", True)):
                results = [result for result in results if result.exact]
            current_scope = self._current_library_scope() if bool(search_settings.get("prefer_current_library_type", True)) else ""
            prefer_exact = bool(search_settings.get("prefer_exact_id_matches", True))
            if current_scope or prefer_exact:
                def primary_exact(result) -> bool:
                    if not prefer_exact:
                        return False
                    return normalize_entity_id(result.entity_type, result.entity_id) == normalize_entity_id(result.entity_type, text)

                results.sort(
                    key=lambda result: (
                        0 if primary_exact(result) else 1,
                        0 if prefer_exact and result.exact else 1,
                        0 if current_scope and result.entity_type == current_scope else 1,
                        -int(getattr(result, "score", 0) or 0),
                        result.display_label.casefold(),
                    )
                )
            results.extend(self._file_search_results(text, search_settings, limit=max(0, int(limit or 0)) - len(results)))
            return EntitySearchQueryResult(query=raw_result.query, results=tuple(results[: max(0, int(limit or 0))]))

    def _file_search_results(self, query: str, search_settings: dict, *, limit: int) -> list[EntitySearchResult]:
        if limit <= 0:
            return []
        text = str(query or "").strip().casefold()
        if not text:
            return []
        candidates: list[tuple[str, str, Path]] = []
        paths = self.minimalist_app_settings.get("paths", {}) if isinstance(self.minimalist_app_settings, dict) else {}
        output_folder = Path(str(paths.get("output_folder") or "")).expanduser() if isinstance(paths, dict) and paths.get("output_folder") else None
        reference_folder = Path(str(paths.get("reference_docs_folder") or "")).expanduser() if isinstance(paths, dict) and paths.get("reference_docs_folder") else None
        if bool(search_settings.get("include_setup_packets", False)) and output_folder is not None:
            candidates.extend(("setup_packet", "Setup Packet", path) for path in self._iter_search_files(output_folder, {".pdf"}))
        include_reference = bool(search_settings.get("include_reference_docs", False)) or bool(
            self.minimalist_setting("reference_documents.include_in_global_search", False)
        )
        if include_reference and reference_folder is not None:
            candidates.extend(
                ("reference_document", "Reference Document", path)
                for path in self._iter_search_files(reference_folder, {".pdf", ".docx", ".xlsx", ".md", ".txt"})
            )
        matches: list[EntitySearchResult] = []
        for entity_type, label, path in candidates:
            haystack = f"{path.name} {path.stem} {path.parent.name}".casefold()
            if text not in haystack:
                continue
            matches.append(
                EntitySearchResult(
                    entity_type=entity_type,
                    entity_id=str(path),
                    display_label=path.stem,
                    subtitle=f"{label} | {path.parent}",
                    route_target={"page": "file", "path": str(path)},
                    score=400,
                    exact=path.stem.casefold() == text,
                    match_kind="file",
                    source="settings-file-index",
                )
            )
            if len(matches) >= limit:
                break
        return matches

    @staticmethod
    def _iter_search_files(folder: Path, suffixes: set[str]) -> list[Path]:
        if not folder.exists():
            return []
        try:
            return sorted(
                (path for path in folder.rglob("*") if path.is_file() and path.suffix.casefold() in suffixes),
                key=lambda path: str(path).casefold(),
            )[:250]
        except OSError:
            return []

    def _current_library_scope(self) -> str:
        content = getattr(getattr(self, "library_page", None), "library_content", None)
        scope = str(getattr(content, "scope_type", "") or "")
        return scope if scope in {"eoat", "tool", "machine"} else ""

    def navigate_to_entity(self, entity_type: str, entity_id: str, *, source: str = "", raw_query: str = "") -> bool:
        normalized_type = normalize_entity_type(entity_type)
        value = str(entity_id or "").strip()
        if normalized_type in {"setup_packet", "reference_document"}:
            path = Path(value)
            if path.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                return True
            self.show_status("That file is no longer available.")
            return False
        with perf_timer(
            self.config.project_root,
            "search.profile_navigation",
            details={"record_type": normalized_type, "record_id": value, "source": source},
            source="minimalist_search",
            page_tool="navigation",
        ):
            result = self._entity_search_index.get(normalized_type, value)
            if result is None:
                remove_recent_entity(normalized_type, value)
                self._refresh_recent_searches()
                self.show_status("That recent item is no longer in the current Atlas data.")
                return False
            navigated = self.navigate_to_profile(result, source=source, raw_query=raw_query or result.entity_id)
            if navigated:
                record_recent_entity_result(result, query=raw_query or result.entity_id)
                self._refresh_recent_searches()
            return navigated

    def open_recent_entity(self, entity) -> bool:
        entity_type = str(getattr(entity, "entity_type", "") or "")
        entity_id = str(getattr(entity, "entity_id", "") or "")
        if isinstance(entity, dict):
            entity_type = entity_type or str(entity.get("type") or entity.get("entity_type") or "")
            entity_id = entity_id or str(entity.get("id") or entity.get("entity_id") or "")
        with perf_timer(
            self.config.project_root,
            "search.recent_item.click",
            details={"record_type": entity_type, "record_id": entity_id},
            source="minimalist_search",
            page_tool="search",
        ):
            return self.navigate_to_entity(entity_type, entity_id, source="recent-search", raw_query=entity_id)

    def run_search_query(
        self,
        query: str,
        *,
        source: str = "",
        kind: str = "",
        record_search: bool = True,
        allow_recommendation: bool = True,
        resolution: SearchResolution | None = None,
    ) -> SearchResolution:
        text = str(query or "").strip()
        resolved = resolution or self.resolve_search_query(text)
        navigation_occurred = False
        recommendation_fallback = False
        if not text:
            self.show_status("Enter a tool, mold, part, machine, EOAT, or description to search.")
            self._log_search_resolution(resolved, source=source, navigation_occurred=False, recommendation_fallback=False)
            return resolved
        if self.bundle is None:
            self.show_status("Atlas data is still loading.")
            self._log_search_resolution(resolved, source=source, navigation_occurred=False, recommendation_fallback=False)
            return resolved
        if resolved.found and resolved.entity_type in {"eoat", "machine", "tool"}:
            default_action = str(self.minimalist_setting("search.default_action", "open_best_match") or "open_best_match")
            if default_action == "show_result_preview":
                self.show_status(f"Best match: {resolved.display_label or resolved.entity_id}. Select it from search results to open.")
                self._log_search_resolution(resolved, source=source, navigation_occurred=False, recommendation_fallback=False)
                return resolved
            if default_action == "ask_when_multiple":
                query_result = self.search_entities(text, limit=3)
                if len(getattr(query_result, "results", ()) or ()) > 1:
                    self.show_status("Multiple Library records match. Pick one from the search results.")
                    self._log_search_resolution(resolved, source=source, navigation_occurred=False, recommendation_fallback=False)
                    return resolved
            navigation_occurred = self.navigate_to_profile(resolved, source=source, raw_query=text, log_search=False)
            if navigation_occurred and record_search:
                self.record_minimalist_search(text, kind=kind or self._result_type_label(resolved.entity_type))
            self._log_search_resolution(
                resolved,
                source=source,
                navigation_occurred=navigation_occurred,
                recommendation_fallback=False,
            )
            return resolved
        if resolved.entity_type == "ambiguous":
            self.show_status("Multiple Library records match. Pick one from the search results.")
            self._log_search_resolution(resolved, source=source, navigation_occurred=False, recommendation_fallback=False)
            return resolved
        if allow_recommendation:
            recommendation_fallback = True
            self.open_recommendation(text, kind=kind, record_search=record_search)
        else:
            self.show_status("No matching Library profile found.")
        self._log_search_resolution(
            resolved,
            source=source,
            navigation_occurred=False,
            recommendation_fallback=recommendation_fallback,
        )
        return resolved

    def navigate_to_profile(self, entity, *, source: str = "", raw_query: str = "", log_search: bool = True) -> bool:
        entity_type = str(getattr(entity, "entity_type", "") or "").casefold()
        entity_id = str(getattr(entity, "entity_id", "") or "").strip()
        if isinstance(entity, dict):
            entity_type = entity_type or str(entity.get("entity_type", "") or "").casefold()
            entity_id = entity_id or str(entity.get("entity_id", "") or "").strip()
        entity_type = entity_type or str(getattr(entity, "result_type", "") or "").casefold()
        entity_id = entity_id or str(getattr(entity, "key", "") or "").strip()
        entity_type = entity_type or str(getattr(entity, "record_type", "") or "").casefold()
        entity_id = entity_id or str(getattr(entity, "record_id", "") or "").strip()
        navigation_occurred = False
        if entity_type == "eoat":
            self.open_eoat(entity_id, source=source)
            navigation_occurred = True
        elif entity_type == "machine":
            self.open_machine(entity_id, source=source)
            navigation_occurred = True
        elif entity_type == "tool":
            self.open_tool(entity_id, source=source)
            navigation_occurred = True
        if log_search and entity_type in {"eoat", "machine", "tool"}:
            self._log_search_resolution(
                SearchResolution(
                    raw_query=str(raw_query or entity_id),
                    normalized_query=normalize_search_term(raw_query or entity_id),
                    found=navigation_occurred,
                    entity_type=entity_type if navigation_occurred else "unknown",
                    entity_id=entity_id if navigation_occurred else "",
                    display_label=str(getattr(entity, "display_label", "") or getattr(entity, "title", "") or entity_id),
                    route_target={"page": "library", "entity_type": entity_type, "entity_id": entity_id} if navigation_occurred else {},
                    confidence=str(getattr(entity, "confidence", "") or "exact"),
                ),
                source=source,
                navigation_occurred=navigation_occurred,
                recommendation_fallback=False,
            )
        return navigation_occurred

    def open_eoat(self, eoat_id: str, *, source: str = "") -> None:
        with perf_timer(
            self.config.project_root,
            "record.open_request.eoat",
            details={"record_type": "eoat", "record_id": eoat_id, "source": source},
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
            if str(source or "").casefold() == "fit_check":
                self.library_page.select_entity_from_fit_check("eoat", record.eoat_id)
            else:
                self.library_page.select_entity("eoat", record.eoat_id)
            tools = ", ".join(record.tools[:3]) or "no linked tools"
            machines = ", ".join(record.machines[:4]) or "no linked machines"
            self.show_status(f"{record.eoat_id}: {record.eoat_type or 'EOAT'} | Tools: {tools} | Machines: {machines}.")

    def open_machine(self, machine: str, *, source: str = "") -> None:
        with perf_timer(
            self.config.project_root,
            "record.open_request.machine",
            details={"record_type": "machine", "record_id": machine, "source": source},
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
            if str(source or "").casefold() == "fit_check":
                self.library_page.select_entity_from_fit_check("machine", record.machine)
            else:
                self.library_page.select_entity("machine", record.machine)
            eoats = ", ".join(record.compatible_eoats[:4]) or "no compatible EOATs indexed"
            self.show_status(f"Machine {record.machine}: {record.robot_type or record.robot_model or 'robot info missing'} | EOATs: {eoats}.")

    def open_tool(self, tool: str, *, source: str = "") -> None:
        with perf_timer(
            self.config.project_root,
            "record.open_request.tool",
            details={"record_type": "tool", "record_id": tool, "source": source},
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
            if str(source or "").casefold() == "fit_check":
                self.library_page.select_entity_from_fit_check("tool", record.tool)
            else:
                self.library_page.select_entity("tool", record.tool)
            eoats = ", ".join(record.compatible_eoats[:4]) or "no validated EOATs indexed"
            machines = ", ".join(record.compatible_machines[:4]) or "no machines indexed"
            self.show_status(f"Tool {record.tool}: EOATs: {eoats} | Machines: {machines}.")

    def open_setup_packet(self, **kwargs) -> None:
        from core.packet_builder_packets import PacketSetup

        setup = kwargs.get("setup")
        if not isinstance(setup, PacketSetup):
            setup = PacketSetup(
                tool_id=kwargs.get("tool_id") or kwargs.get("tool") or "",
                machine_id=kwargs.get("machine_id") or kwargs.get("machine") or "",
                eoat_id=kwargs.get("eoat_id") or kwargs.get("eoat") or "",
            )
        self.show_page("fit_check")
        opener = getattr(self.fit_check_page.fit_content, "open_setup_packet_overlay", None)
        if callable(opener):
            if setup.complete():
                opener(setup)
            else:
                opener()

    def open_photos(self, _eoat_id: str = "") -> None:
        self.show_page("photos")

    def generate_install_packet_current_context(self) -> None:
        setup = self.current_fit_check_setup()
        if setup is not None:
            self.open_setup_packet(setup=setup)
            return
        self.show_page("fit_check")
        self.show_status("Run a complete compatible Fit Check before creating a packet.")

    def current_fit_check_setup(self) -> PacketSetup | None:
        from core.packet_builder_packets import PacketSetup

        getter = getattr(self.fit_check_page.fit_content, "current_valid_setup", None)
        setup = getter() if callable(getter) else None
        return setup if isinstance(setup, PacketSetup) else None

    def make_qr_for_current_eoat(self) -> None:
        self.show_status("QR label generation is not implemented in the minimalist UI yet.")

    def queue_current_eoat_status_review(self) -> None:
        if os.getenv("EOAT_ATLAS_DATA_BACKEND", "mysql_api").strip().casefold() == "mysql_api":
            self.show_status("Legacy pending-update queues are disabled in MySQL/API mode.")
            return
        selected = getattr(getattr(self.library_page, "library_content", None), "selected_entity", None)
        if getattr(selected, "entity_type", "") != "eoat":
            self.show_status("Open an EOAT profile before queuing a status update.")
            return
        eoat_id = str(getattr(selected, "key", "") or "")
        record = self._find_eoat(eoat_id)
        original_status = str(getattr(record, "status", "") or "") if record is not None else ""
        from core.globalization.config import load_or_create_global_config
        from core.globalization.pending_updates import PendingUpdateStore
        from core.globalization.runtime_paths import ensure_runtime_layout, get_runtime_paths
        from core.globalization.write_foundation import ChangeValidationService

        runtime = ensure_runtime_layout(get_runtime_paths())
        config = load_or_create_global_config(runtime)
        submission = {
            "entity_type": "eoat",
            "entity_id": eoat_id,
            "field": "status",
            "proposed_value": "Needs Review",
        }
        valid, message = ChangeValidationService(config).validate_submission(submission)
        if not valid:
            self.show_status(message)
            return
        update = PendingUpdateStore(runtime, config).create_update(
            entity_type="eoat",
            entity_id=eoat_id,
            field_name="status",
            expected_original_value=original_status,
            proposed_value="Needs Review",
            reason="Queued from EOAT Atlas Library profile.",
            source_view="library",
            source_action="queue_current_eoat_status_review",
        )
        self.show_status(f"Queued pending status update for {eoat_id}. Production workbook sync remains disabled.")
        self.refresh_data()
        LOGGER.info("Queued pending EOAT status update %s for %s", update.get("pending_update_id") or update.get("update_id"), eoat_id)

    def open_compare(self, item_type: str) -> None:
        self.show_status(f"{item_type.title()} compare is not implemented in the minimalist UI yet.")

    def toggle_dark_mode(self) -> None:
        next_theme = "light" if self._minimalist_theme_preference == "dark" else "dark"
        content = getattr(self.settings_page, "settings_content", None)
        if self.current_page_key == "settings" and content is not None:
            setter = getattr(content, "_set_setting", None)
            if callable(setter):
                setter("app.theme", next_theme)
                self.show_status(f"Theme preview set to {next_theme.title()}. Save Settings to keep it.")
                return
        settings = load_minimalist_settings()
        settings.setdefault("app", {})["theme"] = next_theme
        save_minimalist_settings(settings)
        self.commit_minimalist_settings(settings)
        self.show_status(f"Theme set to {next_theme.title()}.")

    def show_status(self, message: str) -> None:
        active = self.stack.currentWidget() if hasattr(self, "stack") else self.home_page
        toast = getattr(active, "show_toast", None)
        if callable(toast):
            toast(message)
            return
        self.home_page.show_toast(message)

    def _set_active_back_to_library_visible(self, visible: bool, *, animated: bool) -> None:
        active = self.stack.currentWidget() if hasattr(self, "stack") else None
        shell = getattr(active, "shell", None)
        top_bar = getattr(shell, "top_bar", None)
        setter = getattr(top_bar, "set_back_visible", None)
        if callable(setter):
            setter(bool(visible), animated=animated)

    def record_minimalist_search(self, query: str, *, kind: str = "", update: bool = True) -> None:
        text = str(query or "").strip()
        if not text:
            return
        resolved_kind = kind.strip() or infer_search_kind(text, self.bundle)
        record_recent_search(text, kind=resolved_kind, bundle=self.bundle, limit=int(self.minimalist_setting("search.recent_items_limit", 15) or 15))
        if update:
            self._refresh_recent_searches()

    def record_recent(self, item_type: str, key: str) -> None:
        text = str(key or "").strip()
        if not text:
            return
        result = self._entity_search_index.get(item_type, text)
        if result is not None:
            record_recent_entity_result(result, query=text, limit=int(self.minimalist_setting("search.recent_items_limit", 15) or 15))
        attr = {
            "eoat": "recent_eoats",
            "machine": "recent_machines",
            "tool": "recent_tools",
        }.get(item_type)
        if not attr:
            return
        values = with_front(getattr(self.settings, attr), text, limit=int(self.minimalist_setting("search.recent_items_limit", 15) or 15))
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
        self.fit_check_page.shell.search_overlay.refresh_results()
        self.packet_builder_page.shell.search_overlay.refresh_results()
        self.library_page.shell.search_overlay.refresh_results()
        self.standards_page.shell.search_overlay.refresh_results()
        if self.settings_page is not None:
            self.settings_page.shell.search_overlay.refresh_results()
        self.data_health_page.shell.search_overlay.refresh_results()

    def _context_search_shortcut(self) -> None:
        self.close_all_search_overlays()
        self.stack.currentWidget().open_search_overlay()

    def close_all_search_overlays(self) -> None:
        seen: set[int] = set()
        for page in self.pages.values():
            if id(page) in seen:
                continue
            seen.add(id(page))
            shell = getattr(page, "shell", None)
            close_shell = getattr(shell, "close_overlays", None)
            if callable(close_shell):
                close_shell(immediate=True)
            for attr in ("home_content", "fit_content", "packet_content", "library_content", "simple_content", "settings_content"):
                content = getattr(page, attr, None)
                close_content = getattr(content, "close_search_overlays", None)
                if callable(close_content):
                    close_content()

    def _result_type_label(self, result_type: str) -> str:
        return {
            "eoat": "EOAT",
            "machine": "Machine",
            "tool": "Tool / Mold",
            "part": "Part",
        }.get(str(result_type or "").casefold(), "Search")

    def _log_search_resolution(
        self,
        resolution: SearchResolution,
        *,
        source: str = "",
        navigation_occurred: bool,
        recommendation_fallback: bool,
    ) -> None:
        payload = {
            "raw_query": getattr(resolution, "raw_query", "") or "",
            "normalized_query": getattr(resolution, "normalized_query", "") or normalize_search_term(getattr(resolution, "raw_query", "")),
            "matched_entity_type": getattr(resolution, "entity_type", "") or "unknown",
            "matched_entity_id": getattr(resolution, "entity_id", "") or "",
            "display_label": getattr(resolution, "display_label", "") or "",
            "route_target": dict(getattr(resolution, "route_target", {}) or {}),
            "confidence": getattr(resolution, "confidence", "") or "",
            "source": str(source or ""),
            "navigation_occurred": bool(navigation_occurred),
            "recommendation_fallback": bool(recommendation_fallback),
            "match_count": len(getattr(resolution, "matches", ()) or ()),
        }
        LOGGER.info("Atlas search resolution: %s", payload)
        project_root = str(getattr(self.config, "project_root", "") or "")
        if project_root and bool(self.minimalist_setting("diagnostics.activity_log_enabled", True)):
            warning = log_activity_event(project_root, "atlas_search_resolution", payload)
            if warning:
                LOGGER.warning(warning)

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
        shutdown_admin = getattr(getattr(self, "settings_page", None), "shutdown_admin_session", None)
        if callable(shutdown_admin):
            shutdown_admin()
        for page_name in (
            "home_page",
            "fit_check_page",
            "packet_builder_page",
            "library_page",
            "standards_page",
            "settings_page",
            "data_health_page",
        ):
            shell = getattr(getattr(self, page_name, None), "shell", None)
            remover = getattr(shell, "remove_app_event_filter", None)
            if callable(remover):
                remover()
        load_thread = getattr(self, "_load_thread", None)
        if load_thread is not None and load_thread.isRunning():
            load_thread.quit()
            load_thread.wait(3000)
        super().closeEvent(event)


__all__ = ["MinimalistAtlasWindow"]
