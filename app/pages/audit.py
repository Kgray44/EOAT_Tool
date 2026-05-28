from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QIntValidator
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    Qt = QTimer = None
    QIntValidator = None
    QApplication = QCheckBox = QComboBox = QFormLayout = QGroupBox = QHBoxLayout = QLabel = QLineEdit = QMessageBox = QPushButton = QScrollArea = QSplitter = QTableWidget = QTableWidgetItem = QTabWidget = QTextEdit = QVBoxLayout = QWidget = None

from app.page_tasks import run_tool_background
from app.event_bus import EVENT_ANNOTATION_CHANGED, EVENT_AUDIT_SAVED, EVENT_OPEN_ITEMS_CHANGED, get_event_bus
from app.pages.audit_compatibility_panel import build_compatibility_tab
from app.pages.audit_coach_panel import AuditCoachPanel
from app.pages.audit_defaults_controller import AuditDefaultsController
from app.pages.audit_save_workflow import insert_robot_info_summary, save_audit_with_side_effects
from app.pages.annotation_suggestions_dialog import AnnotationSuggestionsDialog
from app.widgets.field_tag_button import FieldTagButton, FieldTagDialog
from app.widgets.tool_run_panel import ToolRunPanel
from core.action_items import add_action_item
from core.annotations.service import AnnotationService
from core.annotations.tag_colors import TAG_COLOR_PALETTE, highest_priority_tag
from core.annotations.targets import target_id_for
from core.audit_compatibility import (
    MASTER_MACHINE_FIELDS,
    build_compatibility_candidates,
    create_compatibility_entries,
    list_audit_options,
    list_audited_source_options,
    normalize_entry_type,
    parse_machine_tokens,
)
from core.audit_constants import ENTRY_TYPE_AUDITED, ENTRY_TYPE_COMPATIBLE, ENTRY_TYPE_FIELD
from core.audit_entries import (
    AUDIT_DROPDOWNS,
    CUP_TYPE_DEFAULT,
    DOCUMENTATION_PHOTO_DEFAULT_FIELDS,
    EOAT_INTERCHANGEABLE_CIRCUITS_FIELD,
    NA_VALUE,
    NUMBER_OF_PARTS_PICKED_FIELD,
    PART_PRESENT_DETECTION_FIELD,
    PART_PRESENT_SENSOR_DEFAULTS,
    SENSOR_ELECTRICAL_FIELDS,
    audit_field_default,
    cup_type_default_applies,
    generate_audit_id,
    load_audit_entry,
    part_present_sensor_value_allows_default,
)
from core.audit.compatibility_preview import CompatibilityImpactPreview, build_compatibility_impact_preview
from core.audit.coach import calculate_audit_coach_summary, unknown_not_checked_value_for_field
from core.audit.drafts import discard_audit_draft, form_values_changed, load_audit_draft, save_audit_draft
from core.audit_field_rules import PNEUMATIC_CIRCUIT_FIELDS, field_applies, non_applicable_reason
from core.gripper_fields import (
    CUP_COUNT_FIELD,
    GRIPPER_COUNT_FIELD,
    GRIPPER_MODEL_FIELD,
    GRIPPER_TYPE_FIELD,
    GRIPPER_TYPE_VALUES,
    gripper_model_to_ui,
)
from core.gripper_presets import gripper_model_display_values
from core.interview_entries import INTERVIEW_QUESTIONS, generate_interview_id, save_interview_entry
from core.logging import log_activity_event
from core.openers import open_path
from core.paths import resolve_project_paths
from core.press_lookup import PressLookupResult, lookup_machine
from core.robot_info import ROBOT_INFO_SHEET, load_robot_info_for_audit_entry

PNEUMATIC_CIRCUITS_SECTION = "Pneumatic Circuits"
EOAT_PNEUMATIC_FIELDS = [
    "EOAT Vacuum Circuits",
    "EOAT Pressure Circuits",
    EOAT_INTERCHANGEABLE_CIRCUITS_FIELD,
]
ROBOT_PNEUMATIC_FIELDS = [
    "Robot Vacuum Circuits",
    "Robot Pressure Circuits",
    "Robot Interchangeable Circuits",
]
ROBOT_INTERCHANGEABLE_CIRCUITS_FIELD = "Robot Interchangeable Circuits"
GRIPPER_UI_FIELDS = {GRIPPER_COUNT_FIELD, GRIPPER_TYPE_FIELD, GRIPPER_MODEL_FIELD}


