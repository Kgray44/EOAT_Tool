from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from .style import MINIMALIST_STYLES

VALID_THEME_PREFERENCES = ("dark", "light", "system")
REQUIRED_THEME_TOKENS = (
    "app_background",
    "page_background",
    "panel_background",
    "card_background",
    "card_background_hover",
    "input_background",
    "border",
    "border_strong",
    "text_primary",
    "text_secondary",
    "text_muted",
    "accent",
    "accent_hover",
    "accent_soft",
    "success",
    "warning",
    "danger",
    "shadow_glow",
    "disabled_background",
    "disabled_text",
    "disabled_border",
    "dialog_background",
    "dialog_border",
    "dialog_title",
    "dialog_text",
    "dialog_button_background",
    "dialog_button_border",
    "dialog_button_text",
    "primary_button_background",
    "primary_button_text",
    "disabled_button_background",
    "disabled_button_text",
    "warning_indicator_background",
    "warning_indicator_text",
    "warning_indicator_border",
)


@dataclass(frozen=True)
class MinimalistThemeTokens:
    app_background: str
    page_background: str
    panel_background: str
    card_background: str
    card_background_hover: str
    input_background: str
    border: str
    border_strong: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_soft: str
    success: str
    warning: str
    danger: str
    shadow_glow: str
    disabled_background: str
    disabled_text: str
    disabled_border: str
    dialog_background: str = "#041226"
    dialog_border: str = "#4e7ebc"
    dialog_title: str = "#f8fbff"
    dialog_text: str = "#d7e2f0"
    dialog_button_background: str = "#061226"
    dialog_button_border: str = "#4e7ebc"
    dialog_button_text: str = "#f1f6ff"
    primary_button_background: str = "#1f87ff"
    primary_button_text: str = "#ffffff"
    disabled_button_background: str = "#091a34"
    disabled_button_text: str = "#7f90a7"
    warning_indicator_background: str = "#3a2508"
    warning_indicator_text: str = "#ffd08a"
    warning_indicator_border: str = "#ffb145"
    text_on_accent: str = "#ffffff"
    panel_background_alt: str = "#07152b"
    selected_sidebar_background: str = "#dbeeff"
    selected_sidebar_border: str = "#1f87ff"
    secondary_button_background: str = "#f7fbff"
    danger_soft: str = "#ffe7ea"
    warning_soft: str = "#fff3d9"
    success_soft: str = "#dff7ea"
    scrollbar_track: str = "#dbe5f0"
    scrollbar_handle: str = "#9eb5ce"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


THEME_TOKENS: dict[str, MinimalistThemeTokens] = {
    "dark": MinimalistThemeTokens(
        app_background="#020812",
        page_background="#061222",
        panel_background="#041226",
        card_background="#061329",
        card_background_hover="#103260",
        input_background="#051124",
        border="#4e7ebc",
        border_strong="#1f87ff",
        text_primary="#f8fbff",
        text_secondary="#d7e2f0",
        text_muted="#aebdd1",
        accent="#1f87ff",
        accent_hover="#42a6ff",
        accent_soft="#0c365f",
        success="#36d86a",
        warning="#ffb145",
        danger="#ff5c6c",
        shadow_glow="#1f87ff",
        disabled_background="#091a34",
        disabled_text="#7f90a7",
        disabled_border="#5b80ae",
        dialog_background="#041226",
        dialog_border="#4e7ebc",
        dialog_title="#f8fbff",
        dialog_text="#d7e2f0",
        dialog_button_background="#061226",
        dialog_button_border="#4e7ebc",
        dialog_button_text="#f1f6ff",
        primary_button_background="#1f87ff",
        primary_button_text="#ffffff",
        disabled_button_background="#091a34",
        disabled_button_text="#7f90a7",
        warning_indicator_background="#3a2508",
        warning_indicator_text="#ffd08a",
        warning_indicator_border="#ffb145",
        panel_background_alt="#020b18",
        selected_sidebar_background="#074aa4",
        selected_sidebar_border="#47b0ff",
        secondary_button_background="#061226",
        danger_soft="#300812",
        warning_soft="#76470c",
        success_soft="#074a32",
        scrollbar_track="#040c18",
        scrollbar_handle="#3a8fff",
    ),
    "light": MinimalistThemeTokens(
        app_background="#edf3f8",
        page_background="#f5f8fc",
        panel_background="#fbfdff",
        card_background="#ffffff",
        card_background_hover="#f0f6fd",
        input_background="#f8fbff",
        border="#c8d6e5",
        border_strong="#8aa5c0",
        text_primary="#0c1b2e",
        text_secondary="#314960",
        text_muted="#61758c",
        accent="#1f87ff",
        accent_hover="#126fe0",
        accent_soft="#dceeff",
        success="#168a52",
        warning="#a6670b",
        danger="#c73545",
        shadow_glow="#6f93bb",
        disabled_background="#e8eef5",
        disabled_text="#91a1b3",
        disabled_border="#d3deea",
        dialog_background="#ffffff",
        dialog_border="#b6c7da",
        dialog_title="#0c1b2e",
        dialog_text="#314960",
        dialog_button_background="#ffffff",
        dialog_button_border="#b6c7da",
        dialog_button_text="#0c1b2e",
        primary_button_background="#1f87ff",
        primary_button_text="#ffffff",
        disabled_button_background="#e8eef5",
        disabled_button_text="#91a1b3",
        warning_indicator_background="#fff3d9",
        warning_indicator_text="#714400",
        warning_indicator_border="#d99627",
        panel_background_alt="#f2f7fc",
        selected_sidebar_background="#dceeff",
        selected_sidebar_border="#1f87ff",
        secondary_button_background="#f7fbff",
        danger_soft="#ffe7ea",
        warning_soft="#fff2d7",
        success_soft="#def6e9",
        scrollbar_track="#e6edf5",
        scrollbar_handle="#9eb5ce",
    ),
}


