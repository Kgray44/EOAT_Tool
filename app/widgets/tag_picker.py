from __future__ import annotations

try:
    from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget
except ImportError:  # pragma: no cover
    QComboBox = QHBoxLayout = QLabel = QWidget = None


class TagPicker(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.combo = QComboBox()
        self.combo.setEditable(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Tag"))
        layout.addWidget(self.combo, stretch=1)
        self.refresh()

    def refresh(self) -> None:
        current = self.current_tag_id()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("", None)
        for tag in self.service.list_tags():
            self.combo.addItem(f"{tag.name} ({tag.color_key})", tag.id)
        if current:
            index = self.combo.findData(current)
            if index >= 0:
                self.combo.setCurrentIndex(index)
        self.combo.blockSignals(False)

    def current_tag_id(self) -> str | None:
        value = self.combo.currentData()
        return str(value) if value else None
