from __future__ import annotations

try:
    from PySide6.QtWidgets import QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QVBoxLayout = QWidget = None

from .report_viewer import ReportViewer


class ToolRunPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewer = ReportViewer()
        layout = QVBoxLayout(self)
        layout.addWidget(self.viewer)

    def show_result(self, result) -> None:
        self.viewer.show_markdown_text(result.to_markdown())

    def show_text(self, text: str) -> None:
        self.viewer.show_plain_text(text)
