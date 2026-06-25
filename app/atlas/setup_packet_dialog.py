from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.atlas_models import AtlasDataBundle, EOATRecord, MachineRecord, RecommendationResult, ToolRecord
from core.atlas_setup_packets import (
    COMPATIBILITY_CONFIRMED,
    COMPATIBILITY_MANUAL_OVERRIDE,
    PACKET_TYPE_CHOICES,
    PACKET_TYPE_LABELS,
    PHOTO_INCLUSION_CHOICES,
    PHOTO_INCLUSION_LABELS,
    SetupPacketContext,
    SetupPacketOptions,
    build_setup_packet_context,
    selectable_eoats,
    selectable_machines,
    selectable_tools,
    validate_setup_context,
)
from core.openers import open_path
from core.setup_packet_pdf import export_setup_packet_pdf

from .widgets import (
    EmptyStateWidget,
    InfoPanel,
    PrimaryCard,
    ProfileHeaderCard,
    WarningCard,
    action_row,
    badge,
    key_value_grid,
)


class SetupPacketDialog(QDialog):
    def __init__(
        self,
        bundle: AtlasDataBundle,
        *,
        settings=None,
        machine_id: str = "",
        tool_id: str = "",
        eoat_id: str = "",
        recommendation: RecommendationResult | None = None,
        context_label: str = "Atlas",
        parent=None,
    ):
        super().__init__(parent)
        self.bundle = bundle
        self.settings = settings
        self.context_label = context_label
        self.machine_id = str(machine_id or "").strip()
        self.tool_id = str(tool_id or "").strip()
        self.eoat_id = str(eoat_id or "").strip()
        self.override_confirmed = False
        self.export_path: Path | None = None
        self.generated_context: SetupPacketContext | None = None
        self.current_step = 0
        self.starting_item = "machine"
        self._apply_recommendation_prefill(recommendation)
        self._infer_starting_item()
        self.setObjectName("SetupPacketDialog")
        self.setWindowTitle("Changeover Packet Builder")
        self.resize(1040, 780)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        self.header = ProfileHeaderCard(
            "Changeover Packet Builder",
            "Select and validate a Machine + Tool / Mold / Part + EOAT setup before generating a printable PDF.",
            eyebrow="Changeover Packet",
        )
        root.addWidget(self.header)
        self.step_label = QLabel("")
        self.step_label.setObjectName("MetricLabel")
        root.addWidget(self.step_label)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._build_step_start()
        self._build_step_first_item()
        self._build_step_compatible_items()
        self._build_step_review()
        self._build_step_result()
        self._sync_default_options()

        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.back)
        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("PrimaryButton")
        self.next_button.clicked.connect(self.next)
        self.generate_button = QPushButton("Generate PDF")
        self.generate_button.setObjectName("PrimaryButton")
        self.generate_button.clicked.connect(self.generate_pdf)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        root.addWidget(action_row(self.back_button, self.next_button, self.generate_button, self.close_button))
        self._sync_all()

    def _sync_default_options(self) -> None:
        settings = self.settings
        default_type = getattr(settings, "setup_packet_default_type", "standard_changeover")
        default_photo = getattr(settings, "setup_packet_photo_inclusion", "key")
        default_open = getattr(settings, "setup_packet_open_after_generation", "ask_each_time")
        default_detail = getattr(settings, "setup_packet_detail_level", "standard")
        include_qr = bool(getattr(settings, "setup_packet_include_qr_label", False) and getattr(settings, "enable_qr_codes", False))
        self.packet_type_combo.setCurrentText(PACKET_TYPE_LABELS.get(default_type, PACKET_TYPE_LABELS["standard_changeover"]))
        self.photo_inclusion_combo.setCurrentText(PHOTO_INCLUSION_LABELS.get(default_photo, PHOTO_INCLUSION_LABELS["key"]))
        self.open_after_combo.setCurrentText(
            {
                "in_app": "In app",
                "external_pdf": "External PDF viewer",
                "open_folder": "Open folder",
                "ask_each_time": "Ask each time",
            }.get(default_open, "Ask each time")
        )
        self.detail_combo.setCurrentText("Detailed" if default_detail == "detailed" else "Standard")
        self.qr_combo.setCurrentText("On" if include_qr else "Off")

    def _apply_recommendation_prefill(self, recommendation: RecommendationResult | None) -> None:
        if recommendation is None or recommendation.best is None:
            return
        self.eoat_id = self.eoat_id or recommendation.best.eoat_id
        self.tool_id = self.tool_id or (recommendation.best.tools[0] if recommendation.best.tools else "")
        self.machine_id = self.machine_id or (recommendation.best.machines[0] if recommendation.best.machines else "")

    def _infer_starting_item(self) -> None:
        if self.machine_id and not (self.tool_id or self.eoat_id):
            self.starting_item = "machine"
        elif self.tool_id and not (self.machine_id or self.eoat_id):
            self.starting_item = "tool"
        elif self.eoat_id and not (self.machine_id or self.tool_id):
            self.starting_item = "eoat"
        elif self.tool_id:
            self.starting_item = "tool"
        elif self.eoat_id:
            self.starting_item = "eoat"
        else:
            self.starting_item = "machine"

    def _build_step_start(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        card = PrimaryCard("Step 1: Choose Starting Item", "Open context is prefilled, but the workflow can start from any setup item.")
        self.start_combo = QComboBox()
        self.start_combo.addItems(["Machine", "Tool / Mold / Part", "EOAT"])
        self.start_combo.currentTextChanged.connect(self._starting_changed)
        card.layout.addWidget(self.start_combo)
        card.layout.addWidget(self._selection_summary_card())
        layout.addWidget(card)
        layout.addStretch(1)
        self.stack.addWidget(page)

    def _build_step_first_item(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.first_title = QLabel("Step 2: Select First Item")
        self.first_title.setObjectName("CardTitle")
        layout.addWidget(self.first_title)
        self.first_search = QLineEdit()
        self.first_search.setObjectName("ModernSearchBar")
        self.first_search.setPlaceholderText("Search the selected item type")
        self.first_search.textChanged.connect(self.refresh_first_list)
        layout.addWidget(self.first_search)
        self.first_list = QListWidget()
        self.first_list.setObjectName("CardList")
        self.first_list.setWordWrap(True)
        self.first_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.first_list.itemActivated.connect(self._select_first_item)
        self.first_list.currentItemChanged.connect(lambda *_args: self._select_first_item(self.first_list.currentItem()))
        layout.addWidget(self.first_list, 1)
        self.stack.addWidget(page)

    def _build_step_compatible_items(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        top = QHBoxLayout()
        title = QLabel("Step 3: Select Compatible Items")
        title.setObjectName("CardTitle")
        top.addWidget(title)
        top.addStretch(1)
        self.override_button = QPushButton("Allow incompatible / unconfirmed selection")
        self.override_button.clicked.connect(self.confirm_override)
        top.addWidget(self.override_button)
        layout.addLayout(top)
        self.override_notice = WarningCard("Manual Override", severity="warn")
        self.override_notice.layout.addWidget(
            QLabel(
                "Manual Override Used. The generated PDF will be marked Compatibility Not Confirmed."
            )
        )
        self.override_notice.setVisible(False)
        layout.addWidget(self.override_notice)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        self.machine_selector = _RecordSelector("Machine", "Search machines", self._machine_rows, self._machine_selected)
        self.tool_selector = _RecordSelector("Tool / Mold / Part", "Search tools, molds, parts", self._tool_rows, self._tool_selected)
        self.eoat_selector = _RecordSelector("EOAT", "Search EOAT IDs", self._eoat_rows, self._eoat_selected)
        grid.addWidget(self.machine_selector, 0, 0)
        grid.addWidget(self.tool_selector, 0, 1)
        grid.addWidget(self.eoat_selector, 0, 2)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid, 1)
        self.empty_note = QLabel("")
        self.empty_note.setObjectName("MutedText")
        self.empty_note.setWordWrap(True)
        layout.addWidget(self.empty_note)
        self.stack.addWidget(page)

    def _build_step_review(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel("Step 4: Review Setup")
        title.setObjectName("CardTitle")
        layout.addWidget(title)
        options_card = PrimaryCard("Packet Options", "These settings apply only to the generated export.")
        option_grid = QGridLayout()
        option_grid.setContentsMargins(0, 0, 0, 0)
        option_grid.setSpacing(8)
        self.packet_type_combo = QComboBox()
        self.packet_type_combo.addItems([PACKET_TYPE_LABELS[key] for key in PACKET_TYPE_CHOICES])
        self.photo_inclusion_combo = QComboBox()
        self.photo_inclusion_combo.addItems([PHOTO_INCLUSION_LABELS[key] for key in PHOTO_INCLUSION_CHOICES])
        self.open_after_combo = QComboBox()
        self.open_after_combo.addItems(["Ask each time", "In app", "External PDF viewer", "Open folder"])
        self.detail_combo = QComboBox()
        self.detail_combo.addItems(["Standard", "Detailed"])
        self.qr_combo = QComboBox()
        self.qr_combo.addItems(["Off", "On"])
        widgets = [
            ("Packet type", self.packet_type_combo),
            ("Photo inclusion", self.photo_inclusion_combo),
            ("Open packet after generation", self.open_after_combo),
            ("Packet detail level", self.detail_combo),
            ("Include QR label if QR Codes are enabled", self.qr_combo),
        ]
        for index, (label, widget) in enumerate(widgets):
            label_widget = QLabel(label)
            label_widget.setObjectName("MetricLabel")
            row = (index // 2) * 2
            column = (index % 2) * 2
            option_grid.addWidget(label_widget, row, column)
            option_grid.addWidget(widget, row + 1, column)
            option_grid.setColumnStretch(column + 1, 1)
        options_card.layout.addLayout(option_grid)
        self.review_scroll = QScrollArea()
        self.review_scroll.setWidgetResizable(True)
        self.review_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.review_body = QWidget()
        self.review_layout = QVBoxLayout(self.review_body)
        self.review_layout.setContentsMargins(0, 0, 0, 0)
        self.review_layout.setSpacing(8)
        self.review_scroll.setWidget(self.review_body)
        layout.addWidget(self.review_scroll, 1)
        layout.addWidget(options_card)
        for combo in [self.packet_type_combo, self.photo_inclusion_combo, self.open_after_combo, self.detail_combo, self.qr_combo]:
            combo.currentTextChanged.connect(self.refresh_review)
        self.stack.addWidget(page)

    def _build_step_result(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.result_card = PrimaryCard("Step 5: Generate PDF", "The packet result will appear here after export.")
        self.result_label = QLabel("Ready to generate.")
        self.result_label.setObjectName("BodyText")
        self.result_label.setWordWrap(True)
        self.result_card.layout.addWidget(self.result_label)
        self.preview_label = QLabel("PDF preview fallback: use Open PDF or Open Externally to read and print the generated packet.")
        self.preview_label.setObjectName("MutedText")
        self.preview_label.setWordWrap(True)
        self.result_card.layout.addWidget(self.preview_label)
        self.open_pdf_button = QPushButton("Open PDF")
        self.open_pdf_button.clicked.connect(self.open_pdf)
        self.open_folder_button = QPushButton("Open Folder")
        self.open_folder_button.clicked.connect(self.open_folder)
        self.open_external_button = QPushButton("Open Externally")
        self.open_external_button.clicked.connect(self.open_pdf)
        self.copy_path_button = QPushButton("Copy File Path")
        self.copy_path_button.clicked.connect(self.copy_path)
        self.regenerate_button = QPushButton("Regenerate")
        self.regenerate_button.clicked.connect(self.generate_pdf)
        self.print_button = QPushButton("Print PDF")
        self.print_button.clicked.connect(self.open_pdf)
        self.result_card.layout.addWidget(
            action_row(
                self.open_pdf_button,
                self.open_folder_button,
                self.open_external_button,
                self.print_button,
                self.copy_path_button,
                self.regenerate_button,
            )
        )
        layout.addWidget(self.result_card)
        layout.addStretch(1)
        self.stack.addWidget(page)

    def _selection_summary_card(self) -> QWidget:
        card = InfoPanel("Current Context", "Prefilled values can be changed before generation.")
        self.context_summary = QLabel("")
        self.context_summary.setObjectName("BodyText")
        self.context_summary.setWordWrap(True)
        card.layout.addWidget(self.context_summary)
        return card

    def _starting_changed(self) -> None:
        text = self.start_combo.currentText().casefold()
        if "tool" in text:
            self.starting_item = "tool"
        elif "eoat" in text:
            self.starting_item = "eoat"
        else:
            self.starting_item = "machine"
        self.refresh_first_list()

    def next(self) -> None:
        if self.current_step == 1 and not self._has_starting_selection():
            QMessageBox.information(self, "Changeover Packet", "Select the first item before continuing.")
            return
        if self.current_step == 2 and not self._has_all_selections():
            QMessageBox.information(self, "Changeover Packet", "Select Machine, Tool / Mold / Part, and EOAT before reviewing.")
            return
        if self.current_step == 3 and not self._has_all_selections():
            return
        self.current_step = min(4, self.current_step + 1)
        self._sync_all()

    def back(self) -> None:
        self.current_step = max(0, self.current_step - 1)
        self._sync_all()

    def _sync_all(self) -> None:
        self.context_summary.setText(
            f"Machine: {self.machine_id or 'Not selected'}\n"
            f"Tool / Mold / Part: {self.tool_id or 'Not selected'}\n"
            f"EOAT: {self.eoat_id or 'Not selected'}\n"
            f"Opened from: {self.context_label}"
        )
        self.start_combo.blockSignals(True)
        self.start_combo.setCurrentText(
            {"machine": "Machine", "tool": "Tool / Mold / Part", "eoat": "EOAT"}.get(self.starting_item, "Machine")
        )
        self.start_combo.blockSignals(False)
        self.stack.setCurrentIndex(self.current_step)
        labels = [
            "1 of 5 - Choose starting item",
            "2 of 5 - Select first item",
            "3 of 5 - Select compatible items",
            "4 of 5 - Review setup",
            "5 of 5 - Generate PDF",
        ]
        self.step_label.setText(labels[self.current_step])
        self.back_button.setEnabled(self.current_step > 0)
        self.next_button.setVisible(self.current_step < 3)
        self.generate_button.setVisible(self.current_step == 3)
        self.generate_button.setEnabled(self._has_all_selections())
        self.override_notice.setVisible(self.override_confirmed)
        self.override_button.setEnabled(not self.override_confirmed)
        self.refresh_first_list()
        self.refresh_compatible_selectors()
        self.refresh_review()
        self._sync_result_buttons()

    def _has_starting_selection(self) -> bool:
        return bool({"machine": self.machine_id, "tool": self.tool_id, "eoat": self.eoat_id}.get(self.starting_item))

    def _has_all_selections(self) -> bool:
        return bool(self.machine_id and self.tool_id and self.eoat_id)

    def refresh_first_list(self) -> None:
        if not hasattr(self, "first_list"):
            return
        self.first_title.setText(f"Step 2: Select First {self._starting_label()}")
        rows = {"machine": self.bundle.machines, "tool": self.bundle.tools, "eoat": self.bundle.eoats}[self.starting_item]
        query = self.first_search.text().strip().casefold()
        self.first_list.blockSignals(True)
        self.first_list.clear()
        for record in rows:
            if query and query not in self._record_search_text(record):
                continue
            self._add_record_item(self.first_list, record, self._record_title(record), self._record_subtitle(record))
        self.first_list.blockSignals(False)

    def _select_first_item(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        record = item.data(Qt.ItemDataRole.UserRole)
        if self.starting_item == "machine" and isinstance(record, MachineRecord):
            self.machine_id = record.machine
        elif self.starting_item == "tool" and isinstance(record, ToolRecord):
            self.tool_id = record.tool
        elif self.starting_item == "eoat" and isinstance(record, EOATRecord):
            self.eoat_id = record.eoat_id
        self.refresh_compatible_selectors()
        self.refresh_review()

    def refresh_compatible_selectors(self) -> None:
        if not hasattr(self, "machine_selector"):
            return
        self.machine_selector.refresh(self.machine_id)
        self.tool_selector.refresh(self.tool_id)
        self.eoat_selector.refresh(self.eoat_id)
        if self.current_step == 2:
            empties = []
            if self.machine_id and not self.tool_selector.records:
                empties.append("No compatible tools are indexed for the selected machine/EOAT context.")
            if self.tool_id and not self.machine_selector.records:
                empties.append("No compatible machines are indexed for the selected tool/EOAT context.")
            if (self.machine_id or self.tool_id) and not self.eoat_selector.records:
                empties.append("No compatible EOATs are indexed for the selected machine/tool context.")
            if empties and not self.override_confirmed:
                self.empty_note.setText(" ".join(empties) + " Use manual override only after approved external verification.")
            else:
                self.empty_note.setText("")

    def _machine_rows(self):
        return selectable_machines(
            self.bundle,
            tool_id=self.tool_id if self.starting_item != "machine" or self.override_confirmed else self.tool_id,
            eoat_id=self.eoat_id,
            allow_unconfirmed=self.override_confirmed,
        )

    def _tool_rows(self):
        return selectable_tools(
            self.bundle,
            machine_id=self.machine_id,
            eoat_id=self.eoat_id,
            allow_unconfirmed=self.override_confirmed,
        )

    def _eoat_rows(self):
        return selectable_eoats(
            self.bundle,
            machine_id=self.machine_id,
            tool_id=self.tool_id,
            allow_unconfirmed=self.override_confirmed,
        )

    def _machine_selected(self, record: MachineRecord) -> None:
        if not self.override_confirmed and self.tool_id and record not in selectable_machines(self.bundle, tool_id=self.tool_id, eoat_id=self.eoat_id):
            return
        self.machine_id = record.machine
        self.refresh_compatible_selectors()
        self.refresh_review()

    def _tool_selected(self, record: ToolRecord) -> None:
        if not self.override_confirmed and self.machine_id and record not in selectable_tools(self.bundle, machine_id=self.machine_id, eoat_id=self.eoat_id):
            return
        self.tool_id = record.tool
        self.refresh_compatible_selectors()
        self.refresh_review()

    def _eoat_selected(self, record: EOATRecord) -> None:
        if not self.override_confirmed and (self.machine_id or self.tool_id) and record not in selectable_eoats(
            self.bundle, machine_id=self.machine_id, tool_id=self.tool_id
        ):
            return
        self.eoat_id = record.eoat_id
        self.refresh_compatible_selectors()
        self.refresh_review()

    def confirm_override(self) -> None:
        message = (
            "This combination is not confirmed by Atlas compatibility data.\n\n"
            "Generate this packet only if you have verified the setup through another approved source. "
            "The PDF will be marked Compatibility Not Confirmed."
        )
        result = QMessageBox.warning(
            self,
            "Allow incompatible / unconfirmed selection",
            message,
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Cancel,
        )
        if result != QMessageBox.StandardButton.Ok:
            return
        self.override_confirmed = True
        self._sync_all()

    def refresh_review(self) -> None:
        if not hasattr(self, "review_layout"):
            return
        _clear_layout(self.review_layout)
        if not self._has_all_selections():
            self.review_layout.addWidget(
                EmptyStateWidget("Setup selection incomplete", "Select Machine, Tool / Mold / Part, and EOAT before generating a packet.")
            )
            return
        options = self._options()
        validation = validate_setup_context(
            self.bundle,
            self.machine_id,
            self.tool_id,
            self.eoat_id,
            manual_override_used=options.manual_override_used,
        )
        context = build_setup_packet_context(self.bundle, self.machine_id, self.tool_id, self.eoat_id, options)
        status_kind = "good" if validation.status == COMPATIBILITY_CONFIRMED else ("bad" if validation.status == COMPATIBILITY_MANUAL_OVERRIDE else "warn")
        summary = PrimaryCard("Review Summary")
        summary.layout.addWidget(badge(validation.status, status_kind))
        summary_text = QLabel(
            "\n".join(
                [
                    f"Selected: Machine {context.machine_id} | Tool / Mold / Part {context.tool_id} | EOAT {context.eoat_id}",
                    (
                        f"Status: {validation.status} | Manual override: "
                        f"{'Yes' if validation.manual_override_used else 'No'} | Robot info: "
                        f"{'Available' if context.robot_info else 'Missing / partial'}"
                    ),
                    f"Documentation: {context.documentation_score}% | Photos: {context.photo_count} | Warnings: {context.warning_count}",
                    f"Missing key data: {_compact_missing_summary(context.missing_key_data)}",
                    f"Packet: {context.packet_type_label} | Photo inclusion: {context.photo_inclusion_label}",
                    f"Estimated PDF contents: {'; '.join(context.estimated_sections)}",
                ]
            )
        )
        summary_text.setObjectName("BodyText")
        summary_text.setWordWrap(True)
        summary.layout.addWidget(summary_text)
        self.review_layout.addWidget(summary)
        if validation.warnings:
            warning_card = WarningCard("Review Warnings", severity="warn")
            warning_card.layout.addWidget(
                key_value_grid([(warning.title, warning.message) for warning in validation.warnings[:8]])
            )
            self.review_layout.addWidget(warning_card)
        self.review_layout.addStretch(1)

    def generate_pdf(self) -> None:
        if not self._has_all_selections():
            QMessageBox.information(self, "Changeover Packet", "Select Machine, Tool / Mold / Part, and EOAT before generating.")
            return
        context = build_setup_packet_context(self.bundle, self.machine_id, self.tool_id, self.eoat_id, self._options())
        result = export_setup_packet_pdf(context)
        self.export_path = result.path
        self.generated_context = replace(context, export_path=str(result.path))
        self.result_label.setText(f"Generated changeover packet:\n{result.path}")
        self.current_step = 4
        self._sync_all()
        self._run_open_preference()
        controller = getattr(self.parent(), "controller", None)
        if controller is not None and hasattr(controller, "show_status"):
            controller.show_status(f"Generated changeover packet: {result.path}")

    def _run_open_preference(self) -> None:
        if self.export_path is None:
            return
        preference = self._options().open_after_generation
        if preference == "external_pdf":
            open_path(self.export_path)
        elif preference == "open_folder":
            open_path(self.export_path.parent)

    def _sync_result_buttons(self) -> None:
        enabled = self.export_path is not None
        for button in [
            self.open_pdf_button,
            self.open_folder_button,
            self.open_external_button,
            self.print_button,
            self.copy_path_button,
            self.regenerate_button,
        ]:
            button.setEnabled(enabled if button is not self.regenerate_button else self._has_all_selections())

    def open_pdf(self) -> None:
        if self.export_path:
            open_path(self.export_path)

    def open_folder(self) -> None:
        if self.export_path:
            open_path(self.export_path.parent)

    def copy_path(self) -> None:
        if self.export_path:
            QApplication.clipboard().setText(str(self.export_path))

    def _options(self) -> SetupPacketOptions:
        packet_label = self.packet_type_combo.currentText() if hasattr(self, "packet_type_combo") else ""
        packet_type = next((key for key, label in PACKET_TYPE_LABELS.items() if label == packet_label), "standard_changeover")
        photo_label = self.photo_inclusion_combo.currentText() if hasattr(self, "photo_inclusion_combo") else ""
        photo_inclusion = next((key for key, label in PHOTO_INCLUSION_LABELS.items() if label == photo_label), "key")
        open_label = self.open_after_combo.currentText().casefold() if hasattr(self, "open_after_combo") else "ask"
        open_after = "ask_each_time"
        if "external" in open_label:
            open_after = "external_pdf"
        elif "folder" in open_label:
            open_after = "open_folder"
        elif "app" in open_label:
            open_after = "in_app"
        include_qr = bool(
            hasattr(self, "qr_combo")
            and self.qr_combo.currentText() == "On"
            and getattr(self.settings, "enable_qr_codes", False)
        )
        return SetupPacketOptions(
            packet_type=packet_type,
            photo_inclusion=photo_inclusion,
            open_after_generation=open_after,
            include_qr_label=include_qr,
            detail_level=self.detail_combo.currentText().casefold() if hasattr(self, "detail_combo") else "standard",
            manual_override_used=self.override_confirmed,
        ).normalized()

    def _record_title(self, record) -> str:
        if isinstance(record, MachineRecord):
            return f"Machine {record.machine}"
        if isinstance(record, ToolRecord):
            return f"Tool {record.tool}"
        if isinstance(record, EOATRecord):
            return record.eoat_id
        return str(record)

    def _record_subtitle(self, record) -> str:
        if isinstance(record, MachineRecord):
            return (
                f"{record.robot_type or record.robot_model or 'Robot info missing'} | "
                f"{len(record.compatible_tools)} tool(s) | {len(record.compatible_eoats)} EOAT(s)"
            )
        if isinstance(record, ToolRecord):
            return (
                f"{record.part_description or record.part_family or 'Part description missing'} | "
                f"{len(record.compatible_machines)} machine(s) | {len(record.compatible_eoats)} EOAT(s)"
            )
        if isinstance(record, EOATRecord):
            return (
                f"{record.eoat_type or 'Type missing'} / {record.status or 'Status missing'} | "
                f"{len(record.tools)} tool(s) | {len(record.machines)} machine(s) | "
                f"Docs {record.documentation.score}% | Photos {record.photo_count} | Warnings {record.warning_count}"
            )
        return ""

    def _record_search_text(self, record) -> str:
        values = [self._record_title(record), self._record_subtitle(record)]
        values.extend(getattr(record, "compatible_eoats", ()))
        values.extend(getattr(record, "compatible_tools", ()))
        values.extend(getattr(record, "compatible_machines", ()))
        values.extend(getattr(record, "tools", ()))
        values.extend(getattr(record, "machines", ()))
        return " ".join(str(value) for value in values).casefold()

    def _add_record_item(self, list_widget: QListWidget, record, title: str, subtitle: str) -> None:
        item = QListWidgetItem(f"{title}\n{subtitle}")
        item.setToolTip(subtitle)
        item.setData(Qt.ItemDataRole.UserRole, record)
        item.setSizeHint(QSize(0, 58))
        list_widget.addItem(item)

    def _starting_label(self) -> str:
        return {"machine": "Machine", "tool": "Tool / Mold / Part", "eoat": "EOAT"}.get(self.starting_item, "Machine")


class _RecordSelector(QFrame):
    def __init__(self, title: str, placeholder: str, rows_callback, selected_callback):
        super().__init__()
        self.rows_callback = rows_callback
        self.selected_callback = selected_callback
        self.records = ()
        self.setObjectName("DetailCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        layout.addWidget(self.title_label)
        self.search = QLineEdit()
        self.search.setObjectName("ModernSearchBar")
        self.search.setPlaceholderText(placeholder)
        self.search.textChanged.connect(lambda: self.refresh(""))
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName("CardList")
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentItemChanged.connect(lambda *_args: self._selected(self.list.currentItem()))
        self.list.itemActivated.connect(self._selected)
        layout.addWidget(self.list, 1)

    def refresh(self, selected_id: str) -> None:
        query = self.search.text().strip().casefold()
        self.records = tuple(self.rows_callback())
        self.list.blockSignals(True)
        self.list.clear()
        selected_row = -1
        for record in self.records:
            title = self._title(record)
            subtitle = self._subtitle(record)
            haystack = f"{title} {subtitle}".casefold()
            if query and query not in haystack:
                continue
            item = QListWidgetItem(f"{title}\n{subtitle}")
            item.setData(Qt.ItemDataRole.UserRole, record)
            item.setSizeHint(QSize(0, 58))
            self.list.addItem(item)
            if selected_id and self._key(record).casefold() == selected_id.casefold():
                selected_row = self.list.count() - 1
        if not self.list.count():
            empty = QListWidgetItem("No compatible choices found")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)
        elif selected_row >= 0:
            self.list.setCurrentRow(selected_row)
        self.list.blockSignals(False)

    def _selected(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        record = item.data(Qt.ItemDataRole.UserRole)
        if record is not None:
            self.selected_callback(record)

    def _title(self, record) -> str:
        if isinstance(record, MachineRecord):
            return f"Machine {record.machine}"
        if isinstance(record, ToolRecord):
            return f"Tool {record.tool}"
        if isinstance(record, EOATRecord):
            return record.eoat_id
        return str(record)

    def _subtitle(self, record) -> str:
        if isinstance(record, MachineRecord):
            warning = " | Warning" if record.warning_count else ""
            return f"{record.robot_type or record.robot_model or 'Robot info missing'} | {len(record.compatible_tools)} tools | {len(record.compatible_eoats)} EOATs{warning}"
        if isinstance(record, ToolRecord):
            warning = " | Warning" if record.warning_count else ""
            return f"{record.part_description or record.part_family or 'Description missing'} | {len(record.compatible_machines)} machines | {len(record.compatible_eoats)} EOATs{warning}"
        if isinstance(record, EOATRecord):
            warning = " | Warning" if record.warning_count else ""
            return f"{record.eoat_type or 'Type missing'} / {record.status or 'Status missing'} | Docs {record.documentation.score}% | Photos {record.photo_count}{warning}"
        return ""

    def _key(self, record) -> str:
        if isinstance(record, MachineRecord):
            return record.machine
        if isinstance(record, ToolRecord):
            return record.tool
        if isinstance(record, EOATRecord):
            return record.eoat_id
        return str(record)


def open_setup_packet_dialog(
    bundle: AtlasDataBundle,
    *,
    settings=None,
    machine_id: str = "",
    tool_id: str = "",
    eoat_id: str = "",
    recommendation: RecommendationResult | None = None,
    context_label: str = "Atlas",
    parent=None,
) -> int:
    dialog = SetupPacketDialog(
        bundle,
        settings=settings,
        machine_id=machine_id,
        tool_id=tool_id,
        eoat_id=eoat_id,
        recommendation=recommendation,
        context_label=context_label,
        parent=parent,
    )
    return dialog.exec()


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        child = item.widget()
        if child is not None:
            child.deleteLater()
        child_layout = item.layout()
        if child_layout is not None:
            _clear_layout(child_layout)


def _compact_missing_summary(items: tuple[str, ...]) -> str:
    if not items:
        return "None indexed"
    visible = "; ".join(_short_text(item, 58) for item in items[:2])
    more = f"; +{len(items) - 2} more" if len(items) > 2 else ""
    return f"{len(items)} item(s): {visible}{more}"


def _short_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 3)].rstrip() + "..."


__all__ = ["SetupPacketDialog", "open_setup_packet_dialog"]
