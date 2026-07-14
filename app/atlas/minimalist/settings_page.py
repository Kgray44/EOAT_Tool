from __future__ import annotations

import json
import logging
import os
import platform
import sys
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.atlas_data_loader import invalidate_atlas_data_cache
from core.paths import get_press_capacity_file, resolve_project_paths

from .settings_store import (
    ADMIN_LOGOUT_TIMEOUT_SECONDS,
    admin_password_configured,
    custom_defaults_status,
    ensure_default_admin_password,
    get_effective_default_settings,
    load_settings,
    save_custom_defaults,
    save_settings,
    set_admin_password,
    settings_path,
    verify_admin_password,
)
from .shell import AtlasMinimalistShell
from .theme import (
    active_minimalist_tokens,
    apply_glass_theme,
    normalize_theme_preference,
    qcolor,
    set_active_minimalist_theme,
    settings_dialog_styles,
    settings_page_styles,
)
from .widgets import GlassPanel, MinimalistToast, StatusDot, glyph_icon

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SectionSpec:
    key: str
    title: str
    description: str
    glyph: str


@dataclass(frozen=True)
class SourceSpec:
    key: str
    title: str
    description: str
    kind: str
    glyph: str
    extensions: tuple[str, ...] = ()


@dataclass(frozen=True)
class SettingOption:
    value: Any
    label: str


@dataclass(frozen=True)
class SettingDefinition:
    section: str
    key: str
    label: str
    control: str
    default: Any
    consumer: str
    apply: str
    description: str = ""
    options: tuple[SettingOption, ...] = ()
    locked: bool = False
    implemented: bool = True
    visible: bool = True


SECTIONS: tuple[SectionSpec, ...] = (
    SectionSpec("data_sources", "Data Sources", "Workbooks, folders, and documents", "grid"),
    SectionSpec("refresh_cache", "Refresh & Cache", "Data loading and caching behavior", "swap"),
    SectionSpec("read_only_safety", "Read-Only Safety", "Protection and integrity settings", "status"),
    SectionSpec("search_navigation", "Search & Navigation", "Search behavior and navigation", "search"),
    SectionSpec("fit_check", "Fit Check", "Compatibility and flow behavior", "target"),
    SectionSpec("library", "Library", "Library display and defaults", "library"),
    SectionSpec("display_accessibility", "Display & Accessibility", "Theme, appearance, and readability", "target"),
    SectionSpec("setup_packet_pdf", "Setup Packet / PDF", "PDF defaults and output settings", "doc"),
    SectionSpec("validation_health", "Validation & Data Health", "Data checks and validation rules", "status"),
    SectionSpec("reference_documents", "Reference Documents", "Guidelines and reference files", "doc"),
    SectionSpec("diagnostics_support", "Diagnostics & Support", "Logs, tools, and troubleshooting", "gear"),
    SectionSpec("about", "About", "App information and version", "status"),
)


SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec("eoat_master_tracker", "EOAT Master Tracker", "EOAT, Tool, Machine, compatibility, and details", "file", "doc", (".xlsx",)),
    SourceSpec("press_capacity_workbook", "Press Capacity Workbook", "Machine press capacities and compatibility", "file", "grid", (".xlsx",)),
    SourceSpec("robot_workbook", "Robot Workbook", "Robot and cell information", "file", "grid", (".xlsx",)),
    SourceSpec("photos_root", "EOAT Photos Root", "Photos for EOAT profiles", "folder", "folder"),
    SourceSpec("output_folder", "Generated Output Folder", "Setup packets, PDFs, exports, and logs", "folder", "folder"),
    SourceSpec("reference_docs_folder", "Reference Documents", "Guidelines, PM checklists, and training docs", "folder", "doc"),
)


REFERENCE_DOC_SPECS: tuple[tuple[str, str], ...] = (
    ("eoat_guidelines_path", "EOAT Standard Design Guidelines"),
    ("pm_checklist_path", "PM Checklist"),
    ("project_charter_path", "Project Charter"),
    ("training_materials_path", "Training Materials"),
    ("process_binder_references_path", "Process Binder References"),
)

ADMIN_LOGOUT_TIMEOUT_LABELS: dict[int, str] = {
    0: "Immediately",
    15: "15 sec",
    30: "30 sec",
    60: "1 min",
    120: "2 min",
    300: "5 min",
}
ADMIN_LOGOUT_TIMEOUT_OPTIONS: tuple[tuple[int, str], ...] = tuple(
    (value, ADMIN_LOGOUT_TIMEOUT_LABELS[value]) for value in ADMIN_LOGOUT_TIMEOUT_SECONDS
)

SETTINGS_REGISTRY: tuple[SettingDefinition, ...] = (
    *(SettingDefinition("data_sources", f"paths.{spec.key}", spec.title, "path", "", "Atlas data source resolver", "after Save + Reload Data") for spec in SOURCE_SPECS),
    SettingDefinition("refresh_cache", "data_loading.refresh_on_launch", "Refresh on app launch", "checkbox", True, "app.atlas.main startup refresh gate", "next launch"),
    SettingDefinition("refresh_cache", "data_loading.manual_refresh_only", "Manual refresh only", "checkbox", False, "MinimalistAtlasWindow automatic refresh gate", "after Save", "Disables automatic refresh during controlled review sessions."),
    SettingDefinition("refresh_cache", "data_loading.auto_refresh_enabled", "Auto-refresh enabled", "checkbox", False, "MinimalistAtlasWindow auto-refresh timer", "after Save"),
    SettingDefinition("refresh_cache", "data_loading.auto_refresh_minutes", "Auto-refresh interval", "segmented", 15, "MinimalistAtlasWindow auto-refresh timer interval", "after Save", options=(SettingOption(5, "5 min"), SettingOption(10, "10 min"), SettingOption(15, "15 min"), SettingOption(30, "30 min"), SettingOption(60, "60 min"))),
    SettingDefinition("refresh_cache", "data_loading.detect_file_changes", "Detect file changes", "checkbox", True, "MinimalistAtlasWindow source timestamp watcher", "after Save"),
    SettingDefinition("refresh_cache", "data_loading.cache_last_good_data", "Cache last good data", "checkbox", True, "MinimalistAtlasWindow load-failure fallback", "after Save", "Keeps the most recent successful read visible if a source file is temporarily unavailable."),
    SettingDefinition("refresh_cache", "data_loading.cache_photo_thumbnails", "Cache photo thumbnails", "checkbox", True, "Library PhotoService thumbnail cache", "after Save"),
    SettingDefinition("refresh_cache", "data_loading.show_cached_data_warning", "Show cached-data warning", "checkbox", True, "MinimalistAtlasWindow cached-data status message", "after Save"),
    SettingDefinition("refresh_cache", "data_loading.warn_when_files_changed", "Warn when files changed", "checkbox", True, "MinimalistAtlasWindow source timestamp watcher", "after Save"),
    SettingDefinition("refresh_cache", "data_loading.show_last_refresh_timestamp", "Show last refresh timestamp", "checkbox", True, "MinimalistAtlasWindow and Settings status text", "after Save"),
    SettingDefinition("read_only_safety", "safety.read_only_mode", "Read-only mode", "locked", True, "read-only window/workbook guard", "always enforced", locked=True),
    SettingDefinition("read_only_safety", "safety.block_workbook_writes", "Block workbook writes", "locked", True, "workbook write guard", "always enforced", "Prevents write paths from modifying workbook sources.", locked=True),
    SettingDefinition("read_only_safety", "safety.disable_status_updates", "Disable status updates", "locked", True, "status update action guard", "always enforced", locked=True),
    SettingDefinition("read_only_safety", "safety.show_source_warnings", "Show source warnings", "checkbox", True, "MinimalistAtlasWindow source-warning display", "after Save"),
    SettingDefinition("read_only_safety", "safety.warn_on_stale_data", "Warn on stale data", "checkbox", True, "validation/source warning filters", "after Save"),
    SettingDefinition("read_only_safety", "safety.warn_on_incomplete_or_conflicting_data", "Warn on incomplete/conflicting data", "checkbox", True, "Fit Check and profile warning filters", "after Save"),
    SettingDefinition("search_navigation", "search.default_action", "Default search action", "segmented", "open_best_match", "MinimalistAtlasWindow.run_search_query", "after Save", options=(SettingOption("open_best_match", "Open best match"), SettingOption("show_result_preview", "Show preview"), SettingOption("ask_when_multiple", "Ask on multiple"))),
    SettingDefinition("search_navigation", "search.prefer_exact_id_matches", "Prefer exact ID matches", "checkbox", True, "MinimalistAtlasWindow.search_entities ranking", "after Save"),
    SettingDefinition("search_navigation", "search.prefer_current_library_type", "Prefer current Library type", "checkbox", True, "MinimalistAtlasWindow.search_entities ranking", "after Save"),
    SettingDefinition("search_navigation", "search.show_partial_matches", "Show partial matches", "checkbox", True, "MinimalistAtlasWindow.search_entities filtering", "after Save"),
    SettingDefinition("search_navigation", "search.allow_alias_search", "Allow aliases", "checkbox", True, "EntitySearchIndex query aliases", "after Save"),
    SettingDefinition("search_navigation", "search.include_eoats", "EOATs", "checkbox", True, "MinimalistAtlasWindow.search_entities scope filter", "after Save"),
    SettingDefinition("search_navigation", "search.include_tools", "Tools", "checkbox", True, "MinimalistAtlasWindow.search_entities scope filter", "after Save"),
    SettingDefinition("search_navigation", "search.include_machines", "Machines", "checkbox", True, "MinimalistAtlasWindow.search_entities scope filter", "after Save"),
    SettingDefinition("search_navigation", "search.include_setup_packets", "Setup Packets", "checkbox", False, "generated setup-packet filename index", "after Save"),
    SettingDefinition("search_navigation", "search.include_reference_docs", "Reference Documents", "checkbox", False, "reference document filename index", "after Save"),
    SettingDefinition("search_navigation", "search.return_to_previous_workflow", "Return to previous workflow", "checkbox", True, "Library profile return navigation", "after Save"),
    SettingDefinition("search_navigation", "search.recent_items_limit", "Recent items limit", "segmented", 15, "recent search/profile history trim", "after Save", options=(SettingOption(5, "5"), SettingOption(10, "10"), SettingOption(15, "15"), SettingOption(25, "25"), SettingOption(50, "50"))),
    SettingDefinition("search_navigation", "search.remember_last_library_tab", "Remember last Library tab", "checkbox", True, "MinimalistLibraryContent default scope restore", "after Save"),
    SettingDefinition("fit_check", "fit_check.compatibility_strictness", "Compatibility strictness", "segmented", "strict", "FitCheckService result classification", "after Save", "Strict requires known compatibility; balanced and loose keep gaps visible with warnings.", options=(SettingOption("strict", "Strict"), SettingOption("balanced", "Balanced"), SettingOption("loose", "Loose"))),
    SettingDefinition("fit_check", "fit_check.always_show_entered_flow_items", "Always show entered items", "checkbox", True, "Fit Check flow row rendering", "after Save"),
    SettingDefinition("fit_check", "fit_check.show_invalid_entries_in_red", "Show invalid entries in red", "checkbox", True, "Fit Check flow row coloring", "after Save"),
    SettingDefinition("fit_check", "fit_check.use_red_connectors_for_incompatible_links", "Red incompatible connectors", "checkbox", True, "Fit Check connector coloring", "after Save"),
    SettingDefinition("fit_check", "fit_check.show_compatible_eoat_alternatives", "Show EOAT alternatives", "checkbox", True, "Fit Check alternatives panel", "after Save"),
    SettingDefinition("fit_check", "fit_check.show_compatible_machine_alternatives", "Show machine alternatives", "checkbox", True, "Fit Check alternatives panel", "after Save"),
    SettingDefinition("fit_check", "fit_check.show_compatible_tool_alternatives", "Show tool alternatives", "checkbox", True, "Fit Check dropdown suggestions", "after Save"),
    SettingDefinition("fit_check", "fit_check.click_alternatives_to_apply", "Click alternatives to apply", "checkbox", True, "Fit Check alternatives panel selection", "after Save"),
    SettingDefinition("fit_check", "fit_check.save_recent_checks", "Save recent fit checks", "checkbox", True, "Fit Check recent history", "after Save"),
    SettingDefinition("fit_check", "fit_check.save_recent_only_when_complete", "Save only when complete", "checkbox", True, "Fit Check recent history eligibility", "after Save"),
    SettingDefinition("fit_check", "fit_check.save_recent_only_when_different", "Save only when different", "checkbox", True, "Fit Check recent history de-dupe", "after Save"),
    SettingDefinition("fit_check", "fit_check.save_recent_after_seconds", "Save after", "segmented", 20, "Fit Check recent-save timer", "after Save", options=(SettingOption(5, "5 sec"), SettingOption(10, "10 sec"), SettingOption(20, "20 sec"), SettingOption(30, "30 sec"), SettingOption(60, "60 sec"))),
    SettingDefinition("fit_check", "fit_check.max_recent_fit_checks", "Max recent fit checks", "segmented", 15, "Fit Check recent history trim", "after Save", options=(SettingOption(5, "5"), SettingOption(10, "10"), SettingOption(15, "15"), SettingOption(25, "25"), SettingOption(50, "50"))),
    SettingDefinition("library", "library.default_tab", "Default Library tab", "segmented", "last_used", "MinimalistLibraryContent initial scope", "next Library view", options=(SettingOption("last_used", "Last used"), SettingOption("eoats", "EOATs"), SettingOption("tools", "Tools"), SettingOption("machines", "Machines"))),
    SettingDefinition("library", "library.eoat_sort", "EOAT default sort", "segmented", "eoat_id_ascending", "Library browse default sort", "next Library refresh", options=(SettingOption("eoat_id_ascending", "ID ascending"), SettingOption("eoat_id_descending", "ID descending"), SettingOption("status", "Status"), SettingOption("type", "Type"), SettingOption("last_updated", "Last updated"))),
    SettingDefinition("library", "library.tool_sort", "Tool default sort", "segmented", "tool_number_ascending", "Library browse default sort", "next Library refresh", options=(SettingOption("tool_number_ascending", "Number asc"), SettingOption("tool_number_descending", "Number desc"), SettingOption("part_name", "Part name"), SettingOption("compatible_machines_count", "Machine count"))),
    SettingDefinition("library", "library.machine_sort", "Machine default sort", "segmented", "machine_number_ascending", "Library browse default sort", "next Library refresh", options=(SettingOption("machine_number_ascending", "Number asc"), SettingOption("machine_number_descending", "Number desc"), SettingOption("robot_type", "Robot type"), SettingOption("current_eoat", "Current EOAT"))),
    SettingDefinition("library", "library.cards_per_page", "Cards per page", "segmented", 24, "LibraryBrowseStateView grid pagination", "next Library refresh", options=(SettingOption(12, "12"), SettingOption(24, "24"), SettingOption(48, "48"))),
    SettingDefinition("library", "library.stable_pagination", "Stable compact pagination", "checkbox", True, "Library pager algorithm", "next Library refresh"),
    SettingDefinition("library", "library.show_previous_next_arrows", "Show previous/next arrows", "checkbox", True, "Library pager buttons", "next Library refresh"),
    SettingDefinition("library", "library.compact_cards_on_small_screens", "Compact cards on smaller screens", "checkbox", True, "Library responsive grid density", "next Library refresh"),
    SettingDefinition("library", "library.use_cached_thumbnails", "Use cached thumbnails", "checkbox", True, "Library thumbnail loading", "after Save"),
    SettingDefinition("library", "library.show_placeholder_while_loading_images", "Show image placeholders", "checkbox", True, "Library thumbnail placeholder rendering", "after Save"),
    SettingDefinition("library", "library.show_copy_icon_on_profile_ids", "Show copy icon beside primary ID", "checkbox", True, "Library record hero copy action", "after Save"),
    SettingDefinition("library", "library.show_copy_to_clipboard_toast", "Show copied-to-clipboard toast", "checkbox", True, "Library copy button toast", "after Save"),
    SettingDefinition("display_accessibility", "app.theme", "Theme", "segmented", "dark", "Minimalist theme tokens", "immediate preview", options=(SettingOption("dark", "Dark"), SettingOption("light", "Light"), SettingOption("system", "System"))),
    SettingDefinition("display_accessibility", "app.accent", "Accent color", "segmented", "atlas_blue", "Minimalist accent tokens", "immediate preview", options=(SettingOption("atlas_blue", "Atlas Blue"), SettingOption("neutral_gray", "Neutral Gray"), SettingOption("high_contrast_blue", "High Contrast Blue"))),
    SettingDefinition("display_accessibility", "app.text_density", "Text density", "segmented", "comfortable", "Settings row density and Library compact density", "immediate preview", options=(SettingOption("comfortable", "Comfortable"), SettingOption("compact", "Compact"), SettingOption("large", "Large"))),
    SettingDefinition("display_accessibility", "app.enhanced_small_text_contrast", "Enhanced small-label contrast", "checkbox", True, "Minimalist theme contrast helper", "after Save"),
    SettingDefinition("display_accessibility", "app.animation_speed", "Animation speed", "segmented", "smooth", "PageTransitionController duration", "after Save", options=(SettingOption("reduced", "Reduced"), SettingOption("standard", "Standard"), SettingOption("smooth", "Smooth"))),
    SettingDefinition("display_accessibility", "app.reduce_motion", "Reduce motion", "checkbox", False, "page transition and widget animation helpers", "after Save"),
    SettingDefinition("setup_packet_pdf", "pdf.include_fit_check_summary", "Fit Check Summary", "checkbox", True, "setup packet PDF section builder", "after Save"),
    SettingDefinition("setup_packet_pdf", "pdf.include_eoat_profile", "EOAT Profile", "checkbox", True, "setup packet PDF section builder", "after Save"),
    SettingDefinition("setup_packet_pdf", "pdf.include_tool_profile", "Tool Profile", "checkbox", True, "setup packet PDF section builder", "after Save"),
    SettingDefinition("setup_packet_pdf", "pdf.include_machine_profile", "Machine Profile", "checkbox", True, "setup packet PDF section builder", "after Save"),
    SettingDefinition("setup_packet_pdf", "pdf.include_compatibility_notes", "Compatibility Notes", "checkbox", True, "setup packet PDF section builder", "after Save"),
    SettingDefinition("setup_packet_pdf", "pdf.include_required_setup_notes", "Required Setup Notes", "checkbox", True, "setup packet PDF section builder", "after Save"),
    SettingDefinition("setup_packet_pdf", "pdf.include_photos", "Photos", "checkbox", True, "setup packet PDF section builder", "after Save"),
    SettingDefinition("setup_packet_pdf", "pdf.include_reference_warnings", "Reference Warnings", "checkbox", True, "setup packet PDF section builder", "after Save"),
    SettingDefinition("setup_packet_pdf", "pdf.preview_before_save", "Preview before save", "checkbox", True, "setup packet preview workflow", "after Save"),
    SettingDefinition("setup_packet_pdf", "pdf.open_in_app", "Open generated PDF in-app", "checkbox", True, "PDF preview/open behavior", "after Save"),
    SettingDefinition("setup_packet_pdf", "pdf.auto_save_if_closed_under_seconds", "Auto-save on quick close", "segmented", 10, "PDFPreviewSession quick-close behavior", "after Save", "Prevents accidental packet loss when the preview window is dismissed quickly.", options=(SettingOption(5, "5 sec"), SettingOption(10, "10 sec"), SettingOption(15, "15 sec"), SettingOption(30, "30 sec"))),
    SettingDefinition("setup_packet_pdf", "pdf.ask_location_when_save_clicked", "Ask location when Save is clicked", "checkbox", True, "PDF save dialog behavior", "after Save"),
    SettingDefinition("setup_packet_pdf", "pdf.reference_footer_locked", "Reference footer", "locked", True, "PDF footer enforcement", "always enforced", locked=True),
    SettingDefinition("setup_packet_pdf", "pdf.reference_footer_text", "Footer text", "locked_text", "For reference only", "PDF footer text", "always enforced", locked=True),
    SettingDefinition("setup_packet_pdf", "pdf.default_file_name_pattern", "File naming pattern", "text", "SetupPacket_Tool-{tool}_Machine-{machine}_EOAT-{eoat}_{date}.pdf", "setup packet PDF output filename", "after Save"),
    SettingDefinition("validation_health", "validation.run_on_startup", "Run validation on startup", "checkbox", True, "MinimalistAtlasWindow startup validation timestamp/report", "next launch"),
    SettingDefinition("validation_health", "validation.show_sidebar_health_badge", "Show data health badge", "checkbox", True, "Settings/Data Health status display", "after Save"),
    SettingDefinition("validation_health", "validation.warning_level_display", "Warning level display", "segmented", "warnings_and_critical", "validation warning filter", "after Save", options=(SettingOption("critical_only", "Critical only"), SettingOption("warnings_and_critical", "Warnings + critical"), SettingOption("all_validation_details", "All details"))),
    SettingDefinition("validation_health", "validation.cleanroom_prefix", "Cleanroom EOAT prefix", "text", "CL-EOAT-", "EOAT ID validation rules", "after Save"),
    SettingDefinition("validation_health", "validation.plant4_prefix", "Plant 4 EOAT prefix", "text", "P4-EOAT-", "EOAT ID validation rules", "after Save"),
    SettingDefinition("validation_health", "validation.check_missing_eoat_ids", "Missing EOAT IDs", "checkbox", True, "validation check filter", "after Save"),
    SettingDefinition("validation_health", "validation.check_duplicate_eoat_ids", "Duplicate EOAT IDs", "checkbox", True, "validation check filter", "after Save"),
    SettingDefinition("validation_health", "validation.check_broken_photo_paths", "Broken photo paths", "checkbox", True, "validation check filter", "after Save"),
    SettingDefinition("validation_health", "validation.check_missing_compatibility_data", "Missing compatibility data", "checkbox", True, "validation check filter", "after Save"),
    SettingDefinition("validation_health", "validation.check_unknown_machine_references", "Unknown machine references", "checkbox", True, "validation check filter", "after Save"),
    SettingDefinition("validation_health", "validation.check_unknown_tool_references", "Unknown tool references", "checkbox", True, "validation check filter", "after Save"),
    SettingDefinition("validation_health", "validation.check_cleanroom_id_format", "Cleanroom ID format", "checkbox", True, "validation check filter", "after Save"),
    SettingDefinition("validation_health", "validation.check_required_profile_fields", "Required profile fields", "checkbox", True, "validation check filter", "after Save"),
    SettingDefinition("reference_documents", "reference_documents.viewer_default", "Default document behavior", "segmented", "open_in_app", "reference document opener", "after Save", options=(SettingOption("open_in_app", "Open in app"), SettingOption("open_externally", "Open externally"), SettingOption("ask_every_time", "Ask every time"))),
    SettingDefinition("reference_documents", "reference_documents.include_in_global_search", "Include in global search", "checkbox", False, "reference document filename index", "after Save"),
    SettingDefinition("reference_documents", "reference_documents.warn_if_missing_or_outdated", "Warn if missing or outdated", "checkbox", True, "reference document validation warnings", "after Save"),
    *(SettingDefinition("reference_documents", f"reference_documents.{key}", title, "path", "", "reference document resolver", "after Save") for key, title in REFERENCE_DOC_SPECS),
    SettingDefinition("diagnostics_support", "diagnostics.activity_log_enabled", "Activity log enabled", "checkbox", True, "core.logging activity event guard", "after Save"),
    SettingDefinition("diagnostics_support", "diagnostics.last_app_launch", "Last app launch", "status", "", "MinimalistAtlasWindow launch timestamp", "automatic"),
    SettingDefinition("diagnostics_support", "diagnostics.last_successful_data_load", "Last successful data load", "status", "", "MinimalistAtlasWindow data-load timestamp", "automatic"),
    SettingDefinition("diagnostics_support", "diagnostics.last_validation", "Last validation", "status", "", "validation run timestamp", "automatic"),
    SettingDefinition("diagnostics_support", "diagnostics.last_pdf_generated", "Last PDF generated", "status", "", "PDF generation timestamp", "automatic"),
    SettingDefinition("diagnostics_support", "diagnostics.last_source_path_change", "Last source path change", "status", "", "Data Sources path changes", "automatic"),
    SettingDefinition("diagnostics_support", "admin.enabled", "Admin protection enabled", "status", True, "Settings page edit gate", "session-only"),
    SettingDefinition(
        "diagnostics_support",
        "admin.logout_after_leaving_settings_seconds",
        "Auto logout after leaving Settings",
        "combo",
        60,
        "Settings page admin grace timer",
        "after Save",
        options=tuple(SettingOption(value, label) for value, label in ADMIN_LOGOUT_TIMEOUT_OPTIONS),
    ),
    SettingDefinition("diagnostics_support", "admin.password_hash_configured", "Admin password configured", "status", False, "local admin_auth.json credential file", "automatic"),
    SettingDefinition("diagnostics_support", "admin.last_admin_sign_in", "Last admin sign-in", "status", "", "Settings page admin session metadata", "automatic"),
)


