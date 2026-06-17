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
}
SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 18, "xl": 24}
RADIUS = {"sm": 5, "md": 7, "lg": 9}
FONT_SIZES = {"body": 10, "small": 8, "section": 12, "page": 18, "hero": 22}


def atlas_stylesheet() -> str:
    tokens = {
        **DESIGN_TOKENS,
        "body_font": FONT_SIZES["body"],
        "hero_font": FONT_SIZES["hero"],
        "page_font": FONT_SIZES["page"],
        "radius_sm": RADIUS["sm"],
        "radius_md": RADIUS["md"],
        "radius_lg": RADIUS["lg"],
    }
    return Template("""
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
        background: #17324f;
        border: 1px solid #244564;
        border-radius: 10px;
    }
    QLabel#AtlasSidebarLogo {
        background: transparent;
    }
    QLabel#AtlasSidebarTitle {
        color: white;
        font-size: 12pt;
        font-weight: 900;
        padding-bottom: 2px;
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
    QFrame#MetricCard, QFrame#ActionCard {
        background: $surface;
        border: 1px solid $border;
        border-radius: ${radius_lg}px;
    }
    QFrame#MetricCard:hover, QFrame#ActionCard:hover {
        background: $surface_elevated;
        border-color: $border_strong;
    }
    QFrame#EmptyState {
        background: $surface_elevated;
        border: 1px dashed $border_strong;
        border-radius: ${radius_md}px;
    }
    QFrame#AtlasHero, QWidget#AtlasHero {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $hero_start, stop:.55 $hero_mid, stop:1 $hero_end);
        border-radius: ${radius_lg}px;
        border: 0;
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
    QLabel#SectionTitle {
        color: #172033;
        font-size: 12pt;
        font-weight: 800;
    }
    QLabel#ProfileTitle {
        color: #172033;
        font-size: 22pt;
        font-weight: 900;
    }
    QLabel#ProfileSubtitle {
        color: $muted_text;
        font-size: 10pt;
        font-weight: 600;
    }
    QLabel#ProfileMetricValue {
        color: #172033;
        font-size: 16pt;
        font-weight: 900;
    }
    QLabel#ProfileMetricLabel {
        color: $muted_text;
        font-size: 8pt;
        font-weight: 700;
    }
    QLabel#MutedText {
        color: $muted_text;
    }
    QLabel#MetricValue {
        color: #172033;
        font-size: 20pt;
        font-weight: 800;
    }
    QLabel#BadgeGood {
        background: #e6f6ef;
        color: $success;
        border-radius: ${radius_sm}px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#BadgeWarn {
        background: #fff4dd;
        color: $warning;
        border-radius: ${radius_sm}px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#BadgeBad {
        background: #fee2e2;
        color: $danger;
        border-radius: ${radius_sm}px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#BadgeInfo {
        background: #e7f1ff;
        color: #1f5fa8;
        border-radius: ${radius_sm}px;
        padding: 3px 7px;
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
        padding: 8px 12px;
        font-weight: 600;
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
    QPushButton:disabled, QLineEdit:disabled, QComboBox:disabled {
        background: #edf2f7;
        color: #94a3b8;
        border-color: #d8e2ee;
    }
    QTableWidget, QListWidget, QTextEdit {
        background: $surface;
        border: 1px solid $border;
        border-radius: ${radius_md}px;
        gridline-color: transparent;
        selection-background-color: #dbeafe;
        selection-color: #172033;
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
        padding: 10px;
        margin: 0 0 8px 0;
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
        padding: 7px;
    }
    QComboBox::drop-down {
        border: 0;
        width: 24px;
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
        color: #172033;
        border: 1px solid $border_strong;
        border-radius: ${radius_md}px;
        padding: 7px;
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
    """).substitute(tokens)


__all__ = ["DESIGN_TOKENS", "FONT_SIZES", "RADIUS", "SPACING", "atlas_stylesheet"]
