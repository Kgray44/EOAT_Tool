from __future__ import annotations

try:
    from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGroupBox = QVBoxLayout = QWidget = None


def settings_tab() -> tuple[QWidget, QVBoxLayout]:
    tab = QWidget()
    layout = QVBoxLayout(tab)
    return tab, layout


def settings_group(page, title: str, keywords: str) -> tuple[QGroupBox, QVBoxLayout]:
    group = QGroupBox(title)
    layout = QVBoxLayout(group)
    group.setProperty("settings_keywords", keywords)
    page._searchable_sections.append(group)
    return group, layout


def add_stretch(layout: QVBoxLayout) -> None:
    layout.addStretch(1)


__all__ = ["add_stretch", "settings_group", "settings_tab"]
