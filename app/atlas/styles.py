from __future__ import annotations

from string import Template

DESIGN_TOKENS = {
    "background": "#eef3f8",
    "surface": "#ffffff",
    "surface_elevated": "#f8fbff",
    "navy": "#102033",
    "accent": "#2f80ed",
    "accent_hover": "#256fcf",
    "accent_secondary": "#00a3c7",
    "warning": "#b76a00",
    "danger": "#b42318",
    "success": "#087f5b",
    "muted_text": "#627d98",
    "border": "#d7dee8",
    "border_strong": "#b8c7dc",
    "hover": "#e7f1ff",
    "hero_start": "#102033",
    "hero_mid": "#173d66",
    "hero_end": "#2f80ed",
    "scroll_handle": "#b8c7dc",
    "scroll_hover": "#7ea7d8",
    "sidebar_logo_card_bg": "#17324f",
    "sidebar_logo_card_bg_gradient_start": "#17324f",
    "sidebar_logo_card_bg_gradient_end": "#102033",
    "sidebar_logo_card_border": "#244564",
    "sidebar_logo_card_text": "#ffffff",
    "sidebar_logo_card_shadow": "#285f95",
    "sidebar_logo_card_accent": "#7ec8ff",
    "sidebar_logo_image_bg": "#ffffff",
}
DARK_DESIGN_TOKENS = {
    "background": "#0d1624",
    "surface": "#121f30",
    "surface_elevated": "#18283c",
    "navy": "#e5edf7",
    "accent": "#64a7ff",
    "accent_hover": "#86bbff",
    "accent_secondary": "#4fd1e8",
    "warning": "#f5b342",
    "danger": "#ff8179",
    "success": "#4fd39a",
    "muted_text": "#9fb2c8",
    "border": "#2a3c52",
    "border_strong": "#405872",
    "hover": "#1c3148",
    "hero_start": "#0a1320",
    "hero_mid": "#123a5c",
    "hero_end": "#236fb8",
    "scroll_handle": "#405872",
    "scroll_hover": "#5d7b9b",
    "sidebar_logo_card_bg": "#102033",
    "sidebar_logo_card_bg_gradient_start": "#102033",
    "sidebar_logo_card_bg_gradient_end": "#0a1320",
    "sidebar_logo_card_border": "#405872",
    "sidebar_logo_card_text": "#ffffff",
    "sidebar_logo_card_shadow": "#64a7ff",
    "sidebar_logo_card_accent": "#64a7ff",
    "sidebar_logo_image_bg": "#ffffff",
}
NOLATO_DESIGN_TOKENS = {
    "background": "#f2f4f7",
    "surface": "#ffffff",
    "surface_elevated": "#f7f8fa",
    "navy": "#17191d",
    "accent": "#d80621",
    "accent_hover": "#b8051c",
    "accent_secondary": "#2b2f36",
    "warning": "#b76a00",
    "danger": "#b42318",
    "success": "#087f5b",
    "muted_text": "#6c737f",
    "border": "#d8dde5",
    "border_strong": "#b8c0cc",
    "hover": "#fff1f3",
    "hero_start": "#111317",
    "hero_mid": "#2b2f36",
    "hero_end": "#d80621",
    "scroll_handle": "#b8c0cc",
    "scroll_hover": "#d80621",
    "sidebar_logo_card_bg": "#111317",
    "sidebar_logo_card_bg_gradient_start": "#050607",
    "sidebar_logo_card_bg_gradient_end": "#2b2f36",
    "sidebar_logo_card_border": "#d80621",
    "sidebar_logo_card_text": "#ffffff",
    "sidebar_logo_card_shadow": "#8d0718",
    "sidebar_logo_card_accent": "#d80621",
    "sidebar_logo_image_bg": "#ffffff",
}
NOLATO_DARK_DESIGN_TOKENS = {
    "background": "#101114",
    "surface": "#17191d",
    "surface_elevated": "#202328",
    "navy": "#f4f6f8",
    "accent": "#ff4b5f",
    "accent_hover": "#ff6b7b",
    "accent_secondary": "#c9cdd3",
    "warning": "#f5b342",
    "danger": "#ff8179",
    "success": "#4fd39a",
    "muted_text": "#aeb5bf",
    "border": "#333842",
    "border_strong": "#4a515e",
    "hover": "#2a1b20",
    "hero_start": "#050607",
    "hero_mid": "#202328",
    "hero_end": "#d80621",
    "scroll_handle": "#4a515e",
    "scroll_hover": "#ff4b5f",
    "sidebar_logo_card_bg": "#111317",
    "sidebar_logo_card_bg_gradient_start": "#050607",
    "sidebar_logo_card_bg_gradient_end": "#202328",
    "sidebar_logo_card_border": "#ff4b5f",
    "sidebar_logo_card_text": "#ffffff",
    "sidebar_logo_card_shadow": "#d80621",
    "sidebar_logo_card_accent": "#ff4b5f",
    "sidebar_logo_image_bg": "#ffffff",
}
INDUSTRIAL_GRAPHITE_TOKENS = {
    "background": "#eef3f6",
    "surface": "#ffffff",
    "surface_elevated": "#f5f8fa",
    "navy": "#1f252b",
    "accent": "#3d6f8f",
    "accent_hover": "#315d79",
    "accent_secondary": "#1b9aaa",
    "warning": "#b7791f",
    "danger": "#b42318",
    "success": "#2f855a",
    "muted_text": "#64717d",
    "border": "#d3dbe2",
    "border_strong": "#aebbc6",
    "hover": "#e6f1f5",
    "hero_start": "#1f252b",
    "hero_mid": "#34414d",
    "hero_end": "#3d6f8f",
    "scroll_handle": "#aebbc6",
    "scroll_hover": "#3d6f8f",
    "sidebar_logo_card_bg": "#1f252b",
    "sidebar_logo_card_bg_gradient_start": "#1f252b",
    "sidebar_logo_card_bg_gradient_end": "#24394a",
    "sidebar_logo_card_border": "#4f839e",
    "sidebar_logo_card_text": "#ffffff",
    "sidebar_logo_card_shadow": "#1b9aaa",
    "sidebar_logo_card_accent": "#1b9aaa",
    "sidebar_logo_image_bg": "#f8fbff",
}
INDUSTRIAL_GRAPHITE_DARK_TOKENS = {
    "background": "#11161b",
    "surface": "#1b2229",
    "surface_elevated": "#232c34",
    "navy": "#e8edf2",
    "accent": "#6fa6c8",
    "accent_hover": "#8bb9d5",
    "accent_secondary": "#4fd1df",
    "warning": "#e5aa3f",
    "danger": "#ff8179",
    "success": "#69c690",
    "muted_text": "#a8b5c1",
    "border": "#34424f",
    "border_strong": "#506171",
    "hover": "#26333d",
    "hero_start": "#080b0f",
    "hero_mid": "#28333d",
    "hero_end": "#3d6f8f",
    "scroll_handle": "#506171",
    "scroll_hover": "#6fa6c8",
    "sidebar_logo_card_bg": "#11161b",
    "sidebar_logo_card_bg_gradient_start": "#11161b",
    "sidebar_logo_card_bg_gradient_end": "#26333d",
    "sidebar_logo_card_border": "#506171",
    "sidebar_logo_card_text": "#ffffff",
    "sidebar_logo_card_shadow": "#4fd1df",
    "sidebar_logo_card_accent": "#4fd1df",
    "sidebar_logo_image_bg": "#f8fbff",
}
AURORA_TECH_TOKENS = {
    "background": "#edf6fb",
    "surface": "#ffffff",
    "surface_elevated": "#f4f9fd",
    "navy": "#102033",
    "accent": "#147dff",
    "accent_hover": "#0f67d6",
    "accent_secondary": "#00a99d",
    "warning": "#b76a00",
    "danger": "#c03434",
    "success": "#0f8f73",
    "muted_text": "#5f7891",
    "border": "#cfddeb",
    "border_strong": "#a9bfd6",
    "hover": "#e2f3ff",
    "hero_start": "#0c1730",
    "hero_mid": "#1646a0",
    "hero_end": "#00a99d",
    "scroll_handle": "#a9bfd6",
    "scroll_hover": "#147dff",
    "sidebar_logo_card_bg": "#0c1730",
    "sidebar_logo_card_bg_gradient_start": "#0c1730",
    "sidebar_logo_card_bg_gradient_end": "#12356f",
    "sidebar_logo_card_border": "#147dff",
    "sidebar_logo_card_text": "#ffffff",
    "sidebar_logo_card_shadow": "#00a99d",
    "sidebar_logo_card_accent": "#00a99d",
    "sidebar_logo_image_bg": "#f8fbff",
}
AURORA_TECH_DARK_TOKENS = {
    "background": "#081225",
    "surface": "#101c33",
    "surface_elevated": "#162641",
    "navy": "#e8f3ff",
    "accent": "#4ca3ff",
    "accent_hover": "#73b9ff",
    "accent_secondary": "#37d6cb",
    "warning": "#f3b44b",
    "danger": "#ff7676",
    "success": "#4fd3a9",
    "muted_text": "#a7bad3",
    "border": "#2a3a58",
    "border_strong": "#445b7c",
    "hover": "#142849",
    "hero_start": "#050a18",
    "hero_mid": "#12356f",
    "hero_end": "#008fbb",
    "scroll_handle": "#445b7c",
    "scroll_hover": "#4ca3ff",
    "sidebar_logo_card_bg": "#050a18",
    "sidebar_logo_card_bg_gradient_start": "#050a18",
    "sidebar_logo_card_bg_gradient_end": "#12356f",
    "sidebar_logo_card_border": "#4ca3ff",
    "sidebar_logo_card_text": "#ffffff",
    "sidebar_logo_card_shadow": "#37d6cb",
    "sidebar_logo_card_accent": "#37d6cb",
    "sidebar_logo_image_bg": "#f8fbff",
}
SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 18, "xl": 24}
RADIUS = {"sm": 5, "md": 7, "lg": 9}
FONT_SIZES = {"body": 10, "small": 8, "section": 12, "page": 18, "hero": 22}


