from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
from copy import deepcopy
from pathlib import Path
from typing import Any

from core.globalization.runtime_paths import ensure_runtime_layout, get_runtime_paths

SETTINGS_FILE_NAME = "eoat_atlas_settings.json"
SETTINGS_DEFAULTS_FILE_NAME = "eoat_atlas_settings_defaults.json"
ADMIN_AUTH_FILE_NAME = "eoat_atlas_admin_auth.json"
ADMIN_AUTH_ALGORITHM = "pbkdf2_sha256"
ADMIN_AUTH_ITERATIONS = 200_000
DEVELOPMENT_DEFAULT_ADMIN_PASSWORD = "letmein67"
ADMIN_LOGOUT_TIMEOUT_SECONDS = (0, 15, 30, 60, 120, 300)

LOGGER = logging.getLogger(__name__)


DEFAULT_SETTINGS: dict[str, Any] = {
    "app": {
        "mode": "read_only",
        "theme": "dark",
        "accent": "atlas_blue",
        "animation_speed": "smooth",
        "text_density": "comfortable",
        "enhanced_small_text_contrast": True,
        "reduce_motion": False,
    },
    "paths": {
        "eoat_master_tracker": "",
        "press_capacity_workbook": "",
        "robot_workbook": "",
        "photos_root": "",
        "output_folder": "",
        "reference_docs_folder": "",
    },
    "data_loading": {
        "refresh_on_launch": True,
        "manual_refresh_only": False,
        "auto_refresh_enabled": False,
        "auto_refresh_minutes": 15,
        "detect_file_changes": True,
        "cache_last_good_data": True,
        "cache_photo_thumbnails": True,
        "show_cached_data_warning": True,
        "warn_when_files_changed": True,
        "show_last_refresh_timestamp": True,
    },
    "safety": {
        "read_only_mode": True,
        "block_workbook_writes": True,
        "disable_status_updates": True,
        "show_source_warnings": True,
        "warn_on_stale_data": True,
        "warn_on_incomplete_or_conflicting_data": True,
    },
    "search": {
        "default_action": "open_best_match",
        "prefer_exact_id_matches": True,
        "prefer_current_library_type": True,
        "show_partial_matches": True,
        "allow_alias_search": True,
        "include_eoats": True,
        "include_tools": True,
        "include_machines": True,
        "include_setup_packets": False,
        "include_reference_docs": False,
        "recent_items_limit": 15,
        "return_to_previous_workflow": True,
        "remember_last_library_tab": True,
    },
    "fit_check": {
        "compatibility_strictness": "strict",
        "always_show_entered_flow_items": True,
        "show_invalid_entries_in_red": True,
        "use_red_connectors_for_incompatible_links": True,
        "show_compatible_eoat_alternatives": True,
        "show_compatible_machine_alternatives": True,
        "show_compatible_tool_alternatives": True,
        "click_alternatives_to_apply": True,
        "save_recent_checks": True,
        "save_recent_only_when_complete": True,
        "save_recent_only_when_different": True,
        "save_recent_after_seconds": 20,
        "max_recent_fit_checks": 15,
    },
    "library": {
        "default_tab": "last_used",
        "eoat_sort": "eoat_id_ascending",
        "tool_sort": "tool_number_ascending",
        "machine_sort": "machine_number_ascending",
        "cards_per_page": 24,
        "stable_pagination": True,
        "show_previous_next_arrows": True,
        "compact_cards_on_small_screens": True,
        "use_cached_thumbnails": True,
        "show_placeholder_while_loading_images": True,
        "show_copy_icon_on_profile_ids": True,
        "show_copy_to_clipboard_toast": True,
    },
    "pdf": {
        "preview_before_save": True,
        "reference_footer_locked": True,
        "reference_footer_text": "For reference only",
        "open_in_app": True,
        "auto_save_if_closed_under_seconds": 10,
        "ask_location_when_save_clicked": True,
        "default_file_name_pattern": "SetupPacket_Tool-{tool}_Machine-{machine}_EOAT-{eoat}_{date}.pdf",
        "include_fit_check_summary": True,
        "include_eoat_profile": True,
        "include_tool_profile": True,
        "include_machine_profile": True,
        "include_compatibility_notes": True,
        "include_required_setup_notes": True,
        "include_photos": True,
        "include_reference_warnings": True,
    },
    "validation": {
        "run_on_startup": True,
        "show_sidebar_health_badge": True,
        "warning_level_display": "warnings_and_critical",
        "cleanroom_prefix": "CL-EOAT-",
        "plant4_prefix": "P4-EOAT-",
        "check_missing_eoat_ids": True,
        "check_duplicate_eoat_ids": True,
        "check_broken_photo_paths": True,
        "check_missing_compatibility_data": True,
        "check_unknown_machine_references": True,
        "check_unknown_tool_references": True,
        "check_cleanroom_id_format": True,
        "check_required_profile_fields": True,
    },
    "reference_documents": {
        "viewer_default": "open_in_app",
        "include_in_global_search": False,
        "warn_if_missing_or_outdated": True,
        "eoat_guidelines_path": "",
        "pm_checklist_path": "",
        "project_charter_path": "",
        "training_materials_path": "",
        "process_binder_references_path": "",
    },
    "diagnostics": {
        "activity_log_enabled": True,
        "last_app_launch": "",
        "last_successful_data_load": "",
        "last_validation": "",
        "last_pdf_generated": "",
        "last_source_path_change": "",
    },
    "admin": {
        "enabled": True,
        "logout_after_leaving_settings_seconds": 60,
        "password_hash_configured": False,
        "last_admin_sign_in": "",
    },
}


