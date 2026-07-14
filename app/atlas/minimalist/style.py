from __future__ import annotations

MINIMALIST_STYLES = """
QWidget#MinimalistAtlasShell,
QWidget#MinimalistContentHost,
QWidget#MinimalistHomeContent,
QWidget#MinimalistTopBar,
QWidget#MinimalistPillContainer,
QWidget#EntitySearchDropdownBody {
    background: transparent;
}
QScrollArea#EntitySearchScroll {
    background: transparent;
    border: 0;
}
QScrollArea#EntitySearchScroll QWidget {
    background: transparent;
}
QLabel#MinimalistLogoEOAT {
    color: #f8fbff;
    font-size: 20pt;
    font-weight: 850;
}
QLabel#MinimalistLogoAtlas {
    color: #1394ff;
    font-size: 20pt;
    font-weight: 850;
}
QLabel#MinimalistPageTitle {
    color: #f8fbff;
    font-size: 31pt;
    font-weight: 820;
}
QFrame#MinimalistTitleAccent {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(0, 89, 200, 0), stop:.52 #047aff, stop:1 rgba(0, 89, 200, 0));
    border: 0;
    min-height: 3px;
    max-height: 3px;
}
QLabel#MinimalistCardHeading {
    color: #f8fbff;
    font-size: 27pt;
    font-weight: 760;
}
QLabel#MinimalistCardSubtitle {
    color: #d7e2f0;
    font-size: 15pt;
    font-weight: 420;
}
QLabel#MinimalistRecentLabel {
    color: #f7f8fb;
    font-size: 13pt;
    font-weight: 520;
}
QLabel#MinimalistRecentEmpty {
    color: #b7c4d5;
    font-size: 11pt;
    font-weight: 450;
    padding: 3px 0 8px 0;
}
QLineEdit#MinimalistHomeSearchInput {
    background: transparent;
    border: 0;
    color: #eef6ff;
    font-size: 14.5pt;
    selection-background-color: #1f87ff;
}
QLineEdit#MinimalistPanelSearchInput {
    background: transparent;
    border: 0;
    color: #eef6ff;
    font-size: 9pt;
    selection-background-color: #1f87ff;
}
QPushButton#MinimalistPill {
    background: rgba(15, 29, 49, 132);
    color: #f8fbff;
    border: 1px solid rgba(139, 171, 216, 82);
    border-radius: 11px;
    padding: 12px 24px;
    font-size: 11pt;
    font-weight: 620;
    min-height: 36px;
}
QPushButton#MinimalistPill:hover {
    background: rgba(26, 56, 96, 160);
    border-color: rgba(31, 135, 255, 180);
}
QPushButton#MinimalistPill:disabled {
    color: rgba(214, 224, 238, 120);
    border-color: rgba(139, 171, 216, 44);
}
QLabel#MinimalistStatusText {
    color: #d6e1ef;
    font-size: 11pt;
}
QFrame#MinimalistDivider {
    background: rgba(132, 165, 210, 45);
    border: 0;
    min-height: 1px;
    max-height: 1px;
    margin: 10px 0;
}
QPushButton#MinimalistMenuItem {
    background: transparent;
    color: #f5f8ff;
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 0 12px;
    text-align: left;
    font-size: 11pt;
    font-weight: 500;
    min-height: 55px;
}
QPushButton#MinimalistMenuItem:hover {
    background: rgba(28, 72, 128, 132);
    border-color: rgba(31, 135, 255, 132);
}
QPushButton#MinimalistMenuItem:focus {
    border-color: rgba(31, 135, 255, 88);
}
QPushButton#MinimalistMenuItem:pressed {
    background: rgba(26, 76, 142, 148);
    border-color: rgba(31, 135, 255, 152);
}
QPushButton#MinimalistMenuItem[active="true"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(19, 90, 230, 218), stop:1 rgba(14, 58, 132, 154));
    border-color: rgba(71, 176, 255, 214);
}
QPushButton#MinimalistMenuItem[active="true"]:hover,
QPushButton#MinimalistMenuItem[active="true"]:pressed,
QPushButton#MinimalistMenuItem[active="true"]:focus {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(19, 90, 230, 218), stop:1 rgba(14, 58, 132, 154));
    border-color: rgba(71, 176, 255, 214);
}
QLabel#MinimalistPanelTitle {
    color: #f8fbff;
    font-size: 11pt;
    font-weight: 720;
}
QLabel#MinimalistSectionLabel {
    color: #f8fbff;
    font-size: 9pt;
    font-weight: 720;
    padding-top: 2px;
    padding-bottom: 6px;
}
QLabel#FitCheckDropdownGroup {
    color: #62c7ff;
    font-size: 7.6pt;
    font-weight: 780;
    letter-spacing: 0;
    padding: 3px 6px 0 6px;
}
QPushButton#MinimalistSearchRow,
QPushButton#MinimalistSuggestionRow {
    background: rgba(4, 16, 34, 126);
    border: 1px solid rgba(78, 118, 166, 54);
    border-radius: 8px;
    color: #f8fbff;
    text-align: left;
    padding: 0;
}
QPushButton#MinimalistSearchRow:hover,
QPushButton#MinimalistSuggestionRow:hover {
    background: rgba(24, 76, 142, 162);
    border-color: rgba(31, 135, 255, 150);
}
QPushButton#MinimalistSuggestionRow {
    padding-left: 34px;
    font-size: 10pt;
    font-weight: 520;
    min-height: 44px;
}
QLabel#MinimalistRowTitle {
    color: #f8fbff;
    font-size: 10pt;
}
QLabel#MinimalistRowKind {
    color: #cbd7e6;
    font-size: 9pt;
}
QLabel#MinimalistRowSubtitle {
    color: #b3c1d3;
    font-size: 8pt;
}
QLabel#MinimalistPanelEmpty {
    color: #b7c4d5;
    font-size: 9pt;
}
QLabel#MinimalistToastText {
    color: #eef6ff;
    font-size: 10.5pt;
    font-weight: 540;
}
QWidget#MinimalistSearchFooter {
    border-top: 1px solid rgba(132, 165, 210, 72);
    min-height: 64px;
    background: rgba(2, 9, 20, 138);
}
QLabel#MinimalistFooterText {
    color: #c6d3e3;
    font-size: 9pt;
}
QWidget#AtlasMinimalistLibraryPage,
QWidget#MinimalistLibraryContent,
QWidget#LibraryControlRow,
QWidget#LibrarySecondaryControlRow,
QWidget#LibraryActivePillHost,
QWidget#LibrarySmartChipHost,
QWidget#LibraryBodyWidget,
QWidget#LibraryRecordStateView,
QWidget#LibraryRecordSections,
QWidget#LibraryCriteriaBody,
QWidget#LibraryDetailBody,
QWidget#LibraryActionRow,
QWidget#LibraryDetailMiniRow,
QWidget#LibraryDetailChipRow,
QWidget#LibraryDetailChipHost,
QWidget#LibraryHeroChipRow,
QWidget#LibraryCardGridHost,
QWidget#LibraryInspectorHeaderChips,
QWidget#LibraryComposerActiveHost,
QWidget#LibraryComposerCategoryRail,
QWidget#LibraryComposerValueArea,
QWidget#LibraryViewSelector,
QWidget#LibrarySegmentedSelector {
    background: transparent;
}
QScrollArea#LibraryBodyScroll,
QScrollArea#LibraryCriteriaScroll,
QScrollArea#LibraryDetailScroll {
    background: transparent;
    border: 0;
}
QScrollArea#LibraryBodyScroll QWidget,
QScrollArea#LibraryCriteriaScroll QWidget,
QScrollArea#LibraryDetailScroll QWidget {
    background: transparent;
}
QScrollBar:vertical {
    background: rgba(4, 12, 24, 64);
    width: 9px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: rgba(58, 143, 255, 112);
    border-radius: 4px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
QLineEdit#LibrarySearchInput {
    background: transparent;
    border: 0;
    color: #eef6ff;
    font-size: 10.5pt;
    selection-background-color: #1f87ff;
}
QPushButton#LibrarySegmentChip,
QPushButton#LibraryViewChip,
QPushButton#LibrarySmartChip,
QPushButton#LibraryFilterChip,
QPushButton#LibraryActionChip,
QPushButton#LibraryCriteriaCategoryChip,
QPushButton#LibraryCriteriaValueChip {
    background: rgba(15, 38, 72, 178);
    color: #f4faff;
    border: 1px solid rgba(113, 181, 255, 138);
    border-radius: 10px;
    padding: 7px 11px;
    font-size: 9pt;
    font-weight: 700;
}
QPushButton#LibrarySegmentChip:hover,
QPushButton#LibraryViewChip:hover,
QPushButton#LibrarySmartChip:hover,
QPushButton#LibraryFilterChip:hover,
QPushButton#LibraryActionChip:hover,
QPushButton#LibraryCriteriaCategoryChip:hover,
QPushButton#LibraryCriteriaValueChip:hover {
    background: rgba(28, 70, 124, 216);
    border-color: rgba(67, 210, 255, 220);
}
QPushButton#LibrarySegmentChip[active="true"],
QPushButton#LibraryViewChip[active="true"],
QPushButton#LibrarySmartChip[active="true"],
QPushButton#LibraryFilterChip[active="true"],
QPushButton#LibraryCriteriaCategoryChip[active="true"],
QPushButton#LibraryCriteriaValueChip[active="true"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(20, 105, 255, 198), stop:1 rgba(0, 201, 255, 112));
    border-color: rgba(103, 210, 255, 210);
    color: #ffffff;
}
QPushButton#LibraryCriteriaButton,
QPushButton#LibraryPrimaryAction {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(31, 127, 255, 218), stop:1 rgba(9, 71, 166, 198));
    color: #f7fbff;
    border: 1px solid rgba(116, 209, 255, 204);
    border-radius: 11px;
    padding: 8px 15px;
    font-size: 9.5pt;
    font-weight: 720;
}
QPushButton#LibraryCriteriaButton:hover,
QPushButton#LibraryPrimaryAction:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(39, 125, 255, 210), stop:1 rgba(12, 79, 184, 192));
    border-color: rgba(96, 214, 255, 218);
}
QPushButton#LibraryActiveFilterPill {
    background: rgba(20, 58, 104, 184);
    color: #e8f4ff;
    border: 1px solid rgba(104, 190, 255, 162);
    border-radius: 10px;
    padding: 5px 10px;
    font-size: 8.5pt;
    font-weight: 640;
}
QPushButton#LibraryActiveFilterPill:hover {
    border-color: rgba(77, 213, 255, 200);
    background: rgba(23, 69, 124, 172);
}
QPushButton#LibraryClearFilters,
QPushButton#LibraryLinkButton {
    background: transparent;
    color: #8fc9ff;
    border: 1px solid transparent;
    padding: 5px 6px;
    font-size: 8.5pt;
    font-weight: 620;
}
QPushButton#LibraryClearFilters:hover,
QPushButton#LibraryLinkButton:hover {
    color: #d5f1ff;
    border-color: rgba(77, 213, 255, 112);
    border-radius: 8px;
}
QLabel#LibraryPanelHeading {
    color: #f8fbff;
    font-size: 18pt;
    font-weight: 760;
}
QLabel#LibraryHeroSectionTitle {
    color: #83d8ff;
    font-size: 8.5pt;
    font-weight: 780;
}
QLabel#LibraryComposerLabel {
    color: #d9ecff;
    font-size: 9pt;
    font-weight: 780;
}
QLabel#LibraryComposerEmpty {
    color: #b0bfd2;
    font-size: 8.5pt;
    font-weight: 620;
}
QLabel#LibrarySectionTitle {
    color: #dce9f9;
    font-size: 10.5pt;
    font-weight: 700;
}
QLabel#LibraryBreadcrumb {
    color: #dcecff;
    font-size: 10.5pt;
    font-weight: 700;
}
QLabel#LibraryMutedText,
QLabel#LibraryGroupSubtitle,
QLabel#LibraryRecordMeta,
QLabel#LibraryHeroMeta,
QLabel#LibraryEmptySubtitle,
QLabel#LibraryEmptyMini {
    color: #b7c4d5;
    font-size: 9pt;
}
QLabel#LibraryCategoryTitle,
QLabel#LibraryGroupTitle,
QLabel#LibraryDrawerTitle {
    color: #f7fbff;
    font-size: 12.5pt;
    font-weight: 760;
}
QLabel#LibraryDrawerTitle {
    font-size: 18pt;
    font-weight: 820;
}
QLabel#LibraryDrawerSubtitle {
    color: #c0ccdc;
    font-size: 10.5pt;
    font-weight: 560;
}
QLabel#LibraryCategoryCount {
    color: #ffffff;
    font-size: 29pt;
    font-weight: 820;
}
QLabel#LibraryHeroType {
    color: #6edcff;
    font-size: 9pt;
    font-weight: 760;
    letter-spacing: 0;
}
QLabel#LibraryHeroTitle {
    color: #ffffff;
    font-size: 24pt;
    font-weight: 820;
}
QLabel#LibraryHeroSubtitle {
    color: #dce7f4;
    font-size: 11pt;
    font-weight: 560;
}
QLabel#LibraryRecordTitle {
    color: #f8fbff;
    font-size: 10.5pt;
    font-weight: 760;
}
QLabel#LibraryRecordSubtitle,
QLabel#LibraryDetailValue {
    color: #d2deec;
    font-size: 10pt;
}
QLabel#LibraryDetailLabel {
    color: #76cfff;
    font-size: 9pt;
    font-weight: 760;
}
QLabel#LibraryEmptyTitle {
    color: #f8fbff;
    font-size: 15pt;
    font-weight: 740;
}
QLabel#LibraryFilterGroupTitle {
    color: #d9ecff;
    font-size: 9pt;
    font-weight: 760;
}
QLabel#LibraryStatusBadge {
    color: #dfefff;
    background: rgba(20, 61, 111, 112);
    border: 1px solid rgba(103, 171, 255, 92);
    border-radius: 8px;
    padding: 3px 8px;
    font-size: 8pt;
    font-weight: 650;
}
QLabel#LibraryStatusBadge[tone="good"] {
    color: #d8fff0;
    background: rgba(20, 111, 80, 96);
    border-color: rgba(54, 216, 106, 132);
}
QLabel#LibraryStatusBadge[tone="warn"] {
    color: #ffe8c0;
    background: rgba(126, 79, 24, 92);
    border-color: rgba(255, 177, 69, 128);
}
QLabel#LibraryStatusBadge[tone="bad"],
QLabel#LibraryStatusBadge[tone="error"],
QLabel#LibraryStatusBadge[tone="danger"] {
    color: #ffd4d9;
    background: rgba(116, 24, 44, 96);
    border-color: rgba(255, 92, 108, 132);
}
QLabel#LibraryStatusBadge[tone="neutral"] {
    color: #d8e4f3;
    background: rgba(58, 75, 101, 92);
    border-color: rgba(159, 176, 199, 104);
}
QPushButton#LibraryOrbitItem {
    background: rgba(8, 22, 42, 224);
    color: #f5fbff;
    border: 1px solid rgba(93, 184, 255, 148);
    border-radius: 16px;
    padding: 6px 8px;
    font-size: 8.2pt;
    font-weight: 700;
}
QPushButton#LibraryOrbitItem:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(31, 135, 255, 202), stop:1 rgba(0, 201, 255, 116));
    border-color: rgba(151, 231, 255, 226);
}
QPushButton#LibraryDrawerSectionHeader {
    background: transparent;
    color: #f1f8ff;
    border: 0;
    text-align: left;
    font-size: 11pt;
    font-weight: 720;
}
QTableWidget#LibraryDarkTable {
    background: rgba(5, 14, 29, 138);
    color: #e8f2ff;
    gridline-color: rgba(95, 151, 224, 62);
    border: 1px solid rgba(108, 169, 255, 88);
    border-radius: 10px;
    selection-background-color: rgba(31, 135, 255, 120);
    alternate-background-color: rgba(7, 22, 45, 92);
}
QTableWidget#LibraryDarkTable::item {
    padding: 6px;
    border-bottom: 1px solid rgba(95, 151, 224, 34);
}
QTableWidget#LibraryDarkTable::item:hover {
    background: rgba(31, 135, 255, 58);
}
QHeaderView::section {
    background: rgba(9, 31, 63, 210);
    color: #dcecff;
    border: 0;
    border-bottom: 1px solid rgba(95, 151, 224, 76);
    padding: 6px;
    font-weight: 700;
}
"""

__all__ = ["MINIMALIST_STYLES"]
