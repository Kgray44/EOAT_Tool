from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from core.globalization.runtime_paths import ensure_runtime_layout, get_runtime_paths

THEME_CHOICES = ("light", "dark", "system")
COLOR_SCHEME_CHOICES = ("atlas_blue", "nolato_logo", "industrial_graphite", "aurora_tech")
PHOTO_PRELOAD_CHOICES = ("off", "conservative", "balanced", "aggressive")
QR_PAYLOAD_MODE_CHOICES = ("compact", "deep_link", "json", "full")
QR_ERROR_CORRECTION_CHOICES = ("low", "medium", "quartile", "high")
QR_LABEL_SIZE_CHOICES = ("small", "medium", "large")
STARTUP_PAGE_CHOICES = (
    "home",
    "what",
    "setup_packet",
    "eoats",
    "machines",
    "tools",
    "matrix",
    "overview",
    "photos",
    "standards",
    "pm",
    "library",
    "reports",
    "diagnostics",
)
SEARCH_MODE_CHOICES = ("smart", "eoat", "machine", "tool")
PHOTO_BEHAVIOR_CHOICES = ("in_app", "open_folder", "external")
CARD_DENSITY_CHOICES = ("comfortable", "compact")
SETUP_PACKET_TYPE_CHOICES = (
    "standard_changeover",
    "setup_verification",
    "maintenance_pm",
    "documentation_review",
)
SETUP_PACKET_PHOTO_CHOICES = ("none", "key", "all")
SETUP_PACKET_OPEN_CHOICES = ("in_app", "external_pdf", "open_folder", "ask_each_time")
SETUP_PACKET_DETAIL_CHOICES = ("standard", "detailed")


@dataclass(frozen=True)
class AtlasSettings:
    theme: str = "light"
    color_scheme: str = "atlas_blue"
    startup_page: str = "home"
    default_search_mode: str = "smart"
    photo_viewer_behavior: str = "in_app"
    lazy_photo_previews: bool = False
    carousel_prefetch: bool = True
    photo_preload_mode: str = "conservative"
    photo_cache_limit_mb: int = 1024
    show_advanced_diagnostics: bool = True
    compact_list_mode: bool = False
    hide_tools_missing_eoat_links: bool = False
    exclude_unaudited_tools: bool = True
    card_density: str = "comfortable"
    open_after_export: bool = False
    confirm_external_open: bool = False
    auto_refresh_on_startup: bool = True
    enable_qr_codes: bool = False
    qr_payload_mode: str = "compact"
    qr_error_correction: str = "high"
    qr_default_label_size: str = "medium"
    qr_show_payload_preview_before_export: bool = True
    qr_warn_phone_like_payloads: bool = True
    command_palette_enabled: bool = True
    setup_packet_default_type: str = "standard_changeover"
    setup_packet_photo_inclusion: str = "key"
    setup_packet_open_after_generation: str = "ask_each_time"
    setup_packet_include_qr_label: bool = False
    setup_packet_detail_level: str = "standard"
    setup_packet_allow_manual_override_combinations: bool = False
    recent_eoats: tuple[str, ...] = ()
    pinned_eoats: tuple[str, ...] = ()
    recent_machines: tuple[str, ...] = ()
    pinned_machines: tuple[str, ...] = ()
    recent_tools: tuple[str, ...] = ()
    pinned_tools: tuple[str, ...] = ()

    def normalized(self) -> AtlasSettings:
        return AtlasSettings(
            theme=_choice(self.theme, THEME_CHOICES, "light"),
            color_scheme=_choice(self.color_scheme, COLOR_SCHEME_CHOICES, "atlas_blue"),
            startup_page=_choice(self.startup_page, STARTUP_PAGE_CHOICES, "home"),
            default_search_mode=_choice(self.default_search_mode, SEARCH_MODE_CHOICES, "smart"),
            photo_viewer_behavior=_choice(self.photo_viewer_behavior, PHOTO_BEHAVIOR_CHOICES, "in_app"),
            lazy_photo_previews=bool(self.lazy_photo_previews),
            carousel_prefetch=bool(self.carousel_prefetch),
            photo_preload_mode=_choice(self.photo_preload_mode, PHOTO_PRELOAD_CHOICES, "conservative"),
            photo_cache_limit_mb=_bounded_int(self.photo_cache_limit_mb, 128, 8192, 1024),
            show_advanced_diagnostics=bool(self.show_advanced_diagnostics),
            compact_list_mode=bool(self.compact_list_mode),
            hide_tools_missing_eoat_links=bool(self.hide_tools_missing_eoat_links),
            exclude_unaudited_tools=bool(self.exclude_unaudited_tools),
            card_density=_choice(self.card_density, CARD_DENSITY_CHOICES, "comfortable"),
            open_after_export=bool(self.open_after_export),
            confirm_external_open=bool(self.confirm_external_open),
            auto_refresh_on_startup=bool(self.auto_refresh_on_startup),
            enable_qr_codes=bool(self.enable_qr_codes),
            qr_payload_mode=_qr_mode_choice(self.qr_payload_mode),
            qr_error_correction=_choice(self.qr_error_correction, QR_ERROR_CORRECTION_CHOICES, "high"),
            qr_default_label_size=_choice(self.qr_default_label_size, QR_LABEL_SIZE_CHOICES, "medium"),
            qr_show_payload_preview_before_export=bool(self.qr_show_payload_preview_before_export),
            qr_warn_phone_like_payloads=True,
            command_palette_enabled=bool(self.command_palette_enabled),
            setup_packet_default_type=_choice(
                self.setup_packet_default_type,
                SETUP_PACKET_TYPE_CHOICES,
                "standard_changeover",
            ),
            setup_packet_photo_inclusion=_choice(
                self.setup_packet_photo_inclusion,
                SETUP_PACKET_PHOTO_CHOICES,
                "key",
            ),
            setup_packet_open_after_generation=_choice(
                self.setup_packet_open_after_generation,
                SETUP_PACKET_OPEN_CHOICES,
                "ask_each_time",
            ),
            setup_packet_include_qr_label=bool(self.setup_packet_include_qr_label),
            setup_packet_detail_level=_choice(self.setup_packet_detail_level, SETUP_PACKET_DETAIL_CHOICES, "standard"),
            setup_packet_allow_manual_override_combinations=bool(self.setup_packet_allow_manual_override_combinations),
            recent_eoats=_id_tuple(self.recent_eoats),
            pinned_eoats=_id_tuple(self.pinned_eoats, limit=50),
            recent_machines=_id_tuple(self.recent_machines),
            pinned_machines=_id_tuple(self.pinned_machines, limit=50),
            recent_tools=_id_tuple(self.recent_tools),
            pinned_tools=_id_tuple(self.pinned_tools, limit=50),
        )

    @property
    def effective_theme(self) -> str:
        return "dark" if self.theme == "dark" else "light"


