from __future__ import annotations

from datetime import date

try:
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QScrollArea,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QCheckBox = QComboBox = QFormLayout = QHBoxLayout = QLabel = QLineEdit = QPushButton = QScrollArea = QTableWidget = QTableWidgetItem = QTabWidget = QTextEdit = QVBoxLayout = QWidget = None

from app.page_tasks import run_tool_background
from app.widgets.tool_run_panel import ToolRunPanel
from core.audit_entries import AUDIT_DROPDOWNS, CUP_TYPE_DEFAULT, GRIPPER_TOOLING_FIELDS, NA_VALUE, VACUUM_TOOLING_FIELDS, cup_type_default_applies, generate_audit_id, load_audit_entry, save_audit_entry
from core.interview_entries import INTERVIEW_QUESTIONS, generate_interview_id, save_interview_entry
from core.logging import log_activity_event
from core.openers import open_path
from core.paths import resolve_project_paths
from core.press_lookup import PressLookupResult, lookup_machine

CLEANROOM_DEFAULT = "Whiteroom"


def workbook_to_ui_value(value) -> str:
    text = "" if value is None else str(value)
    return "" if text.strip().upper() == NA_VALUE else text

AUDIT_SECTIONS = {
    "Audit Header": [
        "Audit ID",
        "Audit Date",
        "Auditor",
        "Plant/Area",
        "Press/Machine #",
        "Status",
        "Priority",
        "Follow-Up Needed",
    ],
    "Machine / Robot / Tool Context": [
        "Robot Type",
        "Robot Model/Controller",
        "Tool #",
        "Part Family",
        "Part Name/Description",
        "Cleanroom/Non-Cleanroom",
    ],
    "EOAT Type and Tooling": [
        "EOAT Type",
        "Connection Type",
        "Cup Type/Material",
        "Cup Diameter/Size",
        "Gripper Model",
        "Gripper Size",
        "Number of Vacuum Cups",
        "Gripper Type",
        "Vacuum Generator Type",
        "Vacuum Zones",
        "Estimated EOAT Weight",
    ],
    "Sensors and Detection": [
        "Sensors Present?",
        "Sensor Type",
        "Sensor Brand/Model",
        "Vacuum Confirmation Present?",
        "Part-Present Detection Present?",
    ],
    "Connections / Routing / Mechanical": [
        "Quick Disconnects Present?",
        "Pneumatic Quick Disconnect Type",
        "Electrical Quick Disconnect Type",
        "Tubing Condition",
        "Tubing Routing Notes",
        "Cable Management Condition",
        "Mounting Hardware Condition",
        "EOAT Alignment Condition",
        "Fastener/Locking Hardware Present?",
    ],
    "Performance / Reliability / Maintenance": [
        "Known Issues",
        "Drop/Mis-Pick History",
        "Maintenance Frequency",
        "Cycle Time Concern?",
        "Scrap/Quality Concern?",
        "Changeover Difficulty",
    ],
    "Documentation / Photos": [
        "Spare Parts Identified?",
        "Drawing/CAD Available?",
        "BOM Available?",
        "Process Binder Complete?",
        "Photos Taken?",
        "Photo Folder/Link",
    ],
    "Pilot / Final Notes": [
        "Pilot Candidate?",
        "Notes",
    ],
}

UNKNOWN_DEFAULT_FIELDS = {
    "Sensors Present?",
    "Vacuum Confirmation Present?",
    "Part-Present Detection Present?",
    "Quick Disconnects Present?",
    "Tubing Condition",
    "Cable Management Condition",
    "Mounting Hardware Condition",
    "EOAT Alignment Condition",
    "Fastener/Locking Hardware Present?",
    "Cycle Time Concern?",
    "Scrap/Quality Concern?",
    "Changeover Difficulty",
    "Spare Parts Identified?",
    "Drawing/CAD Available?",
    "BOM Available?",
    "Process Binder Complete?",
}