LEGACY_SETTING_ALIASES: tuple[tuple[str, str], ...] = (
    ("app.smooth_page_transitions", "app.animation_speed"),
    ("data_loading.warn_source_changed_since_load", "data_loading.warn_when_files_changed"),
    ("search.scope_eoats", "search.include_eoats"),
    ("search.scope_tools", "search.include_tools"),
    ("search.scope_machines", "search.include_machines"),
    ("search.scope_setup_packets", "search.include_setup_packets"),
    ("fit_check.save_recent_only_complete", "fit_check.save_recent_only_when_complete"),
    ("fit_check.maximum_recent_fit_checks", "fit_check.max_recent_fit_checks"),
    ("library.show_copy_icon_on_profiles", "library.show_copy_icon_on_profile_ids"),
    ("library.show_copied_toast", "library.show_copy_to_clipboard_toast"),
    ("pdf.ask_for_location_on_save", "pdf.ask_location_when_save_clicked"),
    ("reference_documents.eoat_standard_design_guidelines", "reference_documents.eoat_guidelines_path"),
    ("reference_documents.pm_checklist", "reference_documents.pm_checklist_path"),
    ("reference_documents.project_charter", "reference_documents.project_charter_path"),
    ("reference_documents.training_materials", "reference_documents.training_materials_path"),
    ("reference_documents.process_binder_references", "reference_documents.process_binder_references_path"),
)


SECTION_TO_ROOT_KEY = {
    "data_sources": "paths",
    "refresh_cache": "data_loading",
    "read_only_safety": "safety",
    "search_navigation": "search",
    "fit_check": "fit_check",
    "library": "library",
    "display_accessibility": "app",
    "setup_packet_pdf": "pdf",
    "validation_health": "validation",
    "reference_documents": "reference_documents",
    "diagnostics_support": "diagnostics",
    "about": "diagnostics",
}


def settings_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else _runtime_settings_path(SETTINGS_FILE_NAME)


def settings_defaults_path(path: str | Path | None = None, *, settings_file: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    if settings_file is not None:
        return Path(settings_file).with_name(SETTINGS_DEFAULTS_FILE_NAME)
    return _runtime_settings_path(SETTINGS_DEFAULTS_FILE_NAME)


def admin_auth_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else _runtime_settings_path(ADMIN_AUTH_FILE_NAME)


def get_default_settings() -> dict[str, Any]:
    return deepcopy(DEFAULT_SETTINGS)


def get_effective_default_settings(defaults_path: str | Path | None = None, *, settings_file: str | Path | None = None) -> dict[str, Any]:
    baseline = get_default_settings()
    custom = load_custom_defaults(defaults_path, settings_file=settings_file)
    if custom:
        baseline = validate_settings_schema(merge_missing_defaults(custom, defaults=baseline), defaults=baseline)
    return baseline


def custom_defaults_status(defaults_path: str | Path | None = None, *, settings_file: str | Path | None = None) -> dict[str, Any]:
    target = settings_defaults_path(defaults_path, settings_file=settings_file)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"configured": False, "path": str(target), "updated_at": ""}
    if isinstance(payload, dict) and isinstance(payload.get("defaults"), dict):
        return {
            "configured": True,
            "path": str(target),
            "updated_at": str(payload.get("updated_at") or ""),
        }
    return {"configured": False, "path": str(target), "updated_at": ""}