VISIBLE_SETTINGS_AUDIT: tuple[dict[str, Any], ...] = tuple(
    {
        "section": definition.section,
        "key": definition.key,
        "label": definition.label,
        "control": definition.control,
        "default": definition.default,
        "consumer": definition.consumer,
        "apply": definition.apply,
        "implemented": definition.implemented,
        "visible": definition.visible,
    }
    for definition in SETTINGS_REGISTRY
)
VISIBLE_EDITABLE_SETTING_PATHS: tuple[str, ...] = tuple(
    definition.key
    for definition in SETTINGS_REGISTRY
    if definition.visible and definition.implemented and not definition.locked and definition.control not in {"status", "action"}
)
VISIBLE_RESETTABLE_SETTING_PATHS: tuple[str, ...] = tuple(
    dict.fromkeys(
        definition.key
        for definition in SETTINGS_REGISTRY
        if definition.visible and definition.implemented and definition.control != "status"
    )
)
SECTION_SETTING_PATHS: dict[str, tuple[str, ...]] = {
    spec.key: tuple(
        definition.key
        for definition in SETTINGS_REGISTRY
        if definition.section == spec.key and definition.visible and definition.implemented and definition.control != "status"
    )
    for spec in SECTIONS
}
SETTING_SECTION_BY_PATH: dict[str, str] = {
    definition.key: definition.section
    for definition in SETTINGS_REGISTRY
    if definition.visible and definition.implemented and definition.control != "status"
}
EDITABLE_SECTION_KEYS = frozenset(key for key, paths in SECTION_SETTING_PATHS.items() if paths)