GLASS_TOKENS: dict[str, dict[str, dict[str, Any]]] = {
    "dark": {
        "settings_sidebar": {"alpha": 112, "border_alpha": 92, "border_color": "#1f87ff", "fill_color": "#041226"},
        "settings_main": {"alpha": 116, "border_alpha": 92, "border_color": "#1f87ff", "fill_color": "#041226"},
        "settings_bottom": {"alpha": 122, "border_alpha": 36, "border_color": "#315f9d", "fill_color": "#020b18"},
        "settings_section": {"alpha": 72, "border_alpha": 64, "border_color": "#286fa8", "fill_color": "#061329"},
        "settings_row": {"alpha": 66, "border_alpha": 56, "border_color": "#286fa8", "fill_color": "#061329"},
        "settings_card": {"alpha": 76, "border_alpha": 76, "border_color": "#286fa8", "fill_color": "#061329"},
        "settings_card_good": {"alpha": 76, "border_alpha": 76, "border_color": "#36d86a", "fill_color": "#061329"},
        "search_box": {"alpha": 112, "border_alpha": 88, "border_color": "#8ab9ff", "fill_color": "#050e1d", "outer_glow_alpha": 0},
        "overlay": {"alpha": 232, "border_alpha": 184, "border_color": "#8cc4ff", "fill_color": "#020b1b", "outer_glow_alpha": 82},
        "search_overlay": {"alpha": 232, "border_alpha": 182, "border_color": "#8cc4ff", "fill_color": "#020b1b", "outer_glow_alpha": 78},
        "toast": {"alpha": 186, "border_alpha": 100, "border_color": "#8ab9ff", "fill_color": "#050e1d", "outer_glow_alpha": 0},
    },
    "light": {
        "settings_sidebar": {"alpha": 248, "border_alpha": 210, "border_color": "#9eb8d3", "fill_color": "#fbfdff"},
        "settings_main": {"alpha": 252, "border_alpha": 210, "border_color": "#a8bfd8", "fill_color": "#ffffff"},
        "settings_bottom": {"alpha": 252, "border_alpha": 136, "border_color": "#c8d6e5", "fill_color": "#f7fbff"},
        "settings_section": {"alpha": 252, "border_alpha": 170, "border_color": "#c6d6e8", "fill_color": "#ffffff"},
        "settings_row": {"alpha": 252, "border_alpha": 156, "border_color": "#c9d8e8", "fill_color": "#ffffff"},
        "settings_card": {"alpha": 252, "border_alpha": 170, "border_color": "#c6d6e8", "fill_color": "#ffffff"},
        "settings_card_good": {"alpha": 252, "border_alpha": 190, "border_color": "#168a52", "fill_color": "#f8fffb"},
        "search_box": {"alpha": 252, "border_alpha": 190, "border_color": "#8aa5c0", "fill_color": "#f8fbff", "outer_glow_alpha": 0},
        "overlay": {"alpha": 252, "border_alpha": 210, "border_color": "#98b5d2", "fill_color": "#fbfdff", "outer_glow_alpha": 12},
        "search_overlay": {"alpha": 252, "border_alpha": 210, "border_color": "#98b5d2", "fill_color": "#fbfdff", "outer_glow_alpha": 12},
        "toast": {"alpha": 252, "border_alpha": 180, "border_color": "#9eb8d3", "fill_color": "#ffffff", "outer_glow_alpha": 0},
    },
}

