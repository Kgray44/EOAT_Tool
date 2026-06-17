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
}
SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 18, "xl": 24}
RADIUS = {"sm": 5, "md": 7, "lg": 9}
FONT_SIZES = {"body": 10, "small": 8, "section": 12, "page": 18, "hero": 22}


def atlas_stylesheet(theme: str = "light") -> str:
    theme_name = str(theme or "light").casefold()
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
        padding: 6px;
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
    QLabel#PhotoViewerTitle {
        color: #f8fbff;
        font-size: 13pt;
        font-weight: 900;
    }
    QLabel#PhotoViewerMeta {
        color: #b8c7dc;
        font-size: 9pt;
        font-weight: 700;
    }
    QLabel#PhotoViewerImage {
        background: #050a12;
        border: 1px solid #263548;
        border-radius: 9px;
        color: #d7e7f7;
        font-weight: 700;
    }
    """).substitute(tokens)
    if theme_name != "dark":
        return base
    return base + _dark_overrides(tokens)


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
    QFrame#DenseDataPanel {
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
    QTableWidget, QListWidget, QTextEdit {
        background: #0f1a29;
        color: #e5edf7;
        border-color: $border;
        selection-background-color: #214a73;
        selection-color: #f8fbff;
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
    QLabel#LoadingTitle, QLabel#LoadingSubtitle, QLabel#LoadingTip {
        color: #e5edf7;
    }
    QLabel#LoadingTip {
        background: $surface;
        border-color: $border;
    }
    """).substitute(tokens)


__all__ = ["DARK_DESIGN_TOKENS", "DESIGN_TOKENS", "FONT_SIZES", "RADIUS", "SPACING", "atlas_stylesheet"]