class AtlasMinimalistSettingsPage(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.bundle = None
        self.setObjectName("AtlasMinimalistSettingsPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.settings_content = MinimalistSettingsContent(controller)
        self.shell = AtlasMinimalistShell(controller, self.settings_content)
        layout.addWidget(self.shell)

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle
        self.settings_content.set_bundle(bundle)
        self.shell.set_bundle(bundle)

    def page_shown(self) -> None:
        self.settings_content.page_shown()
        self.shell.close_overlays(immediate=True)
        self.shell.set_active_nav("settings")
        self.shell.top_bar.set_back_visible(False, animated=False)
        self.settings_content.set_bundle(self.bundle)
        self.shell.setFocus(Qt.FocusReason.OtherFocusReason)

    def page_hidden(self) -> None:
        self.settings_content.page_hidden()

    def open_search_overlay(self) -> None:
        self.shell.open_search()

    def show_toast(self, message: str) -> None:
        self.settings_content.show_toast(message)

    def confirm_navigation_away(self) -> bool:
        return self.settings_content.confirm_navigation_away()

    def shutdown_admin_session(self) -> None:
        self.settings_content.shutdown_admin_session()


class MinimalistSettingsContent(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.bundle = None
        self.settings_file = settings_path()
        ensure_default_admin_password()
        self.saved_settings = load_settings(self.settings_file)
        self.draft_settings = deepcopy(self.saved_settings)
        password_configured = admin_password_configured()
        self.saved_settings.setdefault("admin", {})["password_hash_configured"] = password_configured
        self.draft_settings.setdefault("admin", {})["password_hash_configured"] = password_configured
        self._theme_preference = normalize_theme_preference(self._setting_from(self.draft_settings, "app.theme"))
        set_active_minimalist_theme(
            self._theme_preference,
            accent=str(self._setting_from(self.draft_settings, "app.accent") or "atlas_blue"),
            enhanced_small_text_contrast=bool(self._setting_from(self.draft_settings, "app.enhanced_small_text_contrast")),
        )
        self.selected_key = "data_sources"
        self.sidebar_items: dict[str, SettingsSidebarItem] = {}
        self.source_rows: dict[str, DataSourceRow] = {}
        self.setting_rows: dict[str, list[SettingRow]] = {}
        self.source_dirty_rows: dict[str, QWidget] = {}
        self.dirty_sections: set[str] = set()
        self.dirty_keys: set[str] = set()
        self._last_logged_dirty_state: tuple[bool, tuple[str, ...], tuple[str, ...]] | None = None
        self._updating_control = False
        self.admin_active = False
        self._pending_admin_timeout_notice = ""
        self._last_admin_sign_in = str(self._setting_from(self.saved_settings, "admin.last_admin_sign_in") or "")
        self._admin_logout_timer = QTimer(self)
        self._admin_logout_timer.setSingleShot(True)
        self._admin_logout_timer.timeout.connect(self._admin_timeout_elapsed)
        self.setObjectName("MinimalistSettingsContent")
        self.setStyleSheet(settings_page_styles(self._theme_preference))

        self.body_scroll = QScrollArea(self)
        self.body_scroll.setObjectName("SettingsPageScroll")
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setWidgetResizable(False)
        self.body = QWidget()
        self.body.setObjectName("SettingsBody")
        self.body_scroll.setWidget(self.body)

        self.title = QLabel("Settings", self.body)
        self.title.setObjectName("SettingsPageTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle = QLabel("Configure data sources, app behavior, and preferences.", self.body)
        self.subtitle.setObjectName("SettingsPageSubtitle")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.sidebar = GlassPanel(self.body, radius=8, streaks=True)
        apply_glass_theme(self.sidebar, "settings_sidebar", self._theme_preference)
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(16, 14, 16, 14)
        self.sidebar_layout.setSpacing(7)
        self._build_sidebar()

        self.main_panel = GlassPanel(self.body, radius=8, streaks=True)
        apply_glass_theme(self.main_panel, "settings_main", self._theme_preference)
        self.main_panel_layout = QVBoxLayout(self.main_panel)
        self.main_panel_layout.setContentsMargins(22, 18, 22, 18)
        self.main_panel_layout.setSpacing(12)
        self.panel_header = SettingsPanelHeader()
        self.main_panel_layout.addWidget(self.panel_header)
        self.main_scroll = QScrollArea()
        self.main_scroll.setObjectName("SettingsMainScroll")
        self.main_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.main_scroll.setWidgetResizable(True)
        self.main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.main_body = QWidget()
        self.main_body.setObjectName("SettingsMainBody")
        self.main_body.setMinimumWidth(0)
        self.main_layout = QVBoxLayout(self.main_body)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(9)
        self.main_scroll.setWidget(self.main_body)
        self.main_panel_layout.addWidget(self.main_scroll, 1)

        self.bottom_bar = GlassPanel(self.body, radius=0)
        apply_glass_theme(self.bottom_bar, "settings_bottom", self._theme_preference)
        self.bottom_layout = QHBoxLayout(self.bottom_bar)
        self.bottom_layout.setContentsMargins(32, 9, 32, 9)
        self.bottom_layout.setSpacing(12)
        self.export_button = settings_button("Export Settings", "ghost", "external")
        self.export_button.clicked.connect(self.export_settings)
        self.admin_button = settings_button("Admin", "ghost", "status")
        self.admin_button.clicked.connect(self.open_admin_overlay)
        self.admin_status_label = QLabel("Settings Locked")
        self.admin_status_label.setObjectName("SettingsAdminPill")
        self.admin_status_label.setProperty("active", False)
        self.unsaved_label = DirtyIndicator()
        self.unsaved_label.hide()
        self.reload_button = settings_button("Reload Data", "ghost", "swap")
        self.reload_button.clicked.connect(self.reload_data)
        self.reset_section_button = settings_button("Reset Section", "ghost", "swap")
        self.reset_section_button.clicked.connect(self.reset_current_section)
        self.save_button = settings_button("Save Settings", "primary", "save")
        self.save_button.clicked.connect(self.save_current_settings)
        self.bottom_layout.addWidget(self.export_button)
        self.bottom_layout.addWidget(self.admin_button)
        self.bottom_layout.addWidget(self.admin_status_label)
        self.bottom_layout.addStretch(1)
        self.bottom_layout.addWidget(self.unsaved_label)
        self.bottom_layout.addSpacing(12)
        self.bottom_layout.addWidget(self.reload_button)
        self.bottom_layout.addWidget(self.reset_section_button)
        self.bottom_layout.addWidget(self.save_button)

        self.toast = MinimalistToast(self)
        self.toast.apply_theme_preference(self._theme_preference)
        self.toast.hide()
        self._render_selected_section()
        self._sync_dirty_state()

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle
        self._refresh_dynamic_rows()

    def show_toast(self, message: str) -> None:
        self.toast.show_message(message)

    def page_shown(self) -> None:
        if self._admin_logout_timer.isActive():
            self._admin_logout_timer.stop()
        self._sync_admin_state()
        if self._pending_admin_timeout_notice:
            message = self._pending_admin_timeout_notice
            self._pending_admin_timeout_notice = ""
            self.show_toast(message)

    def page_hidden(self) -> None:
        if self.admin_active:
            if self._admin_logout_timer.isActive():
                self._admin_logout_timer.stop()
            seconds = self._admin_logout_seconds()
            if seconds == 0:
                if self._end_admin_session(confirm_unsaved=False, notify=False, discard_unsaved=True):
                    self._show_admin_session_notice("Admin session ended.", prefer_controller=True)
                return
            self._admin_logout_timer.start(seconds * 1000)

    def _admin_logout_seconds(self) -> int:
        try:
            value = int(self._setting_from(self.saved_settings, "admin.logout_after_leaving_settings_seconds"))
        except (TypeError, ValueError):
            value = 60
        return value if value in ADMIN_LOGOUT_TIMEOUT_SECONDS else 60

    def _admin_logout_label(self, seconds: int | None = None) -> str:
        value = self._admin_logout_seconds() if seconds is None else int(seconds)
        return ADMIN_LOGOUT_TIMEOUT_LABELS.get(value, "1 min")

    def _sync_admin_state(self, *, rerender: bool = False) -> None:
        if hasattr(self, "admin_button"):
            self.admin_button.setText("Admin: Active" if self.admin_active else "Admin")
        if hasattr(self, "admin_status_label"):
            self.admin_status_label.setText("Admin Active" if self.admin_active else "Settings Locked")
            self.admin_status_label.setProperty("active", self.admin_active)
            self.admin_status_label.style().unpolish(self.admin_status_label)
            self.admin_status_label.style().polish(self.admin_status_label)
        if hasattr(self, "panel_header"):
            self.panel_header.set_admin_state(self.admin_active, self.selected_key in EDITABLE_SECTION_KEYS)
        if rerender:
            self._render_selected_section()

    def _admin_timeout_elapsed(self) -> None:
        if not self.admin_active:
            return
        discarded = self._has_unsaved_settings()
        if discarded:
            self._discard_unsaved_changes()
        self.admin_active = False
        self._sync_admin_state(rerender=True)
        self._sync_dirty_state()
        self._pending_admin_timeout_notice = (
            "Admin session ended. Unsaved settings were discarded." if discarded else "Admin session ended."
        )

    def _has_unsaved_settings(self) -> bool:
        return bool(self.dirty_keys or self._calculate_dirty_keys())

    def _show_admin_session_notice(self, message: str, *, prefer_controller: bool = False) -> None:
        if prefer_controller:
            show_status = getattr(self.controller, "show_status", None)
            if callable(show_status):
                show_status(message)
                return
        if self.isVisible():
            self.show_toast(message)
            return
        self._pending_admin_timeout_notice = message

    def _start_admin_session(self) -> None:
        self.admin_active = True
        if self._admin_logout_timer.isActive():
            self._admin_logout_timer.stop()
        timestamp = datetime.now().isoformat(timespec="seconds")
        self._last_admin_sign_in = timestamp
        for target in (self.saved_settings, self.draft_settings):
            target.setdefault("admin", {})["last_admin_sign_in"] = timestamp
            target.setdefault("admin", {})["password_hash_configured"] = True
        try:
            save_settings(self.saved_settings, self.settings_file)
        except OSError:
            LOGGER.debug("Could not persist admin sign-in timestamp", exc_info=True)
        self._sync_admin_state(rerender=True)
        self._sync_dirty_state()
        self.show_toast("Admin access enabled.")

    def sign_out_admin(self) -> bool:
        return self._end_admin_session(confirm_unsaved=True)

    def _end_admin_session(self, *, confirm_unsaved: bool, notify: bool = True, discard_unsaved: bool = False) -> bool:
        if not self.admin_active:
            return True
        if self._admin_logout_timer.isActive():
            self._admin_logout_timer.stop()
        if confirm_unsaved and self._has_unsaved_settings():
            action = show_settings_confirmation(
                self,
                "Unsaved Settings",
                "You have unsaved settings changes. Save them before ending the admin session?",
                (
                    DialogAction("cancel", "Cancel", "secondary"),
                    DialogAction("discard", "Discard", "danger"),
                    DialogAction("save", "Save", "primary"),
                ),
                default_action="save",
                cancel_action="cancel",
            )
            if action == "cancel":
                return False
            if action == "save" and not self.save_current_settings():
                return False
            if action == "discard":
                self._discard_unsaved_changes()
        elif discard_unsaved and self._has_unsaved_settings():
            self._discard_unsaved_changes()
        self.admin_active = False
        self._sync_admin_state(rerender=True)
        self._sync_dirty_state()
        if notify:
            self.show_toast("Admin session ended.")
        return True

    def shutdown_admin_session(self) -> None:
        if self._admin_logout_timer.isActive():
            self._admin_logout_timer.stop()
        self._end_admin_session(confirm_unsaved=False, notify=False, discard_unsaved=True)

    def open_admin_overlay(self) -> None:
        if self.admin_active:
            self.sign_out_admin()
            return
        dialog = AdminAccessDialog(self, theme_preference=self._theme_preference)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._start_admin_session()

    def close_search_overlays(self) -> None:
        return None

    def apply_theme_preference(self, preference: str | None) -> None:
        self._theme_preference = normalize_theme_preference(preference)
        set_active_minimalist_theme(
            self._theme_preference,
            accent=str(self._setting("app.accent") or "atlas_blue"),
            enhanced_small_text_contrast=bool(self._setting("app.enhanced_small_text_contrast")),
        )
        self.setStyleSheet(settings_page_styles(self._theme_preference))
        apply_glass_theme(self.sidebar, "settings_sidebar", self._theme_preference)
        apply_glass_theme(self.main_panel, "settings_main", self._theme_preference)
        apply_glass_theme(self.bottom_bar, "settings_bottom", self._theme_preference)
        self.toast.apply_theme_preference(self._theme_preference)
        for item in self.sidebar_items.values():
            item.apply_theme_preference(self._theme_preference)
        self.panel_header.apply_theme_preference(self._theme_preference)
        self._sync_admin_state()
        self._refresh_dynamic_rows()
        self.update()

    def _apply_draft_theme(self, *, rerender: bool = False, notify_controller: bool = True) -> None:
        preference = normalize_theme_preference(self._setting("app.theme"))
        self.apply_theme_preference(preference)
        preview = getattr(self.controller, "preview_minimalist_theme", None)
        if notify_controller and callable(preview):
            preview(preference, accent=str(self._setting("app.accent") or "atlas_blue"), enhanced_small_text_contrast=bool(self._setting("app.enhanced_small_text_contrast")))
        if rerender:
            self._render_selected_section()

    def _discard_unsaved_changes(self) -> None:
        self.draft_settings = deepcopy(self.saved_settings)
        self._apply_draft_theme(rerender=True)
        self._sync_dirty_state()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = self.width()
        height = self.height()
        self.body_scroll.setGeometry(self.rect())
        self.body.resize(width, max(height, 820))
        title_y = 108
        self.title.setGeometry((width - 620) // 2, title_y, 620, 44)
        self.subtitle.setGeometry((width - 780) // 2, title_y + 42, 780, 22)
        left_margin = 26
        right_margin = 60
        content_top = title_y + 76
        bar_height = 70
        content_bottom = max(content_top + 520, height - bar_height - 10)
        sidebar_width = 286
        gutter = 14
        main_x = left_margin + sidebar_width + gutter
        main_width = max(720, width - main_x - right_margin)
        panel_height = max(520, content_bottom - content_top)
        self.sidebar.setGeometry(left_margin, content_top, sidebar_width, panel_height)
        self.main_panel.setGeometry(main_x, content_top, main_width, panel_height)
        self.bottom_bar.setGeometry(0, max(height - bar_height, content_top + panel_height + 8), width, bar_height)
        toast_width = min(720, max(260, width - 90))
        self.toast.setGeometry((width - toast_width) // 2, max(90, height - 150), toast_width, 72)

    def _build_sidebar(self) -> None:
        heading = QLabel("Settings Sections")
        heading.setObjectName("SettingsSidebarTitle")
        self.sidebar_layout.addWidget(heading)
        for spec in SECTIONS:
            item = SettingsSidebarItem(spec)
            item.clicked.connect(self.select_section)
            self.sidebar_items[spec.key] = item
            self.sidebar_layout.addWidget(item)
        self.sidebar_layout.addStretch(1)

    def select_section(self, key: str) -> None:
        if key not in self.sidebar_items:
            return
        if key == self.selected_key:
            return
        self.selected_key = key
        self._render_selected_section()
        self._sync_dirty_state()

    def _render_selected_section(self) -> None:
        clear_layout(self.main_layout)
        self.setting_rows = {}
        self.source_dirty_rows = {}
        spec = self._selected_spec()
        self.panel_header.set_section(spec, self._status_for_section(spec.key))
        self.panel_header.set_dirty(spec.key in self.dirty_sections)
        self.panel_header.set_admin_state(self.admin_active, spec.key in EDITABLE_SECTION_KEYS)
        for key, item in self.sidebar_items.items():
            item.set_active(key == self.selected_key)
            item.set_dirty(key in self.dirty_sections)
        renderer = getattr(self, f"_render_{self.selected_key}", self._render_about)
        renderer()
        self.main_layout.addStretch(1)

    def _selected_spec(self) -> SectionSpec:
        return next((spec for spec in SECTIONS if spec.key == self.selected_key), SECTIONS[0])

    def _status_for_section(self, key: str) -> tuple[str, str] | None:
        if key == "data_sources":
            statuses = [validate_source_path(self._effective_source_path(spec), spec) for spec in SOURCE_SPECS]
            if all(status[0] == "Connected" for status in statuses):
                return "All Sources Connected", "good"
            if any(status[0] == "Not Configured" for status in statuses):
                return "Missing Sources", "warn"
            return "Needs Attention", "warn"
        if key == "read_only_safety":
            return "Read-Only Enabled", "good"
        if key == "validation_health":
            warnings = len(getattr(self.bundle, "warnings", ()) or ())
            return (f"{warnings} Warnings Indexed" if warnings else "No Indexed Warnings", "warn" if warnings else "good")
        if key == "about":
            return "v0.9.0 Read-Only", "good"
        return None

    def _render_data_sources(self) -> None:
        self.main_layout.addWidget(
            info_card(
                "Read-only source access",
                "EOAT Atlas validates and opens source locations, but it does not modify source workbooks, folders, or photos.",
                "good",
            )
        )
        workbook_section = CollapsibleSection("Workbook Sources", "Excel workbooks used for EOAT, press, and robot context.", expanded=True)
        folder_section = CollapsibleSection("Folder Sources", "Folder roots used for photos, exports, and reference material.", expanded=True)
        health_section = CollapsibleSection("Source Health", "Validation is read-only and checks existence, type, extension, and accessibility.", expanded=False)
        self.source_rows = {}
        for spec in SOURCE_SPECS:
            row = DataSourceRow(spec, self._effective_source_path(spec), self._last_read_text(), parent=self)
            row.change_requested.connect(self.change_source_path)
            row.open_requested.connect(self.open_source_path)
            row.validate_requested.connect(self.validate_source)
            self.source_rows[spec.key] = row
            self.source_dirty_rows[f"paths.{spec.key}"] = row
            row.set_admin_active(self.admin_active)
            row.set_dirty(f"paths.{spec.key}" in self.dirty_keys)
            target_layout = folder_section.body_layout if spec.kind == "folder" else workbook_section.body_layout
            target_layout.addWidget(row)
        health_section.body_layout.addWidget(self._source_health_summary())
        self.main_layout.addWidget(workbook_section)
        self.main_layout.addWidget(folder_section)
        self.main_layout.addWidget(health_section)

    def _render_refresh_cache(self) -> None:
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Refresh Behavior",
                "Choose when EOAT Atlas reloads source workbooks and folders.",
                (
                    self._setting_row("Refresh on app launch", "", self._check("data_loading.refresh_on_launch")),
                    self._setting_row("Manual refresh only", "Disables automatic refresh during controlled review sessions.", self._check("data_loading.manual_refresh_only")),
                    self._setting_row("Auto-refresh enabled", "", self._check("data_loading.auto_refresh_enabled")),
                    self._setting_row("Auto-refresh interval", "", self._segmented("data_loading.auto_refresh_minutes", ((5, "5 min"), (10, "10 min"), (15, "15 min"), (30, "30 min"), (60, "60 min")))),
                    self._setting_row("Detect file changes", "", self._check("data_loading.detect_file_changes")),
                    self._setting_row("Last refresh", "", value_label(self._last_read_text())),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Cache Behavior",
                "Local app cache only. Source files are never modified.",
                (
                    self._setting_row("Cache last good data", "Keeps the most recent successful read visible if a source file is temporarily unavailable.", self._check("data_loading.cache_last_good_data")),
                    self._setting_row("Cache photo thumbnails", "", self._check("data_loading.cache_photo_thumbnails")),
                    self._setting_row("Show cached-data warning", "", self._check("data_loading.show_cached_data_warning")),
                    self._setting_row("Clear cached thumbnails", "", self._admin_action_button("Clear Thumbnails", self.clear_thumbnail_cache)),
                    self._setting_row("Clear read-only data cache", "", self._admin_action_button("Clear Data Cache", self.clear_data_cache)),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "File Change Warnings",
                "Notify the user when source files changed after the last successful load.",
                (
                    self._setting_row("Warn when files changed", "", self._check("data_loading.warn_when_files_changed")),
                    self._setting_row("Show last refresh timestamp", "", self._check("data_loading.show_last_refresh_timestamp")),
                ),
            )
        )

    def _render_read_only_safety(self) -> None:
        self.main_layout.addWidget(
            info_card(
                "EOAT Atlas is read-only",
                "EOAT Atlas currently reads source files only. It does not write to the EOAT tracker, Press Capacity workbook, Robot workbook, or photo folders.",
                "good",
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Locked Safety Controls",
                "These controls are enforced for the current read-only release.",
                (
                    self._setting_row("Read-only mode", "", locked_value_chip("Locked On")),
                    self._setting_row("Block workbook writes", "Prevents any write path from modifying workbook sources.", locked_value_chip("Locked On")),
                    self._setting_row("Disable status updates", "", locked_value_chip("Locked On")),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Warnings",
                "User-facing source and data-health warnings.",
                (
                    self._setting_row("Show source warnings", "", self._check("safety.show_source_warnings")),
                    self._setting_row("Warn on stale data", "", self._check("safety.warn_on_stale_data")),
                    self._setting_row("Warn on incomplete/conflicting data", "", self._check("safety.warn_on_incomplete_or_conflicting_data")),
                ),
            )
        )

    def _render_search_navigation(self) -> None:
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Global Search Behavior",
                "Tune how the search overlay resolves records and ambiguous matches.",
                (
                    self._setting_row(
                        "Default search action",
                        "Choose what happens when a search has a strong match.",
                        self._segmented(
                            "search.default_action",
                            (
                                ("open_best_match", "Open best match"),
                                ("show_result_preview", "Show preview"),
                                ("ask_when_multiple", "Ask on multiple"),
                            ),
                        ),
                    ),
                    self._setting_row("Prefer exact ID matches", "", self._check("search.prefer_exact_id_matches")),
                    self._setting_row("Prefer current Library type", "", self._check("search.prefer_current_library_type")),
                    self._setting_row("Show partial matches", "", self._check("search.show_partial_matches")),
                    self._setting_row("Allow aliases", "", self._check("search.allow_alias_search")),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Search Scope",
                "Records included in global search.",
                (
                    self._setting_row("EOATs", "", self._check("search.include_eoats")),
                    self._setting_row("Tools", "", self._check("search.include_tools")),
                    self._setting_row("Machines", "", self._check("search.include_machines")),
                    self._setting_row("Setup Packets", "", self._check("search.include_setup_packets")),
                    self._setting_row("Reference Documents", "", self._check("search.include_reference_docs")),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Navigation Memory",
                "Preserve the context a user came from when opening profiles.",
                (
                    self._setting_row("Return to previous workflow", "", self._check("search.return_to_previous_workflow")),
                    self._setting_row("Recent items limit", "", self._segmented("search.recent_items_limit", ((5, "5"), (10, "10"), (15, "15"), (25, "25"), (50, "50")))),
                    self._setting_row("Remember last Library tab", "", self._check("search.remember_last_library_tab")),
                ),
            )
        )

    def _render_fit_check(self) -> None:
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Compatibility Strictness",
                "Adjust how conservative compatibility results should be.",
                (
                    self._setting_row(
                        "Compatibility result strictness",
                        "Strict is the default for read-only engineering review.",
                        self._segmented("fit_check.compatibility_strictness", (("strict", "Strict"), ("balanced", "Balanced"), ("loose", "Loose"))),
                    ),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Flow Row Display",
                "Keep entered EOAT, Tool, and Machine values visible while checking fit.",
                (
                    self._setting_row("Always show entered items", "", self._check("fit_check.always_show_entered_flow_items")),
                    self._setting_row("Show invalid entries in red", "", self._check("fit_check.show_invalid_entries_in_red")),
                    self._setting_row("Red incompatible connectors", "", self._check("fit_check.use_red_connectors_for_incompatible_links")),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Alternative Options",
                "Show compatible substitutes and allow quick application.",
                (
                    self._setting_row("Show EOAT alternatives", "", self._check("fit_check.show_compatible_eoat_alternatives")),
                    self._setting_row("Show machine alternatives", "", self._check("fit_check.show_compatible_machine_alternatives")),
                    self._setting_row("Show tool alternatives", "", self._check("fit_check.show_compatible_tool_alternatives")),
                    self._setting_row("Click alternatives to apply", "", self._check("fit_check.click_alternatives_to_apply")),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Recent Fit Checks",
                "Control how recent checks are remembered.",
                (
                    self._setting_row("Save recent fit checks", "", self._check("fit_check.save_recent_checks")),
                    self._setting_row("Save only when complete", "", self._check("fit_check.save_recent_only_when_complete")),
                    self._setting_row("Save only when different", "", self._check("fit_check.save_recent_only_when_different")),
                    self._setting_row("Save after", "", self._segmented("fit_check.save_recent_after_seconds", ((5, "5 sec"), (10, "10 sec"), (20, "20 sec"), (30, "30 sec"), (60, "60 sec")))),
                    self._setting_row("Max recent fit checks", "", self._segmented("fit_check.max_recent_fit_checks", ((5, "5"), (10, "10"), (15, "15"), (25, "25"), (50, "50")))),
                ),
            )
        )

    def _render_library(self) -> None:
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Defaults",
                "Control the first Library view and default ordering.",
                (
                    self._setting_row(
                        "Default Library tab",
                        "",
                        self._segmented("library.default_tab", (("last_used", "Last used"), ("eoats", "EOATs"), ("tools", "Tools"), ("machines", "Machines"))),
                    ),
                    self._setting_row("EOAT default sort", "", self._segmented("library.eoat_sort", (("eoat_id_ascending", "ID ascending"), ("eoat_id_descending", "ID descending"), ("status", "Status"), ("type", "Type"), ("last_updated", "Last updated")))),
                    self._setting_row("Tool default sort", "", self._segmented("library.tool_sort", (("tool_number_ascending", "Number asc"), ("tool_number_descending", "Number desc"), ("part_name", "Part name"), ("compatible_machines_count", "Machine count")))),
                    self._setting_row("Machine default sort", "", self._segmented("library.machine_sort", (("machine_number_ascending", "Number asc"), ("machine_number_descending", "Number desc"), ("robot_type", "Robot type"), ("current_eoat", "Current EOAT")))),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Pagination",
                "Control Library grid paging.",
                (
                    self._setting_row("Cards per page", "", self._segmented("library.cards_per_page", ((12, "12"), (24, "24"), (48, "48")))),
                    self._setting_row("Stable compact pagination", "", self._check("library.stable_pagination")),
                    self._setting_row("Show previous/next arrows", "", self._check("library.show_previous_next_arrows")),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Cards and Profiles",
                "Image and profile affordances.",
                (
                    self._setting_row("Compact cards on smaller screens", "", self._check("library.compact_cards_on_small_screens")),
                    self._setting_row("Use cached thumbnails", "", self._check("library.use_cached_thumbnails")),
                    self._setting_row("Show image placeholders", "", self._check("library.show_placeholder_while_loading_images")),
                    self._setting_row("Show copy icon beside primary ID", "", self._check("library.show_copy_icon_on_profile_ids")),
                    self._setting_row("Show copied-to-clipboard toast", "", self._check("library.show_copy_to_clipboard_toast")),
                ),
            )
        )

    def _render_display_accessibility(self) -> None:
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Theme",
                "Theme and accent are constrained to production-safe Atlas options.",
                (
                    self._setting_row("Theme", "", self._segmented("app.theme", (("dark", "Dark"), ("light", "Light"), ("system", "System")))),
                    self._setting_row("Accent color", "", self._segmented("app.accent", (("atlas_blue", "Atlas Blue"), ("neutral_gray", "Neutral Gray"), ("high_contrast_blue", "High Contrast Blue")))),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Readability",
                "Tune density and contrast for shop-floor displays.",
                (
                    self._setting_row("Text density", "", self._segmented("app.text_density", (("comfortable", "Comfortable"), ("compact", "Compact"), ("large", "Large")))),
                    self._setting_row("Enhanced small-label contrast", "", self._check("app.enhanced_small_text_contrast")),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Motion",
                "Keep page transitions subtle and accessible.",
                (
                    self._setting_row("Animation speed", "", self._segmented("app.animation_speed", (("reduced", "Reduced"), ("standard", "Standard"), ("smooth", "Smooth")))),
                    self._setting_row("Reduce motion", "", self._check("app.reduce_motion")),
                ),
            )
        )

    def _render_setup_packet_pdf(self) -> None:
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Default Packet Sections",
                "Choose read-only information included in generated setup packets.",
                (
                    self._setting_row("Fit Check Summary", "", self._check("pdf.include_fit_check_summary")),
                    self._setting_row("EOAT Profile", "", self._check("pdf.include_eoat_profile")),
                    self._setting_row("Tool Profile", "", self._check("pdf.include_tool_profile")),
                    self._setting_row("Machine Profile", "", self._check("pdf.include_machine_profile")),
                    self._setting_row("Compatibility Notes", "", self._check("pdf.include_compatibility_notes")),
                    self._setting_row("Required Setup Notes", "", self._check("pdf.include_required_setup_notes")),
                    self._setting_row("Photos", "", self._check("pdf.include_photos")),
                    self._setting_row("Reference Warnings", "", self._check("pdf.include_reference_warnings")),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Save and Preview Behavior",
                "Control preview and save behavior for generated PDFs.",
                (
                    self._setting_row("Preview before save", "", self._check("pdf.preview_before_save")),
                    self._setting_row("Open generated PDF in-app", "", self._check("pdf.open_in_app")),
                    self._setting_row("Auto-save on quick close", "Prevents accidental packet loss when the preview window is dismissed quickly.", self._segmented("pdf.auto_save_if_closed_under_seconds", ((5, "5 sec"), (10, "10 sec"), (15, "15 sec"), (30, "30 sec")))),
                    self._setting_row("Ask location when Save is clicked", "", self._check("pdf.ask_location_when_save_clicked")),
                ),
            )
        )
        output_spec = next(spec for spec in SOURCE_SPECS if spec.key == "output_folder")
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Footer and Naming",
                "The reference footer is locked for read-only packets.",
                (
                    self._setting_row("Reference footer", "", locked_value_chip("Locked On")),
                    self._setting_row("Footer text", "", value_label(str(self._setting("pdf.reference_footer_text") or "For reference only"))),
                    self._setting_row("File naming pattern", "", self._line_edit("pdf.default_file_name_pattern", minimum_width=420)),
                    self._setting_row(
                        "Output folder",
                        "",
                        path_action_widget(
                            str(self._effective_source_path(output_spec)),
                            lambda: self.change_source_path("output_folder"),
                            lambda: self.open_source_path("output_folder"),
                            change_enabled=self.admin_active,
                            setting_path="paths.output_folder",
                        ),
                    ),
                ),
            )
        )

    def _render_validation_health(self) -> None:
        warnings = len(getattr(self.bundle, "warnings", ()) or ())
        errors = 0
        self.main_layout.addWidget(
            validation_summary_card(
                self._setting("diagnostics.last_validation") or self._last_read_text(),
                errors,
                warnings,
                self.run_validation_now,
                self.view_validation_report,
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Startup Validation",
                "Control data-health checks and where validation status is visible.",
                (
                    self._setting_row("Run validation on startup", "", self._check("validation.run_on_startup")),
                    self._setting_row("Show data health badge", "", self._check("validation.show_sidebar_health_badge")),
                    self._setting_row(
                        "Warning level display",
                        "Choose how much validation detail is shown.",
                        self._segmented(
                            "validation.warning_level_display",
                            (
                                ("critical_only", "Critical only"),
                                ("warnings_and_critical", "Warnings + critical"),
                                ("all_validation_details", "All details"),
                            ),
                        ),
                    ),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "ID Rules",
                "Prefixes used for EOAT ID validation.",
                (
                    self._setting_row("Cleanroom EOAT prefix", "", self._line_edit("validation.cleanroom_prefix")),
                    self._setting_row("Plant 4 EOAT prefix", "", self._line_edit("validation.plant4_prefix")),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Validation Checks",
                "Checks run against source data without modifying source workbooks.",
                tuple(
                    self._setting_row(title, description, self._check(path))
                    for title, description, path in (
                        ("Missing EOAT IDs", "", "validation.check_missing_eoat_ids"),
                        ("Duplicate EOAT IDs", "", "validation.check_duplicate_eoat_ids"),
                        ("Broken photo paths", "", "validation.check_broken_photo_paths"),
                        ("Missing compatibility data", "", "validation.check_missing_compatibility_data"),
                        ("Unknown machine references", "", "validation.check_unknown_machine_references"),
                        ("Unknown tool references", "", "validation.check_unknown_tool_references"),
                        ("Cleanroom ID format", "", "validation.check_cleanroom_id_format"),
                        ("Required profile fields", "", "validation.check_required_profile_fields"),
                    )
                ),
            )
        )

    def _render_reference_documents(self) -> None:
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Document Viewer",
                "Choose how guideline and checklist references open.",
                (
                    self._setting_row(
                        "Default document behavior",
                        "",
                        self._segmented(
                            "reference_documents.viewer_default",
                            (("open_in_app", "Open in app"), ("open_externally", "Open externally"), ("ask_every_time", "Ask every time")),
                        ),
                    ),
                    self._setting_row("Include in global search", "", self._check("reference_documents.include_in_global_search")),
                    self._setting_row("Warn if missing or outdated", "", self._check("reference_documents.warn_if_missing_or_outdated")),
                ),
            )
        )
        links = CollapsibleSection("Reference Links", "Guidelines, PM checklists, training, and process binder references.", expanded=True)
        for key, title in REFERENCE_DOC_SPECS:
            links.body_layout.addWidget(self._reference_doc_row(key, title))
        self.main_layout.addWidget(links)

    def _render_diagnostics_support(self) -> None:
        gateway_metrics = getattr(self.bundle, "metrics", {})
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Activity Log",
                "Recent local app activity and diagnostic timestamps.",
                (
                    self._setting_row(
                        "Active data backend",
                        "Development migration diagnostic; production remains legacy.",
                        value_label(
                            str(getattr(self.bundle, "metrics", {}).get("backend") or os.getenv("EOAT_ATLAS_DATA_BACKEND", "legacy"))
                        ),
                    ),
                    self._setting_row("Environment", "Write authority is never selected from this page.", value_label(str(gateway_metrics.get("environment") or os.getenv("EOAT_ATLAS_ENVIRONMENT", "production")))),
                    self._setting_row("Permanent writes", "Enabled only by explicit development configuration.", value_label("Enabled" if gateway_metrics.get("writes_enabled", os.getenv("EOAT_ATLAS_WRITES_ENABLED", "false").casefold() in {"1", "true", "yes", "on"}) else "Disabled")),
                    self._setting_row("Authenticated identity", "Development identity; secrets are never displayed.", value_label(str(gateway_metrics.get("identity") or os.getenv("EOAT_ATLAS_DEV_IDENTITY", "Not configured")))),
                    self._setting_row("Role", "Server authorization role for the current development identity.", value_label(str(gateway_metrics.get("role") or "Not reported"))),
                    self._setting_row("API version", "Reported by the compatible API/cache snapshot.", value_label(str(getattr(self.bundle, "metrics", {}).get("api_version") or "1.1.0"))),
                    self._setting_row("Schema revision", "Required for write compatibility.", value_label(str(getattr(self.bundle, "metrics", {}).get("schema_revision") or "20260714_0003"))),
                    self._setting_row("Application instance", "Stable client UUID; not the computer name.", value_label(str(gateway_metrics.get("application_instance_id") or os.getenv("EOAT_ATLAS_INSTANCE_ID", "Not configured")))),
                    self._setting_row("Last successful write", "Server-confirmed write timestamp.", value_label(str(gateway_metrics.get("last_successful_write") or "Not recorded"))),
                    self._setting_row("Last write request ID", "Correlation identifier only; no credentials are displayed.", value_label(str(gateway_metrics.get("last_write_request_id") or "Not recorded"))),
                    self._setting_row("Last conflict", "Most recent optimistic-concurrency conflict.", value_label(str(gateway_metrics.get("last_conflict") or "None"))),
                    self._setting_row("Last server failure", "Most recent normalized server failure.", value_label(str(gateway_metrics.get("last_server_failure") or "None"))),
                    self._setting_row("Cache status", "Disposable read cache state.", value_label(str(gateway_metrics.get("cache_status") or "Not reported"))),
                    self._setting_row("Change-feed cursor", "Last committed local change cursor.", value_label(str(gateway_metrics.get("last_change_cursor", 0)))),
                    self._setting_row("Activity log enabled", "", self._check("diagnostics.activity_log_enabled")),
                    self._setting_row("Last app launch", "Recorded at application startup.", value_label(self._setting("diagnostics.last_app_launch") or "Not recorded")),
                    self._setting_row("Last successful data load", "Most recent successful read-only data load.", value_label(self._setting("diagnostics.last_successful_data_load") or self._last_read_text())),
                    self._setting_row("Last validation", "Most recent validation run.", value_label(self._setting("diagnostics.last_validation") or "Not recorded")),
                    self._setting_row("Last PDF generated", "Most recent setup packet generated.", value_label(self._setting("diagnostics.last_pdf_generated") or "Not recorded")),
                    self._setting_row("Last source path change", "Most recent Data Sources path change.", value_label(self._setting("diagnostics.last_source_path_change") or "Not recorded")),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Tools",
                "Troubleshoot settings, logs, and local caches.",
                (
                    self._setting_row("Open Logs Folder", "Open the local project logs folder.", action_button("Open Logs", self.open_logs_folder)),
                    self._setting_row("Export Diagnostic Bundle", "Export settings, paths, app version, and recent diagnostics.", self._admin_action_button("Export Bundle", self.export_diagnostic_bundle)),
                    self._setting_row("Clear App Cache", "Clear local in-memory Atlas data cache.", self._admin_action_button("Clear Cache", self.clear_data_cache)),
                    self._setting_row("Reload Settings File", "Discard unsaved edits and reload the settings JSON.", action_button("Reload Settings", self.reload_settings_file)),
                ),
            )
        )
        defaults_status = custom_defaults_status(settings_file=self.settings_file)
        default_text = "Custom defaults set" if defaults_status.get("configured") else "Factory defaults"
        updated_text = format_timestamp(str(defaults_status.get("updated_at") or "")) if defaults_status.get("updated_at") else "Not set"
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Admin Access",
                "Settings edits are locked until an admin signs in.",
                (
                    self._setting_row("Admin status", "", value_label("Active" if self.admin_active else "Locked")),
                    self._setting_row("Auto logout after leaving Settings", "", self._admin_logout_timeout_combo()),
                    self._setting_row("Last admin sign-in", "", value_label(self._last_admin_sign_in or "Not recorded")),
                    self._setting_row("Admin password", "", value_label("Configured" if admin_password_configured() else "Not configured")),
                    self._setting_row("Sign out", "", self._admin_action_button("Sign Out", self.sign_out_admin, variant="small", glyph="status")),
                ),
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Default Configuration",
                "Reset actions use custom defaults when an admin has set a plant baseline.",
                (
                    self._setting_row("Default configuration", "", value_label(default_text)),
                    self._setting_row("Custom defaults last updated", "", value_label(updated_text)),
                    self._setting_row("Defaults file", "", value_label(str(defaults_status.get("path") or ""), muted=True)),
                ),
                expanded=False,
            )
        )
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "Danger Zone",
                "Destructive actions require confirmation.",
                (
                    self._setting_row(
                        "Set Current Configuration as Defaults",
                        "Use the current configuration as the new reset baseline for this app.",
                        self._admin_action_button("Set Current Configuration as Defaults", self.set_current_configuration_as_defaults, variant="caution", glyph="save"),
                    ),
                    self._setting_row("Reset all visible settings", "Resets the implemented Settings controls shown on this page. Source files are not modified.", self._admin_action_button("Reset All Settings", self.reset_all_settings, variant="danger", glyph="swap")),
                ),
            )
        )

    def _render_about(self) -> None:
        project_root = str(getattr(getattr(self.controller, "config", None), "project_root", "") or "")
        source_names = ", ".join(spec.title for spec in SOURCE_SPECS[:3])
        purpose = (
            "EOAT Atlas is a read-only engineering viewer for EOAT, tool, machine, compatibility, "
            "and setup packet information."
        )
        self.main_layout.addWidget(info_card("EOAT Atlas", purpose, "good"))
        self.main_layout.addWidget(
            CollapsibleSection.with_rows(
                "App Information",
                "Version and current runtime details.",
                (
                    self._setting_row("Version", "Read-only minimalist release.", value_label("v0.9.0 Read-Only")),
                    self._setting_row("Mode", "Source files are read only.", value_label("Read-only viewer")),
                    self._setting_row("Last data load", "Most recent loaded bundle timestamp.", value_label(self._last_read_text())),
                    self._setting_row("Build date", "Runtime build metadata.", value_label("2026-07-09")),
                    self._setting_row("Project root", "Current configured EOAT project root.", value_label(project_root or "Not configured")),
                    self._setting_row("Source workbooks", "Primary read-only workbooks.", value_label(source_names)),
                    self._setting_row("Python runtime", "Useful for local support diagnostics.", value_label(platform.python_version())),
                    self._setting_row("Platform", "Operating system runtime.", value_label(platform.platform())),
                ),
            )
        )

    def _setting_row(self, title: str, description: str, control: QWidget, *, key_path: str | None = None) -> QWidget:
        setting_path = key_path or str(control.property("settingPath") or "")
        row = SettingRow(
            title,
            description,
            control,
            density=str(self._setting("app.text_density") or "comfortable"),
            setting_path=setting_path or None,
        )
        if setting_path:
            self.setting_rows.setdefault(setting_path, []).append(row)
            row.set_dirty(setting_path in self.dirty_keys)
        return row

    def _admin_action_button(self, text: str, callback: Callable, *, variant: str = "small", glyph: str | None = None) -> QPushButton:
        button = settings_button(text, variant, glyph, callback)
        button.setEnabled(self.admin_active)
        button.setCursor(Qt.CursorShape.PointingHandCursor if self.admin_active else Qt.CursorShape.ArrowCursor)
        if not self.admin_active:
            button.setToolTip("Admin access required.")
        return button

    @staticmethod
    def _setting_from(settings: dict[str, Any], dotted_path: str) -> Any:
        node: Any = settings
        for key in dotted_path.split("."):
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node

    def _setting(self, dotted_path: str) -> Any:
        return self._setting_from(self.draft_settings, dotted_path)

    def _set_setting(self, dotted_path: str, value: Any, *, require_admin: bool = True) -> None:
        self._on_setting_changed(dotted_path, value, require_admin=require_admin)

    def _on_setting_changed(self, dotted_path: str, value: Any, *, require_admin: bool = True) -> None:
        if require_admin and not self.admin_active:
            self.show_toast("Admin access required to modify settings.")
            self._sync_dirty_state()
            return
        if dotted_path == "app.theme":
            value = normalize_theme_preference(str(value))
        old_value = self._setting(dotted_path)
        if old_value == value:
            self._sync_dirty_state(changed_key=dotted_path, old_value=old_value, new_value=value)
            return
        node = self.draft_settings
        keys = dotted_path.split(".")
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value
        self._refresh_dynamic_rows()
        if dotted_path in {"app.theme", "app.accent", "app.enhanced_small_text_contrast"}:
            self._apply_draft_theme(rerender=True)
        elif dotted_path == "app.text_density":
            self._render_selected_section()
        self._sync_dirty_state(changed_key=dotted_path, old_value=old_value, new_value=value)

    def _set_setting_quiet(self, dotted_path: str, value: Any, *, target: dict[str, Any] | None = None) -> None:
        node = self.draft_settings if target is None else target
        keys = dotted_path.split(".")
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value

    def _configure_edit_control(self, widget: QWidget, dotted_path: str) -> QWidget:
        widget.setProperty("settingPath", dotted_path)
        self._set_widget_tree_enabled(widget, self.admin_active)
        if not self.admin_active:
            widget.setToolTip("Admin access required to modify settings.")
        return widget

    def _set_widget_tree_enabled(self, widget: QWidget, enabled: bool) -> None:
        widget.setEnabled(enabled)
        tooltip = "" if enabled else "Admin access required to modify settings."
        widget.setToolTip(tooltip)
        for child in widget.findChildren(QWidget):
            child.setEnabled(enabled)
            child.setToolTip(tooltip)

    def _check(self, dotted_path: str, *, locked: bool = False) -> QCheckBox:
        box = QCheckBox()
        box.setObjectName("SettingsCheckBox")
        box.setChecked(bool(self._setting(dotted_path)))
        box.setEnabled(not locked and self.admin_active)
        box.setToolTip("" if self.admin_active or locked else "Admin access required to modify settings.")
        box.setProperty("settingPath", dotted_path)
        box.stateChanged.connect(lambda _state, path=dotted_path, widget=box: self._on_setting_changed(path, bool(widget.isChecked())))
        return box

    def _combo(self, dotted_path: str, options: tuple[tuple[Any, str], ...]) -> QComboBox:
        combo = QComboBox()
        combo.setObjectName("SettingsComboBox")
        for value, label in options:
            combo.addItem(label, value)
        index = combo.findData(self._setting(dotted_path))
        combo.setCurrentIndex(max(0, index))
        self._configure_edit_control(combo, dotted_path)
        combo.currentIndexChanged.connect(lambda _index, path=dotted_path, widget=combo: self._on_setting_changed(path, widget.currentData()))
        return combo

    def _admin_logout_timeout_combo(self) -> QComboBox:
        combo = self._combo("admin.logout_after_leaving_settings_seconds", ADMIN_LOGOUT_TIMEOUT_OPTIONS)
        combo.setMinimumWidth(140)
        tooltip = "" if self.admin_active else "Admin access required to change auto-logout timing."
        combo.setToolTip(tooltip)
        return combo

    def _segmented(self, dotted_path: str, options: tuple[tuple[Any, str], ...]) -> QWidget:
        host = QWidget()
        host.setObjectName("SettingsChipRow")
        host.setProperty("settingPath", dotted_path)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        group = QButtonGroup(host)
        group.setExclusive(True)
        current = self._setting(dotted_path)
        for index, (value, label) in enumerate(options):
            button = QPushButton(label)
            button.setObjectName("SettingsSegmentButton")
            button.setCheckable(True)
            button.setProperty("settingValue", value)
            if str(value) == str(current):
                button.setChecked(True)
            group.addButton(button, index)
            layout.addWidget(button)
        group.idClicked.connect(lambda button_id, path=dotted_path, g=group: self._on_setting_changed(path, g.button(button_id).property("settingValue")))
        layout.addStretch(1)
        self._configure_edit_control(host, dotted_path)
        return host

    def _spin(self, dotted_path: str, minimum: int, maximum: int, *, suffix: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setObjectName("SettingsSpinBox")
        spin.setRange(minimum, maximum)
        spin.setValue(int(self._setting(dotted_path) or minimum))
        if suffix:
            spin.setSuffix(suffix)
        self._configure_edit_control(spin, dotted_path)
        spin.valueChanged.connect(lambda value, path=dotted_path: self._on_setting_changed(path, int(value)))
        return spin

    def _line_edit(self, dotted_path: str, *, locked: bool = False, minimum_width: int = 260) -> QLineEdit:
        line = QLineEdit()
        line.setObjectName("SettingsLineEdit")
        line.setText(str(self._setting(dotted_path) or ""))
        line.setMinimumWidth(minimum_width)
        line.setProperty("settingPath", dotted_path)
        line.setEnabled(not locked and self.admin_active)
        line.setToolTip("" if self.admin_active or locked else "Admin access required to modify settings.")
        line.textChanged.connect(lambda text, path=dotted_path: self._on_setting_changed(path, text))
        return line

    def _default_source_path(self, spec: SourceSpec) -> Path:
        project_root = Path(str(getattr(getattr(self.controller, "config", None), "project_root", "") or "."))
        paths = resolve_project_paths(project_root)
        defaults = {
            "eoat_master_tracker": paths.master_workbook,
            "press_capacity_workbook": get_press_capacity_file(project_root),
            "robot_workbook": paths.robot_info_workbook,
            "photos_root": paths.cell_photos,
            "output_folder": paths.final_handoff / "Atlas_Exports",
            "reference_docs_folder": paths.standards,
        }
        return defaults.get(spec.key, project_root)

    def _effective_source_path(self, spec: SourceSpec) -> Path:
        value = str(self._setting(f"paths.{spec.key}") or "").strip()
        return Path(value).expanduser() if value else self._default_source_path(spec)

    def _require_admin(self, message: str = "Admin access required to modify settings.") -> bool:
        if self.admin_active:
            return True
        self.show_toast(message)
        return False

    def _last_read_text(self) -> str:
        loaded_at = str(getattr(self.bundle, "loaded_at", "") or self._setting("diagnostics.last_successful_data_load") or "")
        return format_timestamp(loaded_at) if loaded_at else "Not loaded this session"

    def _source_health_summary(self) -> QWidget:
        connected = 0
        rows = []
        for spec in SOURCE_SPECS:
            path = self._effective_source_path(spec)
            status, _tone = validate_source_path(path, spec)
            if status == "Connected":
                connected += 1
            rows.append((spec.title, status, str(path)))
        panel = GlassPanel(radius=8)
        apply_glass_theme(panel, "settings_card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)
        layout.addWidget(value_label(f"{connected} of {len(SOURCE_SPECS)} source locations connected"))
        for title, status, path_text in rows:
            layout.addWidget(value_label(f"{title}: {status} | {path_text}", muted=True))
        return panel

    def _refresh_dynamic_rows(self) -> None:
        if hasattr(self, "panel_header"):
            self.panel_header.set_section(self._selected_spec(), self._status_for_section(self.selected_key))
        for spec in SOURCE_SPECS:
            row = self.source_rows.get(spec.key) if hasattr(self, "source_rows") else None
            if row is not None:
                row.update_path(self._effective_source_path(spec), self._last_read_text())

    def change_source_path(self, key: str) -> None:
        if not self._require_admin("Admin access required to change source paths."):
            return
        spec = next((item for item in SOURCE_SPECS if item.key == key), None)
        if spec is None:
            return
        current = str(self._effective_source_path(spec))
        if spec.kind == "folder":
            selected = QFileDialog.getExistingDirectory(self, f"Choose {spec.title}", current)
        else:
            filter_text = "Excel Workbooks (*.xlsx *.xlsm *.xls);;All Files (*)"
            selected, _filter = QFileDialog.getOpenFileName(self, f"Choose {spec.title}", current, filter_text)
        if selected:
            self._set_setting(f"paths.{spec.key}", selected)
            self._set_setting_quiet("diagnostics.last_source_path_change", datetime.now().isoformat(timespec="seconds"))
            self.show_toast(f"{spec.title} path changed. Save Settings to keep it.")

    def open_source_path(self, key: str) -> None:
        spec = next((item for item in SOURCE_SPECS if item.key == key), None)
        if spec is None:
            return
        path = self._effective_source_path(spec)
        open_path(path, self.show_toast)

    def validate_source(self, key: str) -> None:
        spec = next((item for item in SOURCE_SPECS if item.key == key), None)
        if spec is None:
            return
        path = self._effective_source_path(spec)
        status, _tone = validate_source_path(path, spec)
        self.show_toast(f"{spec.title}: {status}")
        row = self.source_rows.get(spec.key)
        if row is not None:
            row.update_path(path, self._last_read_text())

    def _reference_doc_row(self, key: str, title: str) -> QWidget:
        raw_path = str(self._setting(f"reference_documents.{key}") or "")
        setting_path = f"reference_documents.{key}"
        row = ReferenceDocumentRow(
            title,
            raw_path,
            change_callback=lambda _checked=False, doc_key=key, doc_title=title: self.change_reference_doc(doc_key, doc_title),
            open_callback=lambda _checked=False, path_text=raw_path: self.open_reference_doc(path_text),
            validate_callback=lambda _checked=False, path_text=raw_path, doc_title=title: self.show_toast(f"{doc_title}: {validate_document_path(Path(path_text))[0] if path_text else 'Not Configured'}"),
            admin_active=self.admin_active,
            parent=self,
        )
        self.source_dirty_rows[setting_path] = row
        row.set_dirty(setting_path in self.dirty_keys)
        return row

    def change_reference_doc(self, key: str, title: str) -> None:
        if not self._require_admin("Admin access required to change reference document paths."):
            return
        selected, _filter = QFileDialog.getOpenFileName(self, f"Choose {title}", "", "Documents (*.pdf *.docx *.xlsx *.md *.txt);;All Files (*)")
        if selected:
            self._set_setting(f"reference_documents.{key}", selected)
            self._render_selected_section()
            self.show_toast(f"{title} path changed. Save Settings to keep it.")

    def open_reference_doc(self, path_text: str) -> None:
        if not str(path_text or "").strip():
            self.show_toast("Reference document is not configured.")
            return
        behavior = str(self._setting("reference_documents.viewer_default") or "open_in_app")
        if behavior == "ask_every_time":
            action = show_settings_confirmation(
                self,
                "Open Reference Document",
                "Open this reference document now?",
                (
                    DialogAction("cancel", "Cancel", "secondary"),
                    DialogAction("open", "Open", "primary"),
                ),
                default_action="open",
                cancel_action="cancel",
            )
            if action != "open":
                return
        open_path_text(path_text, self.show_toast)

    def save_current_settings(self) -> bool:
        if not self._require_admin("Admin access required to save settings."):
            return False
        try:
            save_settings(self.draft_settings, self.settings_file)
            self.saved_settings = load_settings(self.settings_file)
        except OSError:
            LOGGER.exception("Failed to save minimalist settings")
            self.show_toast("Failed to save settings.")
            return False
        self.draft_settings = deepcopy(self.saved_settings)
        commit = getattr(self.controller, "commit_minimalist_settings", None)
        if callable(commit):
            commit(deepcopy(self.saved_settings))
        elif hasattr(self.controller, "minimalist_app_settings"):
            self.controller.minimalist_app_settings = deepcopy(self.saved_settings)
        self._sync_dirty_state()
        self.show_toast("Settings saved.")
        return True

    def reset_current_section(self) -> None:
        if not self._require_admin("Admin access required to reset settings."):
            return
        spec = self._selected_spec()
        if spec.key == "about":
            self.show_toast("About has no editable settings to reset.")
            return
        if spec.key not in EDITABLE_SECTION_KEYS:
            self.show_toast(f"{spec.title} has no editable settings to reset.")
            return
        action = show_settings_confirmation(
            self,
            "Reset Section",
            f"Reset {spec.title} settings to defaults? Unsaved edits in this section will be replaced.",
            (
                DialogAction("cancel", "Cancel", "secondary"),
                DialogAction("reset", "Reset Section", "danger"),
            ),
            default_action="cancel",
            cancel_action="cancel",
        )
        if action != "reset":
            return
        defaults = get_effective_default_settings(settings_file=self.settings_file)
        for dotted_path in SECTION_SETTING_PATHS.get(spec.key, ()):
            self._set_setting_quiet(dotted_path, self._setting_from(defaults, dotted_path))
        self._apply_draft_theme(rerender=False)
        self._render_selected_section()
        self._sync_dirty_state()
        self.show_toast(f"{spec.title} reset. Save settings to keep these changes.")

    def reset_all_settings(self) -> None:
        if not self._require_admin("Admin access required to reset settings."):
            return
        message = (
            "This will reset paths, display preferences, cache behavior, PDF defaults, validation settings, "
            "and app behavior settings. This will not modify source workbooks, folders, or photos."
        )
        action = show_settings_confirmation(
            self,
            "Reset All Settings",
            message,
            (
                DialogAction("cancel", "Cancel", "secondary"),
                DialogAction("reset", "Reset All Settings", "danger"),
            ),
            default_action="cancel",
            cancel_action="cancel",
        )
        if action != "reset":
            return
        defaults = get_effective_default_settings(settings_file=self.settings_file)
        for dotted_path in VISIBLE_RESETTABLE_SETTING_PATHS:
            self._set_setting_quiet(dotted_path, self._setting_from(defaults, dotted_path))
        self._apply_draft_theme(rerender=False)
        self._render_selected_section()
        self._sync_dirty_state()
        self.show_toast("All settings reset. Save settings to keep these changes.")

    def set_current_configuration_as_defaults(self) -> None:
        if not self._require_admin("Admin access required to set default configuration."):
            return
        action = show_settings_confirmation(
            self,
            "Set Current Configuration as Defaults",
            "This will make the current EOAT Atlas configuration the new default used by Reset Section and Reset All Settings. Existing source files, workbooks, folders, and photos will not be modified.",
            (
                DialogAction("cancel", "Cancel", "secondary"),
                DialogAction("set", "Set as Defaults", "caution"),
            ),
            default_action="cancel",
            cancel_action="cancel",
        )
        if action != "set":
            return
        baseline = self.saved_settings
        if self.dirty_keys or self._calculate_dirty_keys():
            choice = show_settings_confirmation(
                self,
                "Unsaved Settings",
                "You have unsaved settings changes. Save them before setting defaults?",
                (
                    DialogAction("cancel", "Cancel", "secondary"),
                    DialogAction("saved", "Use Saved Settings", "caution"),
                    DialogAction("save_current", "Save and Use Current Settings", "primary"),
                ),
                default_action="save_current",
                cancel_action="cancel",
            )
            if choice == "cancel":
                return
            if choice == "save_current":
                if not self.save_current_settings():
                    return
                baseline = self.saved_settings
            else:
                baseline = self.saved_settings
        timestamp = datetime.now().isoformat(timespec="seconds")
        try:
            save_custom_defaults(baseline, settings_file=self.settings_file, updated_at=timestamp)
        except OSError:
            LOGGER.exception("Failed to save custom settings defaults")
            self.show_toast("Failed to update default configuration.")
            return
        self.show_toast("Default configuration updated.")
        if self.selected_key == "diagnostics_support":
            self._render_selected_section()
            self._sync_dirty_state()

    def export_settings(self) -> None:
        target, _filter = QFileDialog.getSaveFileName(
            self,
            "Export Settings",
            str(Path.home() / "eoat_atlas_settings_export.json"),
            "JSON Files (*.json);;All Files (*)",
        )
        if not target:
            return
        Path(target).write_text(json.dumps(self.draft_settings, indent=2, sort_keys=True), encoding="utf-8")
        self.show_toast(f"Settings exported to {target}")

    def reload_data(self) -> None:
        if self._has_unsaved_path_changes():
            action = show_settings_confirmation(
                self,
                "Reload Data",
                "There are unsaved source path changes. Reload uses saved settings unless changes are saved first.",
                (
                    DialogAction("cancel", "Cancel", "secondary"),
                    DialogAction("reload", "Reload Data", "primary"),
                ),
                default_action="cancel",
                cancel_action="cancel",
            )
            if action != "reload":
                return
        refresh = getattr(self.controller, "refresh_data", None)
        if callable(refresh):
            refresh(force=True)
            self.show_toast("Data reloaded.")
        else:
            self.show_toast("Reload Data is not available in this window.")

    def _has_unsaved_path_changes(self) -> bool:
        return self.draft_settings.get("paths") != self.saved_settings.get("paths")

    def _sync_dirty_state(self, *, changed_key: str | None = None, old_value: Any = None, new_value: Any = None) -> None:
        self.dirty_keys = self._calculate_dirty_keys()
        self.dirty_sections = {SETTING_SECTION_BY_PATH[key] for key in self.dirty_keys if key in SETTING_SECTION_BY_PATH}
        dirty = bool(self.dirty_keys)
        save_enabled = dirty and self.admin_active
        self.save_button.setEnabled(save_enabled)
        self.save_button.setProperty("dirty", dirty)
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor if save_enabled else Qt.CursorShape.ArrowCursor)
        self.save_button.style().unpolish(self.save_button)
        self.save_button.style().polish(self.save_button)
        can_reset_section = self.admin_active and self.selected_key in EDITABLE_SECTION_KEYS
        self.reset_section_button.setEnabled(can_reset_section)
        self.reset_section_button.setCursor(Qt.CursorShape.PointingHandCursor if can_reset_section else Qt.CursorShape.ArrowCursor)
        self.unsaved_label.setVisible(dirty)
        for key, item in self.sidebar_items.items():
            item.set_dirty(key in self.dirty_sections)
        if hasattr(self, "panel_header"):
            self.panel_header.set_dirty(self.selected_key in self.dirty_sections)
            self.panel_header.set_admin_state(self.admin_active, self.selected_key in EDITABLE_SECTION_KEYS)
        for key_path, rows in self.setting_rows.items():
            for row in rows:
                row.set_dirty(key_path in self.dirty_keys)
        for key_path, row in self.source_dirty_rows.items():
            row.set_dirty(key_path in self.dirty_keys)
            row.set_admin_active(self.admin_active)
        self._sync_admin_state(rerender=False)
        if changed_key:
            saved_value = self._setting_from(self.saved_settings, changed_key)
            LOGGER.debug(
                "[SettingsDirty] %s: %r -> %r | saved=%r | dirty=%s",
                changed_key,
                old_value,
                new_value,
                saved_value,
                changed_key in self.dirty_keys,
            )
            LOGGER.debug("[SettingsDirty] dirtyKeys=%s", tuple(sorted(self.dirty_keys)))
            LOGGER.debug("[SettingsDirty] dirtySections=%s", tuple(sorted(self.dirty_sections)))
            LOGGER.debug("[SettingsDirty] saveEnabled=%s globalDirty=%s", self.save_button.isEnabled(), dirty)
        state = (dirty, tuple(sorted(self.dirty_sections)), tuple(sorted(self.dirty_keys)))
        if state != self._last_logged_dirty_state:
            LOGGER.debug("Settings dirty=%s sections=%s keys=%s save_enabled=%s", dirty, state[1], state[2], self.save_button.isEnabled())
            self._last_logged_dirty_state = state

    def _calculate_dirty_keys(self) -> set[str]:
        return {
            path
            for path in SETTING_SECTION_BY_PATH
            if self._setting_from(self.draft_settings, path) != self._setting_from(self.saved_settings, path)
        }

    def _calculate_dirty_sections(self) -> set[str]:
        return {SETTING_SECTION_BY_PATH[key] for key in self._calculate_dirty_keys() if key in SETTING_SECTION_BY_PATH}

    def confirm_navigation_away(self) -> bool:
        if not self._calculate_dirty_sections():
            return True
        action = show_settings_confirmation(
            self,
            "Unsaved Settings",
            "You have unsaved settings changes. Save them before leaving Settings?",
            (
                DialogAction("cancel", "Cancel", "secondary"),
                DialogAction("discard", "Discard", "danger"),
                DialogAction("save", "Save", "primary"),
            ),
            default_action="save",
            cancel_action="cancel",
        )
        if action == "save":
            return self.save_current_settings()
        if action == "discard":
            self._discard_unsaved_changes()
            return True
        return False

    def clear_data_cache(self) -> None:
        if not self._require_admin("Admin access required to clear app cache."):
            return
        project_root = str(getattr(getattr(self.controller, "config", None), "project_root", "") or "")
        invalidate_atlas_data_cache(project_root or None)
        self.show_toast("Cache cleared.")

    def clear_thumbnail_cache(self) -> None:
        if not self._require_admin("Admin access required to clear thumbnail cache."):
            return
        try:
            from .library import PHOTO_THUMBNAIL_CACHE

            PHOTO_THUMBNAIL_CACHE.clear()
        except Exception:
            LOGGER.debug("Could not clear minimalist thumbnail cache", exc_info=True)
        photo_service = getattr(getattr(getattr(self.controller, "library_page", None), "library_content", None), "catalog", None)
        photo_service = getattr(photo_service, "photo_service", None)
        clearer = getattr(photo_service, "clear_cache", None)
        if callable(clearer):
            clearer(include_disk=True)
        self.show_toast("Cache cleared. Existing source photos were not modified.")

    def run_validation_now(self) -> None:
        warnings = len(getattr(self.bundle, "warnings", ()) or ())
        timestamp = datetime.now().isoformat(timespec="seconds")
        self._set_setting_quiet("diagnostics.last_validation", timestamp)
        self._set_setting_quiet("diagnostics.last_validation", timestamp, target=self.saved_settings)
        if self.selected_key == "diagnostics_support":
            self._render_selected_section()
            self._sync_dirty_state()
        self.show_toast(f"Validation complete. {warnings} indexed warnings found.")

    def view_validation_report(self) -> None:
        project_root = str(getattr(getattr(self.controller, "config", None), "project_root", "") or "")
        reports = resolve_project_paths(project_root).validation_reports if project_root else Path()
        open_path(reports, self.show_toast)

    def open_logs_folder(self) -> None:
        project_root = str(getattr(getattr(self.controller, "config", None), "project_root", "") or "")
        logs = resolve_project_paths(project_root).logs if project_root else self.settings_file.parent
        open_path(logs, self.show_toast)

    def export_diagnostic_bundle(self) -> None:
        if not self._require_admin("Admin access required to export diagnostic bundles."):
            return
        target, _filter = QFileDialog.getSaveFileName(
            self,
            "Export Diagnostic Bundle",
            str(Path.home() / "eoat_atlas_diagnostics.json"),
            "JSON Files (*.json);;All Files (*)",
        )
        if not target:
            return
        bundle = {
            "app_version": "v0.9.0 Read-Only",
            "settings": self.draft_settings,
            "source_paths": {spec.key: str(self._effective_source_path(spec)) for spec in SOURCE_SPECS},
            "last_validation": self._setting("diagnostics.last_validation"),
            "warnings_indexed": len(getattr(self.bundle, "warnings", ()) or ()),
            "python": sys.version,
            "platform": platform.platform(),
        }
        Path(target).write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
        self.show_toast(f"Diagnostic bundle exported to {target}")

    def reload_settings_file(self) -> None:
        if (self.dirty_keys or self._calculate_dirty_keys()) and not self._require_admin("Admin access required to discard unsaved settings."):
            return
        self.saved_settings = load_settings(self.settings_file)
        self.draft_settings = deepcopy(self.saved_settings)
        self._apply_draft_theme(rerender=True)
        self._sync_dirty_state()
        self.show_toast("Settings reloaded from disk.")


class SettingsSidebarItem(QFrame):
    clicked = Signal(str)

    def __init__(self, spec: SectionSpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.setObjectName("SettingsSidebarItem")
        self.setProperty("active", False)
        self.setProperty("hovered", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(47)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 8, 6)
        layout.setSpacing(10)
        self.icon = QLabel()
        self.icon.setPixmap(glyph_icon(spec.glyph, qcolor(active_minimalist_tokens().text_secondary), 20).pixmap(20, 20))
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        title = QLabel(spec.title)
        title.setObjectName("SettingsSidebarItemTitle")
        description = QLabel(spec.description)
        description.setObjectName("SettingsSidebarItemDescription")
        text_layout.addWidget(title)
        text_layout.addWidget(description)
        layout.addWidget(self.icon)
        layout.addLayout(text_layout, 1)
        self.dirty_indicator = QFrame()
        self.dirty_indicator.setObjectName("SettingsDirtyDot")
        self.dirty_indicator.setFixedSize(8, 8)
        self.dirty_indicator.hide()
        layout.addWidget(self.dirty_indicator, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", bool(active))
        self.style().unpolish(self)
        self.style().polish(self)
        tokens = active_minimalist_tokens()
        color = qcolor(tokens.accent_hover if active else tokens.text_secondary)
        self.icon.setPixmap(glyph_icon(self.spec.glyph, color, 20).pixmap(20, 20))

    def apply_theme_preference(self, _preference: str | None) -> None:
        self.set_active(bool(self.property("active")))

    def set_dirty(self, dirty: bool) -> None:
        self.dirty_indicator.setVisible(bool(dirty))

    def enterEvent(self, event) -> None:
        self.setProperty("hovered", True)
        self.style().unpolish(self)
        self.style().polish(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setProperty("hovered", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.spec.key)
            event.accept()
            return
        super().mousePressEvent(event)


class SettingsPanelHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(46)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.icon = QLabel()
        self.title = QLabel()
        self.title.setObjectName("SettingsPanelTitle")
        self.description = QLabel()
        self.description.setObjectName("SettingsPanelSubtitle")
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(self.title)
        text_layout.addWidget(self.description)
        self.status = QLabel()
        self.status.setObjectName("SettingsStatusPill")
        self.status.hide()
        self.dirty_pill = QLabel("Unsaved")
        self.dirty_pill.setObjectName("SettingsDirtyPill")
        self.dirty_pill.hide()
        self.admin_pill = QLabel("Admin required to edit")
        self.admin_pill.setObjectName("SettingsAdminPill")
        self.admin_pill.setProperty("active", False)
        self.admin_pill.hide()
        layout.addWidget(self.icon)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.dirty_pill)
        layout.addWidget(self.admin_pill)
        layout.addWidget(self.status)

    def set_section(self, spec: SectionSpec, status: tuple[str, str] | None) -> None:
        self.icon.setPixmap(glyph_icon(spec.glyph, qcolor(active_minimalist_tokens().text_secondary), 24).pixmap(24, 24))
        self.title.setText(spec.title if spec.key != "about" else "About EOAT Atlas")
        descriptions = {
            "data_sources": "EOAT Atlas reads data from the following sources. The app is read-only and will never modify your files.",
            "refresh_cache": "Configure how EOAT Atlas loads source data and caches read-only information.",
            "read_only_safety": "Protect source data and prevent accidental edits.",
            "search_navigation": "Control global search behavior and profile navigation.",
            "fit_check": "Configure compatibility checking, flow display, alternatives, and recent check behavior.",
            "library": "Configure Library sorting, pagination, cards, and profile display.",
            "display_accessibility": "Configure theme, accent, readability, contrast, and animation behavior.",
            "setup_packet_pdf": "Configure setup packet generation, preview behavior, and PDF defaults.",
            "validation_health": "Configure source data checks and app health indicators.",
            "reference_documents": "Manage guidelines, PM checklists, and reference document behavior.",
            "diagnostics_support": "View logs, export diagnostics, and troubleshoot source/loading issues.",
            "about": "App version and system information.",
        }
        self.description.setText(descriptions.get(spec.key, spec.description))
        if status is None:
            self.status.hide()
            return
        text, tone = status
        self.status.setText(text)
        self.status.setProperty("tone", tone)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.show()

    def set_dirty(self, dirty: bool) -> None:
        self.dirty_pill.setVisible(bool(dirty))

    def set_admin_state(self, admin_active: bool, editable: bool) -> None:
        if not editable:
            self.admin_pill.hide()
            return
        self.admin_pill.setText("Admin Active" if admin_active else "Admin required to edit")
        self.admin_pill.setProperty("active", bool(admin_active))
        self.admin_pill.style().unpolish(self.admin_pill)
        self.admin_pill.style().polish(self.admin_pill)
        self.admin_pill.show()

    def apply_theme_preference(self, _preference: str | None) -> None:
        pixmap = self.icon.pixmap()
        if pixmap is not None and not pixmap.isNull():
            self.update()


class CollapsibleSection(GlassPanel):
    def __init__(self, title: str, description: str, *, expanded: bool = True, parent=None):
        super().__init__(parent, radius=8)
        apply_glass_theme(self, "settings_section")
        self._expanded = expanded
        self._animation = QPropertyAnimation(self, b"maximumHeight", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 12)
        layout.setSpacing(9)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("SettingsSectionTitle")
        description_label = QLabel(description)
        description_label.setObjectName("SettingsSectionDescription")
        description_label.setWordWrap(True)
        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("SettingsSectionToggle")
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.clicked.connect(self.toggle)
        text.addWidget(title_label)
        text.addWidget(description_label)
        header.addLayout(text, 1)
        header.addWidget(self.toggle_button)
        self.body = QWidget()
        self.body.setObjectName("SettingsSectionBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(7)
        layout.addLayout(header)
        layout.addWidget(self.body)
        self._sync()

    @classmethod
    def with_rows(cls, title: str, description: str, rows: tuple[QWidget, ...], *, expanded: bool = True) -> CollapsibleSection:
        section = cls(title, description, expanded=expanded)
        for row in rows:
            section.body_layout.addWidget(row)
        return section

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._sync()

    def _sync(self) -> None:
        self.body.setVisible(self._expanded)
        self.toggle_button.setText("v" if self._expanded else ">")


class SettingRow(QWidget):
    def __init__(
        self,
        title: str,
        description: str,
        control: QWidget,
        *,
        density: str = "comfortable",
        setting_path: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setting_path = setting_path or ""
        self.setObjectName("SettingsRowBody")
        compact = str(density or "comfortable") == "compact"
        large = str(density or "comfortable") == "large"
        has_description = bool(str(description or "").strip())
        self.setMinimumHeight((58 if has_description else 42) + (6 if large else (-4 if compact else 0)))
        layout = QHBoxLayout(self)
        vertical_margin = 4 if compact else (8 if large else 6)
        layout.setContentsMargins(0, vertical_margin, 0, vertical_margin)
        layout.setSpacing(16)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2 if has_description else 0)
        title_label = QLabel(title)
        title_label.setObjectName("SettingsRowTitle")
        description_label = QLabel(description)
        description_label.setObjectName("SettingsRowDescription")
        description_label.setWordWrap(True)
        text.addWidget(title_label)
        if has_description:
            text.addWidget(description_label)
        layout.addLayout(text, 1)
        self.dirty_indicator = QFrame()
        self.dirty_indicator.setObjectName("SettingsDirtyDot")
        self.dirty_indicator.setFixedSize(8, 8)
        self.dirty_indicator.setToolTip("Unsaved change")
        self.dirty_indicator.hide()
        layout.addWidget(self.dirty_indicator, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def set_dirty(self, dirty: bool) -> None:
        self.dirty_indicator.setVisible(bool(dirty and self.setting_path))


class DataSourceRow(GlassPanel):
    change_requested = Signal(str)
    open_requested = Signal(str)
    validate_requested = Signal(str)

    def __init__(self, spec: SourceSpec, path: Path, last_read: str, parent=None):
        super().__init__(parent, radius=7)
        self.spec = spec
        apply_glass_theme(self, "settings_row")
        self.setMinimumHeight(62)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(12)
        self.icon = QLabel()
        self.icon.setPixmap(glyph_icon(spec.glyph, qcolor(active_minimalist_tokens().text_secondary), 20).pixmap(20, 20))
        name_box = QVBoxLayout()
        name_box.setContentsMargins(0, 0, 0, 0)
        name_box.setSpacing(1)
        title = QLabel(spec.title)
        title.setObjectName("SettingsSourceTitle")
        desc = QLabel(spec.description)
        desc.setObjectName("SettingsSourceDescription")
        name_box.addWidget(title)
        name_box.addWidget(desc)
        path_box = QVBoxLayout()
        path_box.setContentsMargins(0, 0, 0, 0)
        path_box.setSpacing(1)
        self.path_label = QLabel()
        self.path_label.setObjectName("SettingsPathText")
        self.path_label.setWordWrap(True)
        self.path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.last_read_label = QLabel()
        self.last_read_label.setObjectName("SettingsSourceDescription")
        self.last_read_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        path_box.addWidget(self.path_label)
        path_box.addWidget(self.last_read_label)
        self.status = SourceStatusWidget()
        self.dirty_indicator = QFrame()
        self.dirty_indicator.setObjectName("SettingsDirtyDot")
        self.dirty_indicator.setFixedSize(8, 8)
        self.dirty_indicator.setToolTip("Unsaved change")
        self.dirty_indicator.hide()
        self.change_button = settings_button("Change", "small")
        self.open_button = settings_button("Open Folder" if spec.kind == "folder" else "Open File", "small")
        self.validate_button = settings_button("Validate", "small")
        for button in (self.change_button, self.open_button, self.validate_button):
            button.setMinimumWidth(78)
            button.setMaximumWidth(94)
        self.change_button.clicked.connect(lambda: self.change_requested.emit(spec.key))
        self.open_button.clicked.connect(lambda: self.open_requested.emit(spec.key))
        self.validate_button.clicked.connect(lambda: self.validate_requested.emit(spec.key))
        layout.addWidget(self.icon)
        layout.addLayout(name_box, 2)
        layout.addLayout(path_box, 3)
        layout.addWidget(self.dirty_indicator)
        layout.addWidget(self.status)
        layout.addWidget(self.change_button)
        layout.addWidget(self.open_button)
        layout.addWidget(self.validate_button)
        self.update_path(path, last_read)

    def update_path(self, path: Path, last_read: str) -> None:
        path_text = str(path)
        self.path_label.setText(compact_path_text(path_text))
        self.path_label.setToolTip(path_text)
        self.last_read_label.setText(f"Last read: {last_read}")
        status, tone = validate_source_path(path, self.spec)
        self.status.set_status(status, tone)

    def set_dirty(self, dirty: bool) -> None:
        self.dirty_indicator.setVisible(bool(dirty))

    def set_admin_active(self, active: bool) -> None:
        self.change_button.setEnabled(bool(active))
        self.change_button.setCursor(Qt.CursorShape.PointingHandCursor if active else Qt.CursorShape.ArrowCursor)
        self.change_button.setToolTip("" if active else "Admin access required.")


class ReferenceDocumentRow(GlassPanel):
    def __init__(
        self,
        title: str,
        path_text: str,
        *,
        change_callback: Callable,
        open_callback: Callable,
        validate_callback: Callable,
        admin_active: bool,
        parent=None,
    ):
        super().__init__(parent, radius=8)
        apply_glass_theme(self, "settings_row")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 10, 13, 10)
        layout.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(glyph_icon("doc", qcolor(active_minimalist_tokens().text_secondary), 20).pixmap(20, 20))
        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)
        label = QLabel(title)
        label.setObjectName("SettingsSourceTitle")
        self.path_label = QLabel(path_text or "Not configured")
        self.path_label.setObjectName("SettingsPathText")
        self.path_label.setWordWrap(True)
        title_box.addWidget(label)
        title_box.addWidget(self.path_label)
        status, tone = validate_document_path(Path(path_text)) if path_text else ("Not Configured", "warn")
        self.status_label = status_pill(status, tone)
        self.dirty_indicator = QFrame()
        self.dirty_indicator.setObjectName("SettingsDirtyDot")
        self.dirty_indicator.setFixedSize(8, 8)
        self.dirty_indicator.setToolTip("Unsaved change")
        self.dirty_indicator.hide()
        self.change_button = settings_button("Change", "small", None, change_callback)
        self.open_button = settings_button("Open", "small", None, open_callback)
        self.validate_button = settings_button("Validate", "small", None, validate_callback)
        layout.addWidget(icon)
        layout.addLayout(title_box, 1)
        layout.addWidget(self.dirty_indicator)
        layout.addWidget(self.status_label)
        layout.addWidget(self.change_button)
        layout.addWidget(self.open_button)
        layout.addWidget(self.validate_button)
        self.set_admin_active(admin_active)

    def set_dirty(self, dirty: bool) -> None:
        self.dirty_indicator.setVisible(bool(dirty))

    def set_admin_active(self, active: bool) -> None:
        self.change_button.setEnabled(bool(active))
        self.change_button.setCursor(Qt.CursorShape.PointingHandCursor if active else Qt.CursorShape.ArrowCursor)
        self.change_button.setToolTip("" if active else "Admin access required.")


class SourceStatusWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsSourceRowBody")
        self.dot = StatusDot(self)
        self.label = QLabel("")
        self.label.setObjectName("SettingsSmallPill")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(self.dot)
        layout.addWidget(self.label)

    def set_status(self, text: str, tone: str) -> None:
        self.label.setText(text)
        self.label.setProperty("tone", tone)
        self.label.style().unpolish(self.label)
        self.label.style().polish(self.label)
        self.dot.set_ready(tone == "good")


class DirtyIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsDirtyIndicator")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.dot = QFrame()
        self.dot.setObjectName("SettingsDirtyDot")
        self.dot.setFixedSize(8, 8)
        self.label = QLabel("Unsaved changes")
        self.label.setObjectName("SettingsDirtyText")
        layout.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.label)


@dataclass(frozen=True)
class DialogAction:
    key: str
    label: str
    role: str = "secondary"


class SettingsConfirmationDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        title: str,
        message: str,
        actions: tuple[DialogAction, ...],
        *,
        default_action: str,
        cancel_action: str,
        theme_preference: str | None = None,
    ):
        super().__init__(parent)
        self.selected_action = cancel_action
        self.setObjectName("SettingsConfirmDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setStyleSheet(settings_dialog_styles(theme_preference))

        dialog_layout = QVBoxLayout(self)
        dialog_layout.setContentsMargins(10, 10, 10, 10)
        dialog_layout.setSpacing(0)
        panel = QFrame()
        panel.setObjectName("SettingsDialogPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(22, 20, 22, 18)
        panel_layout.setSpacing(14)

        title_label = QLabel(title)
        title_label.setObjectName("SettingsDialogTitle")
        body_label = QLabel(message)
        body_label.setObjectName("SettingsDialogBody")
        body_label.setWordWrap(True)
        body_label.setMinimumWidth(390)
        panel_layout.addWidget(title_label)
        panel_layout.addWidget(body_label)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 4, 0, 0)
        button_row.setSpacing(10)
        button_row.addStretch(1)
        for action in actions:
            button = QPushButton(action.label)
            object_name = {
                "primary": "SettingsDialogPrimaryButton",
                "caution": "SettingsDialogCautionButton",
                "danger": "SettingsDialogDangerButton",
                "destructive": "SettingsDialogDangerButton",
                "secondary": "SettingsDialogSecondaryButton",
            }.get(action.role, "SettingsDialogSecondaryButton")
            button.setObjectName(object_name)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, key=action.key: self._choose(key))
            if action.key == default_action:
                button.setDefault(True)
            button_row.addWidget(button)
        panel_layout.addLayout(button_row)
        dialog_layout.addWidget(panel)

    def _choose(self, key: str) -> None:
        self.selected_action = key
        self.accept()


class AdminAccessDialog(QDialog):
    def __init__(self, parent: QWidget, *, theme_preference: str | None = None):
        super().__init__(parent)
        self._password = ""
        self.setObjectName("SettingsConfirmDialog")
        self.setWindowTitle("Admin Access")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setStyleSheet(settings_dialog_styles(theme_preference))

        dialog_layout = QVBoxLayout(self)
        dialog_layout.setContentsMargins(10, 10, 10, 10)
        dialog_layout.setSpacing(0)
        panel = QFrame()
        panel.setObjectName("SettingsDialogPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(22, 20, 22, 18)
        panel_layout.setSpacing(14)

        title = QLabel("Admin Access")
        title.setObjectName("SettingsDialogTitle")
        body = QLabel("Sign in to modify EOAT Atlas settings.")
        body.setObjectName("SettingsDialogBody")
        body.setWordWrap(True)
        self.password_field = QLineEdit()
        self.password_field.setObjectName("SettingsLineEdit")
        self.password_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_field.setPlaceholderText("Admin password or PIN")
        self.password_field.returnPressed.connect(self._attempt_sign_in)
        self.show_password = QCheckBox("Show password")
        self.show_password.setObjectName("SettingsCheckBox")
        self.show_password.toggled.connect(self._toggle_password_visibility)
        self.error_label = QLabel("Invalid admin password.")
        self.error_label.setObjectName("SettingsDangerText")
        self.error_label.hide()

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 4, 0, 0)
        button_row.setSpacing(10)
        button_row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("SettingsDialogSecondaryButton")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        sign_in = QPushButton("Sign In")
        sign_in.setObjectName("SettingsDialogPrimaryButton")
        sign_in.setDefault(True)
        sign_in.setCursor(Qt.CursorShape.PointingHandCursor)
        sign_in.clicked.connect(self._attempt_sign_in)
        button_row.addWidget(cancel)
        button_row.addWidget(sign_in)

        panel_layout.addWidget(title)
        panel_layout.addWidget(body)
        panel_layout.addWidget(self.password_field)
        panel_layout.addWidget(self.show_password)
        panel_layout.addWidget(self.error_label)
        panel_layout.addLayout(button_row)
        dialog_layout.addWidget(panel)
        self.password_field.setFocus(Qt.FocusReason.OtherFocusReason)

    def password(self) -> str:
        return self._password

    def _toggle_password_visibility(self, visible: bool) -> None:
        self.password_field.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)

    def _attempt_sign_in(self) -> None:
        password = self.password_field.text()
        if verify_admin_password(password):
            self._password = password
            self.accept()
            return
        self.error_label.show()
        self.password_field.selectAll()
        self.password_field.setFocus(Qt.FocusReason.OtherFocusReason)


def show_settings_confirmation(
    parent: QWidget,
    title: str,
    message: str,
    actions: tuple[DialogAction, ...],
    *,
    default_action: str,
    cancel_action: str,
) -> str:
    preference = getattr(parent, "_theme_preference", None)
    dialog = SettingsConfirmationDialog(
        parent,
        title,
        message,
        actions,
        default_action=default_action,
        cancel_action=cancel_action,
        theme_preference=preference,
    )
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.selected_action
    return cancel_action


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        child_layout = item.layout()
        widget = item.widget()
        if child_layout is not None:
            clear_layout(child_layout)
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()


def settings_button(
    text: str,
    variant: str = "ghost",
    glyph: str | None = None,
    callback: Callable | None = None,
) -> QPushButton:
    button = QPushButton(text)
    object_name = {
        "primary": "SettingsPrimaryButton",
        "danger": "SettingsDangerButton",
        "caution": "SettingsCautionButton",
        "small": "SettingsSmallButton",
        "ghost": "SettingsGhostButton",
    }.get(variant, "SettingsButton")
    button.setObjectName(object_name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if glyph:
        tokens = active_minimalist_tokens()
        icon_color = tokens.text_on_accent if variant in {"primary"} else tokens.text_secondary
        if variant == "danger":
            icon_color = tokens.danger
        if variant == "caution":
            icon_color = tokens.warning_indicator_text
        button.setIcon(glyph_icon(glyph, qcolor(icon_color), 16))
        button.setIconSize(QSize(16, 16))
    if callback is not None:
        button.clicked.connect(callback)
    return button


def action_button(text: str, callback: Callable) -> QPushButton:
    return settings_button(text, "small", None, callback)


def value_label(text: str, *, muted: bool = False) -> QLabel:
    label = QLabel(str(text))
    label.setObjectName("SettingsMutedText" if muted else "SettingsValueText")
    label.setWordWrap(True)
    return label


def status_pill(text: str, tone: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SettingsSmallPill")
    label.setProperty("tone", tone)
    return label


def locked_value_chip(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SettingsLockedChip")
    return label


def info_card(title: str, text: str, tone: str = "neutral") -> QWidget:
    card = GlassPanel(radius=8)
    apply_glass_theme(card, "settings_card_good" if tone == "good" else "settings_card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(5)
    title_label = QLabel(title)
    title_label.setObjectName("SettingsSectionTitle")
    text_label = QLabel(text)
    text_label.setObjectName("SettingsSectionDescription")
    text_label.setWordWrap(True)
    layout.addWidget(title_label)
    layout.addWidget(text_label)
    return card


def validation_summary_card(last_validation: str, errors: int, warnings: int, run_callback: Callable, report_callback: Callable) -> QWidget:
    card = GlassPanel(radius=8)
    apply_glass_theme(card, "settings_card")
    layout = QHBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(16)
    title_box = QVBoxLayout()
    title_box.setSpacing(3)
    title = QLabel("Validation Summary")
    title.setObjectName("SettingsSectionTitle")
    detail = QLabel(f"Last validation: {last_validation}")
    detail.setObjectName("SettingsSectionDescription")
    title_box.addWidget(title)
    title_box.addWidget(detail)
    layout.addLayout(title_box, 1)
    for label, value, tone in (("Errors", errors, "bad" if errors else "good"), ("Warnings", warnings, "warn" if warnings else "good")):
        pill = status_pill(f"{label}: {value}", tone)
        layout.addWidget(pill)
    layout.addWidget(settings_button("Run Validation Now", "small", None, run_callback))
    layout.addWidget(settings_button("View Validation Report", "small", None, report_callback))
    return card


def path_action_widget(
    path: str,
    change_callback: Callable,
    open_callback: Callable,
    *,
    change_enabled: bool = True,
    setting_path: str = "",
) -> QWidget:
    host = QWidget()
    host.setObjectName("SettingsButtonRow")
    if setting_path:
        host.setProperty("settingPath", setting_path)
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(7)
    label = value_label(compact_path_text(path), muted=True)
    label.setToolTip(path)
    label.setMinimumWidth(260)
    layout.addWidget(label, 1)
    change_button = settings_button("Change", "small", None, change_callback)
    change_button.setEnabled(change_enabled)
    change_button.setCursor(Qt.CursorShape.PointingHandCursor if change_enabled else Qt.CursorShape.ArrowCursor)
    if not change_enabled:
        change_button.setToolTip("Admin access required.")
    layout.addWidget(change_button)
    layout.addWidget(settings_button("Open", "small", None, open_callback))
    return host


def validate_source_path(path: Path, spec: SourceSpec) -> tuple[str, str]:
    text = str(path or "").strip()
    if not text:
        return "Not Configured", "warn"
    try:
        exists = path.exists()
    except OSError:
        return "Permission Issue", "bad"
    if not exists:
        return "Missing", "bad"
    try:
        if spec.kind == "folder" and not path.is_dir():
            return "Invalid Type", "bad"
        if spec.kind == "file" and not path.is_file():
            return "Invalid Type", "bad"
        if spec.extensions and path.suffix.casefold() not in {ext.casefold() for ext in spec.extensions}:
            return "Invalid Type", "bad"
        if spec.kind == "folder":
            next(path.iterdir(), None)
    except PermissionError:
        return "Permission Issue", "bad"
    except StopIteration:
        pass
    except OSError:
        return "Permission Issue", "bad"
    return "Connected", "good"


def validate_document_path(path: Path) -> tuple[str, str]:
    if not str(path or "").strip():
        return "Not Configured", "warn"
    try:
        if not path.exists():
            return "Missing", "bad"
        if not path.is_file():
            return "Invalid Type", "bad"
    except OSError:
        return "Permission Issue", "bad"
    return "Connected", "good"


def open_path(path: Path, notify: Callable[[str], None]) -> None:
    if not str(path or "").strip():
        notify("No path is configured.")
        return
    if not path.exists():
        notify(f"Path does not exist: {path}")
        return
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def open_path_text(path_text: str, notify: Callable[[str], None]) -> None:
    if not str(path_text or "").strip():
        notify("No path is configured.")
        return
    open_path(Path(path_text), notify)


def compact_path_text(path_text: str, *, max_chars: int = 64) -> str:
    text = str(path_text or "").strip()
    if len(text) <= max_chars:
        return text
    keep = max(12, (max_chars - 5) // 2)
    return f"{text[:keep]} ... {text[-keep:]}"


def confirm(parent: QWidget, title: str, message: str) -> bool:
    action = show_settings_confirmation(
        parent,
        title,
        message,
        (
            DialogAction("cancel", "Cancel", "secondary"),
            DialogAction("confirm", "Continue", "primary"),
        ),
        default_action="cancel",
        cancel_action="cancel",
    )
    return action == "confirm"


def format_timestamp(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "Not loaded this session"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return parsed.strftime("%Y-%m-%d %I:%M %p")


__all__ = ["AtlasMinimalistSettingsPage", "MinimalistSettingsContent"]
