from __future__ import annotations

from dataclasses import dataclass
from datetime import date

try:
    from PySide6.QtCore import Qt
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
    Qt = None
    QCheckBox = QComboBox = QFormLayout = QHBoxLayout = QLabel = QLineEdit = QPushButton = QScrollArea = QTableWidget = QTableWidgetItem = QTabWidget = QTextEdit = QVBoxLayout = QWidget = None

from app.page_tasks import run_tool_background
from app.widgets.tool_run_panel import ToolRunPanel
from core.audit_compatibility import (
    MASTER_MACHINE_FIELDS,
    build_compatibility_candidates,
    create_compatibility_entries,
    list_audit_options,
    list_audited_source_options,
    parse_machine_tokens,
)
from core.audit_entries import (
    AUDIT_DROPDOWNS,
    CUP_TYPE_DEFAULT,
    DOCUMENTATION_PHOTO_DEFAULT_FIELDS,
    NA_VALUE,
    SENSOR_ELECTRICAL_FIELDS,
    audit_field_default,
    cup_type_default_applies,
    generate_audit_id,
    load_audit_entry,
    save_audit_entry,
)
from core.audit_field_rules import field_applies
from core.interview_entries import INTERVIEW_QUESTIONS, generate_interview_id, save_interview_entry
from core.logging import log_activity_event
from core.openers import open_path
from core.paths import resolve_project_paths
from core.press_lookup import PressLookupResult, lookup_machine

CLEANROOM_DEFAULT = "Whiteroom"
RELIABILITY_NONE_DEFAULT_FIELDS = {
    "Known Issues",
    "Drop/Mis-Pick History",
    "Maintenance Frequency",
}


def workbook_to_ui_value(value) -> str:
    text = "" if value is None else str(value)
    return "" if text.strip().upper() == NA_VALUE else text


def _is_empty_workbook_value(value) -> bool:
    text = "" if value is None else str(value).strip()
    return not text or text.upper() == NA_VALUE


@dataclass(frozen=True)
class FieldInfo:
    name: str
    label: str


def get_empty_only_visible_fields(row_data, form_fields, current_visibility_rules, label_for_field=None) -> list[FieldInfo]:
    fields: list[FieldInfo] = []
    for field in form_fields:
        if not current_visibility_rules(field):
            continue
        if _is_empty_workbook_value(row_data.get(field, "")):
            label = label_for_field(field) if label_for_field else field
            fields.append(FieldInfo(name=field, label=label))
    return fields

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
        "EOAT Moves",
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
        "Electrical/Wiring Present?",
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
    "Tubing Condition",
    "Cable Management Condition",
    "Mounting Hardware Condition",
    "EOAT Alignment Condition",
    "Fastener/Locking Hardware Present?",
    "Cycle Time Concern?",
    "Scrap/Quality Concern?",
    "Changeover Difficulty",
}

QUICK_DISCONNECTS_PRESENT_FIELD = "Quick Disconnects Present?"
PNEUMATIC_QUICK_DISCONNECT_TYPE_FIELD = "Pneumatic Quick Disconnect Type"
QUICK_DISCONNECT_DETAIL_FIELDS = {
    PNEUMATIC_QUICK_DISCONNECT_TYPE_FIELD,
    "Electrical Quick Disconnect Type",
}