_active_theme_preference = "dark"
_active_accent = "atlas_blue"
_active_enhanced_small_text_contrast = True


def normalize_theme_preference(value: str | None) -> str:
    normalized = str(value or "dark").strip().casefold().replace(" ", "_").replace("-", "_")
    return normalized if normalized in VALID_THEME_PREFERENCES else "dark"


def effective_minimalist_theme(preference: str | None = None) -> str:
    normalized = normalize_theme_preference(preference if preference is not None else _active_theme_preference)
    if normalized != "system":
        return normalized
    app = QApplication.instance()
    if app is None:
        return "dark"
    hints = app.styleHints()
    color_scheme = getattr(hints, "colorScheme", None)
    if not callable(color_scheme):
        return "dark"
    try:
        scheme = color_scheme()
    except (RuntimeError, TypeError):
        return "dark"
    color_scheme_enum = getattr(Qt, "ColorScheme", None)
    if color_scheme_enum is None:
        return "dark"
    if scheme == color_scheme_enum.Light:
        return "light"
    if scheme == color_scheme_enum.Dark:
        return "dark"
    return "dark"


def normalize_accent(value: str | None) -> str:
    normalized = str(value or "atlas_blue").strip().casefold().replace(" ", "_").replace("-", "_")
    return normalized if normalized in {"atlas_blue", "neutral_gray", "high_contrast_blue"} else "atlas_blue"


def set_active_minimalist_theme(
    preference: str | None,
    *,
    accent: str | None = None,
    enhanced_small_text_contrast: bool | None = None,
) -> str:
    global _active_accent, _active_enhanced_small_text_contrast, _active_theme_preference
    _active_theme_preference = normalize_theme_preference(preference)
    if accent is not None:
        _active_accent = normalize_accent(accent)
    if enhanced_small_text_contrast is not None:
        _active_enhanced_small_text_contrast = bool(enhanced_small_text_contrast)
    return _active_theme_preference


def active_minimalist_theme_preference() -> str:
    return _active_theme_preference


def minimalist_tokens(
    preference: str | None = None,
    *,
    accent: str | None = None,
    enhanced_small_text_contrast: bool | None = None,
) -> MinimalistThemeTokens:
    theme = effective_minimalist_theme(preference)
    tokens = THEME_TOKENS[theme]
    selected_accent = normalize_accent(accent if accent is not None else _active_accent)
    contrast = _active_enhanced_small_text_contrast if enhanced_small_text_contrast is None else bool(enhanced_small_text_contrast)
    if selected_accent == "neutral_gray":
        tokens = replace(
            tokens,
            accent="#7f9ab6" if theme == "dark" else "#637b94",
            accent_hover="#adc4da" if theme == "dark" else "#506a84",
            accent_soft="#203247" if theme == "dark" else "#e2ebf4",
            primary_button_background="#637b94",
            shadow_glow="#7f9ab6",
            selected_sidebar_border="#adc4da" if theme == "dark" else "#637b94",
        )
    elif selected_accent == "high_contrast_blue":
        tokens = replace(
            tokens,
            accent="#00a6ff" if theme == "dark" else "#005fd6",
            accent_hover="#78d8ff" if theme == "dark" else "#004fb5",
            accent_soft="#003d66" if theme == "dark" else "#d6ecff",
            primary_button_background="#008cff" if theme == "dark" else "#005fd6",
            shadow_glow="#00a6ff",
            selected_sidebar_border="#78d8ff" if theme == "dark" else "#005fd6",
        )
    if contrast:
        tokens = replace(
            tokens,
            text_secondary="#eef6ff" if theme == "dark" else "#22384f",
            text_muted="#d0dced" if theme == "dark" else "#435970",
        )
    return tokens


def active_minimalist_tokens() -> MinimalistThemeTokens:
    return minimalist_tokens(_active_theme_preference)


def qcolor(value: str) -> QColor:
    return QColor(value)


def qss_rgba(value: str, alpha: int) -> str:
    color = QColor(value)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {max(0, min(255, int(alpha)))})"


