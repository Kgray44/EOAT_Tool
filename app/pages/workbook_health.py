from __future__ import annotations

try:
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QComboBox,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QAbstractItemView = QComboBox = QGridLayout = QHBoxLayout = QLabel = QLineEdit = QMessageBox = QPushButton = (
        QTableWidget
    ) = QTableWidgetItem = QVBoxLayout = QWidget = None

from app.event_bus import EVENT_WORKBOOK_VALIDATED, get_event_bus
from app.page_tasks import run_tool_background
from app.widgets.annotation_target_navigator import AnnotationTargetNavigator
from app.widgets.status_card import StatusCard
from app.widgets.tool_run_panel import ToolRunPanel
from core.action_items import add_action_item
from core.annotations.service import AnnotationService
from core.audit_by_press import REFRESH_ACTION_NAME, refresh_audit_by_press_view_action
from core.audit_context import backfill_audit_context
from core.audit_entries import repair_workbook_schema
from core.eoat_ids import assign_missing_eoat_assembly_ids_in_workbook
from core.openers import open_path
from core.paths import resolve_project_paths
from core.validation import run_foundation_validation
from core.validation_findings import (
    ValidationFinding,
    ValidationSeverity,
    findings_from_result,
    repair_suggestions_from_findings,
)
from core.workbook_repairs import SAFE_FIX_IDS, apply_safe_fix, preview_safe_fix_action


class WorkbookHealthPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.findings: list[ValidationFinding] = []
        self._visible_findings: list[ValidationFinding] = []
        self.navigator = AnnotationTargetNavigator(self)
        layout = QVBoxLayout(self)
        heading = QLabel("Workbook Health")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        button_row = QHBoxLayout()
        for label, callback in [
            ("Run Foundation Validation", self.run_validation),
            ("Repair Workbook Schema", self.repair_workbook_schema),
            ("Assign Missing EOAT IDs", self.assign_missing_eoat_ids),
            ("Backfill Audit Context", self.backfill_audit_context),
            (REFRESH_ACTION_NAME, self.refresh_audit_by_press_view),
            ("Open Validation Reports Folder", self.open_validation_reports),
            ("Open Master Workbook", self.open_master_workbook),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            button_row.addWidget(button)
        layout.addLayout(button_row)

        grid = QGridLayout()
        self.cards = {}
        for index, key in enumerate(
            [
                "Workbook Status",
                "Missing Major Headers",
                "Missing Detail Headers",
                "Duplicate Audit IDs",
                "Applicable N/A Warnings",
                "Bench Context Rows",
                "Needs Review Context",
                "Semantic Warnings",
                "Fixable Findings",
                "Last Validation",
            ]
        ):
            card = StatusCard(key)
            self.cards[key] = card
            grid.addWidget(card, index // 5, index % 5)
        layout.addLayout(grid)

        filters = QHBoxLayout()
        self.severity_filter = QComboBox()
        self.severity_filter.addItems(["All Severities", *[severity.value for severity in ValidationSeverity]])
        self.category_filter = QComboBox()
        self.category_filter.addItem("All Categories")
        self.fix_filter = QComboBox()
        self.fix_filter.addItems(["All Findings", "Fix Available"])
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search findings")
        for widget in [self.severity_filter, self.category_filter, self.fix_filter, self.search_edit]:
            filters.addWidget(widget)
        layout.addLayout(filters)

        for widget in [self.severity_filter, self.category_filter, self.fix_filter]:
            widget.currentIndexChanged.connect(self._refresh_findings_table)
        self.search_edit.textChanged.connect(self._refresh_findings_table)

        self.findings_table = QTableWidget(0, 9)
        self.findings_table.setHorizontalHeaderLabels(
            ["Severity", "Category", "Sheet", "Row", "Audit ID", "Machine", "Field", "Message", "Fix"]
        )
        self.findings_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.findings_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.findings_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.findings_table.verticalHeader().setVisible(False)
        self.findings_table.setAlternatingRowColors(True)
        layout.addWidget(self.findings_table, stretch=2)

        self.repair_summary_label = QLabel("Repair suggestions will appear after validation.")
        layout.addWidget(self.repair_summary_label)

        self.repair_suggestions_table = QTableWidget(0, 4)
        self.repair_suggestions_table.setHorizontalHeaderLabels(["Fix", "Safety", "Findings", "Categories"])
        self.repair_suggestions_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.repair_suggestions_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.repair_suggestions_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.repair_suggestions_table.verticalHeader().setVisible(False)
        self.repair_suggestions_table.setAlternatingRowColors(True)
        layout.addWidget(self.repair_suggestions_table, stretch=1)

        action_row = QHBoxLayout()
        for label, callback in [
            ("Open Audit", self.open_selected_audit),
            ("Jump to Field", self.jump_to_selected_field),
            ("Create Annotation", self.create_annotation_from_selected),
            ("Create Follow-Up", self.create_followup_from_selected),
            ("Preview Fix", self.preview_selected_fix),
            ("Apply Safe Fix", self.apply_selected_fix),
            ("Export Report", self.run_validation),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            action_row.addWidget(button)
        layout.addLayout(action_row)

        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)
        self.result_panel.show_text(
            "No validation report selected. Run foundation validation to generate a workbook health report."
        )

    def run_validation(self) -> None:
        run_tool_background(
            self.result_panel,
            "workbook_foundation_validation",
            "Foundation Validation",
            lambda: run_foundation_validation(self.config.project_root),
            self._validation_finished,
            modifies_files=True,
        )

    def refresh_audit_by_press_view(self) -> None:
        run_tool_background(
            self.result_panel,
            "audit_by_press_refresh",
            REFRESH_ACTION_NAME,
            lambda: refresh_audit_by_press_view_action(self.config.project_root),
            modifies_files=True,
            workbook_lock=True,
        )

    def repair_workbook_schema(self) -> None:
        run_tool_background(
            self.result_panel,
            "workbook_schema_repair",
            "Repair Workbook Schema",
            lambda: repair_workbook_schema(self.config.project_root),
            modifies_files=True,
            workbook_lock=True,
        )

    def assign_missing_eoat_ids(self) -> None:
        run_tool_background(
            self.result_panel,
            "assign_missing_eoat_ids",
            "Assign Missing EOAT IDs",
            lambda: assign_missing_eoat_assembly_ids_in_workbook(self.config.project_root),
            self._eoat_assignment_finished,
            modifies_files=True,
            workbook_lock=True,
        )

    def backfill_audit_context(self) -> None:
        run_tool_background(
            self.result_panel,
            "audit_context_backfill",
            "Audit Context Backfill",
            lambda: backfill_audit_context(self.config.project_root),
            self._context_backfill_finished,
            modifies_files=True,
            workbook_lock=True,
        )

    def _context_backfill_finished(self, result) -> None:
        self.result_panel.show_result(result)
        self.run_validation()

    def _eoat_assignment_finished(self, result) -> None:
        self.result_panel.show_result(result)
        self.run_validation()

    def _validation_finished(self, result) -> None:
        self.findings = findings_from_result(result)
        self._update_category_filter()
        self._refresh_findings_table()
        self.cards["Workbook Status"].set_value("OK" if result.success else "Needs attention")
        self.cards["Missing Major Headers"].set_value(
            str(result.metrics.get("missing_major_inventory_header_count", 0))
        )
        self.cards["Missing Detail Headers"].set_value(
            str(
                max(
                    0,
                    int(result.metrics.get("missing_full_inventory_header_count", 0))
                    - int(result.metrics.get("missing_major_inventory_header_count", 0)),
                )
            )
        )
        self.cards["Duplicate Audit IDs"].set_value(str(result.metrics.get("duplicate_audit_id_count", 0)))
        self.cards["Applicable N/A Warnings"].set_value(
            str(result.metrics.get("missing_applicable_major_cell_count", 0))
        )
        self.cards["Bench Context Rows"].set_value(str(result.metrics.get("bench_audit_context_count", 0)))
        self.cards["Needs Review Context"].set_value(str(result.metrics.get("needs_review_audit_context_count", 0)))
        self.cards["Semantic Warnings"].set_value(str(result.metrics.get("semantic_warning_count", 0)))
        self.cards["Fixable Findings"].set_value(str(result.metrics.get("validation_fix_available_count", 0)))
        self.cards["Last Validation"].set_value("Just now")
        self._refresh_repair_suggestions(result)
        get_event_bus().emit(
            EVENT_WORKBOOK_VALIDATED,
            {
                "success": result.success,
                "warning_count": len(result.warnings),
                "error_count": len(result.errors),
                "output_reports": list(result.output_reports),
                "finding_count": len(self.findings),
            },
            source="workbook_health",
        )

    def _refresh_repair_suggestions(self, result=None) -> None:
        suggestions = []
        if result is not None:
            suggestions = list((getattr(result, "structured_data", {}) or {}).get("repair_suggestions", []) or [])
        if not suggestions:
            suggestions = repair_suggestions_from_findings(self.findings)
        if not suggestions:
            self.repair_summary_label.setText("No safe repair suggestions are available for the current findings.")
            self.repair_suggestions_table.setRowCount(0)
            return
        safe_count = sum(1 for item in suggestions if str(item.get("safety") or "") == "safe_automatic")
        self.repair_summary_label.setText(
            f"{len(suggestions)} repair suggestion(s), {safe_count} safe automatic preview path(s)."
        )
        self.repair_suggestions_table.setRowCount(len(suggestions))
        for row_number, suggestion in enumerate(suggestions):
            values = [
                suggestion.get("title") or suggestion.get("fix_id") or "",
                suggestion.get("safety") or "",
                suggestion.get("finding_count") or 0,
                ", ".join(str(value) for value in suggestion.get("categories") or []),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(256, suggestion.get("fix_id") or "")
                self.repair_suggestions_table.setItem(row_number, column, item)
        self.repair_suggestions_table.resizeColumnsToContents()

    def _update_category_filter(self) -> None:
        current = self.category_filter.currentText() if hasattr(self, "category_filter") else "All Categories"
        categories = sorted({finding.category for finding in self.findings if finding.category})
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("All Categories")
        self.category_filter.addItems(categories)
        index = self.category_filter.findText(current)
        self.category_filter.setCurrentIndex(index if index >= 0 else 0)
        self.category_filter.blockSignals(False)

    def _refresh_findings_table(self) -> None:
        if not hasattr(self, "findings_table"):
            return
        severity = self.severity_filter.currentText()
        category = self.category_filter.currentText()
        only_fixable = self.fix_filter.currentText() == "Fix Available"
        query = self.search_edit.text().strip().casefold()
        rows = []
        for finding in self.findings:
            if severity != "All Severities" and finding.severity != severity:
                continue
            if category != "All Categories" and finding.category != category:
                continue
            if only_fixable and not finding.fix_available:
                continue
            haystack = " ".join(
                [
                    finding.severity,
                    finding.category,
                    finding.sheet_name,
                    finding.audit_id,
                    finding.machine_number,
                    finding.column_name,
                    finding.message,
                    finding.fix_id,
                ]
            ).casefold()
            if query and query not in haystack:
                continue
            rows.append(finding)
        self._visible_findings = rows
        self.findings_table.setRowCount(len(rows))
        for row_number, finding in enumerate(rows):
            values = [
                finding.severity,
                finding.category,
                finding.sheet_name,
                str(finding.row_number or ""),
                finding.audit_id,
                finding.machine_number,
                finding.column_name,
                finding.message,
                finding.fix_id if finding.fix_available else "",
            ]
            for column, value in enumerate(values):
                self.findings_table.setItem(row_number, column, QTableWidgetItem(str(value)))
        self.findings_table.resizeColumnsToContents()

    def _selected_finding(self) -> ValidationFinding | None:
        selected = self.findings_table.selectionModel().selectedRows() if hasattr(self, "findings_table") else []
        if not selected:
            return self._visible_findings[0] if self._visible_findings else None
        row = selected[0].row()
        if 0 <= row < len(self._visible_findings):
            return self._visible_findings[row]
        return None

    def _selected_fix_id(self) -> str:
        finding = self._selected_finding()
        if finding and finding.fix_available and finding.fix_id in SAFE_FIX_IDS:
            return finding.fix_id
        selected = (
            self.repair_suggestions_table.selectionModel().selectedRows()
            if hasattr(self, "repair_suggestions_table")
            else []
        )
        if selected:
            row = selected[0].row()
            item = self.repair_suggestions_table.item(row, 0)
            fix_id = str(item.data(256) or "") if item is not None else ""
            if fix_id in SAFE_FIX_IDS:
                return fix_id
        return ""

    def open_selected_audit(self) -> None:
        finding = self._selected_finding()
        if finding is None or not finding.audit_id:
            self.result_panel.show_text("Select a finding with an Audit ID to open it.")
            return
        self.navigator.open_target(
            {
                "target_type": "audit",
                "audit_id": finding.audit_id,
                "machine_id": finding.machine_number,
                "target_label": finding.audit_id,
            }
        )

    def jump_to_selected_field(self) -> None:
        finding = self._selected_finding()
        if finding is None or not finding.audit_id:
            self.result_panel.show_text("Select a finding with an Audit ID to jump to the target field.")
            return
        self.navigator.open_target(
            {
                "target_type": "audit_field",
                "audit_id": finding.audit_id,
                "machine_id": finding.machine_number,
                "field_key": finding.column_name,
                "field_label": finding.column_name,
                "target_label": f"{finding.audit_id} / {finding.column_name}",
            }
        )

    def create_annotation_from_selected(self) -> None:
        finding = self._selected_finding()
        if finding is None:
            self.result_panel.show_text("Select a validation finding before creating an annotation.")
            return
        try:
            service = AnnotationService(self.config.project_root)
            target = service.create_or_get_target(
                "audit_field" if finding.audit_id and finding.column_name else "workbook_warning",
                target_label=finding.message[:120],
                audit_id=finding.audit_id,
                machine_id=finding.machine_number,
                field_key=finding.column_name,
                field_label=finding.column_name,
                sheet_name=finding.sheet_name,
                header_name=finding.column_name,
                object_ref=finding.finding_id,
            )
            note = service.create_note(
                subject=f"Validation finding: {finding.category or finding.severity}",
                body_markdown=f"{finding.message}\n\nRecommended action: {finding.recommended_action}",
                importance="Critical" if finding.severity in {"BLOCKER", "ERROR"} else "Important",
                collection="Workbook Health",
                note_type="Validation Finding",
                target_ids=[target.id],
            )
            self.result_panel.show_text(
                f"Created annotation note {note.id} for validation finding {finding.finding_id}."
            )
        except Exception as exc:
            self.result_panel.show_text(f"Could not create annotation: {exc}")

    def create_followup_from_selected(self) -> None:
        finding = self._selected_finding()
        if finding is None:
            self.result_panel.show_text("Select a validation finding before creating a follow-up.")
            return
        result = add_action_item(
            self.config.project_root,
            action_item=f"Review workbook validation finding: {finding.message}",
            related_cell_press=finding.machine_number,
            priority="High" if finding.severity in {"BLOCKER", "ERROR"} else "Medium",
            notes=f"Finding ID: {finding.finding_id}. Audit ID: {finding.audit_id}. Field: {finding.column_name}.",
        )
        self.result_panel.show_result(result)

    def preview_selected_fix(self) -> None:
        fix_id = self._selected_fix_id()
        if not fix_id:
            self.result_panel.show_text("Select an auto-fixable finding before previewing a safe fix.")
            return
        run_tool_background(
            self.result_panel,
            f"workbook_repair_preview_{fix_id}",
            "Workbook Repair Preview",
            lambda: preview_safe_fix_action(self.config.project_root, fix_id),
            modifies_files=False,
        )

    def apply_selected_fix(self) -> None:
        fix_id = self._selected_fix_id()
        if not fix_id:
            self.result_panel.show_text("Select an auto-fixable finding before applying a safe fix.")
            return
        answer = QMessageBox.question(
            self,
            "Apply Safe Fix",
            "Apply the selected safe workbook fix? A backup will be created first and validation will rerun afterward.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        run_tool_background(
            self.result_panel,
            f"workbook_repair_apply_{fix_id}",
            "Workbook Repair",
            lambda: apply_safe_fix(self.config.project_root, fix_id, confirm=True),
            self._repair_finished,
            modifies_files=True,
            workbook_lock=True,
        )

    def _repair_finished(self, result) -> None:
        self.run_validation()

    def open_validation_reports(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).validation_reports)
        if not result.success:
            self.result_panel.show_result(result)

    def open_master_workbook(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).master_workbook)
        if not result.success:
            self.result_panel.show_result(result)
