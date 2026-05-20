from __future__ import annotations

try:
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QTableWidget, QTableWidgetItem
except ImportError:  # pragma: no cover
    QGridLayout = QHBoxLayout = QTableWidget = QTableWidgetItem = None

from app.widgets.status_card import StatusCard


def add_cards(layout: QGridLayout, names: list[str]) -> dict[str, StatusCard]:
    cards: dict[str, StatusCard] = {}
    for index, name in enumerate(names):
        card = StatusCard(name, "Not checked")
        cards[name] = card
        layout.addWidget(card, index // 4, index % 4)
    return cards


def populate_table(table: QTableWidget, rows: list[dict], columns: list[str]) -> None:
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for col_index, column in enumerate(columns):
            table.setItem(row_index, col_index, QTableWidgetItem(str(row.get(column, ""))))
    table.resizeColumnsToContents()


def counts_to_rows(counts: dict[str, int], key_name: str = "Item") -> list[dict[str, object]]:
    return [
        {key_name: key, "Count": value}
        for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]