def theme_glass(role: str, preference: str | None = None) -> dict[str, Any]:
    theme = effective_minimalist_theme(preference)
    styles = GLASS_TOKENS[theme]
    return dict(styles.get(role, styles["settings_card"]))


def apply_glass_theme(panel, role: str, preference: str | None = None) -> None:
    spec = theme_glass(role, preference)
    panel.set_glass(
        alpha=int(spec["alpha"]),
        border_alpha=int(spec["border_alpha"]),
        border_color=QColor(str(spec["border_color"])),
        fill_color=QColor(str(spec["fill_color"])),
        outer_glow_alpha=spec.get("outer_glow_alpha"),
    )


def minimalist_styles(preference: str | None = None) -> str:
    t = minimalist_tokens(preference)
    return (
        MINIMALIST_STYLES
        + f"""
QLabel#MinimalistLogoEOAT,
QLabel#MinimalistPageTitle,
QLabel#MinimalistCardHeading,
QLabel#MinimalistRecentLabel,
QLabel#MinimalistPanelTitle,
QLabel#MinimalistSectionLabel,
QLabel#MinimalistRowTitle {{
    color: {t.text_primary};
}}
QLabel#MinimalistLogoAtlas,
QPushButton#LibraryClearFilters,
QPushButton#LibraryLinkButton {{
    color: {t.accent};
}}
QLabel#MinimalistCardSubtitle,
QLabel#MinimalistStatusText,
QLabel#MinimalistRowKind,
QLabel#MinimalistFooterText {{
    color: {t.text_secondary};
}}
QLabel#MinimalistRecentEmpty,
QLabel#MinimalistRowSubtitle,
QLabel#MinimalistPanelEmpty {{
    color: {t.text_muted};
}}
QPushButton#MinimalistMenuItem {{
    color: {t.text_primary};
}}
QPushButton#MinimalistMenuItem:hover {{
    background: {qss_rgba(t.accent_soft, 180 if effective_minimalist_theme(preference) == "light" else 132)};
    border-color: {qss_rgba(t.accent, 150)};
}}
QPushButton#MinimalistMenuItem[active="true"] {{
    color: {t.text_on_accent};
    background: {qss_rgba(t.accent, 218 if effective_minimalist_theme(preference) == "dark" else 44)};
    border-color: {t.selected_sidebar_border};
}}
QLineEdit#MinimalistHomeSearchInput,
QLineEdit#MinimalistPanelSearchInput,
QLineEdit#LibrarySearchInput {{
    color: {t.text_primary};
    selection-background-color: {t.accent};
}}
QPushButton#MinimalistSearchRow,
QPushButton#MinimalistSuggestionRow {{
    color: {t.text_primary};
    background: {qss_rgba(t.card_background, 224 if effective_minimalist_theme(preference) == "light" else 126)};
    border-color: {qss_rgba(t.border, 150 if effective_minimalist_theme(preference) == "light" else 54)};
}}
QPushButton#MinimalistSearchRow:hover,
QPushButton#MinimalistSuggestionRow:hover {{
    background: {qss_rgba(t.card_background_hover, 242 if effective_minimalist_theme(preference) == "light" else 162)};
    border-color: {qss_rgba(t.accent, 180)};
}}
QLabel#MinimalistToastText {{
    color: {t.text_primary};
}}
QWidget#MinimalistSearchFooter {{
    background: {qss_rgba(t.panel_background_alt, 238 if effective_minimalist_theme(preference) == "light" else 138)};
    border-top: 1px solid {qss_rgba(t.border, 170 if effective_minimalist_theme(preference) == "light" else 72)};
}}
QScrollBar:vertical {{
    background: {qss_rgba(t.scrollbar_track, 155 if effective_minimalist_theme(preference) == "light" else 70)};
}}
QScrollBar::handle:vertical {{
    background: {qss_rgba(t.scrollbar_handle, 205 if effective_minimalist_theme(preference) == "light" else 112)};
}}
"""
    )


