from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QIntValidator
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSplitter,
        QStackedWidget,
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
    QApplication = QAbstractItemView = QCheckBox = QComboBox = QDialog = QFormLayout = QGroupBox = QHBoxLayout = (
        QLabel
    ) = QLineEdit = QMessageBox = QPushButton = QScrollArea = QSplitter = QStackedWidget = QTableWidget = (
        QTableWidgetItem
    ) = QTabWidget = QTextEdit = QVBoxLayout = QWidget = None

from app.event_bus import (
    EVENT_ANNOTATION_CHANGED,
    EVENT_AUDIT_SAVED,
    EVENT_COMPATIBILITY_REGENERATED,
    EVENT_OPEN_ITEMS_CHANGED,
    EVENT_ROBOT_INFO_UPDATED,
    get_event_bus,
)
from app.page_tasks import run_tool_background
from app.pages.annotation_suggestions_dialog import AnnotationSuggestionsDialog
from app.pages.audit_coach_panel import AuditCoachPanel
from app.pages.audit_compatibility_panel import build_compatibility_tab
from app.pages.audit_defaults_controller import AuditDefaultsController
from app.pages.audit_save_workflow import insert_robot_info_summary, save_audit_with_side_effects
from app.task_runner import TaskRequest, get_task_manager
from app.widgets.field_tag_button import FieldTagButton, FieldTagDialog
from app.widgets.tool_run_panel import ToolRunPanel
from core.action_items import add_action_item
from core.annotations.service import AnnotationService
from core.annotations.tag_colors import TAG_COLOR_PALETTE, highest_priority_tag
from core.annotations.targets import target_id_for
from core.audit.coach import calculate_audit_coach_summary, unknown_not_checked_value_for_field
from core.audit.compatibility_preview import CompatibilityImpactPreview, build_compatibility_impact_preview
from core.audit.completion import calculate_audit_completion
from core.audit.diff import build_audit_save_preview
from core.audit.drafts import discard_audit_draft, form_values_changed, load_audit_draft, save_audit_draft
from core.audit.guided import GuidedAuditStep, all_guided_audit_steps
from core.audit_compatibility import (
    MASTER_MACHINE_FIELDS,
    build_compatibility_candidates,
    create_compatibility_entries,
    find_existing_audits_for_machine,
    list_audit_options,
    list_audited_source_options,
    normalize_entry_type,
    parse_machine_tokens,
)
from core.audit_constants import (
    CYLINDER_COUNT_FIELD,
    CYLINDER_TYPE_DEFAULT,
    CYLINDER_TYPE_FIELD,
    ENTRY_TYPE_COMPATIBLE,
    ENTRY_TYPE_FIELD,
    IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_FIELDS,
    MANUAL_COMPLETION_OVERRIDE_TIMESTAMP_FIELD,
    MANUAL_COMPLETION_OVERRIDE_USER_FIELD,
)
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
from core.audit_field_registry import audit_section_groups as registry_audit_section_groups
from core.audit_field_registry import audit_sections as registry_audit_sections
from core.audit_field_rules import (
    PNEUMATIC_CIRCUIT_FIELDS,
    field_applies,
    is_meaningful_value,
    manual_completion_override_enabled,
    non_applicable_reason,
)
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
from core.paths import get_master_press_list_file, get_press_capacity_file, resolve_project_paths
from core.performance import log_performance, log_performance_event
from core.press_lookup import PressLookupResult, lookup_machine
from core.result import ToolResult
from core.robot_info import (
    ROBOT_INFO_AUDIT_FIELDS,
    ROBOT_INFO_SHEET,
    ROBOT_NOTES_FIELD,
    load_robot_info_for_audit_entry,
)

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
ROBOT_INFO_FIELDS = list(ROBOT_INFO_AUDIT_FIELDS)
ROBOT_INTERCHANGEABLE_CIRCUITS_FIELD = "Robot Interchangeable Circuits"
GRIPPER_UI_FIELDS = {GRIPPER_COUNT_FIELD, GRIPPER_TYPE_FIELD, GRIPPER_MODEL_FIELD}
ALWAYS_VISIBLE_AUDIT_FIELDS = {CYLINDER_COUNT_FIELD, CYLINDER_TYPE_FIELD}
_MACHINE_LOOKUP_RESULT_CACHE: dict[tuple[object, ...], dict[str, object]] = {}


def workbook_to_ui_value(value, field: str = "") -> str:
    text = "" if value is None else str(value)
    if field == CYLINDER_TYPE_FIELD and (not text.strip() or text.strip().upper() == NA_VALUE):
        return ""
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


def _lookup_file_signature(path: Path) -> tuple[str, bool, int, int]:
    try:
        target = path.resolve()
    except OSError:
        target = path
    try:
        stat = target.stat()
    except OSError:
        return str(target), False, 0, 0
    return str(target), True, stat.st_mtime_ns, stat.st_size


def _machine_lookup_cache_key(project_root: str | Path, machine_text: str) -> tuple[object, ...]:
    root = Path(project_root)
    paths = resolve_project_paths(root)
    primary_master = get_master_press_list_file(root)
    primary_capacity = get_press_capacity_file(root)
    legacy_master = paths.legacy_reference_data / primary_master.name
    legacy_capacity = paths.legacy_reference_data / primary_capacity.name
    try:
        normalized_machine = ",".join(parse_machine_tokens(machine_text)) or str(machine_text).strip().casefold()
    except Exception:
        normalized_machine = str(machine_text).strip().casefold()
    return (
        str(root.resolve() if root.exists() else root),
        normalized_machine,
        _lookup_file_signature(paths.master_workbook),
        _lookup_file_signature(paths.robot_info_workbook),
        _lookup_file_signature(primary_master),
        _lookup_file_signature(primary_capacity),
        _lookup_file_signature(legacy_master),
        _lookup_file_signature(legacy_capacity),
    )


@dataclass(frozen=True)
class FieldInfo:
    name: str
    label: str


def get_empty_only_visible_fields(
    row_data, form_fields, current_visibility_rules, label_for_field=None
) -> list[FieldInfo]:
    fields: list[FieldInfo] = []
    for field in form_fields:
        if not current_visibility_rules(field):
            continue
        if _is_empty_workbook_value(row_data.get(field, "")):
            label = label_for_field(field) if label_for_field else field
            fields.append(FieldInfo(name=field, label=label))
    return fields


AUDIT_SECTIONS = registry_audit_sections()
AUDIT_SECTION_GROUPS = registry_audit_section_groups()

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


def _more_text(values, shown: int) -> str:
    remaining = max(0, len(values) - shown)
    return "" if remaining <= 0 else f"...and {remaining} more."


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


_AUDIT_STARTUP_LOG_LOCK = threading.Lock()


def _write_audit_startup_log(
    project_root: str, event_name: str, duration_seconds: float, payload: dict[str, object]
) -> None:
    with _AUDIT_STARTUP_LOG_LOCK:
        log_activity_event(project_root, event_name, payload)
        log_performance(
            project_root,
            event_name,
            duration_seconds,
            source="audit_page",
            page_tool="audit",
            details=payload,
            success=bool(payload.get("success", True)),
            error_count=1 if payload.get("error") else 0,
        )


@dataclass(frozen=True)
class ExistingAuditSelection:
    action: str
    audit_id: str = ""


class ExistingMachineAuditsDialog(QDialog):
    ACTION_CONTINUE = "continue_existing"
    ACTION_START_NEW = "start_new"
    ACTION_CANCEL = "cancel"
    COLUMNS = ["Audit ID", "Audit Date", "Tool #", "EOAT Type", "Status", "Priority", "Entry Type", "Completion %"]

    def __init__(self, machine_number: str, matches, parent=None):
        super().__init__(parent)
        self._selection = ExistingAuditSelection(self.ACTION_CANCEL)
        self.setWindowTitle("Existing Audits Found")
        layout = QVBoxLayout(self)

        message = QLabel(
            f"Machine {machine_number} already has existing audit records. "
            "Choose one to continue, or start a new audit for this machine."
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        note = QLabel("Starting a new audit keeps the machine context but does not copy old EOAT/tool data.")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.audit_table = QTableWidget(0, len(self.COLUMNS))
        self.audit_table.setHorizontalHeaderLabels(self.COLUMNS)
        self.audit_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.audit_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.audit_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.audit_table.setAlternatingRowColors(True)
        self._populate_rows(matches)
        layout.addWidget(self.audit_table)

        button_row = QHBoxLayout()
        self.continue_button = QPushButton("Continue Selected Audit")
        self.start_new_button = QPushButton("Start New Audit for This Machine")
        self.cancel_button = QPushButton("Cancel")
        self.continue_button.clicked.connect(self._continue_selected)
        self.start_new_button.clicked.connect(self._start_new)
        self.cancel_button.clicked.connect(self.reject)
        button_row.addStretch(1)
        button_row.addWidget(self.continue_button)
        button_row.addWidget(self.start_new_button)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        if self.audit_table.rowCount():
            self.audit_table.selectRow(0)
        self._update_continue_enabled()
        self.audit_table.itemSelectionChanged.connect(self._update_continue_enabled)
        self.resize(900, 360)

    def _populate_rows(self, matches) -> None:
        self.audit_table.setRowCount(len(matches))
        for row_index, option in enumerate(matches):
            row = dict(option.row)
            values = [
                option.audit_id,
                row.get("Audit Date", ""),
                row.get("Tool #", ""),
                row.get("EOAT Type", ""),
                row.get("Status", ""),
                row.get("Priority", ""),
                normalize_entry_type(row.get(ENTRY_TYPE_FIELD)),
                _completion_percent_label(row),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                if col_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, option.audit_id)
                self.audit_table.setItem(row_index, col_index, item)
        self.audit_table.resizeColumnsToContents()

    def _selected_audit_id(self) -> str:
        selected = self.audit_table.selectionModel().selectedRows()
        if not selected:
            return ""
        item = self.audit_table.item(selected[0].row(), 0)
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or item.text() or "").strip()

    def _update_continue_enabled(self) -> None:
        self.continue_button.setEnabled(bool(self._selected_audit_id()))

    def _continue_selected(self) -> None:
        audit_id = self._selected_audit_id()
        if not audit_id:
            return
        self._selection = ExistingAuditSelection(self.ACTION_CONTINUE, audit_id)
        self.accept()

    def _start_new(self) -> None:
        self._selection = ExistingAuditSelection(self.ACTION_START_NEW)
        self.accept()

    def selection(self) -> ExistingAuditSelection:
        return self._selection


def _completion_percent_label(row: dict[str, object]) -> str:
    try:
        completion = calculate_audit_completion(row, AUDIT_SECTIONS, mode="edit")
    except Exception:
        return ""
    return f"{completion.percent_complete}%"