def load_custom_defaults(defaults_path: str | Path | None = None, *, settings_file: str | Path | None = None) -> dict[str, Any] | None:
    target = settings_defaults_path(defaults_path, settings_file=settings_file)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict) and isinstance(payload.get("defaults"), dict):
        return payload["defaults"]
    if isinstance(payload, dict):
        return payload
    return None


def save_custom_defaults(settings: dict[str, Any], defaults_path: str | Path | None = None, *, settings_file: str | Path | None = None, updated_at: str = "") -> Path:
    baseline = get_default_settings()
    normalized = validate_settings_schema(merge_missing_defaults(settings, defaults=baseline), defaults=baseline)
    target = settings_defaults_path(defaults_path, settings_file=settings_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": str(updated_at or ""),
        "defaults": normalized,
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def clear_custom_defaults(defaults_path: str | Path | None = None, *, settings_file: str | Path | None = None) -> bool:
    target = settings_defaults_path(defaults_path, settings_file=settings_file)
    try:
        target.unlink()
    except FileNotFoundError:
        return False
    return True


def merge_missing_defaults(existing_settings: dict[str, Any] | None, *, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = deepcopy(existing_settings) if isinstance(existing_settings, dict) else {}
    baseline = deepcopy(defaults) if isinstance(defaults, dict) else get_default_settings()
    for legacy_path, current_path in LEGACY_SETTING_ALIASES:
        if _path_exists(existing, legacy_path) and not _path_exists(existing, current_path):
            value = _get_path(existing, legacy_path)
            if legacy_path == "app.smooth_page_transitions":
                value = "smooth" if bool(value) else "reduced"
            _set_path(existing, current_path, value)
    merged = _deep_merge(baseline, existing)
    for legacy_path, _current_path in LEGACY_SETTING_ALIASES:
        _drop_path(merged, legacy_path)
    return merged


def load_settings(path: str | Path | None = None) -> dict[str, Any]:
    target = settings_path(path)
    baseline = get_effective_default_settings(settings_file=target)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return deepcopy(baseline)
    return validate_settings_schema(merge_missing_defaults(raw, defaults=baseline), defaults=baseline)


def save_settings(settings: dict[str, Any], path: str | Path | None = None) -> Path:
    target = settings_path(path)
    baseline = get_effective_default_settings(settings_file=target)
    normalized = validate_settings_schema(merge_missing_defaults(settings, defaults=baseline), defaults=baseline)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(normalized, indent=2, sort_keys=True), encoding="utf-8")
    return target


def reset_section(settings: dict[str, Any], section_name: str, *, settings_file: str | Path | None = None) -> dict[str, Any]:
    defaults = get_effective_default_settings(settings_file=settings_file)
    normalized = validate_settings_schema(merge_missing_defaults(settings, defaults=defaults), defaults=defaults)
    root_key = SECTION_TO_ROOT_KEY.get(str(section_name or ""))
    if root_key and root_key in defaults:
        normalized[root_key] = deepcopy(defaults[root_key])
    return normalized


def reset_all_settings(path: str | Path | None = None) -> dict[str, Any]:
    defaults = get_effective_default_settings(settings_file=settings_path(path))
    save_settings(defaults, path)
    return defaults


def validate_settings_schema(settings: dict[str, Any], *, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = merge_missing_defaults(settings, defaults=defaults)
    for locked_path in (
        "safety.read_only_mode",
        "safety.block_workbook_writes",
        "safety.disable_status_updates",
        "pdf.reference_footer_locked",
    ):
        _set_path(normalized, locked_path, True)
    if not str(_get_path(normalized, "pdf.reference_footer_text") or "").strip():
        _set_path(normalized, "pdf.reference_footer_text", "For reference only")
    _normalize_choice(normalized, "app.theme", {"dark", "light", "system"}, "dark")
    _normalize_choice(normalized, "app.accent", {"atlas_blue", "neutral_gray", "high_contrast_blue"}, "atlas_blue")
    _normalize_choice(normalized, "app.animation_speed", {"reduced", "standard", "smooth"}, "smooth")
    _normalize_choice(normalized, "app.text_density", {"comfortable", "compact", "large"}, "comfortable")
    _normalize_choice(
        normalized,
        "search.default_action",
        {"open_best_match", "show_result_preview", "ask_when_multiple"},
        "open_best_match",
    )
    _normalize_choice(normalized, "fit_check.compatibility_strictness", {"strict", "balanced", "loose"}, "strict")
    _normalize_choice(normalized, "library.default_tab", {"eoats", "tools", "machines", "last_used"}, "last_used")
    _normalize_choice(
        normalized,
        "library.eoat_sort",
        {"eoat_id_ascending", "eoat_id_descending", "status", "type", "last_updated"},
        "eoat_id_ascending",
    )
    _normalize_choice(
        normalized,
        "library.tool_sort",
        {"tool_number_ascending", "tool_number_descending", "part_name", "compatible_machines_count"},
        "tool_number_ascending",
    )
    _normalize_choice(
        normalized,
        "library.machine_sort",
        {"machine_number_ascending", "machine_number_descending", "robot_type", "current_eoat"},
        "machine_number_ascending",
    )
    _normalize_choice(
        normalized,
        "validation.warning_level_display",
        {"critical_only", "warnings_and_critical", "all_validation_details"},
        "warnings_and_critical",
    )
    _normalize_choice(
        normalized,
        "reference_documents.viewer_default",
        {"open_in_app", "open_externally", "ask_every_time"},
        "open_in_app",
    )
    for dotted_path in (
        "data_loading.auto_refresh_minutes",
        "search.recent_items_limit",
        "fit_check.save_recent_after_seconds",
        "fit_check.max_recent_fit_checks",
        "library.cards_per_page",
        "pdf.auto_save_if_closed_under_seconds",
    ):
        _normalize_int(normalized, dotted_path)
    _normalize_int_choice(normalized, "data_loading.auto_refresh_minutes", {5, 10, 15, 30, 60}, 15)
    _normalize_int_choice(normalized, "search.recent_items_limit", {5, 10, 15, 25, 50}, 15)
    _normalize_int_choice(normalized, "fit_check.save_recent_after_seconds", {5, 10, 20, 30, 60}, 20)
    _normalize_int_choice(normalized, "fit_check.max_recent_fit_checks", {5, 10, 15, 25, 50}, 15)
    _normalize_int_choice(normalized, "library.cards_per_page", {12, 24, 48}, 24)
    _normalize_int_choice(normalized, "pdf.auto_save_if_closed_under_seconds", {5, 10, 15, 30}, 10)
    _normalize_admin_logout_timeout(normalized)
    for root_key, root_value in DEFAULT_SETTINGS.items():
        if not isinstance(root_value, dict):
            continue
        for key, default_value in root_value.items():
            value_path = f"{root_key}.{key}"
            if isinstance(default_value, bool):
                _normalize_bool(normalized, value_path)
            elif isinstance(default_value, str):
                _normalize_str(normalized, value_path)
    return normalized


def admin_password_configured(path: str | Path | None = None) -> bool:
    payload = _load_admin_auth(path)
    return bool(payload.get("password_hash") and payload.get("salt"))


def ensure_default_admin_password(path: str | Path | None = None) -> bool:
    if admin_password_configured(path):
        return False
    set_admin_password(DEVELOPMENT_DEFAULT_ADMIN_PASSWORD, path)
    return True


def set_admin_password(password: str, path: str | Path | None = None) -> Path:
    text = str(password or "")
    if not text:
        raise ValueError("Admin password cannot be empty.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", text.encode("utf-8"), salt, ADMIN_AUTH_ITERATIONS)
    payload = {
        "algorithm": ADMIN_AUTH_ALGORITHM,
        "iterations": ADMIN_AUTH_ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "password_hash": base64.b64encode(digest).decode("ascii"),
    }
    target = admin_auth_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def verify_admin_password(password: str, path: str | Path | None = None) -> bool:
    payload = _load_admin_auth(path)
    try:
        salt = base64.b64decode(str(payload.get("salt") or ""), validate=True)
        expected = base64.b64decode(str(payload.get("password_hash") or ""), validate=True)
        iterations = int(payload.get("iterations") or ADMIN_AUTH_ITERATIONS)
    except (ValueError, TypeError):
        return False
    if not salt or not expected:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


def _load_admin_auth(path: str | Path | None = None) -> dict[str, Any]:
    target = admin_auth_path(path)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _runtime_settings_path(filename: str) -> Path:
    runtime = ensure_runtime_layout(get_runtime_paths())
    return runtime.settings_dir / filename


def _deep_merge(defaults: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(defaults)
    for key, value in existing.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _lookup(settings: dict[str, Any], dotted_path: str) -> tuple[dict[str, Any] | None, str]:
    keys = dotted_path.split(".")
    node: Any = settings
    for key in keys[:-1]:
        if not isinstance(node, dict):
            return None, keys[-1]
        node = node.get(key)
    return node if isinstance(node, dict) else None, keys[-1]


def _path_exists(settings: dict[str, Any], dotted_path: str) -> bool:
    node, key = _lookup(settings, dotted_path)
    return node is not None and key in node


def _get_path(settings: dict[str, Any], dotted_path: str) -> Any:
    node, key = _lookup(settings, dotted_path)
    return None if node is None else node.get(key)


def _set_path(settings: dict[str, Any], dotted_path: str, value: Any) -> None:
    keys = dotted_path.split(".")
    node = settings
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[keys[-1]] = deepcopy(value)


def _drop_path(settings: dict[str, Any], dotted_path: str) -> None:
    node, key = _lookup(settings, dotted_path)
    if node is not None:
        node.pop(key, None)


def _normalize_choice(settings: dict[str, Any], dotted_path: str, choices: set[str], default: str) -> None:
    node, key = _lookup(settings, dotted_path)
    if node is None:
        return
    text = str(node.get(key, "") or "").strip().casefold().replace(" ", "_").replace("-", "_")
    node[key] = text if text in choices else default


def _normalize_int(settings: dict[str, Any], dotted_path: str) -> None:
    node, key = _lookup(settings, dotted_path)
    if node is None:
        return
    default_node, _ = _lookup(DEFAULT_SETTINGS, dotted_path)
    default = default_node.get(key) if default_node is not None else 0
    try:
        value = int(str(node.get(key, "")).strip())
    except ValueError:
        value = int(default)
    node[key] = max(0, value)


def _normalize_int_choice(settings: dict[str, Any], dotted_path: str, choices: set[int], default: int) -> None:
    node, key = _lookup(settings, dotted_path)
    if node is None:
        return
    try:
        value = int(node.get(key))
    except (TypeError, ValueError):
        value = int(default)
    node[key] = value if value in choices else int(default)


def _normalize_admin_logout_timeout(settings: dict[str, Any]) -> None:
    dotted_path = "admin.logout_after_leaving_settings_seconds"
    node, key = _lookup(settings, dotted_path)
    if node is None:
        return
    raw_value = node.get(key)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = 60
        LOGGER.warning("Invalid admin auto-logout timeout %r; repaired to 60 seconds.", raw_value)
    else:
        if value not in ADMIN_LOGOUT_TIMEOUT_SECONDS:
            LOGGER.warning("Invalid admin auto-logout timeout %r; repaired to 60 seconds.", raw_value)
            value = 60
    node[key] = value


def _normalize_bool(settings: dict[str, Any], dotted_path: str) -> None:
    node, key = _lookup(settings, dotted_path)
    if node is None:
        return
    value = node.get(key)
    if isinstance(value, str):
        node[key] = value.strip().casefold() in {"1", "true", "yes", "on", "enabled"}
    else:
        node[key] = bool(value)


def _normalize_str(settings: dict[str, Any], dotted_path: str) -> None:
    node, key = _lookup(settings, dotted_path)
    if node is None:
        return
    value = node.get(key)
    node[key] = "" if value is None else str(value)


__all__ = [
    "ADMIN_AUTH_FILE_NAME",
    "ADMIN_AUTH_ITERATIONS",
    "ADMIN_LOGOUT_TIMEOUT_SECONDS",
    "DEFAULT_SETTINGS",
    "DEVELOPMENT_DEFAULT_ADMIN_PASSWORD",
    "SECTION_TO_ROOT_KEY",
    "SETTINGS_DEFAULTS_FILE_NAME",
    "clear_custom_defaults",
    "custom_defaults_status",
    "admin_auth_path",
    "admin_password_configured",
    "ensure_default_admin_password",
    "get_effective_default_settings",
    "get_default_settings",
    "load_settings",
    "load_custom_defaults",
    "merge_missing_defaults",
    "reset_all_settings",
    "reset_section",
    "save_custom_defaults",
    "save_settings",
    "set_admin_password",
    "settings_defaults_path",
    "settings_path",
    "validate_settings_schema",
    "verify_admin_password",
]
