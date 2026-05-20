from __future__ import annotations


REQUIRED_THEME_TOKENS = [
    "window_bg",
    "sidebar_bg",
    "sidebar_group_text",
    "page_bg",
    "card_bg",
    "card_bg_alt",
    "input_bg",
    "table_bg",
    "table_header_bg",
    "report_bg",
    "text_primary",
    "text_secondary",
    "text_muted",
    "text_disabled",
    "text_on_accent",
    "border",
    "border_strong",
    "divider",
    "accent",
    "accent_hover",
    "accent_pressed",
    "primary_button_bg",
    "secondary_button_bg",
    "button_border",
    "danger",
    "warning",
    "success",
    "info",
    "active_nav_bg",
    "active_nav_text",
    "hover_bg",
    "selected_row_bg",
    "focus_ring",
    "disabled_bg",
]


THEME_TOKENS: dict[str, dict[str, str]] = {
    "light": {
        "window_bg": "#f5f7fa",
        "sidebar_bg": "#e8eef5",
        "sidebar_group_text": "#627d98",
        "page_bg": "#f5f7fa",
        "card_bg": "#ffffff",
        "card_bg_alt": "#f8fafc",
        "input_bg": "#ffffff",
        "table_bg": "#ffffff",
        "table_header_bg": "#edf2f7",
        "report_bg": "#ffffff",
        "text_primary": "#1f2933",
        "text_secondary": "#243b53",
        "text_muted": "#627d98",
        "text_disabled": "#9aa5b1",
        "text_on_accent": "#ffffff",
        "border": "#d7dee8",
        "border_strong": "#cbd5e1",
        "divider": "#d7dee8",
        "accent": "#2f80ed",
        "accent_hover": "#256fcf",
        "accent_pressed": "#1e5fb0",
        "primary_button_bg": "#ffffff",
        "secondary_button_bg": "#f8fafc",
        "button_border": "#cbd5e1",
        "danger": "#c2410c",
        "warning": "#b7791f",
        "success": "#2f855a",
        "info": "#2f80ed",
        "active_nav_bg": "#2f80ed",
        "active_nav_text": "#ffffff",
        "hover_bg": "#dbeafe",
        "selected_row_bg": "#dbeafe",
        "focus_ring": "#93c5fd",
        "disabled_bg": "#edf1f5",
    },
    "dark": {
        "window_bg": "#111827",
        "sidebar_bg": "#0f172a",
        "sidebar_group_text": "#93a4b8",
        "page_bg": "#111827",
        "card_bg": "#1f2937",
        "card_bg_alt": "#243244",
        "input_bg": "#172033",
        "table_bg": "#172033",
        "table_header_bg": "#243244",
        "report_bg": "#172033",
        "text_primary": "#f8fafc",
        "text_secondary": "#dbe6f1",
        "text_muted": "#a8b6c7",
        "text_disabled": "#6b7a90",
        "text_on_accent": "#ffffff",
        "border": "#334155",
        "border_strong": "#475569",
        "divider": "#334155",
        "accent": "#4ea1ff",
        "accent_hover": "#64b0ff",
        "accent_pressed": "#3182ce",
        "primary_button_bg": "#243244",
        "secondary_button_bg": "#1b2535",
        "button_border": "#475569",
        "danger": "#fb923c",
        "warning": "#f6c46b",
        "success": "#5ee0a1",
        "info": "#7cc4ff",
        "active_nav_bg": "#2563eb",
        "active_nav_text": "#ffffff",
        "hover_bg": "#1e3a5f",
        "selected_row_bg": "#1e3a5f",
        "focus_ring": "#60a5fa",
        "disabled_bg": "#202a3a",
    },
}


def normalized_theme(theme: str | None) -> str:
    value = (theme or "light").strip().lower()
    return value if value in THEME_TOKENS else "light"


def theme_tokens(theme: str = "light") -> dict[str, str]:
    return THEME_TOKENS[normalized_theme(theme)].copy()