class AuditPage(QWidget):
    def __init__(self, config, parent=None):
        page_open_started = time.perf_counter()
        super().__init__(parent)
        self.config = config
        self._page_open_started = page_open_started
        self._startup_timings: dict[str, float] = {}
        self._suppress_detailed_startup_logging = False
        self._log_startup_event("audit_page_shell_started", 0.0)
        path_started = time.perf_counter()
        resolve_project_paths(self.config.project_root)
        self._startup_path_resolution_seconds = self._record_startup_timing("path_resolution", path_started)
        defaults_started = time.perf_counter()
        self.defaults_controller = AuditDefaultsController(config)
        self._record_startup_timing("AuditDefaultsController", defaults_started)
        self.current_lookup_result: PressLookupResult | None = None
        self._lookup_part_index: int | None = None
        self._lookup_conflict_warnings: list[str] = []
        self._editing_audit_id: str | None = None
        self._duplicated_press_value: str | None = None
        self._duplicated_tool_value: str | None = None
        self._audit_field_labels = {}
        self._loading_audit = False
        self._initializing_form = True
        self._hydrating_form = False
        self._applying_defaults = False
        self._autofilling_fields = False
        self._suppress_dirty_tracking = True
        self._loaded_empty_only_fields: set[str] | None = None
        self._current_audit_mode = "new"
        self._current_loaded_audit_id: str | None = None
        self._programmatic_field_update = False
        self._dirty = False
        self._dirty_fields: set[str] = set()
        self._save_requested = False
        self._save_in_progress = False
        self._save_navigation_requested = False
        self._pending_save_snapshot: dict[str, str] | None = None
        self._pending_save_started_at: str | None = None
        self._pending_completed_update_context: dict[str, object] | None = None
        self._pending_manual_completion_override = False
        self._last_saved_snapshot: dict[str, str] = {}
        self._changeover_user_modified = False
        self._generated_audit_ids: set[str] = set()
        self._machine_lookup_extra_note = ""
        self._part_present_autofilled_sensor_fields: set[str] = set()
        self._cylinder_type_autofilled = False
        annotation_started = time.perf_counter()
        self.annotation_service = AnnotationService(config.project_root, initialize=False)
        self._record_startup_timing("AnnotationService_deferred", annotation_started)
        self._annotation_service_generation = 0
        self._annotation_service_initializing = False
        self._annotation_service_ready = False
        self._field_tag_buttons = {}
        self._audit_field_rows = {}
        self._audit_field_sections = {}
        self._audit_field_scroll_areas = {}
        self._audit_field_group_keys = {}
        self._audit_field_visibility_state = {}
        self._guided_step_tables = {}
        self._guided_step_labels = {}
        self._audit_group_boxes = {}
        self._audit_group_fields = {}
        self._navigation_highlight_row = None
        self._suppress_clear_confirm_this_session = False
        self._audit_form_baseline: dict[str, str] = {}
        self._last_clean_snapshot: dict[str, str] = {}
        self._clean_new_audit_form_values: dict[str, str] = {}
        self._draft_recovery_checked = False
        self._draft_check_generation = 0
        self._draft_check_loading = False
        self._audit_index_generation = 0
        self._audit_indexes_loading = False
        self._audit_indexes_loaded = False
        self._guided_ui_built = False
        self._audit_coach_refresh_count = 0
        self._audit_coach_refresh_pending = False
        self._manual_completion_override_data: dict[str, str] = {}
        self._machine_lookup_generation = 0
        self._pending_machine_lookup_text = ""
        self._pending_machine_lookup_allow_existing_audit_prompt = True
        self._suppress_machine_audit_selection_dialog = False
        self._machine_audit_selection_in_progress = False
        self._starting_new_audit_for_machine = False
        self._loading_existing_audit_from_machine_dialog = False
        self._machine_audit_prompt_suppressed_for_machine: str | None = None
        self._machine_audit_recent_decision_suppresses_next_lookup_for_machine: str | None = None
        self._machine_audit_recent_decision_action = ""
        self._machine_lookup_timer = QTimer(self) if QTimer is not None else None
        if self._machine_lookup_timer is not None:
            self._machine_lookup_timer.setSingleShot(True)
            self._machine_lookup_timer.setInterval(200)
            self._machine_lookup_timer.timeout.connect(self._start_machine_lookup_request)

        layout = QVBoxLayout(self)
        heading = QLabel("EOAT Audit")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        self.main_tabs = QTabWidget()
        tabs = self.main_tabs
        audit_tab_started = time.perf_counter()
        tabs.addTab(self._build_audit_tab(), "Audit Entry")
        self._record_startup_timing("build_audit_tab", audit_tab_started)
        compatibility_tab_started = time.perf_counter()
        tabs.addTab(self._build_compatibility_tab(), "Compatibility Entry")
        self._record_startup_timing("build_compatibility_tab", compatibility_tab_started)
        interview_tab_started = time.perf_counter()
        tabs.addTab(self._build_interview_tab(), "Interview Notes")
        self._record_startup_timing("build_interview_tab", interview_tab_started)

        output_started = time.perf_counter()
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
        self._record_startup_timing("output_panel_construction", output_started)
        self._initializing_form = False
        self._suppress_dirty_tracking = False
        self._recalculate_dirty_state(reason="initial_form_ready")
        total_shell_seconds = time.perf_counter() - page_open_started
        self._log_startup_event(
            "audit_page_shell_ready",
            total_shell_seconds,
            timings={key: round(value, 4) for key, value in self._startup_timings.items()},
            workbook_indexes_deferred=True,
            annotation_database_deferred=True,
            guided_ui_deferred=True,
        )
        if QTimer is not None:
            QTimer.singleShot(250, self._load_lazy_audit_indexes)
            QTimer.singleShot(450, self._start_background_draft_check)
            QTimer.singleShot(750, self._start_annotation_service_initialization)

    def _record_startup_timing(self, step: str, started: float) -> float:
        elapsed = time.perf_counter() - started
        self._startup_timings[step] = elapsed
        return elapsed

    def _log_startup_event(self, event_name: str, duration_seconds: float, **details: object) -> None:
        payload = {"duration_seconds": round(duration_seconds, 4), **details}
        threading.Thread(
            target=_write_audit_startup_log,
            args=(str(self.config.project_root), event_name, duration_seconds, payload),
            daemon=True,
        ).start()

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

    def _current_audit_metadata_values(self) -> dict[str, str]:
        return {
            field: value for field, value in self._manual_completion_override_data.items() if str(value or "").strip()
        }

    def _current_audit_coach_values(self, values: dict[str, str] | None = None) -> dict[str, str]:
        entry = dict(values if values is not None else self._current_audit_form_values())
        entry.update(self._current_audit_metadata_values())
        return entry

    def _connect_audit_coach_refresh(self, widget) -> None:
        if isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(self._schedule_audit_coach_refresh)
        elif isinstance(widget, QTextEdit) or isinstance(widget, QLineEdit):
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
        QTimer.singleShot(75, self._refresh_audit_coach)

    def _refresh_audit_coach(self, values: dict[str, str] | None = None) -> None:
        started = time.perf_counter()
        self._audit_coach_refresh_pending = False
        panel = getattr(self, "audit_coach_panel", None)
        if panel is None or not hasattr(self, "audit_fields"):
            return
        summary = calculate_audit_coach_summary(
            self._current_audit_coach_values(values), AUDIT_SECTIONS, mode=self._current_audit_mode
        )
        panel.refresh(summary)
        self._refresh_guided_audit(values=values)
        elapsed = time.perf_counter() - started
        self._audit_coach_refresh_count += 1
        if not getattr(self, "_suppress_detailed_startup_logging", False) and (
            self._audit_coach_refresh_count <= 3 or elapsed >= 0.25
        ):
            log_performance(
                self.config.project_root,
                "audit_page_audit_coach_refresh",
                elapsed,
                source="audit_page",
                page_tool="audit",
                details={
                    "field_count": len(self.audit_fields),
                    "refresh_count": self._audit_coach_refresh_count,
                    "guided_ui_built": self._guided_ui_built,
                },
            )

    def _refresh_guided_audit(self, values: dict[str, str] | None = None, *, force_io_preview: bool = False) -> None:
        if not getattr(self, "_guided_step_tables", None) or not hasattr(self, "audit_fields"):
            return
        entry = self._current_audit_coach_values(values)
        completion = calculate_audit_completion(entry, AUDIT_SECTIONS, mode=self._current_audit_mode)
        statuses = {status.field: status for section in completion.sections for status in section.fields}
        for step in all_guided_audit_steps():
            table = self._guided_step_tables.get(step.id)
            label = self._guided_step_labels.get(step.id)
            if table is None or label is None:
                continue
            step_statuses = [statuses.get(field) for field in step.fields]
            actionable = [status for status in step_statuses if status is not None and status.is_actionable]
            applicable_count = sum(1 for status in step_statuses if status is not None and status.applies)
            label.setText(f"{step.title}: {len(actionable)} action item(s), {applicable_count} applicable field(s).")
            table.blockSignals(True)
            try:
                table.setRowCount(0)
                if step.id == "final_review_save_impact":
                    self._populate_guided_final_review(table, completion, include_io_preview=force_io_preview)
                else:
                    self._populate_guided_step_table(table, step, entry, statuses)
                table.resizeColumnsToContents()
            finally:
                table.blockSignals(False)

    def _populate_guided_step_table(
        self, table: QTableWidget, step: GuidedAuditStep, entry: dict[str, str], statuses: dict[str, object]
    ) -> None:
        for field in step.fields:
            status = statuses.get(field)
            visible = bool(field in ALWAYS_VISIBLE_AUDIT_FIELDS or field_applies(entry, field))
            state = status.state if status is not None else ("verified_complete" if entry.get(field) else "missing")
            reason = status.reason if status is not None else ""
            display_state = "hidden" if not visible else state
            self._append_guided_row(table, field, display_state, entry.get(field, ""), reason)

    def _populate_guided_final_review(self, table: QTableWidget, completion, *, include_io_preview: bool) -> None:
        entry = self.collect_complete_audit_form_state()
        robot_before = {}
        if include_io_preview:
            try:
                robot_before = load_robot_info_for_audit_entry(self.config.project_root, entry) or {}
            except Exception:
                robot_before = {}
        preview = build_audit_save_preview(
            self._audit_form_baseline,
            entry,
            smart_defaulted_fields=self._part_present_autofilled_sensor_fields,
            robot_before=robot_before,
        )
        self._append_guided_row(table, "Completion", f"{completion.percent_complete}%", "", completion.next_best_reason)
        self._append_guided_row(
            table,
            "Missing fields",
            str(len(completion.missing_fields)),
            ", ".join(completion.missing_fields[:8]),
            _more_text(completion.missing_fields, 8),
        )
        self._append_guided_row(
            table,
            "Unknown / Not Checked",
            str(len(completion.unknown_not_checked_fields)),
            ", ".join(completion.unknown_not_checked_fields[:8]),
            _more_text(completion.unknown_not_checked_fields, 8),
        )
        self._append_guided_row(
            table,
            "Warnings",
            str(len(completion.findings)),
            "; ".join(completion.findings[:5]),
            _more_text(completion.findings, 5),
        )
        self._append_guided_row(
            table,
            "Defaults",
            str(len(preview.smart_defaulted_fields)),
            ", ".join(preview.smart_defaulted_fields),
            "Autofilled fields are marked as smart-defaulted in the save preview.",
        )
        self._append_guided_row(
            table,
            "Robot info updates",
            str(len(preview.robot_info_changes)),
            ", ".join(change.field for change in preview.robot_info_changes),
            "Robot-side fields save to Robot_Info.xlsx when meaningful changes exist.",
        )
        compatibility_text = "Unknown until checked."
        compatibility_reason = "Linked compatibility impact has not been checked for this preview."
        if include_io_preview:
            compatibility_preview = self._safe_compatibility_preview(entry)
            if compatibility_preview is not None:
                compatibility_text = f"{compatibility_preview.compatible_row_count} linked row(s)"
                compatibility_reason = (
                    "Linked compatibility rows may be updated."
                    if compatibility_preview.has_impact
                    else "No linked compatibility row update is expected from the current saved source."
                )
        self._append_guided_row(
            table,
            "Compatibility impact",
            compatibility_text,
            ", ".join(preview.compatibility_impact_fields[:8]),
            compatibility_reason,
        )
        self._append_guided_row(
            table,
            "Photo warnings",
            str(len(preview.photo_warnings)),
            "; ".join(preview.photo_warnings),
            "Photo evidence warnings come from audit completion and save preview checks.",
        )

    def _append_guided_row(self, table: QTableWidget, field: str, status: str, value: str, reason: str) -> None:
        row = table.rowCount()
        table.insertRow(row)
        for column, text in enumerate([field, status, value, reason]):
            table.setItem(row, column, QTableWidgetItem(str(text or "")))

    def _safe_compatibility_preview(self, entry: dict[str, str]) -> CompatibilityImpactPreview | None:
        audit_id = str(entry.get("Audit ID") or "").strip()
        if not audit_id:
            return None
        try:
            return build_compatibility_impact_preview(self.config.project_root, audit_id, entry)
        except Exception:
            return None

    def _log_lifecycle_event(self, event_name: str, payload: dict[str, object]) -> None:
        if getattr(self, "_suppress_detailed_startup_logging", False):
            return
        log_activity_event(self.config.project_root, event_name, payload)

    def _machine_audit_machine_key(self, machine_text: str) -> str:
        return ", ".join(parse_machine_tokens(machine_text)) or str(machine_text or "").strip()

    def _machine_audit_same_machine(self, left: str | None, right: str | None) -> bool:
        left_key = self._machine_audit_machine_key(str(left or ""))
        right_key = self._machine_audit_machine_key(str(right or ""))
        return bool(left_key and right_key and left_key == right_key)

    def _log_machine_audit_selection_event(self, event_name: str, machine_number: str, **details: object) -> None:
        payload = {
            "machine_number": self._machine_audit_machine_key(machine_number),
            **details,
        }
        log_activity_event(self.config.project_root, event_name, payload)
        log_performance_event(
            self.config.project_root,
            event_name,
            0.0,
            source="audit_page",
            page_tool="audit",
            details=payload,
        )

    def _machine_lookup_programmatic_suppression_reason(self) -> str:
        if self._loading_existing_audit_from_machine_dialog or self._loading_audit:
            return "loading_existing_audit"
        if self._starting_new_audit_for_machine:
            return "starting_new_audit_for_machine"
        if self._suppress_machine_audit_selection_dialog:
            return "machine_audit_selection_dialog_suppressed"
        if self._hydrating_form:
            return "hydrating_form"
        if self._programmatic_field_update:
            return "programmatic_field_update"
        if self._applying_defaults:
            return "applying_defaults"
        if self._autofilling_fields:
            return "machine_lookup_autofill"
        if self._initializing_form:
            return "initializing_form"
        return ""

    def _machine_audit_selection_suppression_reason(
        self,
        machine_text: str,
        *,
        user_confirmed: bool,
        allow_existing_audit_prompt: bool,
    ) -> str:
        if not user_confirmed:
            return "machine_not_user_confirmed"
        if not allow_existing_audit_prompt:
            return "existing_audit_prompt_disabled_for_lookup"
        programmatic_reason = self._machine_lookup_programmatic_suppression_reason()
        if programmatic_reason:
            return programmatic_reason
        if self._machine_audit_selection_in_progress:
            return "machine_audit_selection_dialog_already_open"
        if self._machine_audit_same_machine(self._machine_audit_prompt_suppressed_for_machine, machine_text):
            return "machine_prompt_suppressed_for_selected_machine"
        return ""

    def _suppress_next_machine_lookup_after_audit_workflow(self, machine_text: str, action: str) -> None:
        machine = self._machine_audit_machine_key(machine_text)
        if not machine:
            return
        self._machine_audit_recent_decision_suppresses_next_lookup_for_machine = machine
        self._machine_audit_recent_decision_action = action

    def _consume_recent_machine_audit_lookup_suppression(self, machine_text: str) -> bool:
        machine = self._machine_audit_recent_decision_suppresses_next_lookup_for_machine
        if not self._machine_audit_same_machine(machine, machine_text):
            return False
        self._machine_audit_recent_decision_suppresses_next_lookup_for_machine = None
        action = self._machine_audit_recent_decision_action
        self._machine_audit_recent_decision_action = ""
        self._log_machine_audit_selection_event(
            "machine_audit_selection_suppressed",
            machine_text,
            reason="recent_machine_audit_decision_already_handled",
            action=action,
        )
        return True

    def _clear_recent_machine_audit_decision_if_machine_changed(self, machine_text: str) -> None:
        machine = self._machine_audit_recent_decision_suppresses_next_lookup_for_machine
        if machine and not self._machine_audit_same_machine(machine, machine_text):
            self._machine_audit_recent_decision_suppresses_next_lookup_for_machine = None
            self._machine_audit_recent_decision_action = ""

    def _set_dirty_state(
        self,
        dirty: bool,
        *,
        reason: str,
        field: str = "",
        user_driven: bool = False,
        programmatic: bool | None = None,
    ) -> None:
        dirty = bool(dirty)
        if self._dirty == dirty:
            return
        self._dirty = dirty
        self._log_lifecycle_event(
            "audit_dirty_state_changed",
            {
                "audit_id": self._field_value(self.audit_fields.get("Audit ID"))
                if hasattr(self, "audit_fields")
                else "",
                "dirty": dirty,
                "reason": reason,
                "field": field,
                "user_driven": bool(user_driven),
                "programmatic": bool(self._programmatic_field_update if programmatic is None else programmatic),
                "hydrating_form": bool(self._hydrating_form or self._loading_audit),
                "initializing_form": bool(self._initializing_form),
                "applying_defaults": bool(self._applying_defaults),
                "autofilling_fields": bool(self._autofilling_fields),
                "dirty_tracking_suppressed": bool(self._suppress_dirty_tracking),
                "save_requested": bool(self._save_requested),
                "save_in_progress": bool(self._save_in_progress),
            },
        )

    def _recalculate_dirty_state(
        self,
        *,
        reason: str,
        field: str = "",
        user_driven: bool = False,
        ignored_fields: set[str] | None = None,
    ) -> bool:
        current = self._current_audit_form_values()
        baseline = dict(self._audit_form_baseline)
        for ignored_field in ignored_fields or set():
            current.pop(ignored_field, None)
            baseline.pop(ignored_field, None)
        dirty = form_values_changed(current, baseline)
        if ignored_fields is None:
            self._set_dirty_state(dirty, reason=reason, field=field, user_driven=user_driven)
        return dirty

    def _on_audit_field_changed(self, field: str, *_args) -> None:
        programmatic = (
            self._programmatic_field_update
            or self._hydrating_form
            or self._loading_audit
            or self._initializing_form
            or self._applying_defaults
            or self._autofilling_fields
            or self._suppress_dirty_tracking
        )
        if programmatic:
            return
        self._dirty_fields.add(field)
        if field == CYLINDER_TYPE_FIELD:
            self._cylinder_type_autofilled = False
        if field in {CYLINDER_COUNT_FIELD, CYLINDER_TYPE_FIELD}:
            self._apply_cylinder_type_default()
        self._recalculate_dirty_state(reason="field_changed", field=field, user_driven=True)

    def _apply_cylinder_type_default(self) -> None:
        count_widget = self.audit_fields.get(CYLINDER_COUNT_FIELD) if hasattr(self, "audit_fields") else None
        type_widget = self.audit_fields.get(CYLINDER_TYPE_FIELD) if hasattr(self, "audit_fields") else None
        if count_widget is None or type_widget is None:
            return
        count_in_use = is_meaningful_value(self._field_value(count_widget))
        cylinder_type = self._field_value(type_widget)
        if count_in_use and cylinder_type.upper() in {"", NA_VALUE}:
            self._cylinder_type_autofilled = True
            self._set_field_value(type_widget, CYLINDER_TYPE_DEFAULT)
        elif not count_in_use and self._cylinder_type_autofilled and cylinder_type == CYLINDER_TYPE_DEFAULT:
            self._set_field_value(type_widget, "")
            self._cylinder_type_autofilled = False

    def _begin_hydrating_form(self, reason: str = "hydrate_form") -> tuple[bool, bool, bool]:
        previous_hydrating = self._hydrating_form
        previous_programmatic = self._programmatic_field_update
        previous_suppressed = self._suppress_dirty_tracking
        self._hydrating_form = True
        self._programmatic_field_update = True
        self._suppress_dirty_tracking = True
        self._log_lifecycle_event(
            "audit_dirty_tracking_suppressed",
            {
                "reason": reason,
                "audit_id": self._field_value(self.audit_fields.get("Audit ID"))
                if hasattr(self, "audit_fields")
                else "",
            },
        )
        return previous_hydrating, previous_programmatic, previous_suppressed

    def _end_hydrating_form(self, previous_state: tuple[bool, bool, bool], reason: str = "hydrate_form") -> None:
        previous_hydrating, previous_programmatic, previous_suppressed = previous_state
        self._hydrating_form = previous_hydrating
        self._programmatic_field_update = previous_programmatic
        self._suppress_dirty_tracking = previous_suppressed
        self._log_lifecycle_event(
            "audit_dirty_tracking_restored",
            {
                "reason": reason,
                "audit_id": self._field_value(self.audit_fields.get("Audit ID"))
                if hasattr(self, "audit_fields")
                else "",
            },
        )

    def _mark_audit_form_baseline(self, _reason: str = "", *, clean_new_form: bool = False) -> None:
        values = self._current_audit_form_values()
        self._audit_form_baseline = dict(values)
        self._last_clean_snapshot = dict(values)
        self._last_saved_snapshot = dict(values)
        self._dirty_fields.clear()
        self._set_dirty_state(False, reason=_reason or "baseline_marked")
        self._log_lifecycle_event(
            "audit_clean_snapshot_created",
            {
                "audit_id": values.get("Audit ID", ""),
                "reason": _reason,
                "field_count": len(values),
            },
        )
        if clean_new_form:
            self._clean_new_audit_form_values = dict(values)

    def has_unsaved_changes(self, *, ignored_fields: set[str] | None = None) -> bool:
        return self._recalculate_dirty_state(reason="dirty_recalculated", ignored_fields=ignored_fields)

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

    def _assign_startup_audit_id(self) -> str:
        compact = date.today().isoformat().replace("-", "")
        audit_id = f"AUD-{compact}-P{uuid.uuid4().hex[:10].upper()}"
        self._generated_audit_ids.add(audit_id)
        self._set_field_value(self.audit_fields["Audit ID"], audit_id)
        return audit_id

    def _save_current_audit_draft(self) -> str:
        values = self._current_audit_form_values()
        existing_draft = load_audit_draft(self.config.project_root)
        changed_fields = frozenset(self._dirty_fields)
        saved_started = time.perf_counter()
        path = save_audit_draft(
            self.config.project_root,
            audit_id=values.get("Audit ID", ""),
            mode=self._current_audit_mode,
            form_values=values,
            baseline_values=values,
            changed_fields=changed_fields,
        )
        blank_count = sum(1 for value in values.values() if not str(value or "").strip())
        self._log_lifecycle_event(
            "audit_draft_saved",
            {
                "audit_id": values.get("Audit ID", ""),
                "draft_path": str(path),
                "field_count": len(values),
                "blank_field_count": blank_count,
                "full_snapshot": set(values) == set(self.audit_fields),
                "merged_with_existing_draft": existing_draft is not None,
                "changed_field_count": len(changed_fields),
                "duration_seconds": round(time.perf_counter() - saved_started, 3),
            },
        )
        self._draft_recovery_checked = True
        self._mark_audit_form_baseline("draft_saved")
        return str(path)

    def save_current_audit_draft(self) -> None:
        path = self._save_current_audit_draft()
        if hasattr(self, "result_panel"):
            self.result_panel.show_text(f"Saved local audit draft.\n\nDraft file: {path}")

    def resume_saved_audit_draft(self) -> None:
        draft = load_audit_draft(self.config.project_root)
        if draft is None:
            if hasattr(self, "result_panel"):
                self.result_panel.show_text("No saved audit draft was found.")
            return
        self._restore_audit_draft(draft)

    def discard_saved_audit_draft(self) -> None:
        removed = discard_audit_draft(self.config.project_root)
        if hasattr(self, "result_panel"):
            message = "Discarded saved audit draft." if removed else "No saved audit draft was found."
            self.result_panel.show_text(message)

    def _start_background_draft_check(self) -> None:
        if hasattr(self, "isVisible") and not self.isVisible():
            return
        if self._draft_recovery_checked:
            return
        if self._draft_check_loading:
            return
        self._draft_check_loading = True
        self._draft_check_generation += 1
        generation = self._draft_check_generation
        project_root = str(self.config.project_root)
        started = time.perf_counter()
        self._log_startup_event("audit_page_draft_check_started", 0.0)

        def _load_draft() -> object:
            return load_audit_draft(project_root)

        get_task_manager().run_task(
            TaskRequest(
                id=f"audit_draft_check_{generation}",
                name="Audit Draft Check",
                category="page_refresh",
                callable=_load_draft,
            ),
            on_finished=lambda result,
            expected_generation=generation,
            started_at=started: self._apply_draft_check_result(
                result,
                expected_generation,
                started_at,
            ),
        )

    def _apply_draft_check_result(self, task_result, expected_generation: int, started_at: float) -> None:
        if expected_generation != self._draft_check_generation:
            return
        self._draft_check_loading = False
        self._draft_recovery_checked = True
        self._log_startup_event(
            "audit_page_draft_check_ready",
            time.perf_counter() - started_at,
            success=task_result.ok,
            has_draft=bool(task_result.ok and task_result.result_data is not None),
            error=task_result.error,
        )
        if not task_result.ok:
            return
        self._offer_draft_recovery(task_result.result_data)

    def _start_annotation_service_initialization(self) -> None:
        if self._annotation_service_ready or self._annotation_service_initializing:
            return
        self._annotation_service_initializing = True
        self._annotation_service_generation += 1
        generation = self._annotation_service_generation
        project_root = str(self.config.project_root)
        db_path = str(self.annotation_service.db_path)
        started = time.perf_counter()

        def _initialize_annotations() -> dict[str, str]:
            service = AnnotationService(project_root, initialize=True)
            return {"db_path": str(service.db_path)}

        get_task_manager().run_task(
            TaskRequest(
                id=f"audit_annotation_init_{generation}",
                name="Audit Annotation Startup",
                category="page_refresh",
                callable=_initialize_annotations,
            ),
            on_finished=lambda result,
            expected_generation=generation,
            expected_db_path=db_path,
            started_at=started: self._apply_annotation_init_result(
                result,
                expected_generation,
                expected_db_path,
                started_at,
            ),
        )

    def _apply_annotation_init_result(
        self, task_result, expected_generation: int, expected_db_path: str, started_at: float
    ) -> None:
        if expected_generation != self._annotation_service_generation:
            return
        self._annotation_service_initializing = False
        self._annotation_service_ready = bool(task_result.ok)
        if task_result.ok and str((task_result.result_data or {}).get("db_path") or "") == expected_db_path:
            self.annotation_service.mark_initialized()
        self._log_startup_event(
            "audit_page_annotation_service_initialized",
            time.perf_counter() - started_at,
            success=task_result.ok,
            db_path=expected_db_path,
            error=task_result.error,
        )

    def _offer_draft_recovery(self, draft=None) -> None:
        if hasattr(self, "isVisible") and not self.isVisible():
            return
        if draft is None:
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
        restore_started = time.perf_counter()
        previous_dialog_suppression = self._suppress_machine_audit_selection_dialog
        self._suppress_machine_audit_selection_dialog = True
        previous_state = self._begin_hydrating_form("restore_draft")
        try:
            self._set_manual_completion_override_metadata({})
            for field, value in draft.form_values.items():
                widget = self.audit_fields.get(field)
                if widget is not None:
                    self._set_field_value(widget, value)
            self._current_audit_mode = draft.mode or "new"
            self._editing_audit_id = draft.audit_id if self._current_audit_mode == "edit" else None
            self._current_loaded_audit_id = self._editing_audit_id
            self._loaded_empty_only_fields = None
            self._cylinder_type_autofilled = False
            self._apply_cylinder_type_default()
            self.audit_view_mode_combo.blockSignals(True)
            self.audit_view_mode_combo.setCurrentText("Full Audit")
            self.audit_view_mode_combo.setEnabled(False)
            self.audit_view_mode_combo.blockSignals(False)
            self._set_audit_selector_text(draft.audit_id)
            self._update_audit_field_visibility()
            self._refresh_field_tag_indicators()
        finally:
            self._end_hydrating_form(previous_state, "restore_draft")
            self._suppress_machine_audit_selection_dialog = previous_dialog_suppression
        self._mark_audit_form_baseline("draft_restored")
        self._suppress_next_machine_lookup_after_audit_workflow(
            self._field_value(self.audit_fields.get("Press/Machine #")),
            "restore_draft",
        )
        self._log_lifecycle_event(
            "audit_draft_restored",
            {
                "audit_id": draft.audit_id,
                "field_count": len(draft.form_values),
                "duration_seconds": round(time.perf_counter() - restore_started, 3),
            },
        )
        if hasattr(self, "result_panel"):
            self.result_panel.show_text(f"Restored local audit draft {draft.audit_id or '(blank audit ID)'}.")

    def _confirm_unsaved_audit_changes(self, action: str, *, destination_page: str | None = None) -> bool:
        dirty = self.has_unsaved_changes()
        if self._save_requested or self._save_in_progress:
            self._save_navigation_requested = True
            self._log_lifecycle_event(
                "audit_navigation_guard",
                {
                    "destination_page": destination_page or "",
                    "action": action,
                    "dirty": dirty,
                    "save_requested": self._save_requested,
                    "save_in_progress": self._save_in_progress,
                    "prompt_shown": False,
                    "reason": "save_already_requested",
                },
            )
            return True
        if not dirty:
            self._log_lifecycle_event(
                "audit_navigation_guard",
                {
                    "destination_page": destination_page or "",
                    "action": action,
                    "dirty": False,
                    "save_requested": self._save_requested,
                    "save_in_progress": self._save_in_progress,
                    "prompt_shown": False,
                    "reason": "clean_form",
                },
            )
            return True
        if QMessageBox is None:
            self._save_current_audit_draft()
            self._log_lifecycle_event(
                "audit_navigation_guard",
                {
                    "destination_page": destination_page or "",
                    "action": action,
                    "dirty": dirty,
                    "save_requested": self._save_requested,
                    "save_in_progress": self._save_in_progress,
                    "prompt_shown": False,
                    "reason": "message_box_unavailable_saved_draft",
                },
            )
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved Audit Changes")
        box.setText("The current audit form has unsaved changes.")
        box.setInformativeText(f"Save a local draft before you {action}, discard the on-screen changes, or cancel.")
        save_draft_button = box.addButton("Save Draft", QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton("Discard Changes", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        self._log_lifecycle_event(
            "audit_navigation_guard",
            {
                "destination_page": destination_page or "",
                "action": action,
                "dirty": dirty,
                "save_requested": self._save_requested,
                "save_in_progress": self._save_in_progress,
                "prompt_shown": True,
                "reason": "dirty_user_edits",
            },
        )
        box.exec()
        clicked = box.clickedButton()
        if clicked == save_draft_button:
            self._save_current_audit_draft()
            return True
        if clicked == discard_button:
            return True
        return clicked != cancel_button and False

    def can_close(self, destination_page: str | None = None) -> tuple[bool, str]:
        if self._confirm_unsaved_audit_changes("leave the Audit page", destination_page=destination_page):
            return True, ""
        return False, "Audit form has unsaved changes."

    def on_project_root_changed(self, config) -> None:
        self.config = config
        self.defaults_controller = AuditDefaultsController(config)
        self.annotation_service = AnnotationService(config.project_root, initialize=False)
        self._annotation_service_generation += 1
        self._annotation_service_initializing = False
        self._annotation_service_ready = False
        self._draft_recovery_checked = False
        self._set_audit_selector_loading("Loading audit list...")
        self._set_compatibility_sources_loading("Loading compatibility sources...")
        self._load_lazy_audit_indexes()
        self._start_annotation_service_initialization()
        self._refresh_audit_coach()

    def _build_audit_tab(self) -> QWidget:
        self.audit_fields = {}
        container = QWidget()
        outer = QVBoxLayout(container)

        load_row = QHBoxLayout()
        self.load_audit_id_combo = QComboBox()
        self.load_audit_id_combo.setEditable(True)
        self.load_audit_id_combo.setMinimumWidth(520)
        self.load_audit_id_combo.addItem("Loading audit list...", None)
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

        view_mode_row = QHBoxLayout()
        self.audit_entry_mode_combo = QComboBox()
        self.audit_entry_mode_combo.addItems(["Guided Audit", "Section Form"])
        self.audit_entry_mode_combo.setCurrentText("Section Form")
        self.audit_entry_mode_combo.currentTextChanged.connect(self._on_audit_entry_mode_changed)
        view_mode_row.addWidget(QLabel("View Mode"))
        view_mode_row.addWidget(self.audit_entry_mode_combo)
        view_mode_row.addStretch(1)
        outer.addLayout(view_mode_row)

        self.manual_override_status_label = QLabel("")
        self.manual_override_status_label.setObjectName("AuditOverrideStatus")
        self.manual_override_status_label.setWordWrap(True)
        self.manual_override_status_label.setStyleSheet("color: #92400e; font-weight: 600;")
        self.manual_override_status_label.hide()
        outer.addWidget(self.manual_override_status_label)

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

        section_tabs_started = time.perf_counter()
        self.audit_section_tabs = QTabWidget()
        for title, fields in AUDIT_SECTIONS.items():
            section_tab = self._build_section_tab(fields, section_title=title)
            self.audit_section_tabs.addTab(section_tab, title)
        self._record_startup_timing("build_section_tabs", section_tabs_started)
        audit_id_widget = self.audit_fields.get("Audit ID")
        if isinstance(audit_id_widget, QLineEdit):
            audit_id_widget.setPlaceholderText("Startup ID assigned without opening the workbook")
        section_form_widget = QWidget()
        audit_body = QHBoxLayout(section_form_widget)
        audit_body.setContentsMargins(0, 0, 0, 0)
        audit_body.addWidget(self.audit_section_tabs, stretch=3)
        coach_panel_started = time.perf_counter()
        self.audit_coach_panel = AuditCoachPanel(self)
        self.audit_coach_panel.setMinimumWidth(340)
        audit_body.addWidget(self.audit_coach_panel, stretch=1)
        self._record_startup_timing("build_audit_coach_panel", coach_panel_started)
        guided_placeholder_started = time.perf_counter()
        self.guided_audit_panel = self._build_guided_audit_placeholder()
        self._record_startup_timing("build_guided_placeholder", guided_placeholder_started)
        self.audit_mode_stack = QStackedWidget()
        self.audit_mode_stack.addWidget(self.guided_audit_panel)
        self.audit_mode_stack.addWidget(section_form_widget)
        self.audit_mode_stack.setCurrentIndex(1)
        outer.addWidget(self.audit_mode_stack, stretch=1)

        self.audit_followup_check = QCheckBox("Create Follow-Up Action")
        outer.addWidget(self.audit_followup_check)

        button_row = QHBoxLayout()
        suggestions_button = QPushButton("Review Suggestions")
        suggestions_button.clicked.connect(self.review_annotation_suggestions)
        manual_override_button = QPushButton("Manual Override: Mark Audit Complete")
        manual_override_button.setObjectName("ManualCompletionOverrideButton")
        manual_override_button.setStyleSheet(
            "QPushButton#ManualCompletionOverrideButton { background: #7f1d1d; color: white; font-weight: 600; }"
            "QPushButton#ManualCompletionOverrideButton:disabled { background: #9ca3af; }"
        )
        manual_override_button.clicked.connect(self.apply_manual_completion_override)
        self.manual_override_button = manual_override_button
        save_button = QPushButton("Save Audit Entry")
        save_button.clicked.connect(self.save_audit)
        self.save_audit_button = save_button
        save_draft_button = QPushButton("Save Draft")
        save_draft_button.clicked.connect(self.save_current_audit_draft)
        resume_draft_button = QPushButton("Resume Draft")
        resume_draft_button.clicked.connect(self.resume_saved_audit_draft)
        discard_draft_button = QPushButton("Discard Draft")
        discard_draft_button.clicked.connect(self.discard_saved_audit_draft)
        clear_button = QPushButton("Clear Form")
        clear_button.clicked.connect(lambda: self.clear_audit_form(confirm=True))
        button_row.addWidget(suggestions_button)
        button_row.addWidget(manual_override_button)
        button_row.addWidget(save_button)
        button_row.addWidget(save_draft_button)
        button_row.addWidget(resume_draft_button)
        button_row.addWidget(discard_draft_button)
        button_row.addWidget(clear_button)
        outer.addLayout(button_row)

        previous_detailed_logging = self._suppress_detailed_startup_logging
        self._suppress_detailed_startup_logging = True
        try:
            clear_started = time.perf_counter()
            self.clear_audit_form(confirm=False, clear_summary=False, use_startup_audit_id=True)
            self._record_startup_timing("clear_audit_form", clear_started)
            coach_refresh_started = time.perf_counter()
            self._refresh_audit_coach()
            self._record_startup_timing("initial_audit_coach_refresh", coach_refresh_started)
        finally:
            self._suppress_detailed_startup_logging = previous_detailed_logging
        return container

    def _build_guided_audit_placeholder(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Guided Audit")
        title.setStyleSheet("font-size: 13pt; font-weight: 600;")
        layout.addWidget(title)
        note = QLabel("Guided audit steps will load when Guided Audit is selected.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return panel

    def _ensure_guided_audit_built(self) -> None:
        if self._guided_ui_built:
            return
        started = time.perf_counter()
        index = self.audit_mode_stack.indexOf(self.guided_audit_panel) if hasattr(self, "audit_mode_stack") else -1
        old_panel = self.guided_audit_panel
        panel = self._build_guided_audit_panel()
        self.guided_audit_panel = panel
        if index >= 0:
            self.audit_mode_stack.removeWidget(old_panel)
            old_panel.deleteLater()
            self.audit_mode_stack.insertWidget(index, panel)
        self._guided_ui_built = True
        self._log_startup_event(
            "audit_page_guided_ui_built",
            time.perf_counter() - started,
            step_count=len(self._guided_step_tables),
        )
        self._refresh_guided_audit()

    def _build_guided_audit_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        title = QLabel("Guided Audit")
        title.setStyleSheet("font-size: 13pt; font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        open_full_button = QPushButton("Open Full Audit")
        open_full_button.clicked.connect(self.open_full_audit_from_guided)
        header.addWidget(open_full_button)
        layout.addLayout(header)

        self.guided_audit_tabs = QTabWidget()
        self.guided_audit_tabs.currentChanged.connect(lambda *_args: self._refresh_guided_audit())
        self._guided_step_tables = {}
        self._guided_step_labels = {}
        for step in all_guided_audit_steps():
            tab = self._build_guided_step_tab(step)
            self.guided_audit_tabs.addTab(tab, step.title)
        layout.addWidget(self.guided_audit_tabs, stretch=1)
        return panel

    def _build_guided_step_tab(self, step: GuidedAuditStep) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        summary = QLabel("")
        summary.setWordWrap(True)
        layout.addWidget(summary)
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Field", "Status", "Value", "Reason"])
        table.setMinimumHeight(260)
        table.cellDoubleClicked.connect(
            lambda row, _column, step_fields=step.fields: self.open_guided_field(
                step_fields[row] if row < len(step_fields) else ""
            )
        )
        layout.addWidget(table, stretch=1)
        button_row = QHBoxLayout()
        open_step_button = QPushButton("Open Step In Section Form")
        open_step_button.clicked.connect(
            lambda _checked=False, target_step=step: self.open_guided_step_in_section_form(target_step)
        )
        button_row.addWidget(open_step_button)
        if step.id == "final_review_save_impact":
            preview_button = QPushButton("Refresh Save Preview")
            preview_button.clicked.connect(lambda: self._refresh_guided_audit(force_io_preview=True))
            button_row.addWidget(preview_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        self._guided_step_tables[step.id] = table
        self._guided_step_labels[step.id] = summary
        return tab

    def _on_audit_entry_mode_changed(self, mode: str) -> None:
        if not hasattr(self, "audit_mode_stack"):
            return
        guided = str(mode or "") == "Guided Audit"
        if guided:
            self._ensure_guided_audit_built()
        self.audit_mode_stack.setCurrentIndex(0 if guided else 1)
        self._refresh_guided_audit(force_io_preview=False)

    def open_full_audit_from_guided(self) -> None:
        if hasattr(self, "audit_entry_mode_combo"):
            self.audit_entry_mode_combo.setCurrentText("Section Form")
        if hasattr(self, "audit_view_mode_combo"):
            self.audit_view_mode_combo.blockSignals(True)
            self.audit_view_mode_combo.setCurrentText("Full Audit")
            self.audit_view_mode_combo.setEnabled(True)
            self.audit_view_mode_combo.blockSignals(False)
        self._update_audit_field_visibility()

    def open_guided_step_in_section_form(self, step: GuidedAuditStep) -> None:
        self.open_full_audit_from_guided()
        if hasattr(self, "audit_section_tabs") and step.section_hint:
            index = self._section_tab_index(step.section_hint)
            if index >= 0:
                self.audit_section_tabs.setCurrentIndex(index)

    def open_guided_field(self, field: str) -> None:
        if not field:
            return
        self.open_full_audit_from_guided()
        section = audit_section_for_field(field)
        if section:
            index = self._section_tab_index(section)
            if index >= 0:
                self.audit_section_tabs.setCurrentIndex(index)
        row = self._audit_field_rows.get(field)
        scroll = self._audit_field_scroll_areas.get(field)
        if scroll is not None and row is not None:
            scroll.ensureWidgetVisible(row)
        widget = self.audit_fields.get(field)
        if widget is not None:
            widget.setFocus()

    def _section_tab_index(self, section: str) -> int:
        for index in range(self.audit_section_tabs.count()):
            if self.audit_section_tabs.tabText(index) == section:
                return index
        return -1

    def _load_lazy_audit_indexes(self) -> None:
        self._start_background_audit_indexes()

    def _start_background_audit_indexes(self) -> None:
        if self._audit_indexes_loading:
            return
        self._audit_indexes_loading = True
        self._audit_indexes_loaded = False
        self._audit_index_generation += 1
        generation = self._audit_index_generation
        project_root = str(self.config.project_root)
        started = time.perf_counter()
        self._set_audit_selector_loading("Loading audit list...")
        self._set_compatibility_sources_loading("Loading compatibility sources...")
        self._log_startup_event("audit_page_background_indexes_started", 0.0)
        get_task_manager().run_task(
            TaskRequest(
                id=f"audit_indexes_{generation}",
                name="Audit Workbook Indexes",
                category="page_refresh",
                callable=AuditPage._load_audit_indexes_for_project,
                args=(project_root, generation),
            ),
            on_finished=lambda result,
            expected_generation=generation,
            started_at=started: self._apply_audit_indexes_task_result(
                result,
                expected_generation,
                started_at,
            ),
        )

    @staticmethod
    def _load_audit_indexes_for_project(project_root: str, generation: int) -> dict[str, object]:
        existing_started = time.perf_counter()
        audit_options = list_audit_options(project_root)
        existing_seconds = time.perf_counter() - existing_started
        compatibility_started = time.perf_counter()
        source_options = list_audited_source_options(project_root)
        compatibility_seconds = time.perf_counter() - compatibility_started
        return {
            "generation": generation,
            "audit_options": [AuditPage._audit_option_payload(option) for option in audit_options],
            "source_options": [AuditPage._audit_option_payload(option) for option in source_options],
            "existing_audit_index_load_seconds": existing_seconds,
            "compatibility_index_load_seconds": compatibility_seconds,
        }

    @staticmethod
    def _audit_option_payload(option) -> dict[str, object]:
        return {"audit_id": option.audit_id, "label": option.label, "row": dict(option.row)}

    def _apply_audit_indexes_task_result(self, task_result, expected_generation: int, started_at: float) -> None:
        if expected_generation != self._audit_index_generation:
            return
        self._audit_indexes_loading = False
        self._audit_indexes_loaded = bool(task_result.ok)
        payload = dict(task_result.result_data or {}) if task_result.ok else {}
        if task_result.ok:
            self._populate_audit_selector_options(list(payload.get("audit_options") or []))
            if hasattr(self, "compatibility_source_combo"):
                self._populate_compatibility_source_options(list(payload.get("source_options") or []))
        else:
            self._set_audit_selector_loading("Audit list failed to load.")
            self._set_compatibility_sources_loading("Compatibility sources failed to load.")
            if hasattr(self, "compatibility_note_label"):
                self.compatibility_note_label.setText(task_result.error or task_result.message)
        self._log_startup_event(
            "audit_page_background_indexes_ready",
            time.perf_counter() - started_at,
            success=task_result.ok,
            audit_option_count=len(payload.get("audit_options") or []),
            compatibility_source_count=len(payload.get("source_options") or []),
            existing_audit_index_load_seconds=round(float(payload.get("existing_audit_index_load_seconds") or 0.0), 4),
            compatibility_index_load_seconds=round(float(payload.get("compatibility_index_load_seconds") or 0.0), 4),
            total_since_page_open_seconds=round(time.perf_counter() - self._page_open_started, 4),
            error=task_result.error,
        )

    def _set_audit_selector_loading(self, message: str) -> None:
        if not hasattr(self, "load_audit_id_combo"):
            return
        current_text = self.load_audit_id_combo.currentText().strip()
        self.load_audit_id_combo.blockSignals(True)
        self.load_audit_id_combo.clear()
        self.load_audit_id_combo.addItem(message, None)
        self.load_audit_id_combo.setCurrentIndex(0)
        if current_text and not current_text.startswith("Loading "):
            self.load_audit_id_combo.setEditText(current_text)
        self.load_audit_id_combo.blockSignals(False)

    def _set_compatibility_sources_loading(self, message: str) -> None:
        if not hasattr(self, "compatibility_source_combo"):
            return
        self.compatibility_source_combo.blockSignals(True)
        self.compatibility_source_combo.clear()
        self.compatibility_source_combo.addItem(message, None)
        self.compatibility_source_combo.setCurrentIndex(0)
        self.compatibility_source_combo.blockSignals(False)
        if hasattr(self, "compatibility_note_label"):
            self.compatibility_note_label.setText(message)

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

    def _build_audit_field_group(
        self, group_title: str, fields: list[str], scroll: QScrollArea, *, section_title: str
    ) -> QGroupBox:
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

    def _add_audit_field_row(
        self, form_layout: QFormLayout, field: str, scroll: QScrollArea, *, section_title: str, group_key: str = ""
    ) -> None:
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
            lookup_button.clicked.connect(lambda _checked=False: self.run_machine_lookup(immediate=True))
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
        self._connect_dirty_tracking(field, widget)

    def _connect_dirty_tracking(self, field: str, widget) -> None:
        if isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(
                lambda _value="", field_name=field: self._on_audit_field_changed(field_name)
            )
        elif isinstance(widget, QTextEdit):
            widget.textChanged.connect(lambda field_name=field: self._on_audit_field_changed(field_name))
        elif isinstance(widget, QLineEdit):
            widget.textChanged.connect(lambda _value="", field_name=field: self._on_audit_field_changed(field_name))

    def _widget_for_audit_field(self, field: str):
        if field in {
            "Known Issues",
            "Drop/Mis-Pick History",
            "Tubing Routing Notes",
            "Notes",
            "Part Name/Description",
            ROBOT_NOTES_FIELD,
        }:
            text = QTextEdit()
            text.setFixedHeight(70)
            return text
        if field == "Plant/Area":
            return self._combo(["Plant 4", "Cleanroom"], editable=False, include_blank=False)
        if field == "Press/Machine #":
            edit = self._line()
            edit.textChanged.connect(self._on_machine_lookup_text_changed)
            edit.editingFinished.connect(lambda: self.run_machine_lookup(immediate=True))
            return edit
        if field == "Robot Type":
            return self._combo(AUDIT_DROPDOWNS.get("Robot Type", []), editable=True)
        if field == GRIPPER_MODEL_FIELD:
            return self._combo(gripper_model_display_values(self.config.project_root), editable=True)
        if field in PNEUMATIC_CIRCUIT_FIELDS or field in {
            NUMBER_OF_PARTS_PICKED_FIELD,
            CYLINDER_COUNT_FIELD,
            CUP_COUNT_FIELD,
            GRIPPER_COUNT_FIELD,
        }:
            edit = self._line()
            if QIntValidator is not None:
                edit.setValidator(QIntValidator(0, 9999, edit))
            return edit
        if field == CYLINDER_TYPE_FIELD:
            return self._combo(AUDIT_DROPDOWNS.get(CYLINDER_TYPE_FIELD, [CYLINDER_TYPE_DEFAULT]), editable=False)
        if field in {
            "Sensors Present?",
            "Cycle Time Concern?",
            "Scrap/Quality Concern?",
            "Drawing/CAD Available?",
            "BOM Available?",
        }:
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
            if (
                selected is None
                and selected_label
                and self.load_audit_id_combo.currentText().strip() == selected_label.strip()
            ):
                return ""
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
        options = [self._audit_option_payload(option) for option in list_audit_options(self.config.project_root)]
        self._populate_audit_selector_options(options)

    def _populate_audit_selector_options(
        self, options: list[dict[str, object]], current_audit_id: str | None = None
    ) -> None:
        if not hasattr(self, "load_audit_id_combo"):
            return
        current_audit_id = current_audit_id if current_audit_id is not None else self._audit_selector_audit_id()
        self.load_audit_id_combo.blockSignals(True)
        self.load_audit_id_combo.clear()
        self.load_audit_id_combo.addItem("", None)
        for option in options:
            self.load_audit_id_combo.addItem(str(option.get("label") or ""), str(option.get("audit_id") or ""))
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

    def clear_audit_form(
        self, *, confirm: bool = False, clear_summary: bool = True, use_startup_audit_id: bool = False
    ) -> None:
        if confirm and not self._suppress_clear_confirm_this_session and not self._confirm_clear_audit_form():
            return
        previous_dialog_suppression = self._suppress_machine_audit_selection_dialog
        self._suppress_machine_audit_selection_dialog = True
        try:
            self._reset_audit_form_fields(show_generated_message=False, use_startup_audit_id=use_startup_audit_id)
            if clear_summary and hasattr(self, "result_panel"):
                self.result_panel.show_text("")
        finally:
            self._suppress_machine_audit_selection_dialog = previous_dialog_suppression

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

    def _reset_audit_form_fields(
        self, *, show_generated_message: bool = True, use_startup_audit_id: bool = False
    ) -> None:
        previous_state = self._begin_hydrating_form("reset_new_audit_form")
        self._applying_defaults = True
        self._log_lifecycle_event("audit_defaults_started", {"reason": "reset_new_audit_form"})
        try:
            self._editing_audit_id = None
            self._current_loaded_audit_id = None
            self._current_audit_mode = "new"
            self._duplicated_press_value = None
            self._duplicated_tool_value = None
            self._loaded_empty_only_fields = None
            self._set_manual_completion_override_metadata({})
            self._changeover_user_modified = False
            self._part_present_autofilled_sensor_fields.clear()
            self._cylinder_type_autofilled = False
            for widget in self.audit_fields.values():
                self._set_field_value(widget, "")
            self._set_field_value(self.audit_fields["Audit Date"], date.today().isoformat())
            for field, default in self.defaults_controller.initial_form_defaults().items():
                if field in self.audit_fields:
                    self._set_field_value(self.audit_fields[field], default)
            self._apply_quick_disconnect_defaults()
            self._apply_sensor_defaults()
            self._apply_cylinder_type_default()
            self._update_tooling_visibility(apply_defaults=True)
            self.current_lookup_result = None
            self._lookup_part_index = None
            self._lookup_conflict_warnings = []
            if hasattr(self, "lookup_note_label"):
                self.lookup_note_label.setText("Enter a machine number to look up robot and part info.")
                self._set_capacity_choices([])
                self._set_machine_audit_matches([])
            if use_startup_audit_id:
                self._assign_startup_audit_id()
            else:
                self.generate_new_audit_id(show_message=show_generated_message)
                self._refresh_field_tag_indicators()
        finally:
            self._applying_defaults = False
            self._log_lifecycle_event("audit_defaults_finished", {"reason": "reset_new_audit_form"})
            self._end_hydrating_form(previous_state, "reset_new_audit_form")
        self._mark_audit_form_baseline("reset", clean_new_form=True)

    def load_existing_audit(
        self, audit_id: str | None = None, *, loaded_message: str | None = None, confirm_unsaved: bool = True
    ) -> bool:
        audit_id = audit_id or self._audit_selector_audit_id()
        entry = load_audit_entry(self.config.project_root, audit_id)
        if not entry:
            self.result_panel.show_text(f"Audit ID not found: {audit_id}")
            return False
        if confirm_unsaved and not self._confirm_unsaved_audit_changes("load another audit"):
            return False
        self._set_audit_selector_text(audit_id)
        previous_dialog_suppression = self._suppress_machine_audit_selection_dialog
        self._suppress_machine_audit_selection_dialog = True
        previous_state = self._begin_hydrating_form("load_existing_audit")
        self._loading_audit = True
        self._part_present_autofilled_sensor_fields.clear()
        try:
            self._set_manual_completion_override_metadata(self._manual_completion_override_metadata_from_entry(entry))
            for field, widget in self.audit_fields.items():
                if field in GRIPPER_UI_FIELDS and not field_applies(entry, field):
                    self._set_field_value(widget, "")
                else:
                    self._set_field_value(widget, workbook_to_ui_value(entry.get(field, ""), field))
            self._cylinder_type_autofilled = False
            self._apply_cylinder_type_default()
            self._load_robot_info_fields(entry, force=True)
            for field in ROBOT_INFO_FIELDS:
                if field in self.audit_fields:
                    entry[field] = self._field_value(self.audit_fields[field])
        finally:
            self._loading_audit = False
            self._end_hydrating_form(previous_state, "load_existing_audit")
            self._suppress_machine_audit_selection_dialog = previous_dialog_suppression
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
        note = (
            loaded_message
            or "Loaded existing audit in Empty Only view. Switch to Full Audit to review completed fields."
        )
        self.lookup_note_label.setText(note)
        result_message = loaded_message or f"Loaded audit entry {audit_id}."
        self.result_panel.show_text(
            f"{result_message} Empty Only is showing {empty_count} blank or N/A field(s). Save will update this row."
        )
        self._editing_audit_id = audit_id
        self._current_loaded_audit_id = audit_id
        self._current_audit_mode = "edit"
        self._duplicated_press_value = None
        self._duplicated_tool_value = None
        self._changeover_user_modified = False
        self._refresh_field_tag_indicators()
        self._mark_audit_form_baseline("load")
        self._suppress_next_machine_lookup_after_audit_workflow(
            self._field_value(self.audit_fields.get("Press/Machine #")),
            "load_existing_audit",
        )
        return True

    def _load_robot_info_fields(self, entry: dict[str, object], *, force: bool) -> bool:
        robot_info = load_robot_info_for_audit_entry(self.config.project_root, entry)
        if not robot_info:
            if ROBOT_INTERCHANGEABLE_CIRCUITS_FIELD in self.audit_fields:
                widget = self.audit_fields[ROBOT_INTERCHANGEABLE_CIRCUITS_FIELD]
                if force or not self._field_value(widget):
                    self._set_field_value(widget, "0")
            return False
        for field in ROBOT_INFO_FIELDS:
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
            self._set_field_value(
                self.audit_fields["Auditor"], self.defaults_controller.field_default("Auditor") or "Kato Gray"
            )
        self._set_field_value(
            self.audit_fields["Photos Taken?"], self.defaults_controller.field_default("Photos Taken?") or "No"
        )
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
        self._set_manual_completion_override_metadata({})
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
        self.lookup_note_label.setText(
            "Duplicated audit as a new unsaved entry. Adjust Press/Machine # or Tool #, then save."
        )
        self.result_panel.show_text(
            f"Duplicated current audit into new unsaved Audit ID {audit_id}. Original audit will not be overwritten."
        )
        self._update_tooling_visibility(apply_defaults=False)
        self._refresh_field_tag_indicators()
        self._mark_audit_form_baseline("duplicate")

    def _update_tooling_visibility(self, *, apply_defaults: bool = True) -> None:
        if not hasattr(self, "audit_fields") or "EOAT Type" not in self.audit_fields:
            return
        if apply_defaults and not (
            self._loading_audit
            or self._hydrating_form
            or self._programmatic_field_update
            or self._suppress_dirty_tracking
        ):
            self._apply_eoat_type_defaults()
        self._update_audit_field_visibility()

    def _update_audit_field_visibility(self, *_args) -> None:
        if not hasattr(self, "audit_fields") or "EOAT Type" not in self.audit_fields:
            return
        started = time.perf_counter()
        current_entry = self._current_audit_form_values()
        empty_only_fields = self._loaded_empty_only_fields if self._empty_only_mode_active() else None
        self.setUpdatesEnabled(False)
        try:
            for field in self.audit_fields:
                visible = field_applies(current_entry, field)
                if field in ALWAYS_VISIBLE_AUDIT_FIELDS:
                    visible = True
                elif empty_only_fields is not None:
                    visible = visible and field in empty_only_fields
                self._set_audit_field_visible_no_group_refresh(field, visible)
            self._refresh_all_audit_group_visibility()
        finally:
            self.setUpdatesEnabled(True)
        self._refresh_audit_coach(current_entry)
        if not getattr(self, "_suppress_detailed_startup_logging", False):
            log_performance(
                self.config.project_root,
                "audit.visibility_refresh",
                time.perf_counter() - started,
                source="audit",
                page_tool="audit",
                details={"field_count": len(self.audit_fields), "empty_only": bool(empty_only_fields is not None)},
            )

    def _audit_field_applies_in_current_form(self, field: str) -> bool:
        current_entry = {name: self._field_value(widget) for name, widget in self.audit_fields.items()}
        return field_applies(current_entry, field)

    def _apply_eoat_type_defaults(self) -> None:
        eoat_type = self._field_value(self.audit_fields["EOAT Type"])
        cup_widget = self.audit_fields.get("Cup Type/Material")
        if cup_widget is None:
            return
        previous = self._applying_defaults
        self._applying_defaults = True
        self._log_lifecycle_event("audit_defaults_started", {"reason": "eoat_type_defaults", "field": "EOAT Type"})
        try:
            cup_value = self._field_value(cup_widget)
            cup_default = self.defaults_controller.field_default("Cup Type/Material") or CUP_TYPE_DEFAULT
            if cup_type_default_applies(eoat_type):
                if not cup_value:
                    self._set_field_value(cup_widget, cup_default)
            elif cup_value == cup_default:
                self._set_field_value(cup_widget, "")
        finally:
            self._applying_defaults = previous
            self._log_lifecycle_event("audit_defaults_finished", {"reason": "eoat_type_defaults", "field": "EOAT Type"})

    def _on_sensors_present_changed(self) -> None:
        if self._loading_audit or self._hydrating_form or self._programmatic_field_update:
            return
        if self._field_value(self.audit_fields["Sensors Present?"]).lower() != "no":
            self._apply_sensor_defaults()
        self._update_audit_field_visibility()

    def _on_electrical_wiring_present_changed(self, *_args) -> None:
        if self._loading_audit or self._hydrating_form or self._programmatic_field_update:
            return
        self._update_audit_field_visibility()

    def _on_part_present_detection_changed(self, *_args) -> None:
        if self._loading_audit or self._hydrating_form or self._programmatic_field_update:
            return
        if self._field_value(self.audit_fields[PART_PRESENT_DETECTION_FIELD]).lower() == "yes":
            self._apply_part_present_sensor_autofill()
        self._update_audit_field_visibility()

    def _on_connection_type_changed(self, *_args) -> None:
        if self._loading_audit or self._hydrating_form or self._programmatic_field_update:
            return
        self._apply_changeover_difficulty_default()

    def _on_changeover_difficulty_changed(self, *_args) -> None:
        if self._loading_audit or self._hydrating_form or self._programmatic_field_update:
            return
        self._changeover_user_modified = True

    def _on_quick_disconnects_present_changed(self, *_args) -> None:
        if self._loading_audit or self._hydrating_form or self._programmatic_field_update:
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
        previous = self._applying_defaults
        self._applying_defaults = True
        self._log_lifecycle_event("audit_defaults_started", {"reason": "quick_disconnect_defaults"})
        try:
            if (
                QUICK_DISCONNECTS_PRESENT_FIELD in self.audit_fields
                and self._field_value(self.audit_fields[QUICK_DISCONNECTS_PRESENT_FIELD]).lower() == "yes"
            ):
                pneumatic_widget = self.audit_fields[PNEUMATIC_QUICK_DISCONNECT_TYPE_FIELD]
                if not self._field_value(pneumatic_widget):
                    self._set_field_value(pneumatic_widget, self.defaults_controller.quick_disconnect_type_default())
        finally:
            self._applying_defaults = previous
            self._log_lifecycle_event("audit_defaults_finished", {"reason": "quick_disconnect_defaults"})

    def _apply_changeover_difficulty_default(self) -> None:
        if self._changeover_user_modified:
            return
        if CONNECTION_TYPE_FIELD not in self.audit_fields or CHANGEOVER_DIFFICULTY_FIELD not in self.audit_fields:
            return
        difficulty_widget = self.audit_fields[CHANGEOVER_DIFFICULTY_FIELD]
        if not self._smart_default_can_fill(self._field_value(difficulty_widget)):
            return
        entry = self._current_audit_form_values()
        result = self.defaults_controller.smart_defaults(
            entry, only_unset=True, applicable_fields=self._audit_field_applies_in_current_form
        )
        default = result.values.get(CHANGEOVER_DIFFICULTY_FIELD)
        if not default and getattr(self.config, "smart_default_rules", None) is None:
            default = self.defaults_controller.changeover_default(
                self._field_value(self.audit_fields[CONNECTION_TYPE_FIELD])
            )
        if default and default != self._field_value(difficulty_widget):
            self._set_field_value(difficulty_widget, default)

    def _smart_default_can_fill(self, value: str) -> bool:
        return str(value or "").strip().lower() in UNSET_SMART_DEFAULT_VALUES

    def _apply_sensor_defaults(self) -> None:
        previous = self._applying_defaults
        self._applying_defaults = True
        self._log_lifecycle_event("audit_defaults_started", {"reason": "sensor_defaults"})
        try:
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
        finally:
            self._applying_defaults = previous
            self._log_lifecycle_event("audit_defaults_finished", {"reason": "sensor_defaults"})

    def _apply_part_present_sensor_autofill(self) -> None:
        previous = self._autofilling_fields
        self._autofilling_fields = True
        self._log_lifecycle_event("audit_autofill_started", {"reason": "part_present_sensor_autofill"})
        try:
            entry = self._current_audit_form_values()
            result = self.defaults_controller.smart_defaults(
                entry, only_unset=True, applicable_fields=self._audit_field_applies_in_current_form
            )
            for field, default in PART_PRESENT_SENSOR_DEFAULTS.items():
                if field not in self.audit_fields:
                    continue
                widget = self.audit_fields[field]
                current_value = self._field_value(widget)
                value = result.values.get(field, self._field_value(widget))
                if value != current_value and part_present_sensor_value_allows_default(current_value, value):
                    self._set_field_value(widget, value)
                    self._part_present_autofilled_sensor_fields.add(field)
        finally:
            self._autofilling_fields = previous
            self._log_lifecycle_event("audit_autofill_finished", {"reason": "part_present_sensor_autofill"})

    def _empty_only_mode_active(self) -> bool:
        return (
            self._loaded_empty_only_fields is not None
            and hasattr(self, "audit_view_mode_combo")
            and self.audit_view_mode_combo.currentText() == "Empty Only"
        )

    def _set_audit_field_visible(self, field: str, visible: bool) -> None:
        self._set_audit_field_visible_no_group_refresh(field, visible)
        self._refresh_audit_group_visibility(field)

    def _set_audit_field_visible_no_group_refresh(self, field: str, visible: bool) -> None:
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

    def _refresh_audit_group_visibility(self, field: str) -> None:
        group_key = self._audit_field_group_keys.get(field)
        if not group_key:
            return
        group = self._audit_group_boxes.get(group_key)
        if group is None:
            return
        group_fields = self._audit_group_fields.get(group_key, [])
        group.setVisible(any(self._audit_field_visibility_state.get(group_field, True) for group_field in group_fields))

    def _refresh_all_audit_group_visibility(self) -> None:
        for group_key, group in self._audit_group_boxes.items():
            group_fields = self._audit_group_fields.get(group_key, [])
            group.setVisible(
                any(self._audit_field_visibility_state.get(group_field, True) for group_field in group_fields)
            )

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
        workbook_path = paths.robot_info_workbook if field in ROBOT_INFO_FIELDS else paths.master_workbook
        sheet_name = ROBOT_INFO_SHEET if field in ROBOT_INFO_FIELDS else "EOAT Inventory"
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
        self.focus_annotation_target(
            {"target_type": "audit_field", "audit_id": audit_id, "field_label": field, "field_key": field}
        )

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
        get_event_bus().emit(
            EVENT_ANNOTATION_CHANGED,
            {"audit_id": audit_id, "field": field, "tag": "Needs Review"},
            source="audit_coach",
        )
        self.result_panel.show_text(f"Tagged {field} as Needs Review.")

    def _unknown_value_for_audit_field(self, field: str, widget) -> str:
        numeric_only_fields = {
            NUMBER_OF_PARTS_PICKED_FIELD,
            CYLINDER_COUNT_FIELD,
            CUP_COUNT_FIELD,
            GRIPPER_COUNT_FIELD,
            *PNEUMATIC_CIRCUIT_FIELDS,
            *ROBOT_PNEUMATIC_FIELDS,
        }
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
        row.setStyleSheet(
            "#AuditFieldNavigationHighlight { border: 2px solid #2563eb; border-radius: 4px; padding: 1px; }"
        )
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

    def _confirm_completed_audit_update(self, audit_id: str) -> tuple[bool, bool]:
        if QMessageBox is None:
            return True, True
        box = QMessageBox(self)
        box.setWindowTitle("Update Completed Audit?")
        box.setText("This audit has already been completed. Saving will update the existing audit record.")
        box.setInformativeText(
            f"Audit ID: {audit_id}\n\n"
            "The audit row saves first. Linked compatibility rows can be queued for review/update afterward."
        )
        checkbox = QCheckBox("Queue linked compatibility update after save")
        checkbox.setChecked(True)
        box.setCheckBox(checkbox)
        save_button = box.addButton("Save Update", QMessageBox.ButtonRole.AcceptRole)
        cancel_button = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        accepted = box.clickedButton() == save_button and box.clickedButton() != cancel_button
        update_compatibility = checkbox.isChecked()
        self._log_lifecycle_event(
            "audit_completed_update_prompt",
            {
                "audit_id": audit_id,
                "accepted": accepted,
                "update_compatibility": update_compatibility,
            },
        )
        return accepted, update_compatibility

    def _manual_completion_override_metadata_from_entry(self, entry: dict[str, object]) -> dict[str, str]:
        if not manual_completion_override_enabled(entry):
            return {}
        return {
            field: str(entry.get(field) or "")
            for field in MANUAL_COMPLETION_OVERRIDE_FIELDS
            if str(entry.get(field) or "").strip()
        }

    def _set_manual_completion_override_metadata(self, metadata: dict[str, str]) -> None:
        self._manual_completion_override_data = {
            field: str(metadata.get(field) or "")
            for field in MANUAL_COMPLETION_OVERRIDE_FIELDS
            if str(metadata.get(field) or "").strip()
        }
        self._update_manual_completion_override_status()

    def _update_manual_completion_override_status(self) -> None:
        label = getattr(self, "manual_override_status_label", None)
        if label is None:
            return
        if not self._manual_completion_override_data:
            label.setText("")
            label.hide()
            return
        timestamp = self._manual_completion_override_data.get(MANUAL_COMPLETION_OVERRIDE_TIMESTAMP_FIELD, "")
        user = self._manual_completion_override_data.get(MANUAL_COMPLETION_OVERRIDE_USER_FIELD, "")
        pieces = ["Manual completion override applied"]
        if timestamp:
            pieces.append(timestamp)
        if user:
            pieces.append(f"by {user}")
        label.setText(" - ".join(pieces))
        label.show()

    def _confirm_manual_completion_override(self) -> bool:
        if QMessageBox is None:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Manual Completion Override")
        box.setText(
            "This will manually mark this audit as complete even though some fields may still be blank.\n"
            "Blank fields currently remaining on this audit will be ignored by the audit coach for completion percentage purposes.\n"
            "This only affects the current audit. It does not change global validation rules.\n"
            "Are you sure you want to continue?"
        )
        cancel_button = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        mark_button = box.addButton("Mark Complete", QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(cancel_button)
        box.setEscapeButton(cancel_button)
        box.exec()
        return box.clickedButton() == mark_button

    def _empty_fields_for_manual_override(self, entry: dict[str, str]) -> list[str]:
        summary = calculate_audit_completion(entry, AUDIT_SECTIONS, mode=self._current_audit_mode)
        return list(summary.missing_fields)

    def apply_manual_completion_override(self, *_args) -> None:
        if self._save_requested or self._save_in_progress:
            self.result_panel.show_text(
                "Audit save is already in progress. Please wait for it to finish before applying an override."
            )
            return
        if not self._confirm_manual_completion_override():
            self._log_lifecycle_event(
                "audit_manual_completion_override_canceled",
                {"audit_id": self._field_value(self.audit_fields.get("Audit ID"))},
            )
            return
        entry = self._current_audit_form_values()
        audit_id = str(entry.get("Audit ID") or "").strip()
        ignored_fields = self._empty_fields_for_manual_override(entry)
        metadata = {
            MANUAL_COMPLETION_OVERRIDE_FIELD: "Yes",
            MANUAL_COMPLETION_OVERRIDE_TIMESTAMP_FIELD: datetime.now(timezone.utc).isoformat(timespec="seconds"),
            MANUAL_COMPLETION_OVERRIDE_USER_FIELD: str(entry.get("Auditor") or "").strip(),
            IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD: "; ".join(ignored_fields),
        }
        self._set_manual_completion_override_metadata(metadata)
        entry.update(metadata)
        self._refresh_audit_coach(entry)
        self.result_panel.show_text("Manual completion override applied. Saving the audit override now...")
        self._log_lifecycle_event(
            "audit_manual_completion_override_applied",
            {
                "audit_id": audit_id,
                "ignored_empty_field_count": len(ignored_fields),
                "ignored_empty_fields": ignored_fields,
            },
        )
        self._pending_manual_completion_override = True
        self.save_audit(
            skip_completion_prompts=True,
            forced_entry=entry,
            progress_text="Saving manual completion override...",
        )

    def save_audit(
        self,
        *_args,
        skip_completion_prompts: bool = False,
        forced_entry: dict[str, str] | None = None,
        progress_text: str | None = None,
    ) -> None:
        if self._save_requested or self._save_in_progress:
            self._log_lifecycle_event(
                "audit_save_duplicate_prevented",
                {
                    "audit_id": self._field_value(self.audit_fields.get("Audit ID")),
                    "save_requested": self._save_requested,
                    "save_in_progress": self._save_in_progress,
                },
            )
            if hasattr(self, "result_panel"):
                self.result_panel.show_text("Audit save is already in progress. Please wait for it to finish.")
            return
        clicked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        collect_started = time.perf_counter()
        entry = dict(forced_entry) if forced_entry is not None else self.collect_complete_audit_form_state()
        collect_seconds = time.perf_counter() - collect_started
        current_audit_id = str(entry.get("Audit ID") or "").strip()
        allow_update = bool(
            self._current_audit_mode == "edit" and self._editing_audit_id and current_audit_id == self._editing_audit_id
        )
        sync_linked_compatibility = False
        completed_update_context = None
        if allow_update and not skip_completion_prompts:
            existing_completed = str(self._audit_form_baseline.get("Status") or "").strip().casefold() == "complete"
            if existing_completed:
                accepted, update_compatibility = self._confirm_completed_audit_update(current_audit_id)
                completed_update_context = {
                    "audit_id": current_audit_id,
                    "existing_completed_audit": True,
                    "update_compatibility": update_compatibility,
                }
                if not accepted:
                    self.result_panel.show_text("Audit save canceled before updating the completed audit.")
                    self._log_lifecycle_event(
                        "audit_save_canceled",
                        {"audit_id": current_audit_id, "reason": "completed_update_prompt_canceled"},
                    )
                    return
                sync_linked_compatibility = update_compatibility
            else:
                preview = build_compatibility_impact_preview(self.config.project_root, current_audit_id, entry)
                if preview.has_impact:
                    if not self._confirm_compatibility_impact_preview(preview):
                        self.result_panel.show_text("Audit save canceled before updating linked compatibility rows.")
                        self._log_lifecycle_event(
                            "audit_save_canceled",
                            {
                                "audit_id": current_audit_id,
                                "reason": "compatibility_impact_preview_canceled",
                                "linked_compatibility_rows": preview.compatible_row_count,
                            },
                        )
                        return
                    sync_linked_compatibility = True
        self._save_requested = True
        self._save_in_progress = True
        self._save_navigation_requested = False
        self._pending_save_snapshot = {field: str(entry.get(field) or "") for field in self.audit_fields}
        self._pending_save_started_at = clicked_at
        self._pending_completed_update_context = completed_update_context
        if hasattr(self, "save_audit_button"):
            self.save_audit_button.setEnabled(False)
        if hasattr(self, "manual_override_button"):
            self.manual_override_button.setEnabled(False)
        self._log_lifecycle_event(
            "audit_save_started",
            {
                "audit_id": current_audit_id,
                "clicked_at": clicked_at,
                "dirty_before_save": self.has_unsaved_changes(),
                "collect_form_state_seconds": round(collect_seconds, 3),
                "field_count": len(entry),
                "allow_update": allow_update,
                "sync_linked_compatibility": sync_linked_compatibility,
            },
        )
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
            button=getattr(self, "save_audit_button", None),
            progress_text=progress_text or "Saving audit...\nSkipping derived scans unless this edit requires them...",
        )

    def collect_complete_audit_form_state(self) -> dict[str, str]:
        entry = self._current_audit_form_values()
        if (
            not is_meaningful_value(entry.get(CYLINDER_COUNT_FIELD))
            and entry.get(CYLINDER_TYPE_FIELD) == CYLINDER_TYPE_DEFAULT
        ):
            entry[CYLINDER_TYPE_FIELD] = ""
        elif is_meaningful_value(entry.get(CYLINDER_COUNT_FIELD)) and str(
            entry.get(CYLINDER_TYPE_FIELD) or ""
        ).strip().upper() in {"", NA_VALUE}:
            entry[CYLINDER_TYPE_FIELD] = CYLINDER_TYPE_DEFAULT
        entry.update(self._current_audit_metadata_values())
        return entry

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
        completed_update_context = self._pending_completed_update_context
        manual_override_save = bool(self._pending_manual_completion_override)
        pending_snapshot = dict(self._pending_save_snapshot or {})
        navigation_requested = self._save_navigation_requested
        saved_audit_id = str(result.metrics.get("audit_id") or audit_id or "").strip()
        if completed_update_context:
            result.metrics["existing_completed_audit"] = bool(completed_update_context.get("existing_completed_audit"))
            result.metrics["completed_audit_update_compatibility_requested"] = bool(
                completed_update_context.get("update_compatibility")
            )
            if result.success:
                if completed_update_context.get("update_compatibility"):
                    result.details.append("Compatibility update for completed audit was requested.")
                else:
                    result.details.append("Compatibility update skipped by user choice.")
                    if "Compatibility update skipped by user choice." not in result.summary:
                        result.summary = result.summary.rstrip() + "\n\nCompatibility update skipped by user choice."
        if result.success and saved_audit_id:
            current_values = self._current_audit_form_values()
            if pending_snapshot and form_values_changed(current_values, pending_snapshot):
                self._audit_form_baseline = dict(pending_snapshot)
                self._last_clean_snapshot = dict(pending_snapshot)
                self._last_saved_snapshot = dict(pending_snapshot)
                self._recalculate_dirty_state(reason="save_success_with_new_edits")
                self._log_lifecycle_event(
                    "audit_save_completed_with_new_edits",
                    {"audit_id": saved_audit_id, "dirty_after_save": self._dirty},
                )
            else:
                self._mark_audit_form_baseline("save_success")
                discard_audit_draft(self.config.project_root)
            self._duplicated_press_value = None
            self._duplicated_tool_value = None
            self._editing_audit_id = saved_audit_id
            self._current_loaded_audit_id = saved_audit_id
            self._current_audit_mode = "edit"
            self._set_audit_selector_text(saved_audit_id)
            post_save_refresh_started = time.perf_counter()
            self._update_audit_selector_locally_after_save(saved_audit_id, pending_snapshot)
            self._mark_audit_indexes_stale_after_save(saved_audit_id)
            self._refresh_audit_coach()
            result.metrics["audit_save.post_save_refresh_seconds"] = round(
                time.perf_counter() - post_save_refresh_started, 3
            )
            result.details.append(
                f"Post-save UI update: {result.metrics['audit_save.post_save_refresh_seconds']}s "
                "(selector updated locally; workbook index refresh queued)."
            )
            log_performance_event(
                self.config.project_root,
                "audit_save.post_save_ui",
                time.perf_counter() - post_save_refresh_started,
                source="audit_ui",
                page_tool="audit",
                details={"audit_id": saved_audit_id, "selector_refresh": "local", "index_refresh": "debounced"},
            )
            event_started = time.perf_counter()
            try:
                get_event_bus().emit(
                    EVENT_AUDIT_SAVED,
                    {
                        "audit_id": saved_audit_id,
                        "row": result.metrics.get("row"),
                        "updated": result.metrics.get("updated"),
                        "compatibility_created": result.metrics.get("compatibility_created", 0),
                        "refresh_mode": result.metrics.get("refresh_mode", "invalidate_only"),
                    },
                    source="audit",
                )
            except Exception as exc:
                result.warnings.append(f"AuditSaved event listeners did not complete: {exc}")
            event_seconds = time.perf_counter() - event_started
            result.metrics["audit_save.event_dispatch_seconds"] = round(event_seconds, 3)
            log_performance_event(
                self.config.project_root,
                "audit_save.event_dispatch",
                event_seconds,
                source="audit_ui",
                page_tool="audit",
                details={
                    "audit_id": saved_audit_id,
                    "refresh_mode": result.metrics.get("refresh_mode", "invalidate_only"),
                },
            )
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
            if manual_override_save:
                self.result_panel.show_text(
                    "Manual completion override applied. This audit is treated as 100% complete, but blank fields were not field-verified."
                )
            self._queue_deferred_audit_followups(result, saved_audit_id, pending_snapshot)
            self._log_lifecycle_event(
                "audit_save_completed",
                {
                    "audit_id": saved_audit_id,
                    "success": True,
                    "dirty_after_save": self._dirty,
                    "navigation_requested_during_save": navigation_requested,
                    "duration_seconds": round(result.duration_seconds or 0.0, 3),
                    "existing_completed_audit": bool(result.metrics.get("existing_completed_audit")),
                    "completed_audit_update_compatibility_requested": bool(
                        result.metrics.get("completed_audit_update_compatibility_requested")
                    ),
                    "compatibility_rows_synced": result.metrics.get("compatibility_rows_synced", 0),
                },
            )
        else:
            self._recalculate_dirty_state(reason="save_failed")
            self._log_lifecycle_event(
                "audit_save_completed",
                {
                    "audit_id": saved_audit_id or audit_id,
                    "success": False,
                    "errors": result.errors,
                    "dirty_after_save": self._dirty,
                    "navigation_requested_during_save": navigation_requested,
                    "duration_seconds": round(result.duration_seconds or 0.0, 3),
                },
            )
            if hasattr(self, "result_panel"):
                self.result_panel.show_result(result)
        self._save_requested = False
        self._save_in_progress = False
        self._save_navigation_requested = False
        self._pending_save_snapshot = None
        self._pending_save_started_at = None
        self._pending_completed_update_context = None
        self._pending_manual_completion_override = False
        if hasattr(self, "save_audit_button"):
            self.save_audit_button.setEnabled(True)
        if hasattr(self, "manual_override_button"):
            self.manual_override_button.setEnabled(True)

    def _update_audit_selector_locally_after_save(self, audit_id: str, entry: dict[str, str]) -> None:
        if not audit_id or not hasattr(self, "load_audit_id_combo"):
            return
        machine = str(entry.get("Press/Machine #") or "").strip()
        status = str(entry.get("Status") or "").strip()
        label = " | ".join(piece for piece in [audit_id, f"Machine {machine}" if machine else "", status] if piece)
        self.load_audit_id_combo.blockSignals(True)
        try:
            index = self.load_audit_id_combo.findData(audit_id)
            if index < 0:
                self.load_audit_id_combo.addItem(label or audit_id, audit_id)
                index = self.load_audit_id_combo.findData(audit_id)
            elif label:
                self.load_audit_id_combo.setItemText(index, label)
            if index >= 0:
                self.load_audit_id_combo.setCurrentIndex(index)
            else:
                self.load_audit_id_combo.setCurrentIndex(-1)
                self.load_audit_id_combo.setEditText(audit_id)
        finally:
            self.load_audit_id_combo.blockSignals(False)

    def _mark_audit_indexes_stale_after_save(self, audit_id: str) -> None:
        self._audit_indexes_loaded = False
        self._log_lifecycle_event(
            "audit_indexes_marked_stale", {"audit_id": audit_id, "refresh_mode": "invalidate_only"}
        )
        if self._audit_indexes_loading:
            return
        if QTimer is not None:
            QTimer.singleShot(750, self._start_background_audit_indexes)
        else:
            self._start_background_audit_indexes()

    def _queue_deferred_audit_followups(self, result, audit_id: str, entry: dict[str, str]) -> None:
        robot_queued = bool(result.metrics.get("deferred_robot_info_queued"))
        compatibility_queued = bool(result.metrics.get("deferred_compatibility_queued"))
        if robot_queued:
            run_tool_background(
                self.result_panel,
                "robot_info_update_from_audit",
                "Robot Info Update",
                lambda: self._run_deferred_robot_info_update(dict(entry)),
                on_tool_result=lambda robot_result: (
                    self._after_deferred_robot_info(robot_result, audit_id),
                    self._queue_deferred_compatibility_update(audit_id) if compatibility_queued else None,
                ),
                modifies_files=True,
                workbook_lock=True,
                progress_text="Audit row saved. Updating Robot_Info.xlsx in the background...",
            )
        elif compatibility_queued:
            self._queue_deferred_compatibility_update(audit_id)

    def _queue_deferred_compatibility_update(self, audit_id: str) -> None:
        run_tool_background(
            self.result_panel,
            "linked_compatibility_update",
            "Update Linked Compatibility Rows",
            lambda: self._run_deferred_compatibility_update(audit_id),
            on_tool_result=lambda compatibility_result: self._after_deferred_compatibility(
                compatibility_result, audit_id
            ),
            modifies_files=True,
            workbook_lock=True,
            progress_text="Audit row saved. Updating linked compatibility rows in the background...",
        )

    def _run_deferred_robot_info_update(self, entry: dict[str, str]):
        from core.robot_info import upsert_robot_info_from_audit

        started = time.perf_counter()
        result = upsert_robot_info_from_audit(self.config.project_root, entry)
        log_performance_event(
            self.config.project_root,
            "audit_save.deferred_robot_info",
            time.perf_counter() - started,
            source="deferred_audit_followup",
            page_tool="audit",
            details={"audit_id": entry.get("Audit ID", ""), "success": result.success},
            success=result.success,
            warning_count=len(result.warnings),
            error_count=len(result.errors),
        )
        return result

    def _after_deferred_robot_info(self, result, audit_id: str) -> None:
        get_event_bus().emit(
            EVENT_ROBOT_INFO_UPDATED,
            {"audit_id": audit_id, "success": result.success, "refresh_mode": "invalidate_only"},
            source="audit",
        )

    def _run_deferred_compatibility_update(self, audit_id: str):
        from core.audit_compatibility import sync_compatible_rows_from_source

        started = time.perf_counter()
        paths = resolve_project_paths(self.config.project_root)
        sync_result = sync_compatible_rows_from_source(paths.master_workbook, audit_id)
        duration = time.perf_counter() - started
        log_performance_event(
            self.config.project_root,
            "audit_save.deferred_compatibility",
            duration,
            source="deferred_audit_followup",
            page_tool="audit",
            details={
                "audit_id": audit_id,
                "updated_count": sync_result.updated_count,
                "skipped_count": sync_result.skipped_count,
            },
            success=True,
            warning_count=len(sync_result.warning_messages),
        )
        summary = (
            f"Updated {sync_result.updated_count} linked compatibility entrie(s)."
            if sync_result.updated_count
            else "No linked compatibility entries needed updates."
        )
        return ToolResult.ok(
            "linked_compatibility_update",
            "Update Linked Compatibility Rows",
            summary,
            details=[
                f"Source audit ID: {audit_id}",
                f"Updated linked compatibility rows: {sync_result.updated_count}",
                f"Skipped non-compatible linked rows: {sync_result.skipped_count}",
            ],
            warnings=sync_result.warning_messages,
            files_created=[sync_result.backup_path] if sync_result.backup_path else [],
            files_modified=[str(paths.master_workbook)] if sync_result.updated_count else [],
            metrics={"updated_count": sync_result.updated_count, "skipped_count": sync_result.skipped_count},
            duration_seconds=duration,
        )

    def _after_deferred_compatibility(self, result, audit_id: str) -> None:
        get_event_bus().emit(
            EVENT_COMPATIBILITY_REGENERATED,
            {
                "audit_id": audit_id,
                "updated_count": result.metrics.get("updated_count", 0),
                "refresh_mode": "invalidate_only",
            },
            source="audit",
        )

    def refresh_compatibility_sources(self) -> None:
        options = [
            self._audit_option_payload(option) for option in list_audited_source_options(self.config.project_root)
        ]
        self._populate_compatibility_source_options(options)

    def _populate_compatibility_source_options(self, options: list[dict[str, object]]) -> None:
        if not hasattr(self, "compatibility_source_combo"):
            return
        self.compatibility_source_combo.blockSignals(True)
        current = self.compatibility_source_combo.currentData()
        self.compatibility_source_combo.clear()
        for option in options:
            self.compatibility_source_combo.addItem(str(option.get("label") or ""), str(option.get("audit_id") or ""))
        if current:
            index = self.compatibility_source_combo.findData(current)
            if index >= 0:
                self.compatibility_source_combo.setCurrentIndex(index)
        self.compatibility_source_combo.blockSignals(False)
        if options:
            self.compatibility_note_label.setText(
                f"{len(options)} audited source record(s) available for compatibility entry."
            )
        else:
            self.compatibility_note_label.setText(
                "No audited source records found. Save a physical audit before creating compatibility entries."
            )

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
        self.compatibility_note_label.setText(
            f"{create_count} create-compatible candidate(s) found for {audit_id}.{warning_text}"
        )

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

    def _on_machine_lookup_text_changed(self, *_args) -> None:
        if self._programmatic_field_update or self._hydrating_form or self._loading_audit:
            return
        self._clear_recent_machine_audit_decision_if_machine_changed(
            self._field_value(self.audit_fields["Press/Machine #"])
        )
        if self._machine_lookup_timer is not None and self._machine_lookup_timer.isActive():
            self._pending_machine_lookup_text = self._field_value(self.audit_fields["Press/Machine #"])
            self._machine_lookup_timer.start()

    def run_machine_lookup(self, *args, immediate: bool = False, allow_existing_audit_prompt: bool = True) -> None:
        machine_text = self._field_value(self.audit_fields["Press/Machine #"])
        programmatic_reason = self._machine_lookup_programmatic_suppression_reason()
        if programmatic_reason:
            self._log_machine_audit_selection_event(
                "machine_audit_selection_suppressed",
                machine_text,
                reason=programmatic_reason,
            )
            return
        if self._consume_recent_machine_audit_lookup_suppression(machine_text):
            return
        self._clear_copied_tool_if_duplicate_press_changed(machine_text)
        self._machine_lookup_extra_note = ""
        self._pending_machine_lookup_text = machine_text
        self._pending_machine_lookup_allow_existing_audit_prompt = allow_existing_audit_prompt
        if immediate or self._machine_lookup_timer is None:
            if self._machine_lookup_timer is not None:
                self._machine_lookup_timer.stop()
            self._start_machine_lookup_request()
            return
        self.lookup_note_label.setText(f"Looking up machine {machine_text}...")
        self._machine_lookup_timer.start()

    def _start_machine_lookup_request(self) -> None:
        machine_text = str(
            self._pending_machine_lookup_text or self._field_value(self.audit_fields["Press/Machine #"])
        ).strip()
        self._machine_lookup_generation += 1
        generation = self._machine_lookup_generation
        form_snapshot = self._current_audit_form_values()
        allow_existing_audit_prompt = bool(self._pending_machine_lookup_allow_existing_audit_prompt)
        suppression_reason = self._machine_audit_selection_suppression_reason(
            machine_text,
            user_confirmed=True,
            allow_existing_audit_prompt=allow_existing_audit_prompt,
        )
        if suppression_reason:
            self._log_machine_audit_selection_event(
                "machine_audit_selection_suppressed",
                machine_text,
                reason=suppression_reason,
            )
            allow_existing_audit_prompt = False
        context = {
            "current_audit_id": self._field_value(self.audit_fields.get("Audit ID")),
            "current_audit_mode": self._current_audit_mode,
            "allow_existing_audit_prompt": allow_existing_audit_prompt,
        }
        self.lookup_note_label.setText(f"Looking up machine {machine_text}...")

        def _lookup():
            return self._collect_machine_lookup_result(
                self.config.project_root,
                generation,
                machine_text,
                form_snapshot,
                context,
                allow_existing_audit_prompt=allow_existing_audit_prompt,
            )

        get_task_manager().run_task(
            TaskRequest(
                id=f"audit_machine_lookup_{generation}",
                name="Machine Lookup",
                category="page_refresh",
                callable=_lookup,
            ),
            on_finished=self._apply_machine_lookup_task_result,
        )

    def _collect_machine_reference_lookup_payload(
        self,
        project_root: str,
        machine_text: str,
        form_snapshot: dict[str, str],
    ) -> dict[str, object]:
        try:
            result = lookup_machine(project_root, machine_text)
        except ValueError as exc:
            message = str(exc)
            return {"action": "invalid", "errors": [message], "warnings": [message]}

        proposed_entry = dict(form_snapshot)
        proposed_entry["Press/Machine #"] = str(result.machine_number)
        if not str(proposed_entry.get("Robot Type") or "").strip() and result.robot_type_suggestion:
            proposed_entry["Robot Type"] = result.robot_type_suggestion
        if (
            not str(proposed_entry.get("Robot Model/Controller") or "").strip()
            and result.robot_model_controller_suggestion
        ):
            proposed_entry["Robot Model/Controller"] = result.robot_model_controller_suggestion
        try:
            robot_info = load_robot_info_for_audit_entry(project_root, proposed_entry)
        except Exception:
            robot_info = None
        return {"action": "lookup", "result": result, "robot_info": robot_info}

    def _collect_existing_machine_audit_decision_payload(
        self,
        project_root: str,
        machine_text: str,
        context: dict[str, object],
    ) -> dict[str, object]:
        machine_tokens = parse_machine_tokens(machine_text)
        if not machine_tokens:
            return {}
        requested = set(machine_tokens)
        matches = find_existing_audits_for_machine(project_root, machine_text)
        all_matches = [
            option
            for option in list_audit_options(project_root)
            if requested & set(self._audit_option_machine_tokens(option))
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
        current_id = str(context.get("current_audit_id") or "")
        current_mode = str(context.get("current_audit_mode") or "")
        if len(matches) == 1 and matches[0].audit_id == current_id and current_mode == "edit":
            return {}
        if matches:
            return {
                "action": "existing_matches",
                "matches": matches,
                "message": f"Existing audits found for this machine.{compatible_note}",
            }
        if compatible_matches:
            return {
                "extra_note": (
                    f"Machine {machine} has compatible coverage entries, "
                    "but no physical audit yet. Continuing with a new physical audit."
                )
            }
        return {}

    def _collect_machine_lookup_result(
        self,
        project_root: str,
        generation: int,
        machine_text: str,
        form_snapshot: dict[str, str],
        context: dict[str, object],
        *,
        allow_existing_audit_prompt: bool = True,
    ) -> dict[str, object]:
        started = time.perf_counter()
        payload: dict[str, object] = {
            "generation": generation,
            "machine_text": machine_text,
            "allow_existing_audit_prompt": bool(allow_existing_audit_prompt),
            "cache_hit": False,
            "action": "lookup",
            "warnings": [],
            "errors": [],
            "compatible_note": "",
            "extra_note": "",
            "matches": [],
            "result": None,
            "robot_info": None,
        }
        existing_decision_payload = {}
        if allow_existing_audit_prompt:
            existing_decision_payload = self._collect_existing_machine_audit_decision_payload(
                project_root,
                machine_text,
                context,
            )
            if existing_decision_payload.get("action") == "existing_matches":
                payload.update(existing_decision_payload)
                log_performance(
                    project_root,
                    "audit.machine_lookup",
                    time.perf_counter() - started,
                    source="audit",
                    page_tool="audit",
                    details={"cache_status": "miss", "action": "existing_matches"},
                )
                return payload
            payload["extra_note"] = str(existing_decision_payload.get("extra_note") or "")

        cache_key = _machine_lookup_cache_key(project_root, machine_text)
        cached = _MACHINE_LOOKUP_RESULT_CACHE.get(cache_key)
        if cached is not None:
            payload.update(dict(cached))
            payload.update(
                {
                    "generation": generation,
                    "machine_text": machine_text,
                    "allow_existing_audit_prompt": bool(allow_existing_audit_prompt),
                    "cache_hit": True,
                }
            )
            if existing_decision_payload.get("extra_note"):
                payload["extra_note"] = str(existing_decision_payload.get("extra_note") or "")
            log_performance(
                project_root,
                "audit.machine_lookup",
                time.perf_counter() - started,
                source="audit",
                page_tool="audit",
                details={"cache_status": "hit"},
            )
            return payload

        payload.update(self._collect_machine_reference_lookup_payload(project_root, machine_text, form_snapshot))
        if payload.get("action") == "invalid":
            log_performance(
                project_root,
                "audit.machine_lookup",
                time.perf_counter() - started,
                source="audit",
                page_tool="audit",
                details={"cache_status": "miss", "action": "invalid"},
                success=False,
                error_count=1,
            )
            _MACHINE_LOOKUP_RESULT_CACHE[cache_key] = {
                key: value
                for key, value in payload.items()
                if key not in {"generation", "machine_text", "allow_existing_audit_prompt", "cache_hit", "extra_note"}
            }
            return payload
        log_performance(
            project_root,
            "audit.machine_lookup",
            time.perf_counter() - started,
            source="audit",
            page_tool="audit",
            details={"cache_status": "miss", "action": "lookup"},
        )
        _MACHINE_LOOKUP_RESULT_CACHE[cache_key] = {
            key: value
            for key, value in payload.items()
            if key not in {"generation", "machine_text", "allow_existing_audit_prompt", "cache_hit", "extra_note"}
        }
        return payload

    def _apply_machine_lookup_task_result(self, task_result) -> None:
        if not task_result.ok:
            self.lookup_note_label.setText(task_result.error or task_result.message)
            return
        payload = dict(task_result.result_data or {})
        generation = int(payload.get("generation") or 0)
        machine_text = str(payload.get("machine_text") or "")
        if (
            generation != self._machine_lookup_generation
            or self._field_value(self.audit_fields["Press/Machine #"]) != machine_text
        ):
            return
        action = str(payload.get("action") or "lookup")
        if action == "invalid":
            warnings = [str(item) for item in payload.get("warnings", [])]
            errors = [str(item) for item in payload.get("errors", [])]
            self.current_lookup_result = None
            self._lookup_part_index = None
            self._lookup_conflict_warnings = []
            self.lookup_note_label.setText("Invalid machine number.")
            self._set_capacity_choices([])
            self._set_machine_audit_matches([])
            self.result_panel.show_text(errors[0] if errors else "Invalid machine number.")
            self._log_machine_lookup(machine_text, None, warnings, errors, False, False, False)
            return
        if action == "load_existing":
            audit_id = str(payload.get("audit_id") or "")
            confirm_unsaved = not self.is_clean_new_form_or_lookup_only()
            self.load_existing_audit(
                audit_id,
                loaded_message=str(payload.get("message") or f"Existing physical audit found. Loaded {audit_id}."),
                confirm_unsaved=confirm_unsaved,
            )
            return
        if action in {"multiple_matches", "existing_matches"}:
            matches = list(payload.get("matches") or [])
            message = str(payload.get("message") or "Existing audits found for this machine.")
            suppression_reason = self._machine_audit_selection_suppression_reason(
                machine_text,
                user_confirmed=True,
                allow_existing_audit_prompt=bool(payload.get("allow_existing_audit_prompt", True)),
            )
            if suppression_reason:
                self._log_machine_audit_selection_event(
                    "machine_audit_selection_suppressed",
                    machine_text,
                    reason=suppression_reason,
                )
                return
            self._handle_existing_machine_audit_selection(machine_text, matches, message=message)
            return

        self._apply_machine_reference_lookup_payload(machine_text, payload)

    def _apply_machine_reference_lookup_payload(self, machine_text: str, payload: dict[str, object]) -> bool:
        result = payload.get("result")
        if not isinstance(result, PressLookupResult):
            self.lookup_note_label.setText("Machine lookup did not return a usable result.")
            return False

        previous_dialog_suppression = self._suppress_machine_audit_selection_dialog
        previous_autofilling = self._autofilling_fields
        self._suppress_machine_audit_selection_dialog = True
        self._autofilling_fields = True
        try:
            self.current_lookup_result = result
            self._lookup_part_index = None
            self._lookup_conflict_warnings = []
            self._set_field_value(self.audit_fields["Press/Machine #"], str(result.machine_number))

            robot_type_filled = self._apply_suggestion("Robot Type", result.robot_type_suggestion)
            robot_model_filled = self._apply_suggestion(
                "Robot Model/Controller", result.robot_model_controller_suggestion
            )
            tool_filled = self._apply_tool_number_suggestion(result, force=False)
            robot_info_loaded = self._apply_robot_info_fields(payload.get("robot_info"), force=False)
            part_filled = False
            if len(result.part_options) == 1:
                self._lookup_part_index = 0
                option = result.part_options[0]
                part_filled = self._apply_part_suggestion(option, force=False)
            warnings = [*result.warnings, *self._lookup_conflict_warnings]
            lookup_message = self._lookup_status_message(
                result, robot_type_filled or robot_model_filled, part_filled or tool_filled, warnings
            )
            extra_note = str(payload.get("extra_note") or "")
            if extra_note:
                lookup_message = f"{lookup_message} {extra_note}"
            if robot_info_loaded:
                lookup_message = f"{lookup_message} Robot info loaded from Robot_Info.xlsx."
            self.lookup_note_label.setText(lookup_message)
            self._set_capacity_choices(result.capacity_part_rows)
            self._set_machine_audit_matches([])
            self._log_machine_lookup(
                machine_text,
                result,
                warnings,
                result.errors,
                robot_type_filled,
                robot_model_filled,
                part_filled,
                tool_filled,
            )
        finally:
            self._autofilling_fields = previous_autofilling
            self._suppress_machine_audit_selection_dialog = previous_dialog_suppression
        return True

    def _handle_existing_machine_audit_selection(self, machine_text: str, matches, *, message: str = "") -> bool:
        if not matches:
            self._set_machine_audit_matches([])
            return False
        machine = ", ".join(parse_machine_tokens(machine_text)) or str(machine_text or "").strip()
        suppression_reason = self._machine_audit_selection_suppression_reason(
            machine,
            user_confirmed=True,
            allow_existing_audit_prompt=True,
        )
        if suppression_reason:
            self._log_machine_audit_selection_event(
                "machine_audit_selection_suppressed",
                machine,
                reason=suppression_reason,
            )
            return False
        self._set_machine_audit_matches([])
        self.lookup_note_label.setText(message or "Existing audits found for this machine.")
        self.result_panel.show_text(
            "Existing audits found for this machine. Continue an existing audit, or start a new audit for this machine."
        )
        self._log_machine_audit_selection_event(
            "machine_audit_selection_dialog_opened",
            machine,
            match_count=len(matches),
        )
        self._machine_audit_selection_in_progress = True
        try:
            selection = self._choose_existing_machine_audit_action(machine, matches)
        finally:
            self._machine_audit_selection_in_progress = False
        if selection.action == ExistingMachineAuditsDialog.ACTION_CONTINUE:
            audit_id = str(selection.audit_id or "").strip()
            if not audit_id:
                self.result_panel.show_text("Select an audit before continuing.")
                return True
            self._log_machine_audit_selection_event(
                "machine_audit_selection_continue_existing",
                machine,
                audit_id=audit_id,
            )
            previous_loading_from_dialog = self._loading_existing_audit_from_machine_dialog
            previous_dialog_suppression = self._suppress_machine_audit_selection_dialog
            self._loading_existing_audit_from_machine_dialog = True
            self._suppress_machine_audit_selection_dialog = True
            try:
                loaded = self.load_existing_audit(
                    audit_id,
                    loaded_message=f"Existing physical audit found for Machine {machine}. Loaded {audit_id}.",
                    confirm_unsaved=not self.is_clean_new_form_or_lookup_only(),
                )
            finally:
                self._loading_existing_audit_from_machine_dialog = previous_loading_from_dialog
                self._suppress_machine_audit_selection_dialog = previous_dialog_suppression
                self._suppress_next_machine_lookup_after_audit_workflow(
                    machine,
                    ExistingMachineAuditsDialog.ACTION_CONTINUE,
                )
            if not loaded:
                self.lookup_note_label.setText("Existing audit selection canceled.")
            return True
        if selection.action == ExistingMachineAuditsDialog.ACTION_START_NEW:
            self._log_machine_audit_selection_event(
                "machine_audit_selection_start_new",
                machine,
                match_count=len(matches),
            )
            self.start_new_audit_for_machine(machine)
            return True
        self._log_machine_audit_selection_event(
            "machine_audit_selection_cancelled",
            machine,
            match_count=len(matches),
        )
        self._suppress_next_machine_lookup_after_audit_workflow(
            machine,
            ExistingMachineAuditsDialog.ACTION_CANCEL,
        )
        self.lookup_note_label.setText("Existing audit selection canceled.")
        self.result_panel.show_text("Existing audit selection canceled. The current form was left unchanged.")
        return True

    def _choose_existing_machine_audit_action(self, machine_number: str, matches) -> ExistingAuditSelection:
        dialog = ExistingMachineAuditsDialog(machine_number, matches, self)
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            return dialog.selection()
        return ExistingAuditSelection(ExistingMachineAuditsDialog.ACTION_CANCEL)

    def start_new_audit_for_machine(self, machine_number: str) -> bool:
        machine_text = str(machine_number or "").strip()
        if not machine_text:
            return False
        if not self.is_clean_new_form_or_lookup_only() and not self._confirm_unsaved_audit_changes("start a new audit"):
            return False
        self._machine_lookup_generation += 1
        previous_starting_new = self._starting_new_audit_for_machine
        previous_dialog_suppression = self._suppress_machine_audit_selection_dialog
        previous_prompt_suppressed_machine = self._machine_audit_prompt_suppressed_for_machine
        self._starting_new_audit_for_machine = True
        self._suppress_machine_audit_selection_dialog = True
        self._machine_audit_prompt_suppressed_for_machine = machine_text
        previous_state = self._begin_hydrating_form("start_new_audit_for_machine")
        try:
            self._reset_audit_form_fields(show_generated_message=False)
            self._set_field_value(self.audit_fields["Press/Machine #"], machine_text)
            reference_payload = self._collect_machine_reference_lookup_payload(
                self.config.project_root,
                machine_text,
                self._current_audit_form_values(),
            )
            if reference_payload.get("action") == "invalid":
                errors = [str(item) for item in reference_payload.get("errors", [])]
                self.lookup_note_label.setText("Invalid machine number.")
                self.result_panel.show_text(errors[0] if errors else "Invalid machine number.")
            else:
                self._apply_machine_reference_lookup_payload(machine_text, reference_payload)
            self._editing_audit_id = None
            self._current_loaded_audit_id = None
            self._current_audit_mode = "new"
            self._loaded_empty_only_fields = None
            self.audit_view_mode_combo.blockSignals(True)
            self.audit_view_mode_combo.setCurrentText("Full Audit")
            self.audit_view_mode_combo.setEnabled(False)
            self.audit_view_mode_combo.blockSignals(False)
            self._set_machine_audit_matches([])
            self._refresh_field_tag_indicators()
            self._update_audit_field_visibility()
        finally:
            self._end_hydrating_form(previous_state, "start_new_audit_for_machine")
            self._machine_audit_prompt_suppressed_for_machine = previous_prompt_suppressed_machine
            self._suppress_machine_audit_selection_dialog = previous_dialog_suppression
            self._starting_new_audit_for_machine = previous_starting_new
        audit_id = self._field_value(self.audit_fields.get("Audit ID"))
        machine = self._field_value(self.audit_fields.get("Press/Machine #")) or machine_text
        self._mark_audit_form_baseline("start_new_audit_for_machine", clean_new_form=True)
        self._suppress_next_machine_lookup_after_audit_workflow(
            machine,
            ExistingMachineAuditsDialog.ACTION_START_NEW,
        )
        self.result_panel.show_text(
            f"Started a new audit for Machine {machine} with Audit ID {audit_id}. "
            "Existing audits were not changed, and old EOAT/tool data was not copied."
        )
        return True

    def _apply_robot_info_fields(self, robot_info, *, force: bool) -> bool:
        if not robot_info:
            if ROBOT_INTERCHANGEABLE_CIRCUITS_FIELD in self.audit_fields:
                widget = self.audit_fields[ROBOT_INTERCHANGEABLE_CIRCUITS_FIELD]
                if force or not self._field_value(widget):
                    self._set_field_value(widget, "0")
            return False
        for field in ROBOT_INFO_FIELDS:
            if field not in self.audit_fields:
                continue
            widget = self.audit_fields[field]
            if force or not self._field_value(widget):
                self._set_field_value(widget, workbook_to_ui_value(robot_info.get(field, "")))
        return True

    def _load_or_offer_existing_audit_for_machine(self, machine_text: str) -> bool:
        self._machine_lookup_extra_note = ""
        if not parse_machine_tokens(machine_text):
            self._set_machine_audit_matches([])
            return False
        suppression_reason = self._machine_audit_selection_suppression_reason(
            machine_text,
            user_confirmed=True,
            allow_existing_audit_prompt=True,
        )
        if suppression_reason:
            self._log_machine_audit_selection_event(
                "machine_audit_selection_suppressed",
                machine_text,
                reason=suppression_reason,
            )
            self._set_machine_audit_matches([])
            return False
        payload = self._collect_existing_machine_audit_decision_payload(
            self.config.project_root,
            machine_text,
            {
                "current_audit_id": self._field_value(self.audit_fields["Audit ID"]),
                "current_audit_mode": self._current_audit_mode,
            },
        )
        if payload.get("action") == "existing_matches":
            return self._handle_existing_machine_audit_selection(
                machine_text,
                list(payload.get("matches") or []),
                message=str(payload.get("message") or "Existing audits found for this machine."),
            )
        if payload.get("extra_note"):
            note = str(payload.get("extra_note") or "")
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
            self._lookup_conflict_warnings.append(
                f"Reference lookup found a different {field} suggestion. Existing value was preserved."
            )
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
        previous_dialog_suppression = self._suppress_machine_audit_selection_dialog
        self._suppress_machine_audit_selection_dialog = True
        self.capacity_part_combo.blockSignals(True)
        try:
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
        finally:
            self.capacity_part_combo.blockSignals(False)
            self._suppress_machine_audit_selection_dialog = previous_dialog_suppression

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
        questions.setPlainText(
            "Suggested questions:\n\n" + "\n".join(f"- {question}" for question in INTERVIEW_QUESTIONS)
        )
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