REFERENCE_ONLY_FIELD_NAMES = {
    "U.S. Tons",
    "Press Brand",
    "Press Model",
    "Press Tonnage",
    "Press Year",
    "Injection Pressure",
    "Injection Capacity",
    "Screw Diameter",
    "Controller Type",
    "Robot Serial Number",
    "Robot Manufacturing Date",
    "Full Servo",
    "TCU Count",
    "EDART Unit Press Side",
    "Forecasted Capacity",
    "Available Capacity",
    "Hours Allocated per Month",
    "Hours per Week",
    "Committed Hours per Year",
    "Cycle Time (S)",
    "Cavitation",
}


class AuditPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.current_lookup_result: PressLookupResult | None = None
        self._lookup_part_index: int | None = None
        self._lookup_conflict_warnings: list[str] = []
        self._editing_audit_id: str | None = None
        self._duplicated_press_value: str | None = None
        self._duplicated_tool_value: str | None = None
        self._audit_field_labels = {}
        self._loading_audit = False

        layout = QVBoxLayout(self)
        heading = QLabel("EOAT Audit")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        tabs = QTabWidget()
        tabs.addTab(self._build_audit_tab(), "Audit Entry")
        tabs.addTab(self._build_interview_tab(), "Interview Notes")
        layout.addWidget(tabs, stretch=1)

        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)

    def _line(self, default: str = "") -> QLineEdit:
        edit = QLineEdit(default)
        edit.setMinimumWidth(230)
        return edit

    def _combo(self, values: list[str], *, editable: bool = True, include_blank: bool = True) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(editable)
        combo.addItems(([""] if include_blank else []) + values)
        return combo

    def _field_value(self, widget) -> str:
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        if isinstance(widget, QTextEdit):
            return widget.toPlainText().strip()
        return widget.text().strip()

    def _set_field_value(self, widget, value) -> None:
        text = "" if value is None else str(value)
        if isinstance(widget, QComboBox):
            index = widget.findText(text)
            if index >= 0:
                widget.setCurrentIndex(index)
            elif not text:
                widget.setCurrentIndex(-1)
                if widget.isEditable():
                    widget.setEditText("")
            elif not widget.isEditable() and text:
                widget.addItem(text)
                widget.setCurrentIndex(widget.count() - 1)
            else:
                widget.setEditText(text)
        elif isinstance(widget, QTextEdit):
            widget.setPlainText(text)
        else:
            widget.setText(text)

    def _build_audit_tab(self) -> QWidget:
        self.audit_fields = {}
        container = QWidget()
        outer = QVBoxLayout(container)

        load_row = QHBoxLayout()
        self.load_audit_id_edit = QLineEdit()
        load_button = QPushButton("Load Existing Audit ID")
        load_button.clicked.connect(self.load_existing_audit)
        new_id_button = QPushButton("Generate New Audit ID")
        new_id_button.clicked.connect(self.generate_new_audit_id)
        duplicate_button = QPushButton("Duplicate Audit")
        duplicate_button.clicked.connect(self.duplicate_audit)
        open_button = QPushButton("Open Master Workbook")
        open_button.clicked.connect(self.open_workbook)
        load_row.addWidget(QLabel("Audit ID"))
        load_row.addWidget(self.load_audit_id_edit)
        load_row.addWidget(load_button)
        load_row.addWidget(new_id_button)
        load_row.addWidget(duplicate_button)
        load_row.addWidget(open_button)
        outer.addLayout(load_row)

        self.lookup_note_label = QLabel("Enter a machine number to look up robot and part info.")
        self.lookup_note_label.setWordWrap(True)
        outer.addWidget(self.lookup_note_label)

        self.capacity_part_combo = QComboBox()
        self.capacity_part_combo.setEnabled(False)
        self.capacity_part_combo.currentIndexChanged.connect(self.apply_selected_capacity_part)
        outer.addWidget(self.capacity_part_combo)

        self.capacity_matches_table = QTableWidget()
        self.capacity_matches_table.setMaximumHeight(120)
        self.capacity_matches_table.setVisible(False)
        outer.addWidget(self.capacity_matches_table)

        section_tabs = QTabWidget()
        for title, fields in AUDIT_SECTIONS.items():
            section_tabs.addTab(self._build_section_tab(fields), title)
        outer.addWidget(section_tabs, stretch=1)

        self.audit_followup_check = QCheckBox("Create Follow-Up Action")
        outer.addWidget(self.audit_followup_check)

        button_row = QHBoxLayout()
        save_button = QPushButton("Save Audit Entry")
        save_button.clicked.connect(self.save_audit)
        clear_button = QPushButton("Clear Form")
        clear_button.clicked.connect(self.clear_audit_form)
        button_row.addWidget(save_button)
        button_row.addWidget(clear_button)
        outer.addLayout(button_row)

        self.clear_audit_form()
        return container

    def _build_section_tab(self, fields: list[str]) -> QWidget:
        content = QWidget()
        form_layout = QFormLayout(content)
        for field in fields:
            widget = self._widget_for_audit_field(field)
            self.audit_fields[field] = widget
            if field == "Press/Machine #":
                label = QLabel(field)
                machine_row = QHBoxLayout()
                machine_row.addWidget(widget, stretch=1)
                lookup_button = QPushButton("Lookup")
                lookup_button.clicked.connect(self.run_machine_lookup)
                machine_row.addWidget(lookup_button)
                form_layout.addRow(label, machine_row)
                self._audit_field_labels[field] = label
            else:
                label = QLabel(field)
                form_layout.addRow(label, widget)
                self._audit_field_labels[field] = label

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        return scroll

    def _widget_for_audit_field(self, field: str):
        if field in {"Known Issues", "Drop/Mis-Pick History", "Tubing Routing Notes", "Notes", "Part Name/Description"}:
            text = QTextEdit()
            text.setFixedHeight(70)
            return text
        if field == "Plant/Area":
            return self._combo(["Plant 4", "Cleanroom"], editable=False, include_blank=False)
        if field == "Press/Machine #":
            edit = self._line()
            edit.editingFinished.connect(self.run_machine_lookup)
            return edit
        if field == "Robot Type":
            return self._line()
        if field in {"Sensors Present?", "Cycle Time Concern?", "Scrap/Quality Concern?", "Drawing/CAD Available?", "BOM Available?"}:
            return self._combo(AUDIT_DROPDOWNS["YesNoUnknown"], editable=False)
        if field in {"Vacuum Confirmation Present?", "Part-Present Detection Present?"}:
            return self._combo(AUDIT_DROPDOWNS["YesNoUnknownNA"], editable=False)
        if field in {"Fastener/Locking Hardware Present?", "Spare Parts Identified?", "Process Binder Complete?"}:
            return self._combo(AUDIT_DROPDOWNS["YesNoPartialUnknown"], editable=False)
        if field in AUDIT_DROPDOWNS:
            combo = self._combo(AUDIT_DROPDOWNS[field], editable=False, include_blank=field != "Connection Type")
            if field == "EOAT Type":
                combo.currentTextChanged.connect(self._update_tooling_visibility)
            return combo
        return self._line()

    def generate_new_audit_id(self) -> None:
        audit_date = self._field_value(self.audit_fields["Audit Date"]) or date.today().isoformat()
        audit_id = generate_audit_id(self.config.project_root, audit_date)
        self._set_field_value(self.audit_fields["Audit ID"], audit_id)
        self.load_audit_id_edit.setText(audit_id)
        self._editing_audit_id = None
        self._duplicated_press_value = None
        self._duplicated_tool_value = None

    def clear_audit_form(self) -> None:
        self._editing_audit_id = None
        self._duplicated_press_value = None
        self._duplicated_tool_value = None
        for widget in self.audit_fields.values():
            self._set_field_value(widget, "")
        self._set_field_value(self.audit_fields["Audit Date"], date.today().isoformat())
        self._set_field_value(self.audit_fields["Auditor"], "Kato Gray")
        self._set_field_value(self.audit_fields["Plant/Area"], "Plant 4")
        self._set_field_value(self.audit_fields["Status"], "In Progress")
        self._set_field_value(self.audit_fields["Priority"], "Medium")
        self._set_field_value(self.audit_fields["Follow-Up Needed"], "No")
        self._set_field_value(self.audit_fields["Photos Taken?"], "No")
        self._set_field_value(self.audit_fields["Cleanroom/Non-Cleanroom"], CLEANROOM_DEFAULT)
        self._set_field_value(self.audit_fields["Cup Type/Material"], CUP_TYPE_DEFAULT)
        for field in UNKNOWN_DEFAULT_FIELDS:
            if field in self.audit_fields:
                self._set_field_value(self.audit_fields[field], "Unknown / Not Checked")
        self._update_tooling_visibility(apply_defaults=True)
        self.current_lookup_result = None
        self._lookup_part_index = None
        self._lookup_conflict_warnings = []
        if hasattr(self, "lookup_note_label"):
            self.lookup_note_label.setText("Enter a machine number to look up robot and part info.")
            self._set_capacity_choices([])
        self.generate_new_audit_id()

    def load_existing_audit(self) -> None:
        audit_id = self.load_audit_id_edit.text().strip()
        entry = load_audit_entry(self.config.project_root, audit_id)
        if not entry:
            self.result_panel.show_text(f"Audit ID not found: {audit_id}")
            return
        self._loading_audit = True
        try:
            for field, widget in self.audit_fields.items():
                self._set_field_value(widget, workbook_to_ui_value(entry.get(field, "")))
        finally:
            self._loading_audit = False
        self._update_tooling_visibility(apply_defaults=False)
        self.current_lookup_result = None
        self._lookup_part_index = None
        self._lookup_conflict_warnings = []
        self._set_capacity_choices([])
        self.lookup_note_label.setText("Loaded existing audit. Run lookup again only if you want to refresh reference suggestions.")
        self.result_panel.show_text(f"Loaded audit entry {audit_id}. Save will update this row.")
        self._editing_audit_id = audit_id
        self._duplicated_press_value = None
        self._duplicated_tool_value = None

    def duplicate_audit(self) -> None:
        original_press = self._field_value(self.audit_fields["Press/Machine #"])
        original_tool = self._field_value(self.audit_fields["Tool #"])
        today = date.today().isoformat()
        audit_id = generate_audit_id(self.config.project_root, today)
        self._set_field_value(self.audit_fields["Audit ID"], audit_id)
        self._set_field_value(self.audit_fields["Audit Date"], today)
        if not self._field_value(self.audit_fields["Auditor"]):
            self._set_field_value(self.audit_fields["Auditor"], "Kato Gray")
        self._set_field_value(self.audit_fields["Photos Taken?"], "No")
        self._set_field_value(self.audit_fields["Photo Folder/Link"], "")
        self.load_audit_id_edit.setText(audit_id)
        self._editing_audit_id = None
        self._duplicated_press_value = original_press
        self._duplicated_tool_value = original_tool
        self.current_lookup_result = None
        self._lookup_part_index = None
        self._lookup_conflict_warnings = []
        self._set_capacity_choices([])
        self.lookup_note_label.setText("Duplicated audit as a new unsaved entry. Adjust Press/Machine # or Tool #, then save.")
        self.result_panel.show_text(f"Duplicated current audit into new unsaved Audit ID {audit_id}. Original audit will not be overwritten.")
        self._update_tooling_visibility(apply_defaults=False)

    def _update_tooling_visibility(self, *, apply_defaults: bool = True) -> None:
        if not hasattr(self, "audit_fields") or "EOAT Type" not in self.audit_fields:
            return
        eoat_type = self._field_value(self.audit_fields["EOAT Type"]).lower()
        show_all = not eoat_type or eoat_type.startswith("unknown") or eoat_type == "miscellaneous"
        show_vacuum = show_all or eoat_type == "vacuum" or eoat_type == "hybrid"
        show_gripper = show_all or eoat_type == "hybrid" or ("mechanical" in eoat_type and "gripper" in eoat_type)
        for field in VACUUM_TOOLING_FIELDS:
            self._set_audit_field_visible(field, show_vacuum)
        for field in GRIPPER_TOOLING_FIELDS:
            self._set_audit_field_visible(field, show_gripper)
        if apply_defaults and not self._loading_audit:
            self._apply_eoat_type_defaults()

    def _apply_eoat_type_defaults(self) -> None:
        eoat_type = self._field_value(self.audit_fields["EOAT Type"])
        cup_widget = self.audit_fields.get("Cup Type/Material")
        if cup_widget is None:
            return
        cup_value = self._field_value(cup_widget)
        if cup_type_default_applies(eoat_type):
            if not cup_value:
                self._set_field_value(cup_widget, CUP_TYPE_DEFAULT)
        elif cup_value == CUP_TYPE_DEFAULT:
            self._set_field_value(cup_widget, "")

    def _set_audit_field_visible(self, field: str, visible: bool) -> None:
        widget = self.audit_fields.get(field)
        if widget is not None:
            widget.setVisible(visible)
        label = self._audit_field_labels.get(field)
        if label is not None:
            label.setVisible(visible)

    def save_audit(self) -> None:
        entry = {field: self._field_value(widget) for field, widget in self.audit_fields.items()}
        current_audit_id = str(entry.get("Audit ID") or "").strip()
        allow_update = bool(self._editing_audit_id and current_audit_id == self._editing_audit_id)
        run_tool_background(
            self.result_panel,
            "audit_save_entry",
            "Save Audit Entry",
            lambda: save_audit_entry(
                self.config.project_root,
                entry,
                allow_update=allow_update,
                create_followup_action=self.audit_followup_check.isChecked(),
            ),
            on_tool_result=lambda result: self._after_save_audit(result, current_audit_id),
            modifies_files=True,
            workbook_lock=True,
        )

    def _after_save_audit(self, result, audit_id: str) -> None:
        if result.success and audit_id:
            self._editing_audit_id = audit_id
            self._duplicated_press_value = None
            self._duplicated_tool_value = None

    def run_machine_lookup(self) -> None:
        machine_text = self._field_value(self.audit_fields["Press/Machine #"])
        self._clear_copied_tool_if_duplicate_press_changed(machine_text)
        try:
            result = lookup_machine(self.config.project_root, machine_text)
        except ValueError as exc:
            self.current_lookup_result = None
            self._lookup_part_index = None
            self._lookup_conflict_warnings = []
            self.lookup_note_label.setText("Invalid machine number.")
            self._set_capacity_choices([])
            self.result_panel.show_text(str(exc))
            self._log_machine_lookup(machine_text, None, [str(exc)], [], False, False, False)
            return

        self.current_lookup_result = result
        self._lookup_part_index = None
        self._lookup_conflict_warnings = []
        self._set_field_value(self.audit_fields["Press/Machine #"], str(result.machine_number))

        robot_type_filled = self._apply_suggestion("Robot Type", result.robot_type_suggestion)
        robot_model_filled = self._apply_suggestion("Robot Model/Controller", result.robot_model_controller_suggestion)
        tool_filled = self._apply_tool_number_suggestion(result, force=False)
        part_filled = False
        if len(result.part_options) == 1:
            self._lookup_part_index = 0
            option = result.part_options[0]
            part_filled = self._apply_part_suggestion(option, force=False)
        warnings = [*result.warnings, *self._lookup_conflict_warnings]
        self.lookup_note_label.setText(self._lookup_status_message(result, robot_type_filled or robot_model_filled, part_filled or tool_filled, warnings))
        self._set_capacity_choices(result.capacity_part_rows)
        self._log_machine_lookup(machine_text, result, warnings, result.errors, robot_type_filled, robot_model_filled, part_filled, tool_filled)

    def _clear_copied_tool_if_duplicate_press_changed(self, machine_text: str) -> None:
        if self._duplicated_press_value is None or self._duplicated_tool_value is None:
            return
        current_tool = self._field_value(self.audit_fields["Tool #"])
        if current_tool == self._duplicated_tool_value and machine_text.strip() != self._duplicated_press_value.strip():
            self._set_field_value(self.audit_fields["Tool #"], "")
            self._duplicated_tool_value = None

    def _lookup_status_message(
        self,
        result: PressLookupResult,
        robot_filled: bool,
        part_filled: bool,
        warnings: list[str],
    ) -> str:
        if not result.master_matched and not result.capacity_matched:
            note = f"Machine {result.machine_number} not found in reference files. Manual entry allowed."
        elif len(result.part_options) > 1:
            note = f"Machine {result.machine_number} found with multiple possible parts. Select current running part."
        else:
            note = f"Machine {result.machine_number} found."
        if robot_filled and part_filled:
            note += " Robot and part info filled."
        elif robot_filled:
            note += " Robot info filled."
        elif part_filled:
            note += " Part info filled."
        if any("reference file not found" in warning.lower() for warning in warnings):
            note = "Reference files missing. Manual entry allowed."
        if warnings:
            note += f" Warnings: {'; '.join(warnings)}"
        return note

    def _apply_suggestion(self, field: str, suggestion: str) -> bool:
        if not suggestion:
            return False
        current = self._field_value(self.audit_fields[field])
        if not current:
            self._set_field_value(self.audit_fields[field], suggestion)
            return True
        if current != suggestion:
            self._lookup_conflict_warnings.append(f"Reference lookup found a different {field} suggestion. Existing value was preserved.")
        return False

    def _apply_part_suggestion(self, option: dict[str, object], *, force: bool) -> bool:
        part_family = str(option.get("part_family") or "")
        description = str(option.get("part_description") or "")
        filled = False
        if part_family:
            filled = self._apply_suggestion("Part Family", part_family) or filled if not force else True
            if force:
                self._set_field_value(self.audit_fields["Part Family"], part_family)
        if description:
            filled = self._apply_suggestion("Part Name/Description", description) or filled if not force else True
            if force:
                self._set_field_value(self.audit_fields["Part Name/Description"], description)
        return filled

    def _apply_tool_number_suggestion(self, result: PressLookupResult, *, force: bool) -> bool:
        part_numbers = sorted(
            {
                str(option.get("part_number") or "").strip()
                for option in result.part_options
                if str(option.get("part_number") or "").strip()
            }
        )
        if not part_numbers:
            return False
        if len(part_numbers) > 1:
            self._lookup_conflict_warnings.append("Multiple possible Tool # values found for this press.")
            return False
        if force:
            self._set_field_value(self.audit_fields["Tool #"], part_numbers[0])
            return True
        return self._apply_suggestion("Tool #", part_numbers[0])

    def _set_capacity_choices(self, rows) -> None:
        self.capacity_part_combo.blockSignals(True)
        self.capacity_part_combo.clear()
        self.capacity_matches_table.clear()
        columns = ["Part Number", "Description", "Customer", "Cycle Time"]
        self.capacity_matches_table.setColumnCount(len(columns))
        self.capacity_matches_table.setHorizontalHeaderLabels(columns)
        self.capacity_matches_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            option = self.current_lookup_result.part_options[row_index] if self.current_lookup_result else {}
            self.capacity_part_combo.addItem(str(option.get("display_label") or row.display_label()), row_index)
            values = [
                option.get("part_number", ""),
                option.get("part_description", ""),
                option.get("customer", ""),
                option.get("cycle_time", ""),
            ]
            for col_index, value in enumerate(values):
                self.capacity_matches_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
        self.capacity_matches_table.resizeColumnsToContents()
        self.capacity_part_combo.setEnabled(len(rows) > 1)
        self.capacity_matches_table.setVisible(bool(rows))
        if len(rows) == 1:
            self.capacity_part_combo.setCurrentIndex(0)
        elif len(rows) > 1:
            self.capacity_part_combo.insertItem(0, "Select current running part...", None)
            self.capacity_part_combo.setCurrentIndex(0)
        self.capacity_part_combo.blockSignals(False)

    def apply_selected_capacity_part(self, index: int) -> None:
        if self.current_lookup_result is None:
            return
        part_index = self.capacity_part_combo.itemData(index)
        if part_index is None:
            self._lookup_part_index = None
            return
        self._lookup_part_index = int(part_index)
        option = self.current_lookup_result.part_options[self._lookup_part_index]
        self._apply_tool_number_suggestion(
            PressLookupResult(
                machine_number=self.current_lookup_result.machine_number,
                capacity_part_rows=[self.current_lookup_result.capacity_part_rows[self._lookup_part_index]],
            ),
            force=True,
        )
        self._apply_part_suggestion(option, force=True)
        self.lookup_note_label.setText("Selected current part from reference lookup.")

    def _log_machine_lookup(
        self,
        raw_input: str,
        result: PressLookupResult | None,
        warnings: list[str],
        errors: list[str],
        robot_type_filled: bool,
        robot_model_filled: bool,
        part_filled: bool,
        tool_filled: bool = False,
    ) -> None:
        payload = {
            "machine_number_raw": raw_input,
            "machine_number_normalized": result.machine_number if result else "",
            "master_file_loaded": bool(result and result.master_source and result.master_source.exists()),
            "capacity_file_loaded": bool(result and result.capacity_source and result.capacity_source.exists()),
            "master_match_count": result.master_rows_count if result else 0,
            "capacity_match_count": result.capacity_rows_count if result else 0,
            "matched_master": result.master_matched if result else False,
            "matched_capacity": result.capacity_matched if result else False,
            "warnings": warnings,
            "errors": errors,
            "robot_type_autofilled": robot_type_filled,
            "robot_model_controller_autofilled": robot_model_filled,
            "part_family_autofilled": part_filled,
            "tool_number_autofilled": tool_filled,
        }
        log_activity_event(self.config.project_root, "machine_lookup_completed", payload)

    def _build_interview_tab(self) -> QWidget:
        self.interview_fields = {}
        container = QWidget()
        layout = QHBoxLayout(container)
        form_container = QWidget()
        form_layout = QFormLayout(form_container)
        fields = [
            "Interview ID",
            "Date",
            "Person Interviewed",
            "Role/Department",
            "Shift",
            "Plant/Area",
            "Press/Machine #",
            "Main Question/Topic",
            "Notes",
            "Known EOAT Issues Mentioned",
            "Suggested Improvements",
            "Follow-Up Needed",
            "Follow-Up Owner",
        ]
        for field in fields:
            if field in {"Notes", "Known EOAT Issues Mentioned", "Suggested Improvements"}:
                widget = QTextEdit()
                widget.setFixedHeight(80)
            elif field == "Follow-Up Needed":
                widget = self._combo(["Yes", "No"])
            else:
                widget = self._line()
            self.interview_fields[field] = widget
            form_layout.addRow(field, widget)
        self.interview_followup_check = QCheckBox("Create Follow-Up Action")
        form_layout.addRow("", self.interview_followup_check)
        buttons = QHBoxLayout()
        save = QPushButton("Save Interview Note")
        save.clicked.connect(self.save_interview)
        clear = QPushButton("Clear Interview Form")
        clear.clicked.connect(self.clear_interview_form)
        open_workbook = QPushButton("Open Workbook")
        open_workbook.clicked.connect(self.open_workbook)
        buttons.addWidget(save)
        buttons.addWidget(clear)
        buttons.addWidget(open_workbook)
        form_layout.addRow(buttons)
        layout.addWidget(form_container, stretch=2)

        questions = QTextEdit()
        questions.setReadOnly(True)
        questions.setPlainText("Suggested questions:\n\n" + "\n".join(f"- {question}" for question in INTERVIEW_QUESTIONS))
        layout.addWidget(questions, stretch=1)
        self.clear_interview_form()
        return container

    def clear_interview_form(self) -> None:
        for widget in self.interview_fields.values():
            self._set_field_value(widget, "")
        self._set_field_value(self.interview_fields["Date"], date.today().isoformat())
        self._set_field_value(self.interview_fields["Interview ID"], generate_interview_id(self.config.project_root))

    def save_interview(self) -> None:
        entry = {field: self._field_value(widget) for field, widget in self.interview_fields.items()}
        run_tool_background(
            self.result_panel,
            "audit_save_interview",
            "Save Interview Note",
            lambda: save_interview_entry(
                self.config.project_root,
                entry,
                create_followup_action=self.interview_followup_check.isChecked(),
            ),
            modifies_files=True,
            workbook_lock=True,
        )

    def open_workbook(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).master_workbook)
        if not result.success:
            self.result_panel.show_result(result)
