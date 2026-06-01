from __future__ import annotations

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QCheckBox,
        QDialog,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
    )
except ImportError:  # pragma: no cover
    Qt = None
    QCheckBox = QDialog = QHBoxLayout = QLabel = QPushButton = QTableWidget = QTableWidgetItem = QVBoxLayout = None

from app.event_bus import EVENT_ANNOTATION_CHANGED, EVENT_OPEN_ITEMS_CHANGED, get_event_bus
from core.action_items import add_action_item
from core.annotations.service import AnnotationService


class AnnotationSuggestionsDialog(QDialog):
    COLUMNS = [
        "Apply",
        "Tag",
        "Target Field",
        "Reason",
        "Severity / Confidence",
        "Suggested Comment",
        "Existing Status",
    ]

    def __init__(self, audit_page, entry: dict[str, str], parent=None):
        super().__init__(parent or audit_page)
        self.audit_page = audit_page
        self.entry = dict(entry)
        self.config = audit_page.config
        self.service = AnnotationService(self.config.project_root)
        self.suggestions: list[dict[str, object]] = []
        self.setWindowTitle("Annotation Suggestions")
        self.resize(1120, 520)

        layout = QVBoxLayout(self)
        top_row = QHBoxLayout()
        self.show_ignored_check = QCheckBox("Show ignored suggestions")
        self.show_ignored_check.stateChanged.connect(self.refresh)
        top_row.addWidget(QLabel("Suggested Annotations"))
        top_row.addStretch(1)
        top_row.addWidget(self.show_ignored_check)
        layout.addLayout(top_row)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, stretch=1)

        button_row = QHBoxLayout()
        self.apply_selected_button = QPushButton("Apply Selected")
        self.apply_selected_button.clicked.connect(self.apply_selected)
        self.apply_high_button = QPushButton("Apply All High Confidence")
        self.apply_high_button.clicked.connect(self.apply_all_high_confidence)
        self.ignore_button = QPushButton("Ignore Selected")
        self.ignore_button.clicked.connect(self.ignore_selected)
        self.followup_button = QPushButton("Create Follow-Up Actions")
        self.followup_button.clicked.connect(self.create_follow_up_actions)
        self.open_target_button = QPushButton("Open Target Field")
        self.open_target_button.clicked.connect(self.open_target_field)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        for button in [
            self.apply_selected_button,
            self.apply_high_button,
            self.ignore_button,
            self.followup_button,
            self.open_target_button,
            close_button,
        ]:
            button_row.addWidget(button)
        layout.addLayout(button_row)

        self.status_label = QLabel()
        self.status_label.setObjectName("MutedText")
        layout.addWidget(self.status_label)
        self.refresh()

    def refresh(self) -> None:
        include_ignored = self.show_ignored_check.isChecked()
        self.suggestions = self.service.get_suggested_annotations(self.entry, include_ignored=include_ignored)
        self.table.setRowCount(len(self.suggestions))
        for row_index, suggestion in enumerate(self.suggestions):
            apply_item = QTableWidgetItem("")
            apply_item.setFlags(apply_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            apply_item.setCheckState(Qt.CheckState.Unchecked)
            apply_item.setData(Qt.ItemDataRole.UserRole, suggestion)
            if suggestion.get("ignored"):
                apply_item.setToolTip(f"Ignored suggestion ID: {suggestion.get('suggestion_id')}")
            self.table.setItem(row_index, 0, apply_item)
            values = [
                suggestion.get("tag_name"),
                suggestion.get("field_key"),
                suggestion.get("reason"),
                f"{suggestion.get('severity')} / {suggestion.get('confidence')}%",
                suggestion.get("suggested_comment"),
                "Ignored" if suggestion.get("ignored") else suggestion.get("existing_status"),
            ]
            for col, value in enumerate(values, start=1):
                item = QTableWidgetItem(str(value or ""))
                item.setToolTip(str(value or ""))
                if col == 3:
                    item.setData(Qt.ItemDataRole.UserRole, suggestion.get("suggestion_id"))
                self.table.setItem(row_index, col, item)
        self.table.resizeColumnsToContents()
        ignored_note = " including ignored" if include_ignored else ""
        self.status_label.setText(f"{len(self.suggestions)} suggestion(s){ignored_note}.")

    def selected_suggestions(self) -> list[dict[str, object]]:
        rows = sorted({item.row() for item in self.table.selectedItems()})
        checked_rows = [
            row
            for row in range(self.table.rowCount())
            if self.table.item(row, 0) is not None and self.table.item(row, 0).checkState() == Qt.CheckState.Checked
        ]
        chosen_rows = checked_rows or rows
        return [self.suggestions[row] for row in chosen_rows if 0 <= row < len(self.suggestions)]

    def apply_selected(self) -> None:
        suggestions = [item for item in self.selected_suggestions() if not item.get("ignored")]
        if not suggestions:
            self.status_label.setText("Select one or more non-ignored suggestions to apply.")
            return
        assignments = self.service.apply_suggested_annotations(suggestions)
        self._after_annotation_change()
        self.status_label.setText(f"Applied {len(assignments)} suggestion(s).")
        self.refresh()

    def apply_all_high_confidence(self) -> None:
        suggestions = [
            suggestion
            for suggestion in self.suggestions
            if not suggestion.get("ignored") and int(suggestion.get("confidence") or 0) >= 80
        ]
        if not suggestions:
            self.status_label.setText("No high-confidence suggestions are available.")
            return
        assignments = self.service.apply_suggested_annotations(suggestions)
        self._after_annotation_change()
        self.status_label.setText(f"Applied {len(assignments)} high-confidence suggestion(s).")
        self.refresh()

    def ignore_selected(self) -> None:
        suggestions = self.selected_suggestions()
        if not suggestions:
            self.status_label.setText("Select one or more suggestions to ignore.")
            return
        count = self.service.ignore_suggested_annotations(suggestions)
        get_event_bus().emit(EVENT_ANNOTATION_CHANGED, {"ignored_suggestions": count}, source="annotation_suggestions")
        self.status_label.setText(f"Ignored {count} suggestion(s).")
        self.refresh()

    def create_follow_up_actions(self) -> None:
        suggestions = self.selected_suggestions()
        if not suggestions:
            self.status_label.setText("Select one or more suggestions before creating follow-up actions.")
            return
        created = 0
        warnings: list[str] = []
        for suggestion in suggestions:
            result = add_action_item(
                self.config.project_root,
                f"Review annotation suggestion {suggestion.get('tag_name')}: {suggestion.get('field_key')}.",
                related_cell_press=str(suggestion.get("machine_id") or self.entry.get("Press/Machine #") or ""),
                priority="High"
                if str(suggestion.get("severity") or "").casefold() in {"critical", "error"}
                else "Medium",
                notes=str(suggestion.get("reason") or ""),
            )
            if result.success:
                created += 1
            else:
                warnings.extend(result.errors)
        get_event_bus().emit(EVENT_OPEN_ITEMS_CHANGED, {"created_followups": created}, source="annotation_suggestions")
        extra = f" Errors: {'; '.join(warnings)}" if warnings else ""
        self.status_label.setText(f"Created {created} follow-up action(s).{extra}")

    def open_target_field(self) -> None:
        suggestion = self._current_suggestion()
        if not suggestion:
            self.status_label.setText("Select a suggestion to open its target field.")
            return
        field = str(suggestion.get("field_key") or "")
        if hasattr(self.audit_page, "open_audit_coach_field"):
            self.audit_page.open_audit_coach_field(field)
        elif hasattr(self.audit_page, "focus_annotation_target"):
            self.audit_page.focus_annotation_target(
                {
                    "target_type": suggestion.get("target_type") or "audit_field",
                    "audit_id": suggestion.get("audit_id") or self.entry.get("Audit ID"),
                    "machine_id": suggestion.get("machine_id") or self.entry.get("Press/Machine #"),
                    "field_key": field,
                    "field_label": field,
                }
            )
        self.status_label.setText(f"Opened target field: {field}")

    def _current_suggestion(self) -> dict[str, object] | None:
        row = self.table.currentRow()
        if 0 <= row < len(self.suggestions):
            return self.suggestions[row]
        selected = self.selected_suggestions()
        return selected[0] if selected else None

    def _after_annotation_change(self) -> None:
        if hasattr(self.audit_page, "_refresh_field_tag_indicators"):
            self.audit_page._refresh_field_tag_indicators()
        get_event_bus().emit(
            EVENT_ANNOTATION_CHANGED,
            {"audit_id": self.entry.get("Audit ID"), "suggestions_applied": True},
            source="annotation_suggestions",
        )
        get_event_bus().emit(
            EVENT_OPEN_ITEMS_CHANGED, {"audit_id": self.entry.get("Audit ID")}, source="annotation_suggestions"
        )