def settings_page_styles(preference: str | None = None) -> str:
    t = minimalist_tokens(preference)
    light = effective_minimalist_theme(preference) == "light"
    secondary_button_bg = t.secondary_button_background if light else qss_rgba(t.secondary_button_background, 136)
    primary_disabled_bg = t.disabled_background if light else qss_rgba(t.disabled_background, 116)
    danger_bg = t.danger_soft if light else qss_rgba(t.danger_soft, 72)
    danger_hover = "#fbd5da" if light else qss_rgba(t.danger, 116)
    return f"""
QWidget#AtlasMinimalistSettingsPage,
QWidget#MinimalistSettingsContent,
QWidget#SettingsBody,
QWidget#SettingsMainBody,
QWidget#SettingsSectionBody,
QWidget#SettingsRowBody,
QWidget#SettingsSourceRowBody,
QWidget#SettingsBottomBar,
QWidget#SettingsSidebarInner,
QWidget#SettingsMainInner,
QWidget#SettingsButtonRow,
QWidget#SettingsChipRow,
QWidget#SettingsDirtyIndicator {{
    background: transparent;
}}
QFrame#SettingsDirtyDot {{
    background: {t.warning_indicator_border};
    border: 1px solid {t.warning_indicator_border};
    border-radius: 4px;
}}
QLabel#SettingsDirtyText {{
    color: {t.warning_indicator_text};
    background: transparent;
    border: 0;
    padding: 0;
    font-size: 8.2pt;
    font-weight: 820;
}}
QLabel#SettingsDirtyPill {{
    color: {t.warning_indicator_text};
    background: {t.warning_indicator_background};
    border: 1px solid {t.warning_indicator_border};
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 8.1pt;
    font-weight: 820;
}}
QLabel#SettingsAdminPill {{
    color: {t.text_secondary};
    background: {t.accent_soft};
    border: 1px solid {qss_rgba(t.border, 150 if light else 118)};
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 8.1pt;
    font-weight: 820;
}}
QLabel#SettingsAdminPill[active="true"] {{
    color: {t.success};
    background: {t.success_soft};
    border-color: {qss_rgba(t.success, 155)};
}}
QScrollArea#SettingsPageScroll,
QScrollArea#SettingsMainScroll {{
    background: transparent;
    border: 0;
}}
QScrollArea#SettingsPageScroll QWidget,
QScrollArea#SettingsMainScroll QWidget {{
    background: transparent;
}}
QLabel#SettingsPageTitle {{
    color: {t.text_primary};
    font-size: 28pt;
    font-weight: 820;
}}
QLabel#SettingsPageSubtitle {{
    color: {t.text_secondary};
    font-size: 9.5pt;
    font-weight: 520;
}}
QLabel#SettingsSidebarTitle {{
    color: {t.text_primary};
    font-size: 10.5pt;
    font-weight: 800;
}}
QFrame#SettingsSidebarItem {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
}}
QFrame#SettingsSidebarItem[hovered="true"] {{
    background: {qss_rgba(t.card_background_hover if light else t.accent_soft, 220 if light else 122)};
    border-color: {qss_rgba(t.accent, 170 if light else 132)};
}}
QFrame#SettingsSidebarItem[active="true"] {{
    background: {t.selected_sidebar_background if light else qss_rgba(t.selected_sidebar_background, 146)};
    border-color: {qss_rgba(t.selected_sidebar_border, 230 if light else 218)};
}}
QLabel#SettingsSidebarItemTitle {{
    color: {t.text_primary};
    font-size: 9.2pt;
    font-weight: 760;
}}
QLabel#SettingsSidebarItemDescription {{
    color: {t.text_muted};
    font-size: 8.2pt;
    font-weight: 520;
}}
QFrame#SettingsSidebarItem[active="true"] QLabel#SettingsSidebarItemTitle {{
    color: {t.accent_hover if light else "#51b8ff"};
}}
QLabel#SettingsPanelTitle {{
    color: {t.text_primary};
    font-size: 12.5pt;
    font-weight: 820;
}}
QLabel#SettingsPanelSubtitle {{
    color: {t.text_secondary};
    font-size: 8.8pt;
    font-weight: 520;
}}
QLabel#SettingsStatusPill,
QLabel#SettingsSmallPill {{
    color: {t.text_secondary};
    background: {t.accent_soft};
    border: 1px solid {qss_rgba(t.accent, 112)};
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 8.1pt;
    font-weight: 760;
}}
QLabel#SettingsStatusPill[tone="good"],
QLabel#SettingsSmallPill[tone="good"] {{
    color: {t.success};
    background: {t.success_soft};
    border-color: {qss_rgba(t.success, 155)};
}}
QLabel#SettingsStatusPill[tone="warn"],
QLabel#SettingsSmallPill[tone="warn"] {{
    color: {t.warning};
    background: {t.warning_soft};
    border-color: {qss_rgba(t.warning, 150)};
}}
QLabel#SettingsStatusPill[tone="bad"],
QLabel#SettingsSmallPill[tone="bad"] {{
    color: {t.danger};
    background: {t.danger_soft};
    border-color: {qss_rgba(t.danger, 155)};
}}
QLabel#SettingsSectionTitle {{
    color: {t.text_primary};
    font-size: 10.4pt;
    font-weight: 800;
}}
QLabel#SettingsSectionDescription,
QLabel#SettingsRowDescription,
QLabel#SettingsSourceDescription,
QLabel#SettingsMutedText {{
    color: {t.text_muted};
    font-size: 8.4pt;
    font-weight: 510;
}}
QLabel#SettingsRowTitle,
QLabel#SettingsSourceTitle {{
    color: {t.text_primary};
    font-size: 9.3pt;
    font-weight: 760;
}}
QLabel#SettingsValueText,
QLabel#SettingsPathText {{
    color: {t.text_secondary};
    font-size: 8.6pt;
    font-weight: 530;
}}
QLabel#SettingsPathText {{
    color: {t.text_muted};
}}
QLabel#SettingsDangerText {{
    color: {t.danger};
    font-size: 8.6pt;
    font-weight: 620;
}}
QLabel#SettingsLockedChip {{
    color: {t.text_secondary};
    background: {qss_rgba(t.card_background_hover if light else t.accent_soft, 126 if light else 96)};
    border: 1px solid {qss_rgba(t.border, 170 if light else 128)};
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 8.1pt;
    font-weight: 800;
}}
QPushButton#SettingsButton,
QPushButton#SettingsSmallButton,
QPushButton#SettingsGhostButton,
QPushButton#SettingsDangerButton,
QPushButton#SettingsCautionButton,
QPushButton#SettingsPrimaryButton {{
    min-height: 34px;
    padding: 0 13px;
    border-radius: 6px;
    font-size: 8.4pt;
    font-weight: 760;
}}
QPushButton#SettingsButton,
QPushButton#SettingsSmallButton,
QPushButton#SettingsGhostButton {{
    color: {t.text_primary};
    background: {secondary_button_bg};
    border: 1px solid {qss_rgba(t.border, 150 if light else 118)};
}}
QPushButton#SettingsSmallButton {{
    min-height: 28px;
    padding: 0 10px;
    font-size: 7.9pt;
}}
QPushButton#SettingsButton:hover,
QPushButton#SettingsSmallButton:hover,
QPushButton#SettingsGhostButton:hover {{
    background: {t.card_background_hover if light else qss_rgba(t.card_background_hover, 166)};
    border-color: {qss_rgba(t.accent, 210 if light else 202)};
}}
QPushButton#SettingsButton:disabled,
QPushButton#SettingsSmallButton:disabled,
QPushButton#SettingsGhostButton:disabled {{
    color: {t.disabled_button_text};
    background: {t.disabled_button_background if light else qss_rgba(t.disabled_background, 92)};
    border-color: {t.disabled_border};
}}
QPushButton#SettingsPrimaryButton {{
    color: {t.primary_button_text};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {t.primary_button_background}, stop:1 {t.accent_hover});
    border: 1px solid {qss_rgba(t.accent_hover, 224)};
}}
QPushButton#SettingsPrimaryButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {t.accent_hover}, stop:1 {t.primary_button_background});
}}
QPushButton#SettingsPrimaryButton:disabled {{
    color: {t.disabled_button_text};
    background: {t.disabled_button_background if light else primary_disabled_bg};
    border-color: {t.disabled_border};
}}
QPushButton#SettingsDangerButton {{
    color: {t.danger};
    background: {danger_bg};
    border: 1px solid {qss_rgba(t.danger, 150)};
}}
QPushButton#SettingsDangerButton:hover {{
    color: {t.text_on_accent if not light else t.danger};
    background: {danger_hover};
    border-color: {qss_rgba(t.danger, 214)};
}}
QPushButton#SettingsCautionButton {{
    color: {t.warning_indicator_text};
    background: {t.warning_indicator_background};
    border: 1px solid {t.warning_indicator_border};
}}
QPushButton#SettingsCautionButton:hover {{
    background: {t.warning_soft};
    border-color: {qss_rgba(t.warning, 214)};
}}
QPushButton#SettingsCautionButton:disabled {{
    color: {t.disabled_button_text};
    background: {t.disabled_button_background if light else qss_rgba(t.disabled_background, 92)};
    border-color: {t.disabled_border};
}}
QPushButton#SettingsSegmentButton {{
    min-height: 30px;
    padding: 0 11px;
    color: {t.text_secondary};
    background: {t.input_background if light else qss_rgba(t.input_background, 142)};
    border: 1px solid {qss_rgba(t.border, 150 if light else 94)};
    border-radius: 7px;
    font-size: 8.2pt;
    font-weight: 720;
}}
QPushButton#SettingsSegmentButton:hover {{
    border-color: {qss_rgba(t.accent, 190 if light else 166)};
}}
QPushButton#SettingsSegmentButton:checked {{
    color: {t.text_on_accent if not light else t.accent_hover};
    background: {qss_rgba(t.accent, 42 if light else 174)};
    border-color: {qss_rgba(t.accent, 230 if light else 216)};
}}
QPushButton#SettingsSegmentButton:disabled {{
    color: {t.disabled_button_text};
    background: {t.disabled_button_background if light else qss_rgba(t.disabled_background, 92)};
    border-color: {t.disabled_border};
}}
QPushButton#SettingsSegmentButton:checked:disabled {{
    color: {t.accent_hover if light else "#b8dcff"};
    background: {qss_rgba(t.accent, 48 if light else 118)};
    border-color: {qss_rgba(t.accent, 148 if light else 172)};
}}
QCheckBox#SettingsCheckBox {{
    color: {t.text_secondary};
    font-size: 8.8pt;
    font-weight: 660;
}}
QCheckBox#SettingsCheckBox:disabled {{
    color: {t.text_secondary if light else qss_rgba(t.text_secondary, 205)};
}}
QCheckBox#SettingsCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border-radius: 4px;
    border: 1px solid {qss_rgba(t.border_strong, 170)};
    background: {t.input_background if light else qss_rgba(t.input_background, 148)};
}}
QCheckBox#SettingsCheckBox::indicator:checked {{
    background: {t.accent};
    border-color: {t.accent_hover};
}}
QCheckBox#SettingsCheckBox::indicator:disabled {{
    background: {t.disabled_background};
    border-color: {t.disabled_border};
}}
QCheckBox#SettingsCheckBox::indicator:checked:disabled {{
    background: {qss_rgba(t.accent, 104 if light else 154)};
    border-color: {qss_rgba(t.accent_hover, 160 if light else 190)};
}}
QCheckBox#SettingsCheckBox::indicator:checked:disabled:hover {{
    background: {qss_rgba(t.accent, 104 if light else 154)};
}}
QComboBox#SettingsComboBox,
QSpinBox#SettingsSpinBox,
QLineEdit#SettingsLineEdit {{
    min-height: 32px;
    color: {t.text_primary};
    background: {t.input_background if light else qss_rgba(t.input_background, 150)};
    border: 1px solid {qss_rgba(t.border, 150 if light else 105)};
    border-radius: 7px;
    padding: 0 9px;
    font-size: 8.7pt;
    font-weight: 610;
    selection-background-color: {t.accent};
}}
QComboBox#SettingsComboBox:hover,
QSpinBox#SettingsSpinBox:hover,
QLineEdit#SettingsLineEdit:hover {{
    border-color: {qss_rgba(t.accent, 190 if light else 178)};
}}
QComboBox#SettingsComboBox:disabled,
QSpinBox#SettingsSpinBox:disabled,
QLineEdit#SettingsLineEdit:disabled {{
    color: {t.disabled_button_text};
    background: {t.disabled_background};
    border-color: {t.disabled_border};
}}
QComboBox#SettingsComboBox::drop-down {{
    border: 0;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    color: {t.text_primary};
    background: {t.panel_background};
    border: 1px solid {qss_rgba(t.accent, 140)};
    selection-background-color: {t.accent_soft};
}}
QToolButton#SettingsSectionToggle {{
    color: {t.text_primary};
    background: transparent;
    border: 0;
    font-size: 13pt;
    font-weight: 800;
}}
QScrollBar:vertical {{
    background: {qss_rgba(t.scrollbar_track, 155 if light else 70)};
    width: 9px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {qss_rgba(t.scrollbar_handle, 205 if light else 112)};
    border-radius: 4px;
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


def settings_dialog_styles(preference: str | None = None) -> str:
    t = minimalist_tokens(preference)
    light = effective_minimalist_theme(preference) == "light"
    secondary_hover = t.card_background_hover if light else qss_rgba(t.card_background_hover, 170)
    danger_background = "#fff5f6" if light else qss_rgba(t.danger_soft, 95)
    danger_hover = "#fbd5da" if light else qss_rgba(t.danger, 118)
    return f"""