def atlas_stylesheet(theme: str = "light", color_scheme: str = "atlas_blue") -> str:
    theme_name = str(theme or "light").casefold()
    scheme_name = str(color_scheme or "atlas_blue").casefold()
    scheme_tokens = {
        "nolato_logo": (NOLATO_DESIGN_TOKENS, NOLATO_DARK_DESIGN_TOKENS),
        "industrial_graphite": (INDUSTRIAL_GRAPHITE_TOKENS, INDUSTRIAL_GRAPHITE_DARK_TOKENS),
        "aurora_tech": (AURORA_TECH_TOKENS, AURORA_TECH_DARK_TOKENS),
    }
    if scheme_name in scheme_tokens:
        light_tokens, dark_tokens = scheme_tokens[scheme_name]
        base_tokens = dark_tokens if theme_name == "dark" else light_tokens
    else:
        scheme_name = "atlas_blue"
        base_tokens = DARK_DESIGN_TOKENS if theme_name == "dark" else DESIGN_TOKENS
    tokens = {
        **base_tokens,
        "body_font": FONT_SIZES["body"],
        "hero_font": FONT_SIZES["hero"],
        "page_font": FONT_SIZES["page"],
        "radius_sm": RADIUS["sm"],
        "radius_md": RADIUS["md"],
        "radius_lg": RADIUS["lg"],
    }
    base = Template("""
    QMainWindow, QWidget {
        background: $background;
        color: #172033;
        font-family: "Segoe UI";
        font-size: ${body_font}pt;
    }
    QLabel {
        background: transparent;
    }
    QWidget#AtlasSidebarPanel {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0c1c2e, stop:.55 #102033, stop:1 #132a44);
    }
    QFrame#AtlasSidebarHeader {
        background: $sidebar_logo_card_bg;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $sidebar_logo_card_bg_gradient_start, stop:1 $sidebar_logo_card_bg_gradient_end);
        border: 1px solid $sidebar_logo_card_border;
        border-bottom: 3px solid $sidebar_logo_card_accent;
        border-radius: 10px;
    }
    QFrame#AtlasSidebarHeader:hover {
        border-color: $sidebar_logo_card_shadow;
    }
    QLabel#AtlasSidebarLogo {
        background: $sidebar_logo_image_bg;
        border: 1px solid rgba(255, 255, 255, 110);
        border-radius: 14px;
        padding: 4px;
    }
    QLabel#AtlasSidebarTitle {
        color: $sidebar_logo_card_text;
        font-size: 12pt;
        font-weight: 900;
        padding-top: 2px;
        padding-bottom: 3px;
    }
    QScrollArea#AtlasSidebarScroll {
        background: transparent;
        border: 0;
    }
    QLabel#AtlasNavSectionLabel {
        color: #8fb3d9;
        font-size: 8pt;
        font-weight: 800;
        letter-spacing: .08em;
        padding: 12px 8px 4px 8px;
    }
    QPushButton#AtlasNavItem {
        background: transparent;
        color: #d7e7f7;
        border: 0;
        border-left: 3px solid transparent;
        border-radius: 9px;
        padding: 8px 10px 8px 12px;
        text-align: left;
        font-size: 9pt;
        font-weight: 600;
    }
    QPushButton#AtlasNavItem:hover {
        background: #1c3755;
        color: white;
        border-left-color: #7ea7d8;
    }
    QPushButton#AtlasNavItem:checked {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2f80ed, stop:1 #1f4e7e);
        color: white;
        border-left-color: #7ec8ff;
    }
    QFrame#AtlasCard {
        background: $surface;
        border: 1px solid $border;
        border-radius: ${radius_md}px;
    }
    QFrame QWidget {
        background: transparent;
    }
    QFrame#HeroPanel, QFrame#AtlasHero, QWidget#AtlasHero {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $hero_start, stop:.55 $hero_mid, stop:1 $hero_end);
        border-radius: ${radius_lg}px;
        border: 0;
    }
    QFrame#ProfileHeaderCard {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #102033, stop:.55 #214f7c, stop:1 #e7f1ff);
        border: 0;
        border-radius: 10px;
    }
    QFrame#PrimaryCard {
        background: #ffffff;
        border: 1px solid #b8c7dc;
        border-top: 4px solid $accent;
        border-radius: 9px;
    }
    QFrame#SecondaryCard {
        background: #f8fbff;
        border: 1px solid #d7e2ef;
        border-radius: 8px;
    }
    QFrame#DetailCard {
        background: #f3f7fb;
        border: 1px solid #dfe8f3;
        border-radius: 7px;
    }
    QFrame#WarningCard {
        background: #fff7e8;
        border: 1px solid #f4c982;
        border-left: 5px solid $warning;
        border-radius: 8px;
    }
    QFrame#DangerCard {
        background: #fff1f1;
        border: 1px solid #f2b8b5;
        border-left: 5px solid $danger;
        border-radius: 8px;
    }
    QFrame#SuccessCard {
        background: #ebfbf4;
        border: 1px solid #a8e6ca;
        border-left: 5px solid $success;
        border-radius: 8px;
    }
    QFrame#InfoPanel {
        background: #edf5ff;
        border: 1px solid #cfe1f7;
        border-radius: 8px;
    }
    QFrame#CompactStatCard {
        background: #f8fbff;
        border: 1px solid #d7e2ef;
        border-radius: 8px;
    }
    QFrame#CompactStatCard:hover {
        background: #ffffff;
        border-color: #b8c7dc;
    }
    QFrame#FeatureActionCard {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffffff, stop:1 #edf6ff);
        border: 1px solid #c5d8ed;
        border-left: 4px solid $accent;
        border-radius: 9px;
    }
    QFrame#ExportActionCard {
        background: #f9fbfe;
        border: 1px solid #cfdbe8;
        border-left: 4px solid $accent_secondary;
        border-radius: 9px;
    }
    QFrame#CompatibilityCard {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #eef8fb);
        border: 1px solid #bfe4ee;
        border-top: 4px solid $accent_secondary;
        border-radius: 9px;
    }
    QFrame#PhotoGalleryCard {
        background: #fbfcff;
        border: 1px solid #ccd8e7;
        border-top: 4px solid #6b8fca;
        border-radius: 9px;
    }
    QFrame#ChecklistCard {
        background: #ffffff;
        border: 1px solid #cbd8e8;
        border-top: 4px solid $success;
        border-radius: 9px;
    }
    QFrame#DenseDataPanel {
        background: #f5f8fc;
        border: 1px solid #cdd8e5;
        border-radius: 7px;
    }
    QFrame#EmptyState {
        background: #f6f9fc;
        border: 1px dashed $border_strong;
        border-radius: ${radius_md}px;
    }
    QLabel#HeroTitle {
        color: white;
        font-size: ${hero_font}pt;
        font-weight: 800;
    }
    QLabel#HeroSubtitle {
        color: #dbeafe;
        font-size: 11pt;
    }
    QLabel#PageTitle {
        color: #172033;
        font-size: ${page_font}pt;
        font-weight: 800;
    }
    QLabel#PageSubtitle {
        color: $muted_text;
        font-size: 10pt;
        font-weight: 600;
    }
    QLabel#EyebrowLabel {
        color: #4f78a3;
        font-size: 7pt;
        font-weight: 900;
        letter-spacing: .09em;
    }
    QFrame#HeroPanel QLabel#EyebrowLabel, QFrame#ProfileHeaderCard QLabel#EyebrowLabel {
        color: #b8d7ff;
    }
    QLabel#CardTitle, QLabel#SectionTitle {
        color: #172033;
        font-size: 12pt;
        font-weight: 800;
    }
    QLabel#DetailTitle {
        color: #243b53;
        font-size: 10pt;
        font-weight: 800;
    }
    QLabel#ProfileTitle {
        color: white;
        font-size: 22pt;
        font-weight: 900;
    }
    QLabel#ProfileSubtitle {
        color: #dbeafe;
        font-size: 10pt;
        font-weight: 600;
    }
    QLabel#ProfileMetricValue {
        color: white;
        font-size: 16pt;
        font-weight: 900;
    }
    QLabel#ProfileMetricLabel {
        color: #dbeafe;
        font-size: 8pt;
        font-weight: 700;
    }
    QFrame#ProfileHeaderCard QLabel#MutedText {
        color: #c8dcf3;
    }
    QLabel#BodyText {
        color: #172033;
    }
    QLabel#MutedText {
        color: $muted_text;
    }
    QLabel#MicroText {
        color: #7891aa;
        font-size: 8pt;
        font-weight: 600;
    }
    QLabel#MetricValue {
        color: #172033;
        font-size: 20pt;
        font-weight: 800;
    }
    QLabel#MetricLabel {
        color: $muted_text;
        font-size: 8pt;
        font-weight: 800;
    }
    QLabel#MetricIcon {
        color: #6c86a4;
        font-size: 13pt;
        font-weight: 900;
    }
    QLabel#DocumentCategory {
        color: #4f78a3;
        font-size: 7pt;
        font-weight: 900;
        letter-spacing: .08em;
    }
    QLabel#DocumentTitle {
        color: #172033;
        font-size: 12.5pt;
        font-weight: 900;
    }
    QLabel#DocumentDescription {
        color: #30465f;
        font-size: 9.5pt;
        font-weight: 700;
    }
    QLabel#DocumentMetadata, QLabel#DocumentPath {
        color: #7891aa;
        font-size: 8pt;
        font-weight: 700;
    }
    QLabel#DocumentPreview {
        color: #465f78;
        font-size: 9pt;
    }
    QLabel#AccordionSummary {
        color: $muted_text;
        font-size: 8.5pt;
        font-weight: 650;
    }
    QLabel#WarningTitle {
        color: #78350f;
        font-size: 11pt;
        font-weight: 900;
    }
    QLabel#ActionText {
        color: #173d66;
        font-weight: 700;
    }
    QLabel#SuccessChip, QLabel#BadgeGood {
        background: #e6f6ef;
        color: $success;
        border-radius: ${radius_sm}px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#WarningChip, QLabel#BadgeWarn {
        background: #fff4dd;
        color: $warning;
        border-radius: ${radius_sm}px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#DangerChip, QLabel#BadgeBad {
        background: #fee2e2;
        color: $danger;
        border-radius: ${radius_sm}px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#PrimaryChip, QLabel#BadgeInfo {
        background: #e7f1ff;
        color: #1f5fa8;
        border-radius: ${radius_sm}px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#BadgeVerified {
        background: #ecfdf3;
        color: #087f5b;
        border: 1px solid #b7e4c7;
        border-radius: ${radius_sm}px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#BadgeReview {
        background: #fff7e6;
        color: #9a5a00;
        border: 1px solid #f2d18a;
        border-radius: ${radius_sm}px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#BadgeMissing, QLabel#BadgeInvalid {
        background: #fff1f1;
        color: #a61b1b;
        border: 1px solid #f2b8b5;
        border-radius: ${radius_sm}px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#BadgeUnknown {
        background: #eef4fb;
        color: #3d5a78;
        border: 1px solid #cbd8e8;
        border-radius: ${radius_sm}px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#NeutralChip {
        background: #eef3f9;
        color: #34495e;
        border-radius: ${radius_sm}px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#OutlineChip {
        background: transparent;
        color: #1f5fa8;
        border: 1px solid #9fc5f3;
        border-radius: ${radius_sm}px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#GhostChip {
        background: transparent;
        color: $muted_text;
        border-radius: ${radius_sm}px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#CountChip {
        background: #172033;
        color: white;
        border-radius: 9px;
        padding: 2px 7px;
        font-size: 8pt;
        font-weight: 800;
    }
    QFrame#MetricAccentGood {
        background: #2f9e68;
        border: 0;
        border-radius: 2px;
    }
    QFrame#MetricAccentWarn {
        background: #f59e0b;
        border: 0;
        border-radius: 2px;
    }
    QFrame#MetricAccentBad {
        background: #dc2626;
        border: 0;
        border-radius: 2px;
    }
    QFrame#MetricAccentPrimary {
        background: $accent;
        border: 0;
        border-radius: 2px;
    }
    QFrame#MetricAccentNeutral {
        background: #94a3b8;
        border: 0;
        border-radius: 2px;
    }
    QFrame#MiniProgressTrack {
        background: #dfe8f3;
        border: 0;
        border-radius: 4px;
    }
    QFrame#MiniProgressGood {
        background: $success;
        border-radius: 4px;
    }
    QFrame#MiniProgressWarn {
        background: #f59e0b;
        border-radius: 4px;
    }
    QFrame#MiniProgressBad {
        background: $danger;
        border-radius: 4px;
    }
    QLabel#PhotoThumb {
        background: #eaf1f8;
        border: 1px solid #cbd8e8;
        border-radius: 7px;
        color: $muted_text;
        font-weight: 700;
    }
    QLineEdit, QLineEdit#ModernSearchBar {
        background: $surface;
        border: 1px solid #cbd5e1;
        border-radius: ${radius_md}px;
        padding: 9px;
        min-height: 26px;
        selection-background-color: #dbeafe;
    }
    QLineEdit#ModernSearchBar {
        padding: 11px 12px;
        font-weight: 600;
    }
    QLineEdit:focus, QLineEdit#ModernSearchBar:focus {
        border-color: $accent;
    }
    QPushButton {
        background: $surface;
        border: 1px solid #cbd5e1;
        border-radius: ${radius_md}px;
        padding: 6px 12px;
        font-weight: 600;
        min-height: 18px;
    }
    QPushButton:hover {
        background: $hover;
        border-color: #93c5fd;
    }
    QPushButton#PrimaryButton {
        background: $accent;
        color: white;
        border-color: $accent;
    }
    QPushButton#PrimaryButton:hover {
        background: $accent_hover;
    }
    QPushButton#HeroPrimaryButton {
        background: white;
        color: #102033;
        border: 1px solid white;
        font-weight: 800;
    }
    QPushButton#HeroPrimaryButton:hover {
        background: #eaf3ff;
        border-color: #eaf3ff;
    }
    QPushButton#HeroSecondaryButton {
        background: rgba(255, 255, 255, 44);
        color: white;
        border: 1px solid rgba(255, 255, 255, 170);
    }
    QPushButton#HeroSecondaryButton:hover {
        background: rgba(255, 255, 255, 70);
        border-color: white;
    }
    QPushButton#HeroDisabledButton {
        background: rgba(255, 255, 255, 18);
        color: #d8e5f5;
        border: 1px solid rgba(255, 255, 255, 75);
    }
    QPushButton:disabled, QLineEdit:disabled, QComboBox:disabled {
        background: #edf2f7;
        color: #94a3b8;
        border-color: #d8e2ee;
    }
    QFrame#SectionCard, QFrame#ChartCard, QFrame#DocumentCard, QFrame#AccordionSection {
        background: $surface;
        border: 1px solid $border;
        border-radius: ${radius_lg}px;
    }
    QFrame#ChartCard, QFrame#DocumentCard {
        background: $surface_elevated;
    }
    QFrame#MetricCard {
        background: $surface_elevated;
        border: 1px solid $border;
        border-radius: ${radius_lg}px;
    }
    QWidget#ToolbarFilterRow {
        background: transparent;
    }
    QToolButton#AccordionHeader {
        background: transparent;
        border: 0;
        border-radius: ${radius_lg}px;
        padding: 12px 14px;
        color: #172033;
        font-size: 11pt;
        font-weight: 850;
        text-align: left;
    }
    QToolButton#AccordionHeader:hover {
        background: $hover;
    }
    QFrame#AccordionSection[expanded="true"] {
        border-color: #9fc5f3;
        border-top-color: $accent;
    }
    QWidget#AccordionBody {
        background: transparent;
    }
    QTableWidget, QListWidget, QTextEdit, QTreeWidget {
        background: $surface;
        color: $navy;
        border: 1px solid $border;
        border-radius: ${radius_md}px;
        gridline-color: transparent;
        selection-background-color: #dbeafe;
        selection-color: #172033;
    }
    QTreeWidget#InformationTree {
        background: $surface;
        border: 1px solid $border;
        border-radius: ${radius_md}px;
        padding: 6px;
        outline: 0;
    }
    QTreeWidget#InformationTree::item {
        min-height: 27px;
        padding: 4px 6px;
        border-radius: 5px;
    }
    QTreeWidget#InformationTree::item:hover {
        background: $hover;
    }
    QTreeWidget#InformationTree::item:selected {
        background: $accent;
        color: white;
    }
    QTreeWidget#InformationTree::branch {
        background: transparent;
    }
    QTableWidget {
        alternate-background-color: #f7faff;
    }
    QTableWidget::item {
        padding: 5px;
        border: 0;
    }
    QTableWidget::item:selected {
        background: #dbeafe;
        color: #172033;
    }
    QTableCornerButton::section {
        background: #eef3f9;
        border: 0;
    }
    QListWidget#CardList {
        background: transparent;
        border: 0;
        outline: 0;
    }
    QListWidget#CardList::item {
        background: $surface;
        border: 1px solid $border;
        border-radius: ${radius_md}px;
        padding: 6px;
        margin: 0 0 8px 0;
    }
    QListWidget#CardList::item:hover {
        background: $surface_elevated;
        border-color: $border_strong;
    }
    QListWidget#CardList::item:focus {
        border: 1px dashed $accent;
    }
    QListWidget#CardList::item:selected {
        background: #dbeafe;
        border-color: $accent;
        color: #172033;
    }
    QScrollArea {
        background: transparent;
        border: 0;
    }
    QScrollArea > QWidget > QWidget {
        background: transparent;
    }
    QAbstractScrollArea::viewport {
        background: transparent;
    }
    QHeaderView::section {
        background: #eef3f9;
        color: #243b53;
        border: 0;
        border-bottom: 1px solid $border;
        padding: 7px;
        font-weight: 700;
    }
    QComboBox {
        background: $surface;
        border: 1px solid #cbd5e1;
        border-radius: ${radius_md}px;
        padding: 6px 30px 6px 9px;
        min-height: 28px;
    }
    QCheckBox {
        color: #172033;
        spacing: 7px;
        font-weight: 600;
    }
    QCheckBox::indicator {
        width: 15px;
        height: 15px;
        border: 1px solid #cbd5e1;
        border-radius: 4px;
        background: $surface;
    }
    QCheckBox::indicator:checked {
        background: $accent;
        border-color: $accent;
    }
    QComboBox::drop-down {
        border: 0;
        width: 28px;
    }
    QComboBox QAbstractItemView, QMenu {
        background: $surface;
        color: #172033;
        border: 1px solid $border;
        border-radius: ${radius_md}px;
        padding: 6px;
        selection-background-color: #dbeafe;
        selection-color: #172033;
    }
    QMenu::item {
        padding: 7px 18px;
        border-radius: 5px;
    }
    QMenu::item:selected {
        background: $hover;
    }
    QSplitter::handle {
        background: transparent;
        margin: 4px;
    }
    QSplitter::handle:hover {
        background: #dbeafe;
        border-radius: 3px;
    }
    QStatusBar {
        background: #e6eef7;
        border-top: 1px solid $border;
        color: $muted_text;
        padding: 3px 8px;
    }
    QStatusBar QLabel {
        color: $muted_text;
    }
    QToolTip {
        background: $surface;
        color: $navy;
        border: 1px solid $border_strong;
        border-radius: ${radius_md}px;
        padding: 7px;
    }
    QDialog, QMessageBox {
        background: $background;
        color: $navy;
    }
    QDialog QLabel, QMessageBox QLabel {
        color: $navy;
    }
    QMessageBox {
        border: 1px solid $border;
    }
    QMessageBox QPushButton {
        min-width: 86px;
        padding: 7px 14px;
    }
    QDialogButtonBox QPushButton {
        min-width: 86px;
        padding: 7px 14px;
    }
    QScrollBar:vertical {
        background: transparent;
        width: 10px;
        margin: 4px 2px 4px 2px;
    }
    QScrollBar::handle:vertical {
        background: $scroll_handle;
        border-radius: 4px;
        min-height: 32px;
    }
    QScrollBar::handle:vertical:hover {
        background: $scroll_hover;
    }
    QScrollBar::handle:vertical:pressed {
        background: $accent;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
        border: 0;
        background: transparent;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: transparent;
    }
    QScrollBar:horizontal {
        background: transparent;
        height: 10px;
        margin: 2px 4px 2px 4px;
    }
    QScrollBar::handle:horizontal {
        background: $scroll_handle;
        border-radius: 4px;
        min-width: 32px;
    }
    QScrollBar::handle:horizontal:hover {
        background: $scroll_hover;
    }
    QScrollBar::handle:horizontal:pressed {
        background: $accent;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
        border: 0;
        background: transparent;
    }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
        background: transparent;
    }
    QLabel#LoadingTitle {
        color: #111827;
        font-size: 26pt;
        font-weight: 900;
    }
    QLabel#LoadingSubtitle {
        color: #243b53;
        font-size: 11pt;
        font-weight: 600;
    }
    QLabel#LoadingTip {
        background: #f4f7fb;
        color: #172033;
        border: 1px solid $border;
        border-radius: ${radius_md}px;
        padding: 12px;
        min-height: 54px;
    }
    QLabel#LoadingStatus {
        color: $muted_text;
        font-size: 9pt;
        font-weight: 600;
    }
    QWidget#ListTile {
        background: transparent;
    }
    QLabel#TileTitle {
        color: #172033;
        font-size: 13pt;
        font-weight: 900;
    }
    QLabel#TileSubtitle {
        color: #324a63;
        font-size: 9pt;
        font-weight: 700;
    }
    QLabel#TileMeta {
        color: $muted_text;
        font-size: 8pt;
        font-weight: 700;
    }
    QDialog#PhotoViewerDialog {
        background: #0b1220;
        color: #f8fbff;
    }
    QFrame#PhotoViewerStage {
        background: #050a12;
        border: 1px solid #263548;
        border-radius: 10px;
    }
    QScrollArea#PhotoViewerFilmstrip {
        background: #101927;
        border: 1px solid #31445d;
        border-radius: 9px;
        min-height: 116px;
    }
    QScrollArea#PhotoViewerFilmstrip QWidget {
        background: transparent;
    }
    QDialog#AtlasCommandPalette, QDialog#InstallPacketDialog, QDialog#SetupPacketDialog, QDialog#SetupPacketPdfViewerDialog, QDialog#CompareDialog, QDialog#QRLabelPreviewDialog {
        background: $background;
        color: $navy;
    }
    QListWidget#CommandPaletteResults {
        background: $surface;
        border: 1px solid $border;
        border-radius: ${radius_md}px;
        padding: 6px;
        outline: 0;
    }
    QListWidget#CommandPaletteResults::item {
        min-height: 32px;
        padding: 6px 8px;
        border-radius: 5px;
    }
    QListWidget#CommandPaletteResults::item:selected {
        background: $hover;
        color: #172033;
    }
    QLabel#PhotoViewerTitle {
        color: #f8fbff;
        font-size: 13pt;
        font-weight: 900;
    }
    QLabel#PhotoViewerMeta {
        color: #d7e7f7;
        font-size: 9pt;
        font-weight: 700;
    }
    QLabel#PhotoViewerCount {
        background: #f8fbff;
        color: #0b1220;
        border-radius: 12px;
        padding: 5px 10px;
        font-size: 10pt;
        font-weight: 900;
    }
    QLabel#PhotoViewerImage {
        background: transparent;
        border: 0;
        color: #d7e7f7;
        font-weight: 700;
    }
    QLabel#PhotoViewerThumb {
        background: #172033;
        border: 2px solid #405872;
        border-radius: 8px;
        color: #d7e7f7;
        font-weight: 800;
        padding: 4px;
    }
    QLabel#PhotoViewerThumb[selected="true"] {
        background: #f8fbff;
        border: 3px solid $accent;
        color: #0b1220;
    }
    QPushButton#PhotoViewerButton, QPushButton#PhotoViewerSecondaryButton, QToolButton#PhotoViewerToolButton {
        background: #f8fbff;
        color: #0b1220;
        border: 1px solid #b8c7dc;
        border-radius: ${radius_md}px;
        padding: 6px 12px;
        font-weight: 800;
    }
    QPushButton#PhotoViewerButton:hover, QPushButton#PhotoViewerSecondaryButton:hover, QToolButton#PhotoViewerToolButton:hover {
        background: #e7f1ff;
        border-color: $accent;
    }
    QPushButton#PhotoViewerCloseButton {
        background: #fee2e2;
        color: #7f1d1d;
        border: 1px solid #fecaca;
        border-radius: ${radius_md}px;
        padding: 6px 12px;
        font-weight: 900;
    }
    QPushButton#PhotoViewerCloseButton:hover {
        background: #fecaca;
        border-color: #f87171;
    }
    QPushButton#PhotoViewerButton:disabled, QPushButton#PhotoViewerSecondaryButton:disabled, QToolButton#PhotoViewerToolButton:disabled {
        background: #263548;
        color: #b8c7dc;
        border-color: #405872;
    }
    QLabel#ScoreTotal {
        color: #102033;
        font-size: 18pt;
        font-weight: 900;
    }
    QLabel#ScorePoints {
        background: #102033;
        color: white;
        border-radius: 12px;
        min-width: 46px;
        padding: 5px 8px;
        font-weight: 900;
    }
    QFrame#ScoreFactorPositive {
        background: #e6f6ef;
        border: 1px solid #a7e1c8;
        border-left: 5px solid $success;
        border-radius: 7px;
    }
    QFrame#ScoreFactorNeutral {
        background: #e7f1ff;
        border: 1px solid #b9d7fb;
        border-left: 5px solid $accent;
        border-radius: 7px;
    }
    QFrame#ScoreFactorNegative {
        background: #fff4dd;
        border: 1px solid #f8d99a;
        border-left: 5px solid $warning;
        border-radius: 7px;
    }
    """).substitute(tokens)
    stylesheet = base
    if theme_name == "dark":
        stylesheet += _dark_overrides(tokens)
    if scheme_name != "atlas_blue":
        stylesheet += _scheme_overrides(tokens, scheme_name=scheme_name, dark=theme_name == "dark")
    return stylesheet


