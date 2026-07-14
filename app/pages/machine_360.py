from __future__ import annotations

import time
from pathlib import Path
from typing import Any

try:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QProgressBar,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QTimer = None
    QAbstractItemView = QHBoxLayout = QLabel = QLineEdit = QProgressBar = QPushButton = QTableWidget = (
        QTableWidgetItem
    ) = QTextEdit = QVBoxLayout = QWidget = None

from app.page_tasks import run_tool_background
from app.task_runner import TaskRequest, get_task_manager
from app.widgets.annotation_target_navigator import AnnotationTargetNavigator
from core.action_items import add_action_item
from core.logging import log_activity_event
from core.machine_360 import (
    Machine360Action,
    Machine360Context,
    build_machine_360_context,
    generate_machine_360_summary,
)
from core.openers import open_path
from core.performance import log_performance
from core.pm_checklists import generate_pm_checklists
from core.validation import run_foundation_validation


class _DetailResultPanel:
    def __init__(self, page: Machine360Page):
        self.page = page

    def show_text(self, text: str) -> None:
        self.page._set_action_result(text)

    def show_result(self, result) -> None:
        self.page._set_action_result(result.to_markdown() if hasattr(result, "to_markdown") else str(result))


class Machine360Page(QWidget):
    SUMMARY_COLUMNS = ["Section", "Metric", "Value"]
    AUDIT_COLUMNS = ["Audit ID", "Entry Type", "Tool #", "EOAT Type", "Status", "Priority", "Source Audit"]
    ACTION_BUTTONS = [
        ("open_audit", "Open Audit"),
        ("open_press_view", "Open Press View"),
        ("add_note", "Add Note"),
        ("add_tag", "Add Tag"),
        ("create_follow_up", "Create Follow-Up"),
        ("run_machine_validation", "Run Machine Validation"),
        ("generate_machine_summary", "Generate Machine Summary"),
        ("open_photo_folder", "Open Photo Folder"),
        ("generate_pm_checklist", "Generate PM Checklist"),
        ("generate_work_instruction_draft", "Work Instruction Draft"),
    ]

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.context: Machine360Context | None = None
        self.navigator = AnnotationTargetNavigator(self)
        self.result_panel = _DetailResultPanel(self)
        self.action_buttons: dict[str, QPushButton] = {}
        self.last_action_payload: dict[str, Any] = {}
        self._suppress_text_refresh = False
        self._search_generation = 0
        self._search_in_progress = False
        self._current_search_machine = ""
        self._refresh_timer = QTimer(self) if QTimer is not None else None
        if self._refresh_timer is not None:
            self._refresh_timer.setSingleShot(True)
            self._refresh_timer.setInterval(400)
            self._refresh_timer.timeout.connect(self.refresh)

        layout = QVBoxLayout(self)
        heading = QLabel("Machine 360")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        controls = QHBoxLayout()
        self.machine_edit = QLineEdit()
        self.machine_edit.setPlaceholderText("Press/Machine #")
        self.machine_edit.returnPressed.connect(self.refresh)
        self.machine_edit.textChanged.connect(self._schedule_refresh)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(QLabel("Machine"))
        controls.addWidget(self.machine_edit)
        controls.addWidget(self.refresh_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        status_row = QHBoxLayout()
        self.last_refreshed_label = QLabel("Last refreshed: Unknown")
        self.data_source_label = QLabel("Data source: Unknown")
        self.search_status_label = QLabel("Idle")
        self.search_progress = QProgressBar()
        self.search_progress.setRange(0, 0)
        self.search_progress.setFixedWidth(130)
        self.search_progress.hide()
        self.status_label = QLabel("")
        status_row.addWidget(self.last_refreshed_label)
        status_row.addWidget(self.data_source_label)
        status_row.addStretch(1)
        status_row.addWidget(self.search_status_label)
        status_row.addWidget(self.search_progress)
        status_row.addWidget(self.status_label)
        layout.addLayout(status_row)

        action_row = QHBoxLayout()
        for action_id, label in self.ACTION_BUTTONS:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, selected_action=action_id: self.run_action(selected_action))
            self.action_buttons[action_id] = button
            action_row.addWidget(button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.summary_table = QTableWidget(0, len(self.SUMMARY_COLUMNS))
        self.summary_table.setHorizontalHeaderLabels(self.SUMMARY_COLUMNS)
        self.summary_table.setAlternatingRowColors(True)
        if QAbstractItemView is not None:
            self.summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.summary_table)

        self.audit_table = QTableWidget(0, len(self.AUDIT_COLUMNS))
        self.audit_table.setHorizontalHeaderLabels(self.AUDIT_COLUMNS)
        self.audit_table.setAlternatingRowColors(True)
        if QAbstractItemView is not None:
            self.audit_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.audit_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.audit_table, stretch=1)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMinimumHeight(220)
        layout.addWidget(self.detail_text, stretch=1)
        self._update_action_buttons()

    def refresh(self, *_args) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
        machine = self.machine_edit.text().strip()
        if not machine:
            self._search_generation += 1
            self._search_in_progress = False
            self._current_search_machine = ""
            self._set_search_busy(False, "No machine selected")
            if self.context is None:
                self._clear_context_tables()
                self.detail_text.setPlainText("No machine selected.")
                self._update_action_buttons()
            return
        self._start_machine_search(machine)

    def refresh_data(self) -> None:
        self.refresh()

    def select_machine(self, machine: str) -> bool:
        self._suppress_text_refresh = True
        try:
            self.machine_edit.setText(str(machine or "").strip())
        finally:
            self._suppress_text_refresh = False
        self.refresh()
        return bool(str(machine or "").strip())

    def on_project_root_changed(self, config) -> None:
        self.config = config
        self.refresh()

    def action_payload(self, action_id: str) -> dict[str, Any]:
        action = self._action(action_id)
        return action.to_dict() if action is not None else {}

    def run_action(self, action_id: str) -> None:
        action = self._action(action_id)
        if action is None:
            self._set_action_result("Refresh Machine 360 before running this action.")
            return
        self.last_action_payload = action.to_dict()
        if not action.available:
            self._set_action_result(action.help_text or f"{action.label} is not available for this machine.")
            return
        machine = str(action.payload.get("machine") or self.context.machine_number if self.context else "").strip()
        if action_id == "open_audit":
            self._open_audit(action)
        elif action_id == "open_press_view":
            self._open_press_view(machine)
        elif action_id == "add_note":
            self._navigate_with_message("notes", f"Ready to add a note for {self._display_name()}.")
        elif action_id == "add_tag":
            self._navigate_with_message("tags", f"Ready to add a tag for {self._display_name()}.")
        elif action_id == "create_follow_up":
            self._create_follow_up(machine)
        elif action_id == "run_machine_validation":
            self._run_validation()
        elif action_id == "generate_machine_summary":
            self._generate_summary()
        elif action_id == "open_photo_folder":
            self._open_photo_folder(action)
        elif action_id == "generate_pm_checklist":
            self._generate_pm_checklist(machine)
        else:
            self._set_action_result(action.help_text or f"{action.label} is not wired to a command yet.")

    def _schedule_refresh(self, *_args) -> None:
        if self._suppress_text_refresh:
            return
        if self._refresh_timer is None:
            return
        self._refresh_timer.start()

    def _start_machine_search(self, machine: str) -> None:
        self._search_generation += 1
        generation = self._search_generation
        self._search_in_progress = True
        self._current_search_machine = machine
        started = time.perf_counter()
        project_root = str(self.config.project_root)
        self._set_search_busy(True, f"Searching Machine {machine}...")
        self._log_search_event(
            "machine_360_search_started",
            machine=machine,
            generation=generation,
            duration_seconds=0.0,
            stale=False,
        )
        get_task_manager().run_task(
            TaskRequest(
                id=f"machine_360_search_{generation}",
                name=f"Machine 360 Search {machine}",
                category="page_refresh",
                callable=Machine360Page._build_context_for_search,
                args=(project_root, machine, generation),
            ),
            on_finished=lambda result, expected_generation=generation, started_at=started: self._apply_search_result(
                result,
                expected_generation,
                started_at,
            ),
        )

    @staticmethod
    def _build_context_for_search(project_root: str, machine: str, generation: int) -> dict[str, Any]:
        context = build_machine_360_context(project_root, machine)
        return {"generation": generation, "machine": machine, "context": context}

    def _apply_search_result(self, task_result, expected_generation: int, started_at: float) -> None:
        elapsed = time.perf_counter() - started_at
        payload = task_result.result_data if isinstance(task_result.result_data, dict) else {}
        machine = str(payload.get("machine") or self._current_search_machine or self.machine_edit.text().strip())
        stale = (
            expected_generation != self._search_generation
            or int(payload.get("generation") or expected_generation) != self._search_generation
        )
        if stale:
            self._log_search_event(
                "machine_360_search_finished",
                machine=machine,
                generation=expected_generation,
                duration_seconds=elapsed,
                stale=True,
            )
            return
        self._search_in_progress = False
        if not task_result.ok:
            safe_error = self._safe_error(task_result.error or task_result.message)
            self._set_search_busy(False, f"Search failed: {safe_error}")
            self.detail_text.setPlainText(f"Search failed: {safe_error}")
            self._update_action_buttons()
            self._log_search_event(
                "machine_360_search_failed",
                machine=machine,
                generation=expected_generation,
                duration_seconds=elapsed,
                stale=False,
                error=safe_error,
            )
            return
        context = payload.get("context")
        if not isinstance(context, Machine360Context):
            safe_error = "Machine 360 search returned no usable context."
            self._set_search_busy(False, f"Search failed: {safe_error}")
            self.detail_text.setPlainText(f"Search failed: {safe_error}")
            self._update_action_buttons()
            self._log_search_event(
                "machine_360_search_failed",
                machine=machine,
                generation=expected_generation,
                duration_seconds=elapsed,
                stale=False,
                error=safe_error,
            )
            return
        self.context = context
        self._populate_context(context)
        self._set_search_busy(False, f"Loaded Machine {context.machine_number or machine}")
        self._log_search_event(
            "machine_360_search_finished",
            machine=machine,
            generation=expected_generation,
            duration_seconds=elapsed,
            stale=False,
            physical_audit_count=int(context.metrics.get("physical_audit_count") or 0),
            compatible_entry_count=int(context.metrics.get("compatible_entry_count") or 0),
            open_item_count=int(context.metrics.get("open_item_count") or 0),
        )

    def _set_search_busy(self, busy: bool, text: str) -> None:
        self.search_status_label.setText(text)
        self.search_progress.setVisible(bool(busy))
        self.refresh_button.setText("Searching..." if busy else "Refresh")
        self.refresh_button.setEnabled(not busy)

    def _clear_context_tables(self) -> None:
        self.summary_table.setRowCount(0)
        self.audit_table.setRowCount(0)

    def _safe_error(self, message: str) -> str:
        text = str(message or "Unknown error").replace("\n", " ").strip()
        return text[:180] or "Unknown error"

    def _log_search_event(
        self,
        event_name: str,
        *,
        machine: str,
        generation: int,
        duration_seconds: float,
        stale: bool,
        physical_audit_count: int = 0,
        compatible_entry_count: int = 0,
        open_item_count: int = 0,
        error: str = "",
    ) -> None:
        payload = {
            "machine_number": machine,
            "generation": generation,
            "duration_seconds": round(duration_seconds, 4),
            "physical_audit_count": physical_audit_count,
            "compatible_entry_count": compatible_entry_count,
            "open_item_count": open_item_count,
            "stale_ignored": bool(stale),
        }
        if error:
            payload["error"] = error
        log_activity_event(self.config.project_root, event_name, payload)
        log_performance(
            self.config.project_root,
            event_name,
            duration_seconds,
            source="machine_360",
            page_tool="machine_360",
            details=payload,
            success=not error,
            error_count=1 if error else 0,
        )

    def _populate_context(self, context: Machine360Context) -> None:
        self.last_refreshed_label.setText(f"Last refreshed: {context.last_refreshed or 'Unknown'}")
        self.data_source_label.setText(f"Data source: {self._data_source_label(context)}")
        self.status_label.setText(
            f"{context.metrics.get('physical_audit_count', 0)} physical / {context.metrics.get('compatible_entry_count', 0)} compatible"
        )
        summary_rows = self._summary_rows(context)
        self.summary_table.setRowCount(len(summary_rows))
        for row, (section, metric, value) in enumerate(summary_rows):
            for col, text in enumerate([section, metric, self._format_value(value)]):
                item = QTableWidgetItem(text)
                if col == 2:
                    item.setToolTip(text)
                self.summary_table.setItem(row, col, item)
        self.summary_table.resizeColumnsToContents()

        audit_rows: list[tuple[str, dict[str, Any]]] = [("Audited", row) for row in context.physical_audits]
        audit_rows.extend(("Compatible", row) for row in context.compatible_entries)
        self.audit_table.setRowCount(len(audit_rows))
        for row_index, (default_type, row) in enumerate(audit_rows):
            values = [
                row.get("Audit ID", ""),
                row.get("Entry Type", default_type) or default_type,
                row.get("Tool #", ""),
                row.get("EOAT Type", ""),
                row.get("Status", ""),
                row.get("Priority", ""),
                row.get("Source Audit ID", ""),
            ]
            for col, value in enumerate(values):
                self.audit_table.setItem(row_index, col, QTableWidgetItem(str(value or "")))
        self.audit_table.resizeColumnsToContents()
        self.detail_text.setPlainText(self._details_text(context))
        self._update_action_buttons()

    def _summary_rows(self, context: Machine360Context) -> list[tuple[str, str, Any]]:
        return [
            ("Machine Identity", "Machine", context.display_name),
            ("Machine Identity", "Plant / Area", context.machine_identity.get("plant_area")),
            ("Machine Identity", "Robot", context.machine_identity.get("robot_type")),
            ("Physical Audit Summary", "Physical audits", context.metrics.get("physical_audit_count", 0)),
            ("Physical Audit Summary", "Guided audit gaps", context.metrics.get("guided_gap_count", 0)),
            ("Fit Check Summary", "Compatible assigned here", context.metrics.get("compatible_entry_count", 0)),
            ("Fit Check Summary", "Linked compatible entries", context.metrics.get("linked_compatible_count", 0)),
            ("EOAT Tooling Summary", "Tools", context.tooling_summary.get("tools")),
            ("Pneumatic Circuits", "Vacuum circuits", context.pneumatic_circuits.get("vacuum_circuits")),
            ("Sensors and Detection", "Sensor types", context.sensors_detection.get("sensor_types")),
            ("Mechanical / Routing", "Tubing condition", context.mechanical_routing.get("tubing_condition")),
            ("Reliability / Performance", "Open items", context.metrics.get("open_item_count", 0)),
            ("Documentation / Photos", "Photo index rows", context.metrics.get("photo_index_rows", 0)),
            (
                "Documentation / Photos",
                "Missing required evidence",
                context.metrics.get("missing_required_photo_evidence", 0),
            ),
            ("Risk / FMEA", "Highest RPN", context.risk_fmea.get("highest_rpn", 0)),
            ("KPI Signals", "Downtime minutes", context.kpi_signals.get("downtime_minutes", 0)),
            ("PM Status", "Due now", context.pm_status.get("due_now", 0)),
        ]

    def _details_text(self, context: Machine360Context) -> str:
        lines = [context.display_name, ""]
        lines.append(f"Last refreshed: {context.last_refreshed or 'Unknown'}")
        lines.append(f"Data sources: {self._data_source_label(context)}")
        lines.append("")
        if context.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in context.warnings)
            lines.append("")
        lines.append("Recommended Actions:")
        lines.extend(f"- {action}" for action in context.recommended_actions)
        lines.append("")
        for title, section in [
            ("Machine Identity", context.machine_identity),
            ("Physical Audit Summary", context.physical_audit_summary),
            ("Fit Check Summary", context.compatibility_summary),
            ("EOAT Tooling Summary", context.tooling_summary),
            ("Pneumatic Circuits", context.pneumatic_circuits),
            ("Sensors and Detection", context.sensors_detection),
            ("Mechanical / Routing", context.mechanical_routing),
            ("Reliability / Performance", context.reliability_performance),
            (
                "Documentation / Photos",
                {k: v for k, v in context.documentation_photos.items() if k != "evidence_items"},
            ),
            (
                "Open Items",
                {"count": len(context.open_items), "items": [item.get("title", "") for item in context.open_items[:8]]},
            ),
            ("Risk / FMEA", context.risk_fmea),
            ("KPI Signals", context.kpi_signals),
            ("PM Status", {k: v for k, v in context.pm_status.items() if k != "items"}),
        ]:
            lines.append(f"{title}:")
            if section:
                lines.extend(f"- {key}: {self._format_value(value)}" for key, value in section.items())
            else:
                lines.append("- No data available.")
            lines.append("")
        if context.validation_findings:
            lines.append("Validation Findings From Latest Report:")
            lines.extend(f"- {item.get('severity')}: {item.get('message')}" for item in context.validation_findings[:8])
            lines.append("")
        if context.reports:
            lines.append("Reports Referencing This Machine:")
            lines.extend(f"- {item.get('name')} ({item.get('folder')})" for item in context.reports[:8])
            lines.append("")
        return "\n".join(lines).strip()

    def _action(self, action_id: str) -> Machine360Action | None:
        if self.context is None:
            return None
        return next((action for action in self.context.actions if action.action_id == action_id), None)

    def _update_action_buttons(self) -> None:
        actions = {action.action_id: action for action in self.context.actions} if self.context is not None else {}
        for action_id, button in self.action_buttons.items():
            action = actions.get(action_id)
            button.setEnabled(bool(action and action.available))
            if action is not None and action.help_text:
                button.setToolTip(action.help_text)
            elif action is not None and action.requires_expensive_validation:
                button.setToolTip("Runs validation only after this explicit button click.")
            else:
                button.setToolTip("")

    def _open_audit(self, action: Machine360Action) -> None:
        audit_id = str(action.payload.get("audit_id") or "").strip()
        if not audit_id:
            self._set_action_result("No physical audit is available to open for this machine.")
            return
        self.navigator.open_target(
            {
                "target_type": "audit",
                "audit_id": audit_id,
                "machine_id": self.context.machine_number if self.context else "",
            }
        )

    def _open_press_view(self, machine: str) -> None:
        self.navigator.open_target(
            {"target_type": "machine", "machine_id": machine, "target_label": self._display_name()}
        )

    def _create_follow_up(self, machine: str) -> None:
        run_tool_background(
            self.result_panel,
            f"machine_360_follow_up_{machine}",
            "Machine 360 Follow-Up",
            lambda: add_action_item(
                self.config.project_root,
                action_item=f"Review Machine 360 context for {self._display_name()}.",
                related_cell_press=f"Press {machine}" if machine else self._display_name(),
                priority="Medium",
                notes="Created from Machine 360.",
            ),
            modifies_files=True,
            workbook_lock=True,
        )

    def _run_validation(self) -> None:
        run_tool_background(
            self.result_panel,
            "machine_360_validation",
            "Machine 360 Validation",
            lambda: run_foundation_validation(self.config.project_root),
            lambda _result: self.refresh(),
            modifies_files=True,
            workbook_lock=False,
        )

    def _generate_summary(self) -> None:
        run_tool_background(
            self.result_panel,
            "machine_360_summary",
            "Machine 360 Summary",
            lambda: generate_machine_360_summary(
                self.config.project_root, self.context.machine_number if self.context else "", self.context
            ),
            modifies_files=True,
        )

    def _open_photo_folder(self, action: Machine360Action) -> None:
        path = str(action.payload.get("path") or "").strip()
        if not path:
            self._set_action_result("No photo folder is recorded for this machine.")
            return
        result = open_path(Path(path))
        self._set_action_result(result.summary if result.success else result.to_markdown())
        if not result.success:
            self._navigate_with_message(
                "photos", f"Photo folder could not be opened directly for {self._display_name()}."
            )

    def _generate_pm_checklist(self, machine: str) -> None:
        run_tool_background(
            self.result_panel,
            f"machine_360_pm_{machine}",
            "Machine PM Checklist",
            lambda: generate_pm_checklists(self.config.project_root, press=machine, formats=["markdown"]),
            modifies_files=True,
        )

    def _navigate_with_message(self, page_key: str, message: str) -> bool:
        window = self.window()
        navigated = False
        if hasattr(window, "_navigate_to_page"):
            window._navigate_to_page(page_key)
            navigated = True
        elif hasattr(window, "_show_page"):
            window._show_page(page_key)
            navigated = True
        if navigated and hasattr(window, "show_page_message"):
            window.show_page_message(page_key, message)
        else:
            self._set_action_result(message)
        return navigated

    def _set_action_result(self, text: str) -> None:
        if self.context is not None:
            existing = self._details_text(self.context)
            self.detail_text.setPlainText(f"{existing}\n\nAction Result:\n{text}".strip())
        else:
            self.detail_text.setPlainText(text)
        self.status_label.setText(text.splitlines()[0][:120] if text else "")

    def _data_source_label(self, context: Machine360Context) -> str:
        loaded = [source for source in context.data_sources if source.get("status") == "loaded"]
        if not loaded:
            return "Unknown"
        return ", ".join(str(source.get("name") or "source") for source in loaded[:4])

    def _display_name(self) -> str:
        return self.context.display_name if self.context is not None else "selected machine"

    def _format_value(self, value: Any) -> str:
        if isinstance(value, dict):
            if not value:
                return "None"
            return ", ".join(f"{key}: {item}" for key, item in value.items())
        if isinstance(value, list):
            if not value:
                return "None"
            if len(value) > 5:
                return ", ".join(str(item) for item in value[:5]) + f" (+{len(value) - 5} more)"
            return ", ".join(str(item) for item in value)
        if value in (None, ""):
            return "Unknown"
        return str(value)
