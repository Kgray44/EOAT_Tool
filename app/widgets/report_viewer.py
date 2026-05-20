from __future__ import annotations

try:
    from PySide6.QtWidgets import QTextEdit
except ImportError:  # pragma: no cover
    QTextEdit = None


class ReportViewer(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ReportViewer")
        self.setReadOnly(True)
        self.setPlaceholderText("No report selected.")

    def show_markdown_text(self, text: str) -> None:
        self.setMarkdown(text)

    def show_plain_text(self, text: str) -> None:
        self.setPlainText(text)

    def load_report_file(self, path) -> None:
        from core.reports import read_report_preview

        text, warning = read_report_preview(path)
        if warning:
            self.setPlainText(warning)
        else:
            self.setPlainText(f"{path}\n\n{text}")
