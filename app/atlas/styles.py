from __future__ import annotations


def atlas_stylesheet() -> str:
    return """
    QMainWindow, QWidget {
        background: #f4f7fb;
        color: #172033;
        font-family: "Segoe UI";
        font-size: 10pt;
    }
    QListWidget#AtlasSidebar {
        background: #102033;
        border: 0;
        padding: 10px;
        color: #dbeafe;
        font-weight: 600;
    }
    QWidget#AtlasSidebarPanel {
        background: #102033;
    }
    QLabel#AtlasSidebarTitle {
        color: white;
        font-size: 13pt;
        font-weight: 900;
        padding-bottom: 8px;
    }
    QListWidget#AtlasSidebar::item {
        padding: 10px 11px;
        border-radius: 6px;
        margin: 2px 0;
    }
    QListWidget#AtlasSidebar::item:selected {
        background: #2f80ed;
        color: white;
    }
    QListWidget#AtlasSidebar::item:hover {
        background: #1f3654;
    }
    QFrame#AtlasCard {
        background: white;
        border: 1px solid #d7dee8;
        border-radius: 7px;
    }
    QFrame#AtlasHero {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #17324f, stop:1 #2f80ed);
        border-radius: 7px;
        border: 0;
    }
    QLabel#HeroTitle {
        color: white;
        font-size: 22pt;
        font-weight: 800;
    }
    QLabel#HeroSubtitle {
        color: #dbeafe;
        font-size: 11pt;
    }
    QLabel#PageTitle {
        color: #172033;
        font-size: 18pt;
        font-weight: 800;
    }
    QLabel#SectionTitle {
        color: #172033;
        font-size: 12pt;
        font-weight: 800;
    }
    QLabel#MutedText {
        color: #627d98;
    }
    QLabel#MetricValue {
        color: #172033;
        font-size: 20pt;
        font-weight: 800;
    }
    QLabel#BadgeGood {
        background: #e6f6ef;
        color: #146c43;
        border-radius: 5px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#BadgeWarn {
        background: #fff4dd;
        color: #9a5b00;
        border-radius: 5px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLabel#BadgeInfo {
        background: #e7f1ff;
        color: #1f5fa8;
        border-radius: 5px;
        padding: 3px 7px;
        font-weight: 700;
    }
    QLineEdit {
        background: white;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        padding: 9px;
        min-height: 26px;
        selection-background-color: #dbeafe;
    }
    QPushButton {
        background: white;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        padding: 8px 12px;
        font-weight: 600;
    }
    QPushButton:hover {
        background: #e7f1ff;
        border-color: #93c5fd;
    }
    QPushButton#PrimaryButton {
        background: #2f80ed;
        color: white;
        border-color: #2f80ed;
    }
    QPushButton#PrimaryButton:hover {
        background: #256fcf;
    }
    QTableWidget, QListWidget, QTextEdit {
        background: white;
        border: 1px solid #d7dee8;
        border-radius: 6px;
        gridline-color: #e2e8f0;
        selection-background-color: #dbeafe;
        selection-color: #172033;
    }
    QHeaderView::section {
        background: #eef3f9;
        color: #243b53;
        border: 0;
        border-bottom: 1px solid #d7dee8;
        padding: 7px;
        font-weight: 700;
    }
    QComboBox {
        background: white;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        padding: 7px;
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
        border: 1px solid #d7dee8;
        border-radius: 7px;
        padding: 12px;
        min-height: 54px;
    }
    QLabel#LoadingStatus {
        color: #627d98;
        font-size: 9pt;
        font-weight: 600;
    }
    """


__all__ = ["atlas_stylesheet"]