QDialog#SettingsConfirmDialog {{
    background: transparent;
}}
QFrame#SettingsDialogPanel {{
    background: {t.dialog_background};
    border: 1px solid {t.dialog_border};
    border-radius: 10px;
}}
QLabel#SettingsDialogTitle {{
    color: {t.dialog_title};
    font-size: 14pt;
    font-weight: 820;
}}
QLabel#SettingsDialogBody {{
    color: {t.dialog_text};
    font-size: 10pt;
    font-weight: 520;
}}
QLabel#SettingsDangerText {{
    color: {t.danger};
    font-size: 8.8pt;
    font-weight: 720;
}}
QLineEdit#SettingsLineEdit {{
    min-height: 34px;
    color: {t.text_primary};
    background: {t.input_background if light else qss_rgba(t.input_background, 150)};
    border: 1px solid {qss_rgba(t.border, 150 if light else 105)};
    border-radius: 7px;
    padding: 0 10px;
    font-size: 9pt;
    font-weight: 610;
    selection-background-color: {t.accent};
}}
QLineEdit#SettingsLineEdit:focus {{
    border-color: {qss_rgba(t.accent, 220)};
}}
QCheckBox#SettingsCheckBox {{
    color: {t.dialog_text};
    font-size: 8.6pt;
    font-weight: 620;
}}
QCheckBox#SettingsCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {qss_rgba(t.border_strong, 170)};
    background: {t.input_background if light else qss_rgba(t.input_background, 148)};
}}
QCheckBox#SettingsCheckBox::indicator:checked {{
    background: {t.accent};
    border-color: {t.accent_hover};
}}
QPushButton#SettingsDialogPrimaryButton,
QPushButton#SettingsDialogSecondaryButton,
QPushButton#SettingsDialogCautionButton,
QPushButton#SettingsDialogDangerButton {{
    min-height: 34px;
    padding: 0 16px;
    border-radius: 6px;
    font-size: 9pt;
    font-weight: 780;
}}
QPushButton#SettingsDialogPrimaryButton {{
    color: {t.primary_button_text};
    background: {t.primary_button_background};
    border: 1px solid {qss_rgba(t.accent_hover, 225)};
}}
QPushButton#SettingsDialogPrimaryButton:hover {{
    background: {t.accent_hover};
}}
QPushButton#SettingsDialogSecondaryButton {{
    color: {t.dialog_button_text};
    background: {t.dialog_button_background};
    border: 1px solid {t.dialog_button_border};
}}
QPushButton#SettingsDialogSecondaryButton:hover {{
    background: {secondary_hover};
    border-color: {t.accent};
}}
QPushButton#SettingsDialogDangerButton {{
    color: {t.danger};
    background: {danger_background};
    border: 1px solid {qss_rgba(t.danger, 190)};
}}
QPushButton#SettingsDialogDangerButton:hover {{
    color: {t.text_on_accent if not light else t.danger};
    background: {danger_hover};
    border-color: {qss_rgba(t.danger, 230)};
}}
QPushButton#SettingsDialogCautionButton {{
    color: {t.warning_indicator_text};
    background: {t.warning_indicator_background};
    border: 1px solid {t.warning_indicator_border};
}}
QPushButton#SettingsDialogCautionButton:hover {{
    background: {t.warning_soft};
    border-color: {qss_rgba(t.warning, 220)};
}}
QPushButton#SettingsDialogPrimaryButton:disabled,
QPushButton#SettingsDialogSecondaryButton:disabled,
QPushButton#SettingsDialogCautionButton:disabled,
QPushButton#SettingsDialogDangerButton:disabled {{
    color: {t.disabled_button_text};
    background: {t.disabled_button_background};
    border-color: {t.disabled_border};
}}
"""


__all__ = [
    "REQUIRED_THEME_TOKENS",
    "THEME_TOKENS",
    "VALID_THEME_PREFERENCES",
    "MinimalistThemeTokens",
    "active_minimalist_theme_preference",
    "active_minimalist_tokens",
    "apply_glass_theme",
    "effective_minimalist_theme",
    "minimalist_styles",
    "minimalist_tokens",
    "normalize_theme_preference",
    "qcolor",
    "qss_rgba",
    "set_active_minimalist_theme",
    "settings_dialog_styles",
    "settings_page_styles",
    "theme_glass",
]
