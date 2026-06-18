from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from core.resources import writable_config_path

THEME_CHOICES = ("light", "dark", "system")
COLOR_SCHEME_CHOICES = ("atlas_blue", "nolato_logo")
STARTUP_PAGE_CHOICES = (
    "home",
    "what",
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


@dataclass(frozen=True)
class AtlasSettings:
    theme: str = "light"
    color_scheme: str = "atlas_blue"
    startup_page: str = "home"
    default_search_mode: str = "smart"
    photo_viewer_behavior: str = "in_app"
    lazy_photo_previews: bool = False
    carousel_prefetch: bool = True
    show_advanced_diagnostics: bool = True
    compact_list_mode: bool = False
    card_density: str = "comfortable"
    open_after_export: bool = False
    confirm_external_open: bool = False
    auto_refresh_on_startup: bool = True

    def normalized(self) -> AtlasSettings:
        return AtlasSettings(
            theme=_choice(self.theme, THEME_CHOICES, "light"),
            color_scheme=_choice(self.color_scheme, COLOR_SCHEME_CHOICES, "atlas_blue"),
            startup_page=_choice(self.startup_page, STARTUP_PAGE_CHOICES, "home"),
            default_search_mode=_choice(self.default_search_mode, SEARCH_MODE_CHOICES, "smart"),
            photo_viewer_behavior=_choice(self.photo_viewer_behavior, PHOTO_BEHAVIOR_CHOICES, "in_app"),
            lazy_photo_previews=bool(self.lazy_photo_previews),
            carousel_prefetch=bool(self.carousel_prefetch),
            show_advanced_diagnostics=bool(self.show_advanced_diagnostics),
            compact_list_mode=bool(self.compact_list_mode),
            card_density=_choice(self.card_density, CARD_DENSITY_CHOICES, "comfortable"),
            open_after_export=bool(self.open_after_export),
            confirm_external_open=bool(self.confirm_external_open),
            auto_refresh_on_startup=bool(self.auto_refresh_on_startup),
        )

    @property
    def effective_theme(self) -> str:
        return "dark" if self.theme == "dark" else "light"


def atlas_settings_path() -> Path:
    return writable_config_path("atlas_settings.json")


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


__all__ = [
    "AtlasSettings",
    "CARD_DENSITY_CHOICES",
    "COLOR_SCHEME_CHOICES",
    "PHOTO_BEHAVIOR_CHOICES",
    "SEARCH_MODE_CHOICES",
    "STARTUP_PAGE_CHOICES",
    "THEME_CHOICES",
    "atlas_settings_path",
    "load_atlas_settings",
    "save_atlas_settings",
]