def atlas_settings_path() -> Path:
    runtime = ensure_runtime_layout(get_runtime_paths())
    return runtime.settings_dir / "atlas_settings.json"


def load_atlas_settings(path: str | Path | None = None) -> AtlasSettings:
    target = Path(path) if path is not None else atlas_settings_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AtlasSettings()
    if not isinstance(raw, dict):
        return AtlasSettings()
    names = {field.name for field in fields(AtlasSettings)}
    values: dict[str, Any] = {name: raw.get(name) for name in names if name in raw}
    return AtlasSettings(**values).normalized()


def save_atlas_settings(settings: AtlasSettings, path: str | Path | None = None) -> Path:
    normalized = settings.normalized()
    target = Path(path) if path is not None else atlas_settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(normalized), indent=2, sort_keys=True), encoding="utf-8")
    return target


def _choice(value: str, choices: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().casefold().replace(" ", "_").replace("-", "_")
    return text if text in choices else default


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return default
    return max(minimum, min(maximum, parsed))


def _qr_mode_choice(value: str) -> str:
    text = str(value or "").strip().casefold().replace(" ", "_").replace("-", "_")
    aliases = {
        "compact_label": "compact",
        "compact_human_readable": "compact",
        "compact_human_readable_text": "compact",
        "atlas_deep_link": "deep_link",
        "deep": "deep_link",
        "deeplink": "deep_link",
        "json_record": "json",
        "full_offline": "full",
        "full_offline_record": "full",
        "id": "compact",
        "eoat_id": "compact",
        "id_only": "compact",
    }
    text = aliases.get(text, text)
    return text if text in QR_PAYLOAD_MODE_CHOICES else "compact"


def _id_tuple(value: Any, *, limit: int = 12) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list | tuple | set):
        raw_items = list(value)
    else:
        raw_items = []
    items: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        text = str(raw or "").strip()
        folded = text.casefold()
        if not text or folded in seen:
            continue
        seen.add(folded)
        items.append(text)
        if len(items) >= limit:
            break
    return tuple(items)


__all__ = [
    "AtlasSettings",
    "CARD_DENSITY_CHOICES",
    "COLOR_SCHEME_CHOICES",
    "PHOTO_BEHAVIOR_CHOICES",
    "PHOTO_PRELOAD_CHOICES",
    "QR_LABEL_SIZE_CHOICES",
    "QR_ERROR_CORRECTION_CHOICES",
    "QR_PAYLOAD_MODE_CHOICES",
    "SEARCH_MODE_CHOICES",
    "STARTUP_PAGE_CHOICES",
    "SETUP_PACKET_DETAIL_CHOICES",
    "SETUP_PACKET_OPEN_CHOICES",
    "SETUP_PACKET_PHOTO_CHOICES",
    "SETUP_PACKET_TYPE_CHOICES",
    "THEME_CHOICES",
    "atlas_settings_path",
    "load_atlas_settings",
    "save_atlas_settings",
]