CHANGEOVER_DIFFICULTY_FIELD = "Changeover Difficulty"
CONNECTION_TYPE_FIELD = "Connection Type"
UNSET_SMART_DEFAULT_VALUES = {"", NA_VALUE.lower(), "unknown / not checked", "not applicable"}

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
        self._loaded_empty_only_fields: set[str] | None = None
        self._current_audit_mode = "new"
        self._current_loaded_audit_id: str | None = None
        self._programmatic_field_update = False
        self._changeover_user_modified = False
        self._generated_audit_ids: set[str] = set()

        layout = QVBoxLayout(self)
        heading = QLabel("EOAT Audit")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        tabs = QTabWidget()
        tabs.addTab(self._build_audit_tab(), "Audit Entry")
        tabs.addTab(self._build_compatibility_tab(), "Compatibility Entry")
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
        previous = self._programmatic_field_update
        self._programmatic_field_update = True
        try:
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
        finally:
            self._programmatic_field_update = previous

    def _build_audit_tab(self) -> QWidget:
        self.audit_fields = {}
        container = QWidget()
        outer = QVBoxLayout(container)

        load_row = QHBoxLayout()
        self.load_audit_id_combo = QComboBox()
        self.load_audit_id_combo.setEditable(True)
        self.load_audit_id_combo.setMinimumWidth(520)
        self.load_audit_id_combo.activated.connect(self._on_audit_selector_activated)
        self.load_audit_id_edit = self.load_audit_id_combo.lineEdit()
        load_button = QPushButton("Load Existing Audit ID")
        load_button.clicked.connect(self.load_existing_audit)
        new_id_button = QPushButton("Generate New Audit ID")
        new_id_button.clicked.connect(self.generate_new_audit_id)
        duplicate_button = QPushButton("Duplicate Audit")
        duplicate_button.clicked.connect(self.duplicate_audit)
        open_button = QPushButton("Open Master Workbook")
        open_button.clicked.connect(self.open_workbook)
        self.audit_view_mode_combo = QComboBox()
        self.audit_view_mode_combo.addItems(["Empty Only", "Full Audit"])
        self.audit_view_mode_combo.setEnabled(False)
        self.audit_view_mode_combo.currentTextChanged.connect(self._update_audit_field_visibility)
        load_row.addWidget(QLabel("Audit ID"))
        load_row.addWidget(self.load_audit_id_combo, stretch=1)
        load_row.addWidget(load_button)
        load_row.addWidget(QLabel("View"))
        load_row.addWidget(self.audit_view_mode_combo)
        load_row.addWidget(new_id_button)
        load_row.addWidget(duplicate_button)
        load_row.addWidget(open_button)
        outer.addLayout(load_row)

        self.lookup_note_label = QLabel("Enter a machine number to look up robot and part info.")
        self.lookup_note_label.setWordWrap(True)
        outer.addWidget(self.lookup_note_label)

        self.audit_visibility_note_label = QLabel(
            "Fields are hidden when they do not apply to the selected EOAT type or configuration. Hidden non-applicable fields save as N/A."
        )
        self.audit_visibility_note_label.setWordWrap(True)
        outer.addWidget(self.audit_visibility_note_label)

        self.capacity_part_combo = QComboBox()
        self.capacity_part_combo.setEnabled(False)
        self.capacity_part_combo.currentIndexChanged.connect(self.apply_selected_capacity_part)
        outer.addWidget(self.capacity_part_combo)

        self.capacity_matches_table = QTableWidget()
        self.capacity_matches_table.setMaximumHeight(120)
        self.capacity_matches_table.setVisible(False)
        outer.addWidget(self.capacity_matches_table)

        self.machine_audit_match_combo = QComboBox()
        self.machine_audit_match_combo.setVisible(False)
        self.machine_audit_match_combo.activated.connect(self._on_machine_audit_match_selected)
        outer.addWidget(self.machine_audit_match_combo)

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
        self.refresh_audit_selector()
        return container

    def _build_compatibility_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source Audit"))
        self.compatibility_source_combo = QComboBox()
        self.compatibility_source_combo.setMinimumWidth(520)
        source_row.addWidget(self.compatibility_source_combo, stretch=1)
        refresh_sources = QPushButton("Refresh Compatible Machines")
        refresh_sources.clicked.connect(self.refresh_compatible_machines)
        source_row.addWidget(refresh_sources)
        layout.addLayout(source_row)

        self.compatibility_note_label = QLabel("Select a physical audit source to see compatible machines from the Press Capacity list.")
        self.compatibility_note_label.setWordWrap(True)
        layout.addWidget(self.compatibility_note_label)

        self.compatibility_table = QTableWidget()
        self.compatibility_table.setColumnCount(6)
        self.compatibility_table.setHorizontalHeaderLabels(
            [
                "Select",
                "Machine No.",
                "NGW Part Number",
                "NGW Part Description",
                "Existing Master Audit Status",
                "Recommended Action",
            ]
        )
        layout.addWidget(self.compatibility_table, stretch=1)

        button_row = QHBoxLayout()
        refresh_sources_button = QPushButton("Refresh Source Audits")
        refresh_sources_button.clicked.connect(self.refresh_compatibility_sources)
        select_all = QPushButton("Select All Create-Compatible Candidates")
        select_all.clicked.connect(self.select_all_create_compatible_candidates)
        clear = QPushButton("Clear Selection")
        clear.clicked.connect(self.clear_compatibility_selection)
        create = QPushButton("Create Selected Compatibility Entries")
        create.clicked.connect(self.create_selected_compatibility_entries)
        button_row.addWidget(refresh_sources_button)
        button_row.addWidget(select_all)
        button_row.addWidget(clear)
        button_row.addWidget(create)
        layout.addLayout(button_row)

        self.refresh_compatibility_sources()
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
            return self._combo(AUDIT_DROPDOWNS.get("Robot Type", []), editable=True)
        if field in {"Sensors Present?", "Cycle Time Concern?", "Scrap/Quality Concern?", "Drawing/CAD Available?", "BOM Available?"}:
            combo = self._combo(AUDIT_DROPDOWNS["YesNoUnknown"], editable=False)
            if field == "Sensors Present?":
                combo.currentTextChanged.connect(self._on_sensors_present_changed)
            return combo
        if field == "Electrical/Wiring Present?":
            combo = self._combo(AUDIT_DROPDOWNS.get(field, AUDIT_DROPDOWNS["YesNoUnknown"]), editable=False)
            combo.currentTextChanged.connect(self._on_electrical_wiring_present_changed)
            return combo
        if field in {"Vacuum Confirmation Present?", "Part-Present Detection Present?"}:
            return self._combo(AUDIT_DROPDOWNS["YesNoUnknownNA"], editable=False)
        if field in {"Fastener/Locking Hardware Present?", "Spare Parts Identified?", "Process Binder Complete?"}:
            return self._combo(AUDIT_DROPDOWNS["YesNoPartialUnknown"], editable=False)
        if field in AUDIT_DROPDOWNS:
            combo = self._combo(AUDIT_DROPDOWNS[field], editable=False, include_blank=field != "Connection Type")
            if field == "EOAT Type":
                combo.currentTextChanged.connect(self._update_tooling_visibility)
            elif field == CONNECTION_TYPE_FIELD:
                combo.currentTextChanged.connect(self._on_connection_type_changed)
            elif field == QUICK_DISCONNECTS_PRESENT_FIELD:
                combo.currentTextChanged.connect(self._on_quick_disconnects_present_changed)
            elif field == CHANGEOVER_DIFFICULTY_FIELD:
                combo.currentTextChanged.connect(self._on_changeover_difficulty_changed)
            return combo
        return self._line()

    def _audit_selector_audit_id(self) -> str:
        if hasattr(self, "load_audit_id_combo"):
            selected = self.load_audit_id_combo.currentData()
            current_index = self.load_audit_id_combo.currentIndex()
            selected_label = self.load_audit_id_combo.itemText(current_index) if current_index >= 0 else ""
            if selected and self.load_audit_id_combo.currentText().strip() == selected_label.strip():
                return str(selected).strip()
            text = self.load_audit_id_combo.currentText().strip()
            return text.split("|", 1)[0].strip()
        return self.load_audit_id_edit.text().strip()

    def _set_audit_selector_text(self, audit_id: str) -> None:
        if hasattr(self, "load_audit_id_combo"):
            self.load_audit_id_combo.blockSignals(True)
            index = self.load_audit_id_combo.findData(audit_id)
            if index >= 0:
                self.load_audit_id_combo.setCurrentIndex(index)
            else:
                self.load_audit_id_combo.setCurrentIndex(-1)
                self.load_audit_id_combo.setEditText(audit_id)
            self.load_audit_id_combo.blockSignals(False)
        else:
            self.load_audit_id_edit.setText(audit_id)

    def refresh_audit_selector(self) -> None:
        if not hasattr(self, "load_audit_id_combo"):
            return
        current_audit_id = self._audit_selector_audit_id()
        self.load_audit_id_combo.blockSignals(True)
        self.load_audit_id_combo.clear()
        self.load_audit_id_combo.addItem("", None)
        for option in list_audit_options(self.config.project_root):
            self.load_audit_id_combo.addItem(option.label, option.audit_id)
        if current_audit_id:
            index = self.load_audit_id_combo.findData(current_audit_id)
            if index >= 0:
                self.load_audit_id_combo.setCurrentIndex(index)
            else:
                self.load_audit_id_combo.setCurrentIndex(-1)
                self.load_audit_id_combo.setEditText(current_audit_id)
        else:
            self.load_audit_id_combo.setCurrentIndex(-1)
            self.load_audit_id_combo.setEditText("")
        self.load_audit_id_combo.blockSignals(False)

    def _on_audit_selector_activated(self, _index: int) -> None:
        if self.load_audit_id_combo.currentData():
            self.load_existing_audit(str(self.load_audit_id_combo.currentData()))

    def generate_new_audit_id(self) -> None:
        audit_date = self._field_value(self.audit_fields["Audit Date"]) or date.today().isoformat()
        audit_id = generate_audit_id(self.config.project_root, audit_date)
        while audit_id in self._generated_audit_ids:
            prefix, sequence_text = audit_id.rsplit("-", 1)
            try:
                audit_id = f"{prefix}-{int(sequence_text) + 1:03d}"
            except ValueError:
                break
        self._generated_audit_ids.add(audit_id)
        self._set_field_value(self.audit_fields["Audit ID"], audit_id)
        self._set_audit_selector_text(audit_id)
        self._editing_audit_id = None
        self._current_loaded_audit_id = None
        self._current_audit_mode = "new"
        self._duplicated_press_value = None
        self._duplicated_tool_value = None
        self._loaded_empty_only_fields = None
        self.audit_view_mode_combo.blockSignals(True)
        self.audit_view_mode_combo.setCurrentText("Full Audit")
        self.audit_view_mode_combo.setEnabled(False)
        self.audit_view_mode_combo.blockSignals(False)
        self._update_audit_field_visibility()
        self._set_machine_audit_matches([])
        if hasattr(self, "result_panel"):
            self.result_panel.show_text(f"Generated new audit ID {audit_id}. Save will create a new audit row.")

    def clear_audit_form(self) -> None:
        self._editing_audit_id = None
        self._current_loaded_audit_id = None
        self._current_audit_mode = "new"
        self._duplicated_press_value = None
        self._duplicated_tool_value = None
        self._loaded_empty_only_fields = None
        self._changeover_user_modified = False
        for widget in self.audit_fields.values():
            self._set_field_value(widget, "")
        self._set_field_value(self.audit_fields["Audit Date"], date.today().isoformat())
        self._set_field_value(self.audit_fields["Auditor"], "Kato Gray")
        self._set_field_value(self.audit_fields["Plant/Area"], "Plant 4")
        self._set_field_value(self.audit_fields["Status"], "In Progress")
        self._set_field_value(self.audit_fields["Priority"], "Medium")
        self._set_field_value(self.audit_fields["Follow-Up Needed"], "No")
        self._set_field_value(self.audit_fields["Cleanroom/Non-Cleanroom"], CLEANROOM_DEFAULT)
        self._set_field_value(self.audit_fields["Cup Type/Material"], CUP_TYPE_DEFAULT)
        for field in RELIABILITY_NONE_DEFAULT_FIELDS:
            if field in self.audit_fields:
                self._set_field_value(self.audit_fields[field], "None")
        for field in UNKNOWN_DEFAULT_FIELDS:
            if field in self.audit_fields:
                self._set_field_value(self.audit_fields[field], "Unknown / Not Checked")
        if QUICK_DISCONNECTS_PRESENT_FIELD in self.audit_fields:
            self._set_field_value(self.audit_fields[QUICK_DISCONNECTS_PRESENT_FIELD], "Yes")
        if "Electrical/Wiring Present?" in self.audit_fields:
            self._set_field_value(self.audit_fields["Electrical/Wiring Present?"], "Unknown / Not Checked")
        self._apply_quick_disconnect_defaults()
        for field in DOCUMENTATION_PHOTO_DEFAULT_FIELDS:
            if field in self.audit_fields:
                self._set_field_value(self.audit_fields[field], "No")
        self._apply_sensor_defaults()
        self._update_tooling_visibility(apply_defaults=True)
        self.current_lookup_result = None
        self._lookup_part_index = None
        self._lookup_conflict_warnings = []
        if hasattr(self, "lookup_note_label"):
            self.lookup_note_label.setText("Enter a machine number to look up robot and part info.")
            self._set_capacity_choices([])
            self._set_machine_audit_matches([])
        self.generate_new_audit_id()

    def load_existing_audit(self, audit_id: str | None = None, *, loaded_message: str | None = None) -> None:
        audit_id = audit_id or self._audit_selector_audit_id()
        entry = load_audit_entry(self.config.project_root, audit_id)
        if not entry:
            self.result_panel.show_text(f"Audit ID not found: {audit_id}")
            return
        self._set_audit_selector_text(audit_id)
        self._loading_audit = True
        try:
            for field, widget in self.audit_fields.items():
                self._set_field_value(widget, workbook_to_ui_value(entry.get(field, "")))
        finally:
            self._loading_audit = False
        self.audit_view_mode_combo.blockSignals(True)
        self.audit_view_mode_combo.setCurrentText("Empty Only")
        self.audit_view_mode_combo.setEnabled(True)
        self.audit_view_mode_combo.blockSignals(False)
        empty_fields = get_empty_only_visible_fields(
            entry,
            self.audit_fields,
            self._audit_field_applies_in_current_form,
            lambda field: self._audit_field_labels.get(field).text() if field in self._audit_field_labels else field,
        )
        self._loaded_empty_only_fields = {field_info.name for field_info in empty_fields}
        self._update_audit_field_visibility()
        self.current_lookup_result = None
        self._lookup_part_index = None
        self._lookup_conflict_warnings = []
        self._set_capacity_choices([])
        self._set_machine_audit_matches([])
        empty_count = len(empty_fields)
        if empty_fields:
            log_activity_event(
                self.config.project_root,
                "empty_only_visible_fields_counted",
                {"audit_id": audit_id, "fields": [field_info.label for field_info in empty_fields]},
            )
        note = loaded_message or "Loaded existing audit in Empty Only view. Switch to Full Audit to review completed fields."
        self.lookup_note_label.setText(note)
        result_message = loaded_message or f"Loaded audit entry {audit_id}."
        self.result_panel.show_text(f"{result_message} Empty Only is showing {empty_count} blank or N/A field(s). Save will update this row.")
        self._editing_audit_id = audit_id
        self._current_loaded_audit_id = audit_id
        self._current_audit_mode = "edit"
        self._duplicated_press_value = None
        self._duplicated_tool_value = None
        self._changeover_user_modified = False

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
        for field in DOCUMENTATION_PHOTO_DEFAULT_FIELDS:
            if field in self.audit_fields:
                self._set_field_value(self.audit_fields[field], "No")
        self._set_audit_selector_text(audit_id)
        self._editing_audit_id = None
        self._current_loaded_audit_id = None
        self._current_audit_mode = "new"
        self._duplicated_press_value = original_press
        self._duplicated_tool_value = original_tool
        self._loaded_empty_only_fields = None
        self.audit_view_mode_combo.blockSignals(True)
        self.audit_view_mode_combo.setCurrentText("Full Audit")
        self.audit_view_mode_combo.setEnabled(False)
        self.audit_view_mode_combo.blockSignals(False)
        self.current_lookup_result = None
        self._lookup_part_index = None
        self._lookup_conflict_warnings = []
        self._set_capacity_choices([])
        self._set_machine_audit_matches([])
        self.lookup_note_label.setText("Duplicated audit as a new unsaved entry. Adjust Press/Machine # or Tool #, then save.")
        self.result_panel.show_text(f"Duplicated current audit into new unsaved Audit ID {audit_id}. Original audit will not be overwritten.")
        self._update_tooling_visibility(apply_defaults=False)

    def _update_tooling_visibility(self, *, apply_defaults: bool = True) -> None:
        if not hasattr(self, "audit_fields") or "EOAT Type" not in self.audit_fields:
            return
        if apply_defaults and not self._loading_audit:
            self._apply_eoat_type_defaults()
        self._update_audit_field_visibility()

    def _update_audit_field_visibility(self, *_args) -> None:
        if not hasattr(self, "audit_fields") or "EOAT Type" not in self.audit_fields:
            return
        empty_only_fields = self._loaded_empty_only_fields if self._empty_only_mode_active() else None
        for field in self.audit_fields:
            visible = self._audit_field_applies_in_current_form(field)
            if empty_only_fields is not None:
                visible = visible and field in empty_only_fields
            self._set_audit_field_visible(field, visible)

    def _audit_field_applies_in_current_form(self, field: str) -> bool:
        current_entry = {name: self._field_value(widget) for name, widget in self.audit_fields.items()}
        return field_applies(current_entry, field)

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

    def _on_sensors_present_changed(self) -> None:
        if self._loading_audit:
            return
        if self._field_value(self.audit_fields["Sensors Present?"]).lower() != "no":
            self._apply_sensor_defaults()
        self._update_audit_field_visibility()

    def _on_electrical_wiring_present_changed(self, *_args) -> None:
        if self._loading_audit:
            return
        self._update_audit_field_visibility()

    def _on_connection_type_changed(self, *_args) -> None:
        if self._loading_audit or self._programmatic_field_update:
            return
        self._apply_changeover_difficulty_default()

    def _on_changeover_difficulty_changed(self, *_args) -> None:
        if self._loading_audit or self._programmatic_field_update:
            return
        self._changeover_user_modified = True

    def _on_quick_disconnects_present_changed(self, *_args) -> None:
        if self._loading_audit or self._programmatic_field_update:
            return
        if self._field_value(self.audit_fields[QUICK_DISCONNECTS_PRESENT_FIELD]).lower() == "yes":
            self._apply_quick_disconnect_defaults()
        elif self._field_value(self.audit_fields[QUICK_DISCONNECTS_PRESENT_FIELD]).lower() == "no":
            for field in QUICK_DISCONNECT_DETAIL_FIELDS:
                if field in self.audit_fields:
                    self._set_field_value(self.audit_fields[field], "")
        self._update_audit_field_visibility()

    def _apply_quick_disconnect_defaults(self) -> None:
        if PNEUMATIC_QUICK_DISCONNECT_TYPE_FIELD not in self.audit_fields:
            return
        if QUICK_DISCONNECTS_PRESENT_FIELD in self.audit_fields and self._field_value(self.audit_fields[QUICK_DISCONNECTS_PRESENT_FIELD]).lower() == "yes":
            pneumatic_widget = self.audit_fields[PNEUMATIC_QUICK_DISCONNECT_TYPE_FIELD]
            if not self._field_value(pneumatic_widget):
                self._set_field_value(pneumatic_widget, "PTC")

    def _apply_changeover_difficulty_default(self) -> None:
        if self._changeover_user_modified:
            return
        if CONNECTION_TYPE_FIELD not in self.audit_fields or CHANGEOVER_DIFFICULTY_FIELD not in self.audit_fields:
            return
        difficulty_widget = self.audit_fields[CHANGEOVER_DIFFICULTY_FIELD]
        if not self._smart_default_can_fill(self._field_value(difficulty_widget)):
            return
        connection_type = self._field_value(self.audit_fields[CONNECTION_TYPE_FIELD]).lower()
        if "ati" in connection_type:
            self._set_field_value(difficulty_widget, "Easy")
        elif "dovetail" in connection_type or "dove tail" in connection_type:
            self._set_field_value(difficulty_widget, "Medium")

    def _smart_default_can_fill(self, value: str) -> bool:
        return str(value or "").strip().lower() in UNSET_SMART_DEFAULT_VALUES

    def _apply_sensor_defaults(self) -> None:
        for field in SENSOR_ELECTRICAL_FIELDS:
            default = audit_field_default(field)
            if default is None or field not in self.audit_fields:
                continue
            widget = self.audit_fields[field]
            if not self._field_value(widget):
                self._set_field_value(widget, default)

    def _empty_only_mode_active(self) -> bool:
        return (
            self._loaded_empty_only_fields is not None
            and hasattr(self, "audit_view_mode_combo")
            and self.audit_view_mode_combo.currentText() == "Empty Only"
        )

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
        allow_update = bool(self._current_audit_mode == "edit" and self._editing_audit_id and current_audit_id == self._editing_audit_id)
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
            self._current_loaded_audit_id = audit_id
            self._current_audit_mode = "edit"
            self._duplicated_press_value = None
            self._duplicated_tool_value = None
            self.refresh_audit_selector()
            if hasattr(self, "compatibility_source_combo"):
                self.refresh_compatibility_sources()

    def refresh_compatibility_sources(self) -> None:
        self.compatibility_source_combo.blockSignals(True)
        current = self.compatibility_source_combo.currentData()
        self.compatibility_source_combo.clear()
        options = list_audited_source_options(self.config.project_root)
        for option in options:
            self.compatibility_source_combo.addItem(option.label, option.audit_id)
        if current:
            index = self.compatibility_source_combo.findData(current)
            if index >= 0:
                self.compatibility_source_combo.setCurrentIndex(index)
        self.compatibility_source_combo.blockSignals(False)
        if options:
            self.compatibility_note_label.setText(f"{len(options)} audited source record(s) available for compatibility entry.")
        else:
            self.compatibility_note_label.setText("No audited source records found. Save a physical audit before creating compatibility entries.")

    def refresh_compatible_machines(self) -> None:
        audit_id = self.compatibility_source_combo.currentData()
        if not audit_id:
            self.compatibility_note_label.setText("Select an audited source record first.")
            self.compatibility_table.setRowCount(0)
            return
        result = build_compatibility_candidates(self.config.project_root, str(audit_id))
        if result.errors:
            self.compatibility_note_label.setText("; ".join(result.errors))
            self.compatibility_table.setRowCount(0)
            return
        self.compatibility_table.setRowCount(len(result.candidates))
        for row_index, candidate in enumerate(result.candidates):
            select_item = QTableWidgetItem("")
            select_item.setFlags(select_item.flags() | Qt.ItemIsUserCheckable)
            select_item.setCheckState(Qt.Checked if candidate.can_create else Qt.Unchecked)
            if not candidate.can_create:
                select_item.setFlags(select_item.flags() & ~Qt.ItemIsEnabled)
            select_item.setData(Qt.UserRole, candidate.machine_no)
            self.compatibility_table.setItem(row_index, 0, select_item)
            values = [
                candidate.machine_no,
                candidate.part_number,
                candidate.part_description,
                candidate.existing_status,
                candidate.recommended_action,
            ]
            for col_index, value in enumerate(values, start=1):
                item = QTableWidgetItem(str(value))
                if col_index == 5:
                    item.setData(Qt.UserRole, candidate.recommended_action)
                self.compatibility_table.setItem(row_index, col_index, item)
        self.compatibility_table.resizeColumnsToContents()
        create_count = sum(1 for candidate in result.candidates if candidate.can_create)
        warning_text = f" Warnings: {'; '.join(result.warnings)}" if result.warnings else ""
        self.compatibility_note_label.setText(f"{create_count} create-compatible candidate(s) found for {audit_id}.{warning_text}")

    def select_all_create_compatible_candidates(self) -> None:
        for row in range(self.compatibility_table.rowCount()):
            action_item = self.compatibility_table.item(row, 5)
            select_item = self.compatibility_table.item(row, 0)
            if not select_item or not action_item:
                continue
            if action_item.text() == "Create Compatible Entry":
                select_item.setCheckState(Qt.Checked)

    def clear_compatibility_selection(self) -> None:
        for row in range(self.compatibility_table.rowCount()):
            item = self.compatibility_table.item(row, 0)
            if item:
                item.setCheckState(Qt.Unchecked)

    def create_selected_compatibility_entries(self) -> None:
        audit_id = self.compatibility_source_combo.currentData()
        if not audit_id:
            self.result_panel.show_text("Select an audited source record first.")
            return
        machines = []
        for row in range(self.compatibility_table.rowCount()):
            item = self.compatibility_table.item(row, 0)
            action_item = self.compatibility_table.item(row, 5)
            if not item or not action_item:
                continue
            if item.checkState() == Qt.Checked and action_item.text() == "Create Compatible Entry":
                machines.append(str(item.data(Qt.UserRole) or self.compatibility_table.item(row, 1).text()))
        if not machines:
            self.result_panel.show_text("No create-compatible candidates selected.")
            return
        run_tool_background(
            self.result_panel,
            "compatibility_create_entries",
            "Create Compatibility Entries",
            lambda: create_compatibility_entries(self.config.project_root, str(audit_id), machines),
            on_tool_result=lambda _result: (self.refresh_compatibility_sources(), self.refresh_compatible_machines()),
            modifies_files=True,
            workbook_lock=True,
        )

    def run_machine_lookup(self) -> None:
        machine_text = self._field_value(self.audit_fields["Press/Machine #"])
        self._clear_copied_tool_if_duplicate_press_changed(machine_text)
        if self._load_or_offer_existing_audit_for_machine(machine_text):
            return
        try:
            result = lookup_machine(self.config.project_root, machine_text)
        except ValueError as exc:
            self.current_lookup_result = None
            self._lookup_part_index = None
            self._lookup_conflict_warnings = []
            self.lookup_note_label.setText("Invalid machine number.")
            self._set_capacity_choices([])
            self._set_machine_audit_matches([])
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
        self._set_machine_audit_matches([])
        self._log_machine_lookup(machine_text, result, warnings, result.errors, robot_type_filled, robot_model_filled, part_filled, tool_filled)

    def _load_or_offer_existing_audit_for_machine(self, machine_text: str) -> bool:
        machine_tokens = parse_machine_tokens(machine_text)
        if not machine_tokens:
            self._set_machine_audit_matches([])
            return False
        requested = set(machine_tokens)
        matches = [
            option
            for option in list_audit_options(self.config.project_root)
            if requested & set(self._audit_option_machine_tokens(option))
        ]
        current_id = self._field_value(self.audit_fields["Audit ID"])
        if len(matches) == 1 and matches[0].audit_id == current_id and self._current_audit_mode == "edit":
            self._set_machine_audit_matches([])
            return False
        if len(matches) == 1:
            audit_id = matches[0].audit_id
            machine = ", ".join(machine_tokens)
            self.load_existing_audit(
                audit_id,
                loaded_message=f"Existing audit found for Machine {machine}. Loaded {audit_id}.",
            )
            return True
        if len(matches) > 1:
            self._set_machine_audit_matches(matches)
            self.lookup_note_label.setText("Multiple existing audits found for this machine. Select the audit to load.")
            self.result_panel.show_text("Multiple existing audits found for this machine. Select one from the audit match list; no audit was loaded automatically.")
            return True
        self._set_machine_audit_matches([])
        return False

    def _audit_option_machine_tokens(self, option) -> list[str]:
        tokens: list[str] = []
        for field_name in MASTER_MACHINE_FIELDS:
            tokens.extend(parse_machine_tokens(option.row.get(field_name)))
        return tokens

    def _set_machine_audit_matches(self, matches) -> None:
        if not hasattr(self, "machine_audit_match_combo"):
            return
        self.machine_audit_match_combo.blockSignals(True)
        self.machine_audit_match_combo.clear()
        if matches:
            self.machine_audit_match_combo.addItem("Select existing audit to load...", None)
            for option in matches:
                self.machine_audit_match_combo.addItem(option.label, option.audit_id)
            self.machine_audit_match_combo.setCurrentIndex(0)
            self.machine_audit_match_combo.setVisible(True)
        else:
            self.machine_audit_match_combo.setVisible(False)
        self.machine_audit_match_combo.blockSignals(False)

    def _on_machine_audit_match_selected(self, index: int) -> None:
        audit_id = self.machine_audit_match_combo.itemData(index)
        if audit_id:
            self.load_existing_audit(str(audit_id))

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