def _dark_overrides(tokens: dict[str, object]) -> str:
    return Template("""
    QMainWindow, QWidget {
        background: $background;
        color: #e5edf7;
    }
    QLabel#PageTitle, QLabel#CardTitle, QLabel#SectionTitle, QLabel#DetailTitle,
    QLabel#BodyText, QLabel#MetricValue, QLabel#TileTitle {
        color: #e5edf7;
    }
    QLabel#PageSubtitle, QLabel#DocumentMetadata, QLabel#DocumentPath, QLabel#AccordionSummary {
        color: $muted_text;
    }
    QLabel#DocumentTitle, QLabel#DocumentDescription, QLabel#DocumentPreview {
        color: #e5edf7;
    }
    QLabel#DocumentCategory, QLabel#MetricIcon {
        color: $accent;
    }
    QLabel#TileSubtitle {
        color: #c6d6e8;
    }
    QLabel#MutedText, QLabel#MicroText, QLabel#MetricLabel, QLabel#TileMeta {
        color: $muted_text;
    }
    QFrame#AtlasCard,
    QFrame#PrimaryCard,
    QFrame#SecondaryCard,
    QFrame#DetailCard,
    QFrame#InfoPanel,
    QFrame#CompactStatCard,
    QFrame#FeatureActionCard,
    QFrame#ExportActionCard,
    QFrame#DenseDataPanel,
    QFrame#SectionCard,
    QFrame#ChartCard,
    QFrame#DocumentCard,
    QFrame#MetricCard,
    QFrame#AccordionSection {
        background: $surface;
        border-color: $border;
    }
    QFrame#PrimaryCard {
        border-top-color: $accent;
    }
    QFrame#SecondaryCard,
    QFrame#CompactStatCard {
        background: $surface_elevated;
    }
    QFrame#DetailCard {
        background: #101b2a;
    }
    QFrame#CompatibilityCard {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #142237, stop:1 #102f3c);
        border-color: #296a7d;
        border-top-color: $accent_secondary;
    }
    QFrame#PhotoGalleryCard {
        background: #131f32;
        border-color: #354861;
        border-top-color: #7aa2e3;
    }
    QFrame#ChecklistCard {
        background: #122438;
        border-color: #31506d;
        border-top-color: $success;
    }
    QFrame#WarningCard {
        background: #332514;
        border-color: #7a5525;
        border-left-color: $warning;
    }
    QFrame#DangerCard {
        background: #361d22;
        border-color: #7e3d45;
        border-left-color: $danger;
    }
    QToolButton#AccordionHeader {
        background: transparent;
        color: #e5edf7;
        border: 0;
    }
    QToolButton#AccordionHeader:hover {
        background: $hover;
    }
    QFrame#SuccessCard {
        background: #123124;
        border-color: #2e704f;
        border-left-color: $success;
    }
    QFrame#ProfileHeaderCard {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #07111e, stop:.55 #143f63, stop:1 #1f75bd);
    }
    QFrame#EmptyState {
        background: #101b2a;
        border-color: $border_strong;
    }
    QLabel#SuccessChip, QLabel#BadgeGood {
        background: #123a2a;
        color: $success;
    }
    QLabel#WarningChip, QLabel#BadgeWarn {
        background: #3a2d12;
        color: $warning;
    }
    QLabel#DangerChip, QLabel#BadgeBad {
        background: #412028;
        color: $danger;
    }
    QLabel#PrimaryChip, QLabel#BadgeInfo {
        background: #17314f;
        color: #a8d3ff;
    }
    QLabel#NeutralChip {
        background: #1a293d;
        color: #c7d6e8;
    }
    QLabel#OutlineChip {
        background: transparent;
        color: #a8d3ff;
        border-color: #49739f;
    }
    QLabel#CountChip {
        background: #dbeafe;
        color: #102033;
    }
    QFrame#MiniProgressTrack {
        background: #26364a;
    }
    QLabel#PhotoThumb {
        background: #101b2a;
        border-color: $border;
        color: $muted_text;
    }
    QLineEdit, QLineEdit#ModernSearchBar, QComboBox {
        background: $surface;
        color: #e5edf7;
        border-color: $border_strong;
        selection-background-color: #264d78;
    }
    QCheckBox {
        color: #e5edf7;
    }
    QCheckBox::indicator {
        background: #0f1a29;
        border-color: $border_strong;
    }
    QCheckBox::indicator:checked {
        background: $accent;
        border-color: $accent;
    }
    QPushButton {
        background: $surface;
        color: #e5edf7;
        border-color: $border_strong;
    }
    QPushButton:hover {
        background: $hover;
        border-color: $accent;
    }
    QPushButton#PrimaryButton {
        background: $accent;
        color: #07111e;
        border-color: $accent;
    }
    QPushButton:disabled, QLineEdit:disabled, QComboBox:disabled {
        background: #182536;
        color: #8798ad;
        border-color: $border;
    }
    QTableWidget, QListWidget, QTextEdit, QTreeWidget {
        background: #0f1a29;
        color: #e5edf7;
        border-color: $border;
        selection-background-color: #214a73;
        selection-color: #f8fbff;
    }
    QTreeWidget#InformationTree {
        background: #0f1a29;
        color: #e5edf7;
        border-color: $border;
    }
    QTreeWidget#InformationTree::item:hover {
        background: $hover;
    }
    QTreeWidget#InformationTree::item:selected {
        background: $accent;
        color: #07111e;
    }
    QTableWidget {
        alternate-background-color: #142135;
    }
    QTableWidget::item:selected, QListWidget#CardList::item:selected {
        background: #214a73;
        color: #f8fbff;
    }
    QListWidget#CardList::item {
        background: $surface;
        border-color: $border;
    }
    QListWidget#CardList::item:selected {
        background: #173a5f;
        border-color: $accent;
        color: #f8fbff;
    }
    QHeaderView::section, QTableCornerButton::section {
        background: #18283c;
        color: #d9e5f2;
        border-bottom-color: $border;
    }
    QComboBox QAbstractItemView, QMenu {
        background: $surface;
        color: #e5edf7;
        border-color: $border;
        selection-background-color: #214a73;
        selection-color: #f8fbff;
    }
    QStatusBar {
        background: #0a1320;
        border-top-color: $border;
        color: $muted_text;
    }
    QToolTip {
        background: $surface;
        color: #e5edf7;
        border-color: $border_strong;
    }
    QDialog, QMessageBox,
    QDialog#AtlasCommandPalette, QDialog#InstallPacketDialog, QDialog#SetupPacketDialog, QDialog#SetupPacketPdfViewerDialog, QDialog#CompareDialog, QDialog#QRLabelPreviewDialog {
        background: $background;
        color: #e5edf7;
    }
    QDialog QLabel, QMessageBox QLabel {
        color: #e5edf7;
    }
    QMessageBox {
        border: 1px solid $border;
    }
    QLabel#LoadingTitle, QLabel#LoadingSubtitle, QLabel#LoadingTip {
        color: #e5edf7;
    }
    QLabel#LoadingTip {
        background: $surface;
        border-color: $border;
    }
    QLabel#ScoreTotal {
        color: #e5edf7;
    }
    QLabel#ScorePoints {
        background: #dbeafe;
        color: #07111e;
    }
    QFrame#ScoreFactorPositive {
        background: #123a2a;
        border-color: #246849;
        border-left-color: $success;
    }
    QFrame#ScoreFactorNeutral {
        background: #17314f;
        border-color: #31577f;
        border-left-color: $accent;
    }
    QFrame#ScoreFactorNegative {
        background: #3a2d12;
        border-color: #735a25;
        border-left-color: $warning;
    }
    """).substitute(tokens)