def workbook_to_ui_value(value, field: str = "") -> str:
    text = "" if value is None else str(value)
    if text.strip().upper() == NA_VALUE:
        return ""
    if field == GRIPPER_MODEL_FIELD:
        return gripper_model_to_ui(text)
    if field == GRIPPER_TYPE_FIELD and text.strip() not in GRIPPER_TYPE_VALUES:
        return ""
    return text


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
        NUMBER_OF_PARTS_PICKED_FIELD,
        GRIPPER_COUNT_FIELD,
        GRIPPER_TYPE_FIELD,
        GRIPPER_MODEL_FIELD,
        "Gripper Size",
        CUP_COUNT_FIELD,
        "Cup Type/Material",
        "Cup Diameter/Size",
        "Vacuum Generator Type",
        "Estimated EOAT Weight",
    ],
    PNEUMATIC_CIRCUITS_SECTION: [
        *EOAT_PNEUMATIC_FIELDS,
        *ROBOT_PNEUMATIC_FIELDS,
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

AUDIT_SECTION_GROUPS = {
    "Audit Header": [
        ("Audit Identity", ["Audit ID", "Audit Date", "Auditor"]),
        ("Location / Machine", ["Plant/Area", "Press/Machine #"]),
        ("Audit Status", ["Status", "Priority", "Follow-Up Needed"]),
    ],
    "Machine / Robot / Tool Context": [
        ("Robot Information", ["Robot Type", "Robot Model/Controller"]),
        ("Tool / Part Information", ["Tool #", "Part Family", "Part Name/Description"]),
        ("Production Environment", ["Cleanroom/Non-Cleanroom"]),
    ],
    "EOAT Type and Tooling": [
        ("EOAT Classification", ["EOAT Type", "EOAT Moves", "Connection Type"]),
        ("Part Pickup", [NUMBER_OF_PARTS_PICKED_FIELD, GRIPPER_COUNT_FIELD, GRIPPER_TYPE_FIELD, GRIPPER_MODEL_FIELD, "Gripper Size"]),
        ("Vacuum / Cup Details", [CUP_COUNT_FIELD, "Cup Type/Material", "Cup Diameter/Size", "Vacuum Generator Type"]),
        ("Physical Details", ["Estimated EOAT Weight"]),
    ],
    PNEUMATIC_CIRCUITS_SECTION: [
        ("EOAT Side", EOAT_PNEUMATIC_FIELDS),
        ("Robot Side", ROBOT_PNEUMATIC_FIELDS),
    ],
    "Sensors and Detection": [
        ("Detection Presence", ["Sensors Present?", "Vacuum Confirmation Present?", "Part-Present Detection Present?"]),
        ("Sensor Details", ["Sensor Type", "Sensor Brand/Model"]),
        ("Electrical / Wiring", ["Electrical/Wiring Present?"]),
    ],
    "Connections / Routing / Mechanical": [
        ("Quick Disconnects", ["Quick Disconnects Present?", "Pneumatic Quick Disconnect Type", "Electrical Quick Disconnect Type"]),
        ("Tubing / Routing", ["Tubing Condition", "Tubing Routing Notes"]),
        ("Cable Management", ["Cable Management Condition"]),
        ("Mechanical Condition", ["Mounting Hardware Condition", "EOAT Alignment Condition", "Fastener/Locking Hardware Present?"]),
    ],
    "Performance / Reliability / Maintenance": [
        ("Known Problems", ["Known Issues", "Drop/Mis-Pick History"]),
        ("Maintenance", ["Maintenance Frequency"]),
        ("Production Impact", ["Cycle Time Concern?", "Scrap/Quality Concern?"]),
        ("Changeover", ["Changeover Difficulty"]),
    ],
    "Documentation / Photos": [
        ("Documentation Status", ["Drawing/CAD Available?", "BOM Available?", "Process Binder Complete?"]),
        ("Photo Evidence", ["Photos Taken?", "Photo Folder/Link"]),
        ("Spare Parts", ["Spare Parts Identified?"]),
    ],
    "Pilot / Final Notes": [
        ("Pilot Evaluation", ["Pilot Candidate?"]),
        ("Final Notes", ["Notes"]),
    ],
}

FIELD_ANNOTATION_TINTS = {
    "yellow": "#fefce8",
    "red": "#fef2f2",
    "green": "#f0fdf4",
    "blue": "#eff6ff",
    "purple": "#faf5ff",
    "orange": "#fff7ed",
    "gray": "#f9fafb",
    "teal": "#f0fdfa",
    "pink": "#fdf2f8",
}


def audit_section_for_field(field: str) -> str | None:
    normalized = str(field or "").strip()
    if not normalized:
        return None
    for section, fields in AUDIT_SECTIONS.items():
        if normalized in fields:
            return section
    folded = normalized.casefold()
    for section, fields in AUDIT_SECTIONS.items():
        if any(item.casefold() == folded for item in fields):
            return section
    return None

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
        self.defaults_controller = AuditDefaultsController(config)
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
        self._machine_lookup_extra_note = ""
        self._part_present_autofilled_sensor_fields: set[str] = set()
        self.annotation_service = AnnotationService(config.project_root)
        self._field_tag_buttons = {}
        self._audit_field_rows = {}
        self._audit_field_sections = {}
        self._audit_field_scroll_areas = {}
        self._audit_field_group_keys = {}
        self._audit_field_visibility_state = {}
        self._audit_group_boxes = {}
        self._audit_group_fields = {}
        self._navigation_highlight_row = None
        self._suppress_clear_confirm_this_session = False
        self._audit_form_baseline: dict[str, str] = {}
        self._clean_new_audit_form_values: dict[str, str] = {}
        self._draft_recovery_checked = False
        self._audit_coach_refresh_pending = False

        layout = QVBoxLayout(self)
        heading = QLabel("EOAT Audit")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        self.main_tabs = QTabWidget()
        tabs = self.main_tabs
        tabs.addTab(self._build_audit_tab(), "Audit Entry")
        tabs.addTab(self._build_compatibility_tab(), "Compatibility Entry")
        tabs.addTab(self._build_interview_tab(), "Interview Notes")

        self.audit_output_splitter = QSplitter(Qt.Orientation.Vertical)
        self.audit_output_splitter.setChildrenCollapsible(False)
        self.audit_output_splitter.addWidget(tabs)
        self.output_panel_container = QWidget()
        output_layout = QVBoxLayout(self.output_panel_container)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_header = QHBoxLayout()
        output_label = QLabel("Output")
        output_label.setStyleSheet("font-weight: 600;")
        output_header.addWidget(output_label)
        output_header.addStretch(1)
        for label, callback in [
            ("Expand Output", self.expand_output_panel),
            ("Collapse Output", self.collapse_output_panel),
            ("Copy Output", self.copy_output_panel),
            ("Clear Output", self.clear_output_panel),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            output_header.addWidget(button)
        output_layout.addLayout(output_header)
        self.result_panel = ToolRunPanel()
        self.result_panel.setMinimumHeight(180)
        self.result_panel.viewer.setMinimumHeight(160)
        output_layout.addWidget(self.result_panel)
        self.output_panel_container.setMinimumHeight(220)
        self.audit_output_splitter.addWidget(self.output_panel_container)
        self.audit_output_splitter.setStretchFactor(0, 1)
        self.audit_output_splitter.setStretchFactor(1, 0)
        self.audit_output_splitter.setSizes([640, 220])
        layout.addWidget(self.audit_output_splitter, stretch=1)
        if QTimer is not None:
            QTimer.singleShot(0, self._offer_draft_recovery)

    def expand_output_panel(self) -> None:
        total = sum(self.audit_output_splitter.sizes()) or 860
        output_height = min(max(320, total // 2), max(220, total - 260))
        self.audit_output_splitter.setSizes([max(260, total - output_height), output_height])

    def collapse_output_panel(self) -> None:
        total = sum(self.audit_output_splitter.sizes()) or 860
        self.audit_output_splitter.setSizes([max(260, total - 220), 220])

    def copy_output_panel(self) -> None:
        app = QApplication.instance() if QApplication is not None else None
        if app is not None:
            app.clipboard().setText(self.result_panel.viewer.toPlainText())

    def clear_output_panel(self) -> None:
        self.result_panel.show_text("")

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
        if widget is None:
            return ""
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

    def _current_audit_form_values(self) -> dict[str, str]:
        if not hasattr(self, "audit_fields"):
            return {}
        return {field: self._field_value(widget) for field, widget in self.audit_fields.items()}

    def _connect_audit_coach_refresh(self, widget) -> None:
        if isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(self._schedule_audit_coach_refresh)
        elif isinstance(widget, QTextEdit):
            widget.textChanged.connect(self._schedule_audit_coach_refresh)
        elif isinstance(widget, QLineEdit):
            widget.textChanged.connect(self._schedule_audit_coach_refresh)

    def _schedule_audit_coach_refresh(self, *_args) -> None:
        if self._programmatic_field_update:
            return
        if QTimer is None:
            self._refresh_audit_coach()
            return
        if self._audit_coach_refresh_pending:
            return
        self._audit_coach_refresh_pending = True
        QTimer.singleShot(0, self._refresh_audit_coach)

    def _refresh_audit_coach(self) -> None:
        self._audit_coach_refresh_pending = False
        panel = getattr(self, "audit_coach_panel", None)
        if panel is None or not hasattr(self, "audit_fields"):
            return
        summary = calculate_audit_coach_summary(self._current_audit_form_values(), AUDIT_SECTIONS, mode=self._current_audit_mode)
        panel.refresh(summary)

    def _mark_audit_form_baseline(self, _reason: str = "", *, clean_new_form: bool = False) -> None:
        values = self._current_audit_form_values()
        self._audit_form_baseline = dict(values)
        if clean_new_form:
            self._clean_new_audit_form_values = dict(values)

    def has_unsaved_changes(self, *, ignored_fields: set[str] | None = None) -> bool:
        current = self._current_audit_form_values()
        baseline = dict(self._audit_form_baseline)
        for field in ignored_fields or set():
            current.pop(field, None)
            baseline.pop(field, None)
        return form_values_changed(current, baseline)

    def is_clean_new_form_or_lookup_only(self, *, lookup_fields: set[str] | None = None) -> bool:
        if self._current_audit_mode != "new" or self._editing_audit_id or self._current_loaded_audit_id:
            return False
        clean_values = dict(self._clean_new_audit_form_values or self._audit_form_baseline)
        ignored = lookup_fields if lookup_fields is not None else {"Press/Machine #"}
        if not clean_values:
            return not self.has_unsaved_changes(ignored_fields=ignored)
        current = self._current_audit_form_values()
        for field in set(current) | set(clean_values):
            if field in ignored:
                continue
            current_value = current.get(field, "")
            clean_value = clean_values.get(field, "")
            if field == "Audit ID" and current_value != clean_value and self._is_generated_new_audit_id(current_value):
                continue
            if current_value != clean_value:
                return False
        return True

    def _is_generated_new_audit_id(self, audit_id: str) -> bool:
        return bool(str(audit_id or "").strip() in self._generated_audit_ids)

    def _save_current_audit_draft(self) -> str:
        values = self._current_audit_form_values()
        path = save_audit_draft(
            self.config.project_root,
            audit_id=values.get("Audit ID", ""),
            mode=self._current_audit_mode,
            form_values=values,
            baseline_values=self._audit_form_baseline,
        )
        return str(path)

    def save_current_audit_draft(self) -> None:
        path = self._save_current_audit_draft()
        if hasattr(self, "result_panel"):
            self.result_panel.show_text(f"Saved local audit draft.\n\nDraft file: {path}")

    def discard_saved_audit_draft(self) -> None:
        removed = discard_audit_draft(self.config.project_root)
        if hasattr(self, "result_panel"):
            message = "Discarded saved audit draft." if removed else "No saved audit draft was found."
            self.result_panel.show_text(message)

    def _offer_draft_recovery(self) -> None:
        if self._draft_recovery_checked:
            return
        self._draft_recovery_checked = True
        draft = load_audit_draft(self.config.project_root)
        if draft is None:
            return
        if QMessageBox is None:
            self._restore_audit_draft(draft)
            return
        box = QMessageBox(self)
        box.setWindowTitle("Recover Audit Draft")
        box.setText("A local unsaved audit draft is available.")
        box.setInformativeText(
            f"Draft audit ID: {draft.audit_id or '(blank)'}\n"
            f"Saved at: {draft.saved_at}\n\n"
            "Restore it now, discard it, or leave it for later."
        )
        restore_button = box.addButton("Restore Draft", QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton("Discard Draft", QMessageBox.ButtonRole.DestructiveRole)
        later_button = box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == restore_button:
            self._restore_audit_draft(draft)
        elif clicked == discard_button:
            discard_audit_draft(self.config.project_root)
        elif clicked == later_button:
            return

    def _restore_audit_draft(self, draft) -> None:
        for field, value in draft.form_values.items():
            widget = self.audit_fields.get(field)
            if widget is not None:
                self._set_field_value(widget, value)
        self._audit_form_baseline = dict(draft.baseline_values)
        self._current_audit_mode = draft.mode or "new"
        self._editing_audit_id = draft.audit_id if self._current_audit_mode == "edit" else None
        self._current_loaded_audit_id = self._editing_audit_id
        self._loaded_empty_only_fields = None
        self.audit_view_mode_combo.blockSignals(True)
        self.audit_view_mode_combo.setCurrentText("Full Audit")
        self.audit_view_mode_combo.setEnabled(False)
        self.audit_view_mode_combo.blockSignals(False)
        self._set_audit_selector_text(draft.audit_id)
        self._update_audit_field_visibility()
        self._refresh_field_tag_indicators()
        if hasattr(self, "result_panel"):
            self.result_panel.show_text(f"Restored local audit draft {draft.audit_id or '(blank audit ID)'}.")

    def _confirm_unsaved_audit_changes(self, action: str) -> bool:
        if not self.has_unsaved_changes():
            return True
        if QMessageBox is None:
            self._save_current_audit_draft()
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved Audit Changes")
        box.setText("The current audit form has unsaved changes.")
        box.setInformativeText(
            f"Save a local draft before you {action}, discard the on-screen changes, or cancel."
        )
        save_draft_button = box.addButton("Save Draft", QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton("Discard Changes", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == save_draft_button:
            self._save_current_audit_draft()
            return True
        if clicked == discard_button:
            return True
        return clicked != cancel_button and False

    def can_close(self) -> tuple[bool, str]:
        if self._confirm_unsaved_audit_changes("leave the Audit page"):
            return True, ""
        return False, "Audit form has unsaved changes."

    def on_project_root_changed(self, config) -> None:
        self.config = config
        self.defaults_controller = AuditDefaultsController(config)
        self.annotation_service = AnnotationService(config.project_root)
        self._draft_recovery_checked = False
        self.refresh_audit_selector()
        if hasattr(self, "compatibility_source_combo"):
            self.refresh_compatibility_sources()
        self._refresh_audit_coach()

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

        self.audit_section_tabs = QTabWidget()
        for title, fields in AUDIT_SECTIONS.items():
            section_tab = self._build_section_tab(fields, section_title=title)
            self.audit_section_tabs.addTab(section_tab, title)
        audit_body = QHBoxLayout()
        audit_body.addWidget(self.audit_section_tabs, stretch=3)
        self.audit_coach_panel = AuditCoachPanel(self)
        self.audit_coach_panel.setMinimumWidth(340)
        audit_body.addWidget(self.audit_coach_panel, stretch=1)
        outer.addLayout(audit_body, stretch=1)

        self.audit_followup_check = QCheckBox("Create Follow-Up Action")
        outer.addWidget(self.audit_followup_check)

        button_row = QHBoxLayout()
        suggestions_button = QPushButton("Review Suggestions")
        suggestions_button.clicked.connect(self.review_annotation_suggestions)
        save_button = QPushButton("Save Audit Entry")
        save_button.clicked.connect(self.save_audit)
        save_draft_button = QPushButton("Save Draft")
        save_draft_button.clicked.connect(self.save_current_audit_draft)
        discard_draft_button = QPushButton("Discard Draft")
        discard_draft_button.clicked.connect(self.discard_saved_audit_draft)
        clear_button = QPushButton("Clear Form")
        clear_button.clicked.connect(lambda: self.clear_audit_form(confirm=True))
        button_row.addWidget(suggestions_button)
        button_row.addWidget(save_button)
        button_row.addWidget(save_draft_button)
        button_row.addWidget(discard_draft_button)
        button_row.addWidget(clear_button)
        outer.addLayout(button_row)

        self.clear_audit_form(confirm=False, clear_summary=False)
        self._refresh_audit_coach()
        self.refresh_audit_selector()
        return container

    def _build_compatibility_tab(self) -> QWidget:
        return build_compatibility_tab(self)

    def _build_section_tab(self, fields: list[str], *, section_title: str = "") -> QWidget:
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        groups = AUDIT_SECTION_GROUPS.get(section_title) or [(section_title or "Fields", fields)]
        for group_title, group_fields in groups:
            group = self._build_audit_field_group(group_title, group_fields, scroll, section_title=section_title)
            content_layout.addWidget(group)
        content_layout.addStretch(1)

        scroll.setWidget(content)
        return scroll

    def _build_audit_field_group(self, group_title: str, fields: list[str], scroll: QScrollArea, *, section_title: str) -> QGroupBox:
        group = QGroupBox(group_title)
        group.setObjectName("AuditFieldGroup")
        group_layout = QFormLayout(group)
        group_layout.setContentsMargins(10, 8, 10, 10)
        group_layout.setHorizontalSpacing(12)
        group_layout.setVerticalSpacing(6)
        group_key = f"{section_title}::{group_title}"
        self._audit_group_boxes[group_key] = group
        self._audit_group_fields[group_key] = list(fields)
        for field in fields:
            self._add_audit_field_row(group_layout, field, scroll, section_title=section_title, group_key=group_key)
        return group

    def _add_audit_field_row(self, form_layout: QFormLayout, field: str, scroll: QScrollArea, *, section_title: str, group_key: str = "") -> None:
        widget = self._widget_for_audit_field(field)
        self.audit_fields[field] = widget
        label = QLabel(field)
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(5)
        if field == "Press/Machine #":
            row_layout.addWidget(widget, stretch=1)
            lookup_button = QPushButton("Lookup")
            lookup_button.clicked.connect(self.run_machine_lookup)
            row_layout.addWidget(lookup_button)
        else:
            row_layout.addWidget(widget, stretch=1)
        tag_button = FieldTagButton()
        tag_button.clicked.connect(lambda _checked=False, field_name=field: self.open_field_tag_dialog(field_name))
        row_layout.addWidget(tag_button)
        form_layout.addRow(label, row_widget)
        self._field_tag_buttons[field] = tag_button
        self._audit_field_rows[field] = row_widget
        self._audit_field_labels[field] = label
        self._audit_field_sections[field] = section_title
        self._audit_field_scroll_areas[field] = scroll
        self._audit_field_group_keys[field] = group_key
        self._audit_field_visibility_state[field] = True
        self._connect_audit_coach_refresh(widget)

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
        if field == GRIPPER_MODEL_FIELD:
            return self._combo(gripper_model_display_values(self.config.project_root), editable=True)
        if field in PNEUMATIC_CIRCUIT_FIELDS or field in {NUMBER_OF_PARTS_PICKED_FIELD, CUP_COUNT_FIELD, GRIPPER_COUNT_FIELD}:
            edit = self._line()
            if QIntValidator is not None:
                edit.setValidator(QIntValidator(0, 9999, edit))
            return edit
        if field in {"Sensors Present?", "Cycle Time Concern?", "Scrap/Quality Concern?", "Drawing/CAD Available?", "BOM Available?"}:
            combo = self._combo(AUDIT_DROPDOWNS["YesNoUnknown"], editable=False)
            if field == "Sensors Present?":
                combo.currentTextChanged.connect(self._on_sensors_present_changed)
            return combo
        if field == "Electrical/Wiring Present?":
            combo = self._combo(AUDIT_DROPDOWNS.get(field, AUDIT_DROPDOWNS["YesNoUnknown"]), editable=False)
            combo.currentTextChanged.connect(self._on_electrical_wiring_present_changed)
            return combo
        if field in {"Vacuum Confirmation Present?", PART_PRESENT_DETECTION_FIELD}:
            combo = self._combo(AUDIT_DROPDOWNS["YesNoUnknownNA"], editable=False)
            if field == PART_PRESENT_DETECTION_FIELD:
                combo.currentTextChanged.connect(self._on_part_present_detection_changed)
            return combo
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

    def generate_new_audit_id(self, _checked: bool = False, *, show_message: bool = True) -> None:
        was_clean_new_form = (
            self._current_audit_mode == "new"
            and self._editing_audit_id is None
            and self._current_loaded_audit_id is None
            and not self.has_unsaved_changes(ignored_fields={"Audit ID"})
        )
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
        self._refresh_field_tag_indicators()
        if show_message and hasattr(self, "result_panel"):
            self.result_panel.show_text(f"Generated new audit ID {audit_id}. Save will create a new audit row.")
        if was_clean_new_form:
            self._mark_audit_form_baseline("generate_new_audit_id", clean_new_form=True)

    def clear_audit_form(self, *, confirm: bool = False, clear_summary: bool = True) -> None:
        if confirm and not self._suppress_clear_confirm_this_session and not self._confirm_clear_audit_form():
            return
        self._reset_audit_form_fields(show_generated_message=False)
        if clear_summary and hasattr(self, "result_panel"):
            self.result_panel.show_text("")

    def _confirm_clear_audit_form(self) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("Clear Form")
        box.setText("Clear this form?")
        box.setInformativeText(
            "This will erase the current on-screen entries and clear the summary panel.\n"
            "It will not delete any audit entries already saved to the workbook."
        )
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok)
        clear_button = box.button(QMessageBox.StandardButton.Ok)
        if clear_button is not None:
            clear_button.setText("Clear Form")
        checkbox = QCheckBox("Do not ask again this session")
        box.setCheckBox(checkbox)
        result = box.exec()
        accepted = result == QMessageBox.StandardButton.Ok
        if accepted and checkbox.isChecked():
            self._suppress_clear_confirm_this_session = True
        return accepted

    def _reset_audit_form_fields(self, *, show_generated_message: bool = True) -> None:
        self._editing_audit_id = None
        self._current_loaded_audit_id = None
        self._current_audit_mode = "new"
        self._duplicated_press_value = None
        self._duplicated_tool_value = None
        self._loaded_empty_only_fields = None
        self._changeover_user_modified = False
        self._part_present_autofilled_sensor_fields.clear()
        for widget in self.audit_fields.values():
            self._set_field_value(widget, "")
        self._set_field_value(self.audit_fields["Audit Date"], date.today().isoformat())
        for field, default in self.defaults_controller.initial_form_defaults().items():
            if field in self.audit_fields:
                self._set_field_value(self.audit_fields[field], default)
        self._apply_quick_disconnect_defaults()
        self._apply_sensor_defaults()
        self._update_tooling_visibility(apply_defaults=True)
        self.current_lookup_result = None
        self._lookup_part_index = None
        self._lookup_conflict_warnings = []
        if hasattr(self, "lookup_note_label"):
            self.lookup_note_label.setText("Enter a machine number to look up robot and part info.")
            self._set_capacity_choices([])
            self._set_machine_audit_matches([])
        self.generate_new_audit_id(show_message=show_generated_message)
        self._refresh_field_tag_indicators()
        self._mark_audit_form_baseline("reset", clean_new_form=True)

    def load_existing_audit(self, audit_id: str | None = None, *, loaded_message: str | None = None, confirm_unsaved: bool = True) -> bool:
        audit_id = audit_id or self._audit_selector_audit_id()
        entry = load_audit_entry(self.config.project_root, audit_id)
        if not entry:
            self.result_panel.show_text(f"Audit ID not found: {audit_id}")
            return False
        if confirm_unsaved and not self._confirm_unsaved_audit_changes("load another audit"):
            return False
        self._set_audit_selector_text(audit_id)
        self._loading_audit = True
        self._part_present_autofilled_sensor_fields.clear()
        try:
            for field, widget in self.audit_fields.items():
                if field in GRIPPER_UI_FIELDS and not field_applies(entry, field):
                    self._set_field_value(widget, "")
                else:
                    self._set_field_value(widget, workbook_to_ui_value(entry.get(field, ""), field))
            self._load_robot_info_fields(entry, force=True)
            for field in ROBOT_PNEUMATIC_FIELDS:
                if field in self.audit_fields:
                    entry[field] = self._field_value(self.audit_fields[field])
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
        self._refresh_field_tag_indicators()
        self._mark_audit_form_baseline("load")
        return True

    def _load_robot_info_fields(self, entry: dict[str, object], *, force: bool) -> bool:
        robot_info = load_robot_info_for_audit_entry(self.config.project_root, entry)
        if not robot_info:
            if ROBOT_INTERCHANGEABLE_CIRCUITS_FIELD in self.audit_fields:
                widget = self.audit_fields[ROBOT_INTERCHANGEABLE_CIRCUITS_FIELD]
                if force or not self._field_value(widget):
                    self._set_field_value(widget, "0")
            return False
        for field in ROBOT_PNEUMATIC_FIELDS:
            if field not in self.audit_fields:
                continue
            widget = self.audit_fields[field]
            if force or not self._field_value(widget):
                self._set_field_value(widget, workbook_to_ui_value(robot_info.get(field, "")))
        return True

    def duplicate_audit(self) -> None:
        original_press = self._field_value(self.audit_fields["Press/Machine #"])
        original_tool = self._field_value(self.audit_fields["Tool #"])
        today = date.today().isoformat()
        audit_id = generate_audit_id(self.config.project_root, today)
        self._set_field_value(self.audit_fields["Audit ID"], audit_id)
        self._set_field_value(self.audit_fields["Audit Date"], today)
        if not self._field_value(self.audit_fields["Auditor"]):
            self._set_field_value(self.audit_fields["Auditor"], self.defaults_controller.field_default("Auditor") or "Kato Gray")
        self._set_field_value(self.audit_fields["Photos Taken?"], self.defaults_controller.field_default("Photos Taken?") or "No")
        self._set_field_value(self.audit_fields["Photo Folder/Link"], "")
        for field in DOCUMENTATION_PHOTO_DEFAULT_FIELDS:
            if field in self.audit_fields:
                self._set_field_value(self.audit_fields[field], self.defaults_controller.field_default(field) or "No")
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
        self._refresh_field_tag_indicators()
        self._mark_audit_form_baseline("duplicate")

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
        self._refresh_audit_coach()

    def _audit_field_applies_in_current_form(self, field: str) -> bool:
        current_entry = {name: self._field_value(widget) for name, widget in self.audit_fields.items()}
        return field_applies(current_entry, field)

    def _apply_eoat_type_defaults(self) -> None:
        eoat_type = self._field_value(self.audit_fields["EOAT Type"])
        cup_widget = self.audit_fields.get("Cup Type/Material")
        if cup_widget is None:
            return
        cup_value = self._field_value(cup_widget)
        cup_default = self.defaults_controller.field_default("Cup Type/Material") or CUP_TYPE_DEFAULT
        if cup_type_default_applies(eoat_type):
            if not cup_value:
                self._set_field_value(cup_widget, cup_default)
        elif cup_value == cup_default:
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

    def _on_part_present_detection_changed(self, *_args) -> None:
        if self._loading_audit or self._programmatic_field_update:
            return
        if self._field_value(self.audit_fields[PART_PRESENT_DETECTION_FIELD]).lower() == "yes":
            self._apply_part_present_sensor_autofill()
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
                self._set_field_value(pneumatic_widget, self.defaults_controller.quick_disconnect_type_default())

    def _apply_changeover_difficulty_default(self) -> None:
        if self._changeover_user_modified:
            return
        if CONNECTION_TYPE_FIELD not in self.audit_fields or CHANGEOVER_DIFFICULTY_FIELD not in self.audit_fields:
            return
        difficulty_widget = self.audit_fields[CHANGEOVER_DIFFICULTY_FIELD]
        if not self._smart_default_can_fill(self._field_value(difficulty_widget)):
            return
        connection_type = self._field_value(self.audit_fields[CONNECTION_TYPE_FIELD])
        default = self.defaults_controller.changeover_default(connection_type)
        if default:
            self._set_field_value(difficulty_widget, default)

    def _smart_default_can_fill(self, value: str) -> bool:
        return str(value or "").strip().lower() in UNSET_SMART_DEFAULT_VALUES

    def _apply_sensor_defaults(self) -> None:
        for field in SENSOR_ELECTRICAL_FIELDS:
            default = self.defaults_controller.field_default(field) or audit_field_default(field)
            if default is None or field not in self.audit_fields:
                continue
            widget = self.audit_fields[field]
            if not self._field_value(widget):
                self._set_field_value(widget, default)
        if (
            PART_PRESENT_DETECTION_FIELD in self.audit_fields
            and self._field_value(self.audit_fields[PART_PRESENT_DETECTION_FIELD]).lower() == "yes"
        ):
            self._apply_part_present_sensor_autofill()

    def _apply_part_present_sensor_autofill(self) -> None:
        for field, default in PART_PRESENT_SENSOR_DEFAULTS.items():
            if field not in self.audit_fields:
                continue
            widget = self.audit_fields[field]
            if part_present_sensor_value_allows_default(self._field_value(widget), default):
                self._set_field_value(widget, default)
                self._part_present_autofilled_sensor_fields.add(field)

    def _empty_only_mode_active(self) -> bool:
        return (
            self._loaded_empty_only_fields is not None
            and hasattr(self, "audit_view_mode_combo")
            and self.audit_view_mode_combo.currentText() == "Empty Only"
        )

    def _set_audit_field_visible(self, field: str, visible: bool) -> None:
        self._audit_field_visibility_state[field] = visible
        widget = self.audit_fields.get(field)
        if widget is not None:
            widget.setVisible(visible)
        row = self._audit_field_rows.get(field)
        if row is not None:
            row.setVisible(visible)
        label = self._audit_field_labels.get(field)
        if label is not None:
            label.setVisible(visible)
        self._refresh_audit_group_visibility(field)

    def _refresh_audit_group_visibility(self, field: str) -> None:
        group_key = self._audit_field_group_keys.get(field)
        if not group_key:
            return
        group = self._audit_group_boxes.get(group_key)
        if group is None:
            return
        group_fields = self._audit_group_fields.get(group_key, [])
        group.setVisible(any(self._audit_field_visibility_state.get(group_field, True) for group_field in group_fields))

    def _field_tag_target_id(self, field: str) -> str:
        existing = self.annotation_service.find_audit_field_target(
            self._field_value(self.audit_fields.get("Audit ID")),
            field,
        )
        if existing is not None:
            return existing.id
        return target_id_for(
            target_type="audit_field",
            audit_id=self._field_value(self.audit_fields.get("Audit ID")),
            machine_id=self._field_value(self.audit_fields.get("Press/Machine #")),
            field_key=field,
            object_ref="",
        )

    def _create_or_get_field_tag_target(self, field: str):
        audit_id = self._field_value(self.audit_fields.get("Audit ID"))
        machine = self._field_value(self.audit_fields.get("Press/Machine #"))
        paths = resolve_project_paths(self.config.project_root)
        workbook_path = paths.robot_info_workbook if field in ROBOT_PNEUMATIC_FIELDS else paths.master_workbook
        sheet_name = ROBOT_INFO_SHEET if field in ROBOT_PNEUMATIC_FIELDS else "EOAT Inventory"
        return self.annotation_service.create_or_get_target(
            "audit_field",
            target_label=f"{audit_id} / {field}" if audit_id else field,
            audit_id=audit_id,
            machine_id=machine,
            field_key=field,
            field_label=field,
            sheet_name=sheet_name,
            header_name=field,
            workbook_path=workbook_path,
        )

    def open_field_tag_dialog(self, field: str) -> None:
        audit_id = self._field_value(self.audit_fields.get("Audit ID"))
        if not audit_id:
            QMessageBox.information(
                self,
                "Tag Audit Field",
                "Generate or save an Audit ID before tagging this field so the annotation can be linked safely.",
            )
            return
        target = self._create_or_get_field_tag_target(field)
        dialog = FieldTagDialog(
            self.annotation_service,
            target,
            field_label=field,
            current_value=self._field_value(self.audit_fields[field]),
            parent=self,
        )
        dialog.exec()
        self._refresh_field_tag_indicators()

    def open_audit_coach_field(self, field: str) -> None:
        if field not in self.audit_fields:
            self.result_panel.show_text(f"Audit Coach could not find field: {field}")
            return
        entry = self._current_audit_form_values()
        if not field_applies(entry, field):
            reason = non_applicable_reason(entry, field)
            self.result_panel.show_text(f"{field} is hidden because: {reason}")
            return
        audit_id = self._field_value(self.audit_fields.get("Audit ID"))
        self.focus_annotation_target({"target_type": "audit_field", "audit_id": audit_id, "field_label": field, "field_key": field})

    def mark_audit_coach_field_unknown(self, field: str) -> None:
        widget = self.audit_fields.get(field)
        if widget is None:
            self.result_panel.show_text(f"Audit Coach could not find field: {field}")
            return
        entry = self._current_audit_form_values()
        if not field_applies(entry, field):
            self.result_panel.show_text(f"{field} is non-applicable: {non_applicable_reason(entry, field)}")
            return
        unknown_value = self._unknown_value_for_audit_field(field, widget)
        if not unknown_value:
            self.result_panel.show_text(
                f"{field} uses a restricted value format. Create a follow-up or tag it Needs Review instead of writing Unknown / Not Checked."
            )
            return
        self._set_field_value(widget, unknown_value)
        self._update_audit_field_visibility()
        self._refresh_audit_coach()
        self.result_panel.show_text(f"Marked {field} as {unknown_value}. This is not counted as verified complete.")

    def create_audit_coach_follow_up(self, field: str) -> None:
        if field not in self.audit_fields:
            self.result_panel.show_text(f"Audit Coach could not find field: {field}")
            return
        entry = self._current_audit_form_values()
        audit_id = entry.get("Audit ID") or "(unsaved audit)"
        action_text = f"Review EOAT audit {audit_id} field {field}."
        result = add_action_item(
            self.config.project_root,
            action_text,
            related_cell_press=entry.get("Press/Machine #", ""),
            priority=entry.get("Priority") or "Medium",
            notes="Created from Audit Coach guided completion.",
        )
        if result.success:
            followup_widget = self.audit_fields.get("Follow-Up Needed")
            if followup_widget is not None:
                self._set_field_value(followup_widget, "Yes")
            if hasattr(self, "audit_followup_check"):
                self.audit_followup_check.setChecked(True)
            get_event_bus().emit(EVENT_OPEN_ITEMS_CHANGED, {"audit_id": audit_id, "field": field}, source="audit_coach")
            self._refresh_audit_coach()
        self.result_panel.show_result(result)

    def tag_audit_coach_needs_review(self, field: str) -> None:
        if field not in self.audit_fields:
            self.result_panel.show_text(f"Audit Coach could not find field: {field}")
            return
        audit_id = self._field_value(self.audit_fields.get("Audit ID"))
        if not audit_id:
            self.result_panel.show_text("Generate or save an Audit ID before tagging a field from Audit Coach.")
            return
        tag = self.annotation_service.get_tag_by_name("Needs Review")
        if tag is None:
            self.result_panel.show_text("The default Needs Review tag is missing from the annotation database.")
            return
        target = self._create_or_get_field_tag_target(field)
        self.annotation_service.assign_tag_to_target(
            tag.id,
            target.id,
            comment="Flagged by Audit Coach guided completion.",
            sync_workbook=False,
        )
        self._refresh_field_tag_indicators()
        get_event_bus().emit(EVENT_ANNOTATION_CHANGED, {"audit_id": audit_id, "field": field, "tag": "Needs Review"}, source="audit_coach")
        self.result_panel.show_text(f"Tagged {field} as Needs Review.")

    def _unknown_value_for_audit_field(self, field: str, widget) -> str:
        numeric_only_fields = {NUMBER_OF_PARTS_PICKED_FIELD, CUP_COUNT_FIELD, GRIPPER_COUNT_FIELD, *PNEUMATIC_CIRCUIT_FIELDS, *ROBOT_PNEUMATIC_FIELDS}
        if field in numeric_only_fields or field == GRIPPER_TYPE_FIELD:
            return ""
        if field == "EOAT Type":
            return "Unknown / Needs Review"
        unknown_value = unknown_not_checked_value_for_field(field)
        if isinstance(widget, QComboBox) and not widget.isEditable() and widget.findText(unknown_value) < 0:
            return ""
        return unknown_value

    def focus_annotation_target(self, target: dict[str, object]) -> None:
        field = str(target.get("field_label") or target.get("field_key") or target.get("header_name") or "").strip()
        audit_id = str(target.get("audit_id") or "").strip()
        section = audit_section_for_field(field)
        if hasattr(self, "main_tabs"):
            self.main_tabs.setCurrentIndex(0)
        if hasattr(self, "audit_view_mode_combo"):
            self.audit_view_mode_combo.blockSignals(True)
            self.audit_view_mode_combo.setCurrentText("Full Audit")
            self.audit_view_mode_combo.setEnabled(True)
            self.audit_view_mode_combo.blockSignals(False)
            self._update_audit_field_visibility()
        if section and hasattr(self, "audit_section_tabs"):
            for index in range(self.audit_section_tabs.count()):
                if self.audit_section_tabs.tabText(index) == section:
                    self.audit_section_tabs.setCurrentIndex(index)
                    break
        if field and field in self.audit_fields:
            widget = self.audit_fields[field]
            widget.setFocus(Qt.FocusReason.OtherFocusReason)
            row = self._audit_field_rows.get(field)
            scroll = self._audit_field_scroll_areas.get(field)
            if scroll is not None and row is not None:
                scroll.ensureWidgetVisible(row, 0, 90)
            self._show_navigation_highlight(field)
            widget.setToolTip(f"Target field: {field}")
        if hasattr(self, "result_panel"):
            if audit_id and field and section:
                self.result_panel.show_text(f"Opened {audit_id}. Target field: {field}. Section: {section}.")
            elif audit_id and field:
                self.result_panel.show_text(f"Opened {audit_id}. Target field: {field}. Could not determine section.")
            elif audit_id:
                self.result_panel.show_text(f"Opened {audit_id}.")

    def _show_navigation_highlight(self, field: str) -> None:
        self._clear_navigation_highlight()
        row = self._audit_field_rows.get(field)
        if row is None:
            return
        row.setProperty("previous_navigation_style", row.styleSheet())
        row.setObjectName("AuditFieldNavigationHighlight")
        row.setStyleSheet("#AuditFieldNavigationHighlight { border: 2px solid #2563eb; border-radius: 4px; padding: 1px; }")
        self._navigation_highlight_row = row
        if QTimer is not None:
            QTimer.singleShot(3500, self._clear_navigation_highlight)

    def _clear_navigation_highlight(self) -> None:
        row = self._navigation_highlight_row
        if row is None:
            return
        previous = str(row.property("previous_navigation_style") or "")
        row.setStyleSheet(previous)
        row.setProperty("previous_navigation_style", None)
        self._navigation_highlight_row = None

    def _refresh_field_tag_indicators(self) -> None:
        if not hasattr(self, "audit_fields"):
            return
        audit_id = self._field_value(self.audit_fields.get("Audit ID"))
        for field, widget in self.audit_fields.items():
            button = self._field_tag_buttons.get(field)
            if button is None:
                continue
            tags = []
            notes = []
            if audit_id:
                target_id = self._field_tag_target_id(field)
                tags = self.annotation_service.get_tags_for_target(target_id)
                notes = self.annotation_service.get_notes_for_target(target_id)
            tag_names = [str(tag["name"]) for tag in tags]
            note_subjects = [str(note["subject"]) for note in notes]
            button.set_annotation_state(tag_names, note_subjects)
            if tag_names or note_subjects:
                tooltip_parts = []
                if tag_names:
                    tooltip_parts.append("Tags: " + ", ".join(tag_names))
                if note_subjects:
                    tooltip_parts.append("Notes: " + ", ".join(note_subjects[:3]))
                widget.setToolTip("\n".join(tooltip_parts))
                priority_tag = highest_priority_tag(tags)
                color_key = str(priority_tag.get("color_key") or "blue") if priority_tag else "blue"
                color = TAG_COLOR_PALETTE.get(color_key, TAG_COLOR_PALETTE["blue"])
                tint = FIELD_ANNOTATION_TINTS.get(color_key, "#eff6ff")
                widget.setStyleSheet(f"border: 1px solid {color.ui_hex}; background: {tint};")
            else:
                widget.setToolTip("")
                widget.setStyleSheet("")

    def _sync_annotation_colors_for_audit(self, audit_id: str) -> None:
        if not audit_id:
            return
        self.annotation_service.sync_tag_colors_to_workbook_for_audit(audit_id)

    def review_annotation_suggestions(self) -> None:
        entry = {field: self._field_value(widget) for field, widget in self.audit_fields.items()}
        suggestions = self.annotation_service.get_suggested_annotations(entry)
        if not suggestions:
            self.result_panel.show_text("No annotation suggestions for the current audit form.")
            return
        dialog = AnnotationSuggestionsDialog(self, entry, parent=self)
        dialog.exec()
        self._refresh_field_tag_indicators()
        self._refresh_audit_coach()

    def _confirm_compatibility_impact_preview(self, preview: CompatibilityImpactPreview) -> bool:
        if QMessageBox is None:
            return True
        fields = ", ".join(preview.fields_likely_to_propagate[:12])
        if len(preview.fields_likely_to_propagate) > 12:
            fields += ", ..."
        box = QMessageBox(self)
        box.setWindowTitle("Compatibility Impact Preview")
        box.setText("Saving this physical audit will update linked compatibility rows.")
        box.setInformativeText(
            f"Source audit ID: {preview.source_audit_id}\n"
            f"Linked compatible rows: {preview.compatible_row_count}\n"
            f"Compatibility auto-run: {'Yes' if preview.will_run_autorun else 'No'}\n"
            f"Press view refresh: {'Yes' if preview.will_refresh_press_view else 'No'}\n"
            f"Fields likely to propagate: {fields or '(none)'}\n\n"
            "This app currently saves source audit changes and updates linked compatibility rows together."
        )
        save_button = box.addButton("Save and Update Compatibility", QMessageBox.ButtonRole.AcceptRole)
        cancel_button = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() == save_button and box.clickedButton() != cancel_button

    def save_audit(self) -> None:
        entry = {field: self._field_value(widget) for field, widget in self.audit_fields.items()}
        current_audit_id = str(entry.get("Audit ID") or "").strip()
        allow_update = bool(self._current_audit_mode == "edit" and self._editing_audit_id and current_audit_id == self._editing_audit_id)
        sync_linked_compatibility = False
        if allow_update:
            preview = build_compatibility_impact_preview(self.config.project_root, current_audit_id, entry)
            sync_linked_compatibility = preview.has_impact
            if preview.has_impact and not self._confirm_compatibility_impact_preview(preview):
                self.result_panel.show_text("Audit save canceled before updating linked compatibility rows.")
                return
        run_tool_background(
            self.result_panel,
            "audit_save_entry",
            "Save Audit Entry",
            lambda: self._save_audit_workflow(
                entry,
                allow_update=allow_update,
                create_followup_action=self.audit_followup_check.isChecked(),
                sync_linked_compatibility=sync_linked_compatibility,
            ),
            on_tool_result=lambda result: self._after_save_audit(result, current_audit_id),
            modifies_files=True,
            workbook_lock=True,
            progress_text="Saving audit...\nSkipping derived scans unless this edit requires them...",
        )

    def _save_audit_workflow(
        self,
        entry: dict[str, str],
        *,
        allow_update: bool,
        create_followup_action: bool,
        sync_linked_compatibility: bool | None = None,
    ):
        return save_audit_with_side_effects(
            self.config,
            entry,
            allow_update=allow_update,
            create_followup_action=create_followup_action,
            sync_linked_compatibility=sync_linked_compatibility,
        )

    def _insert_robot_info_summary(self, summary: str, robot_result) -> str:
        return insert_robot_info_summary(summary, robot_result)

    def _after_save_audit(self, result, audit_id: str) -> None:
        saved_audit_id = str(result.metrics.get("audit_id") or audit_id or "").strip()
        if result.success and saved_audit_id:
            self._reset_audit_form_fields(show_generated_message=False)
            discard_audit_draft(self.config.project_root)
            self._duplicated_press_value = None
            self._duplicated_tool_value = None
            self.refresh_audit_selector()
            if hasattr(self, "compatibility_source_combo"):
                self.refresh_compatibility_sources()
            event_started = time.perf_counter()
            try:
                get_event_bus().emit(
                    EVENT_AUDIT_SAVED,
                    {
                        "audit_id": saved_audit_id,
                        "row": result.metrics.get("row"),
                        "updated": result.metrics.get("updated"),
                        "compatibility_created": result.metrics.get("compatibility_created", 0),
                        "refresh_mode": "invalidate_only",
                    },
                    source="audit",
                )
            except Exception as exc:
                result.warnings.append(f"AuditSaved event listeners did not complete: {exc}")
            event_seconds = time.perf_counter() - event_started
            result.metrics["audit_save.event_dispatch_seconds"] = round(event_seconds, 3)
            timing = result.metrics.get("audit_save_timing")
            if isinstance(timing, dict):
                timing["event_dispatch_seconds"] = round(event_seconds, 3)
            event_detail = f"Events/UI: {event_seconds:.2f}s (cache invalidation only)."
            for index, detail in enumerate(result.details):
                if str(detail).startswith("Events/UI:"):
                    result.details[index] = event_detail
                    break
            else:
                result.details.append(event_detail)
            self.result_panel.show_result(result)

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
        self._machine_lookup_extra_note = ""
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
        robot_info_loaded = self._load_robot_info_fields(
            {field: self._field_value(widget) for field, widget in self.audit_fields.items()},
            force=False,
        )
        part_filled = False
        if len(result.part_options) == 1:
            self._lookup_part_index = 0
            option = result.part_options[0]
            part_filled = self._apply_part_suggestion(option, force=False)
        warnings = [*result.warnings, *self._lookup_conflict_warnings]
        lookup_message = self._lookup_status_message(result, robot_type_filled or robot_model_filled, part_filled or tool_filled, warnings)
        if self._machine_lookup_extra_note:
            lookup_message = f"{lookup_message} {self._machine_lookup_extra_note}"
        if robot_info_loaded:
            lookup_message = f"{lookup_message} Robot circuit info loaded from Robot_Info.xlsx."
        self.lookup_note_label.setText(lookup_message)
        self._set_capacity_choices(result.capacity_part_rows)
        self._set_machine_audit_matches([])
        self._log_machine_lookup(machine_text, result, warnings, result.errors, robot_type_filled, robot_model_filled, part_filled, tool_filled)

    def _load_or_offer_existing_audit_for_machine(self, machine_text: str) -> bool:
        self._machine_lookup_extra_note = ""
        machine_tokens = parse_machine_tokens(machine_text)
        if not machine_tokens:
            self._set_machine_audit_matches([])
            return False
        requested = set(machine_tokens)
        all_matches = [
            option
            for option in list_audit_options(self.config.project_root)
            if requested & set(self._audit_option_machine_tokens(option))
        ]
        matches = [
            option
            for option in all_matches
            if normalize_entry_type(option.row.get(ENTRY_TYPE_FIELD)) == ENTRY_TYPE_AUDITED
        ]
        compatible_matches = [
            option
            for option in all_matches
            if normalize_entry_type(option.row.get(ENTRY_TYPE_FIELD)) == ENTRY_TYPE_COMPATIBLE
        ]
        machine = ", ".join(machine_tokens)
        compatible_note = ""
        if compatible_matches:
            count = len(compatible_matches)
            noun = "entry" if count == 1 else "entries"
            compatible_note = f" Machine {machine} also has {count} compatible coverage {noun}."
        current_id = self._field_value(self.audit_fields["Audit ID"])
        if len(matches) == 1 and matches[0].audit_id == current_id and self._current_audit_mode == "edit":
            self._set_machine_audit_matches([])
            return False
        if len(matches) == 1:
            audit_id = matches[0].audit_id
            confirm_unsaved = not self.is_clean_new_form_or_lookup_only()
            self.load_existing_audit(
                audit_id,
                loaded_message=f"Existing physical audit found for Machine {machine}. Loaded {audit_id}.{compatible_note}",
                confirm_unsaved=confirm_unsaved,
            )
            return True
        if len(matches) > 1:
            self._set_machine_audit_matches(matches)
            self.lookup_note_label.setText(f"Multiple existing physical audits found for this machine. Select the audit to load.{compatible_note}")
            self.result_panel.show_text(
                "Multiple existing physical audits found for this machine. Select one from the audit match list; no audit was loaded automatically."
            )
            return True
        if compatible_matches:
            note = f"Machine {machine} has compatible coverage entries, but no physical audit yet. Continuing with a new physical audit."
            self._machine_lookup_extra_note = note
            self.lookup_note_label.setText(note)
            self._set_machine_audit_matches([])
            return False
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
            self.machine_audit_match_combo.addItem("Select existing physical audit to load...", None)
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
            self.load_existing_audit(
                str(audit_id),
                confirm_unsaved=not self.is_clean_new_form_or_lookup_only(),
            )

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