def app_stylesheet(theme: str = "light") -> str:
    t = theme_tokens(theme)
    return f"""
    QWidget {{
        background: {t["page_bg"]};
        color: {t["text_primary"]};
        font-size: 10pt;
    }}
    QMainWindow, QSplitter, QStackedWidget#ContentStack {{
        background: {t["window_bg"]};
    }}
    QLabel {{
        background: transparent;
        color: {t["text_primary"]};
    }}
    QLabel#MutedText {{
        color: {t["text_muted"]};
    }}
    QToolTip {{
        background: {t["card_bg"]};
        color: {t["text_primary"]};
        border: 1px solid {t["border_strong"]};
        padding: 6px;
    }}
    QPushButton {{
        background: {t["primary_button_bg"]};
        color: {t["text_primary"]};
        border: 1px solid {t["button_border"]};
        padding: 7px 11px;
        border-radius: 5px;
        min-height: 24px;
    }}
    QPushButton:hover {{
        background: {t["hover_bg"]};
        border-color: {t["focus_ring"]};
    }}
    QPushButton:pressed {{
        background: {t["accent_pressed"]};
        color: {t["text_on_accent"]};
    }}
    QPushButton:disabled {{
        color: {t["text_disabled"]};
        background: {t["disabled_bg"]};
        border-color: {t["border"]};
    }}
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
        background: {t["input_bg"]};
        color: {t["text_primary"]};
        border: 1px solid {t["border_strong"]};
        border-radius: 5px;
        padding: 6px;
        selection-background-color: {t["selected_row_bg"]};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border-color: {t["focus_ring"]};
    }}
    QComboBox QAbstractItemView {{
        background: {t["input_bg"]};
        color: {t["text_primary"]};
        border: 1px solid {t["border_strong"]};
        selection-background-color: {t["selected_row_bg"]};
    }}
    QCheckBox {{
        color: {t["text_primary"]};
        spacing: 7px;
    }}
    QTextEdit#ReportViewer {{
        background: {t["report_bg"]};
        color: {t["text_primary"]};
        border: 1px solid {t["border"]};
        border-radius: 7px;
        padding: 8px;
        line-height: 130%;
    }}
    QListWidget, QTreeWidget, QTableWidget, QTableView {{
        background: {t["table_bg"]};
        color: {t["text_primary"]};
        alternate-background-color: {t["card_bg_alt"]};
        border: 1px solid {t["border"]};
        border-radius: 6px;
        gridline-color: {t["divider"]};
        selection-background-color: {t["selected_row_bg"]};
        selection-color: {t["text_primary"]};
    }}
    QListWidget::item, QTreeWidget::item, QTableWidget::item {{
        padding: 4px;
    }}
    QHeaderView::section {{
        background: {t["table_header_bg"]};
        color: {t["text_secondary"]};
        padding: 7px;
        border: 0;
        border-bottom: 1px solid {t["border"]};
        font-weight: 600;
    }}
    QTreeWidget#SidebarNav {{
        background: {t["sidebar_bg"]};
        border: 0;
        padding: 8px 6px;
        font-weight: 500;
    }}
    QTreeWidget#SidebarNav::item {{
        padding: 7px 8px;
        border-radius: 5px;
        margin: 1px 0;
        color: {t["text_secondary"]};
    }}
    QTreeWidget#SidebarNav::item:selected {{
        background: {t["active_nav_bg"]};
        color: {t["active_nav_text"]};
    }}
    QTreeWidget#SidebarNav::item:hover {{
        background: {t["hover_bg"]};
        color: {t["text_primary"]};
    }}
    QTreeWidget#SidebarNav::branch {{
        background: transparent;
    }}
    QFrame#WorkflowCard, QFrame#StatusCard, QGroupBox {{
        background: {t["card_bg"]};
        border: 1px solid {t["border"]};
        border-radius: 7px;
    }}
    QLabel#WorkflowCardTitle {{
        color: {t["text_primary"]};
        font-size: 11pt;
        font-weight: 700;
    }}
    QLabel#WorkflowCardDescription, QLabel#StatusCardTitle {{
        color: {t["text_muted"]};
        font-size: 9pt;
    }}
    QLabel#StatusCardTitle {{
        font-size: 8.5pt;
        font-weight: 600;
    }}
    QLabel#StatusCardValue {{
        color: {t["text_primary"]};
        font-size: 10.5pt;
    }}
    QPushButton#WorkflowActionButton {{
        text-align: left;
        background: {t["secondary_button_bg"]};
    }}
    QPushButton#WorkflowActionButton:hover {{
        background: {t["hover_bg"]};
    }}
    QGroupBox {{
        margin-top: 14px;
        padding: 10px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
        color: {t["text_secondary"]};
    }}
    QTabWidget::pane {{
        border: 1px solid {t["border"]};
        border-radius: 6px;
        background: {t["card_bg"]};
    }}
    QTabBar::tab {{
        background: {t["secondary_button_bg"]};
        color: {t["text_secondary"]};
        border: 1px solid {t["border"]};
        padding: 7px 12px;
        margin-right: 2px;
        border-top-left-radius: 5px;
        border-top-right-radius: 5px;
    }}
    QTabBar::tab:selected {{
        background: {t["card_bg"]};
        color: {t["text_primary"]};
        border-bottom-color: {t["card_bg"]};
    }}
    QProgressBar {{
        background: {t["input_bg"]};
        color: {t["text_primary"]};
        border: 1px solid {t["border"]};
        border-radius: 4px;
        text-align: center;
        min-height: 10px;
    }}
    QProgressBar::chunk {{
        background: {t["accent"]};
        border-radius: 4px;
    }}
    QSplitter::handle {{
        background: {t["divider"]};
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {t["border_strong"]};
        border-radius: 5px;
        min-height: 24px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {t["border_strong"]};
        border-radius: 5px;
        min-width: 24px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    """