def _scheme_overrides(tokens: dict[str, object], *, scheme_name: str, dark: bool = False) -> str:
    tree_selected_text = "#07111e" if dark else "#ffffff"
    soft_surfaces = {
        "nolato_logo": ("#201014", "#fff7f8"),
        "industrial_graphite": ("#1e262d", "#f3f7f9"),
        "aurora_tech": ("#111f3a", "#f2f8ff"),
    }
    dark_surface, light_surface = soft_surfaces.get(scheme_name, ("#1f2228", "#f7f8fa"))
    card_surface = dark_surface if dark else light_surface
    info_surface = str(tokens["surface_elevated"])
    profile_end = str(tokens["accent"])
    return Template("""
    QWidget#AtlasSidebarPanel {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #050607, stop:.62 #17191d, stop:1 $hero_start);
    }
    QFrame#AtlasSidebarHeader {
        background: $sidebar_logo_card_bg;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $sidebar_logo_card_bg_gradient_start, stop:1 $sidebar_logo_card_bg_gradient_end);
        border-color: $sidebar_logo_card_border;
        border-bottom-color: $sidebar_logo_card_accent;
    }
    QFrame#AtlasSidebarHeader:hover {
        border-color: $sidebar_logo_card_shadow;
    }
    QLabel#AtlasSidebarTitle {
        color: $sidebar_logo_card_text;
    }
    QLabel#AtlasSidebarLogo {
        background: $sidebar_logo_image_bg;
    }
    QLabel#AtlasNavSectionLabel {
        color: $accent_secondary;
    }
    QPushButton#AtlasNavItem:hover {
        background: $hover;
        border-left-color: $accent;
    }
    QPushButton#AtlasNavItem:checked {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent, stop:1 $hero_mid);
        border-left-color: #ffffff;
    }
    QFrame#ProfileHeaderCard {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $hero_start, stop:.58 $hero_mid, stop:1 $profile_end);
    }
    QFrame#PrimaryCard {
        border-top-color: $accent;
    }
    QFrame#FeatureActionCard {
        background: $card_surface;
        border-left-color: $accent;
    }
    QFrame#InfoPanel, QFrame#SecondaryCard, QFrame#CompactStatCard {
        background: $info_surface;
    }
    QLabel#PrimaryChip, QLabel#BadgeInfo {
        background: $card_surface;
        color: $accent;
    }
    QLabel#OutlineChip {
        color: $accent;
        border-color: $accent;
    }
    QLabel#CountChip {
        background: #17191d;
        color: #ffffff;
    }
    QPushButton#PrimaryButton, QCheckBox::indicator:checked {
        background: $accent;
        border-color: $accent;
        color: #ffffff;
    }
    QPushButton#PrimaryButton:hover {
        background: $accent_hover;
    }
    QLineEdit:focus, QLineEdit#ModernSearchBar:focus {
        border-color: $accent;
    }
    QTreeWidget#InformationTree::item:selected {
        background: $accent;
        color: $tree_selected_text;
    }
    QStatusBar {
        border-top-color: $border;
    }
    """).substitute({**tokens, "tree_selected_text": tree_selected_text, "card_surface": card_surface, "info_surface": info_surface, "profile_end": profile_end})


__all__ = [
    "DARK_DESIGN_TOKENS",
    "DESIGN_TOKENS",
    "FONT_SIZES",
    "AURORA_TECH_DARK_TOKENS",
    "AURORA_TECH_TOKENS",
    "INDUSTRIAL_GRAPHITE_DARK_TOKENS",
    "INDUSTRIAL_GRAPHITE_TOKENS",
    "NOLATO_DARK_DESIGN_TOKENS",
    "NOLATO_DESIGN_TOKENS",
    "RADIUS",
    "SPACING",
    "atlas_stylesheet",
]
