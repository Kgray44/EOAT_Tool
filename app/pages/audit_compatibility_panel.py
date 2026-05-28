from __future__ import annotations

try:
    from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QTableWidget, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QComboBox = QHBoxLayout = QLabel = QPushButton = QTableWidget = QVBoxLayout = QWidget = None


def build_compatibility_tab(page) -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)

    source_row = QHBoxLayout()
    source_row.addWidget(QLabel("Source Audit"))
    page.compatibility_source_combo = QComboBox()
    page.compatibility_source_combo.setMinimumWidth(520)
    source_row.addWidget(page.compatibility_source_combo, stretch=1)
    refresh_sources = QPushButton("Refresh Compatible Machines")
    refresh_sources.clicked.connect(page.refresh_compatible_machines)
    source_row.addWidget(refresh_sources)
    layout.addLayout(source_row)

    page.compatibility_note_label = QLabel("Select a physical audit source to see compatible machines from the Press Capacity list.")
    page.compatibility_note_label.setWordWrap(True)
    layout.addWidget(page.compatibility_note_label)

    page.compatibility_table = QTableWidget()
    page.compatibility_table.setColumnCount(6)
    page.compatibility_table.setHorizontalHeaderLabels(
        [
            "Select",
            "Machine No.",
            "NGW Part Number",
            "NGW Part Description",
            "Existing Master Audit Status",
            "Recommended Action",
        ]
    )
    layout.addWidget(page.compatibility_table, stretch=1)

    button_row = QHBoxLayout()
    refresh_sources_button = QPushButton("Refresh Source Audits")
    refresh_sources_button.clicked.connect(page.refresh_compatibility_sources)
    select_all = QPushButton("Select All Create-Compatible Candidates")
    select_all.clicked.connect(page.select_all_create_compatible_candidates)
    clear = QPushButton("Clear Selection")
    clear.clicked.connect(page.clear_compatibility_selection)
    create = QPushButton("Create Selected Compatibility Entries")
    create.clicked.connect(page.create_selected_compatibility_entries)
    button_row.addWidget(refresh_sources_button)
    button_row.addWidget(select_all)
    button_row.addWidget(clear)
    button_row.addWidget(create)
    layout.addLayout(button_row)

    page.refresh_compatibility_sources()
    return container
