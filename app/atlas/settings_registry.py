"""GUI-independent EOAT Atlas Settings registry shared by desktop and API."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Kept local to this non-GUI registry so a headless API never imports PySide.
ADMIN_LOGOUT_TIMEOUT_SECONDS = (0, 15, 30, 60, 120, 300)

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
    SectionSpec("data_sources", "Data Services and Engineering Files", "API, network documents, and controlled imports", "grid"),
    SectionSpec("refresh_cache", "Server, Synchronization, and Cache", "Server refresh and disposable cache behavior", "swap"),
    SectionSpec("read_only_safety", "Server Write Safety", "Transactions, authorization, conflicts, and offline behavior", "status"),
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
    *(SettingDefinition("data_sources", f"paths.{spec.key}", spec.title, "path", "", "Atlas data source resolver", "after Save + Deep Refresh") for spec in SOURCE_SPECS),
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
    SettingDefinition("refresh_cache", "data_loading.automatic_polling_enabled", "Automatic polling", "checkbox", True, "DataFreshnessService", "after Save"),
    SettingDefinition("refresh_cache", "data_loading.polling_interval_seconds", "Polling interval", "segmented", 60, "DataFreshnessService", "after Save", options=(SettingOption(15, "15 sec"), SettingOption(30, "30 sec"), SettingOption(60, "1 min"), SettingOption(300, "5 min"), SettingOption(900, "15 min"), SettingOption(1800, "30 min"))),
    SettingDefinition("refresh_cache", "data_loading.refresh_when_data_changes", "New-data behavior", "segmented", "notify", "DataFreshnessService", "after Save", options=(SettingOption("automatic", "Refresh safely"), SettingOption("notify", "Notify me"))),
    SettingDefinition("refresh_cache", "data_loading.pause_refresh_while_editing", "Pause refresh while editing", "checkbox", True, "DataFreshnessService", "after Save"),
    SettingDefinition("refresh_cache", "data_loading.poll_while_minimized", "Poll while minimized", "checkbox", True, "QtDataFreshnessPoller", "after Save"),
    SettingDefinition("refresh_cache", "data_loading.timestamp_display", "Timestamp display", "segmented", "relative", "DataFreshnessService", "after Save", options=(SettingOption("relative", "Relative"), SettingOption("exact", "Exact"))),
    SettingDefinition("read_only_safety", "safety.read_only_mode", "Production workbook sync disabled", "locked", True, "production workbook mutation guard", "always enforced", locked=True),
    SettingDefinition("read_only_safety", "safety.block_workbook_writes", "Block production workbook writes", "locked", True, "production workbook write guard", "always enforced", "Prevents production workbook mutation unless an explicit config gate is enabled.", locked=True),
    SettingDefinition("read_only_safety", "safety.disable_status_updates", "Queue status updates locally", "locked", True, "pending update guard", "always enforced", locked=True),
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
    SettingDefinition("diagnostics_support", "admin.authentication_provider", "Settings authentication provider", "status", "unselected", "API authentication configuration", "automatic"),
    SettingDefinition("diagnostics_support", "admin.last_admin_sign_in", "Last admin sign-in", "status", "", "Settings page admin session metadata", "automatic"),
)

