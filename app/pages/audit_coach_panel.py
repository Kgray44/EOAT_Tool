from __future__ import annotations

try:
    from PySide6.QtWidgets import (
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QProgressBar,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QGroupBox = QHBoxLayout = QLabel = QPushButton = QProgressBar = QTextEdit = QVBoxLayout = QWidget = None

from core.audit.coach import (
    AuditCoachSummary,
    STATE_FOLLOW_UP_NEEDED,
    STATE_MISSING,
    STATE_STALE_CONFLICT,
    STATE_UNKNOWN_NOT_CHECKED,
)


STATE_LABELS = {
    STATE_MISSING: "Missing",
    STATE_UNKNOWN_NOT_CHECKED: "Unknown / Not Checked",
    STATE_FOLLOW_UP_NEEDED: "Follow-Up Needed",
    STATE_STALE_CONFLICT: "Stale / Conflict",
}


class AuditCoachPanel(QWidget):
    def __init__(self, audit_page):
        super().__init__(audit_page)
        self.audit_page = audit_page
        self.summary: AuditCoachSummary | None = None
        self._guided_fields: list[str] = []
        self._guided_index = 0
        self._guided_active = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("Audit Coach")
        title.setObjectName("AuditCoachTitle")
        layout.addWidget(title)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.override_label = QLabel("")
        self.override_label.setWordWrap(True)
        self.override_label.setStyleSheet("color: #92400e; font-weight: 600;")
        self.override_label.hide()
        layout.addWidget(self.override_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        self.next_label = QLabel("")
        self.next_label.setWordWrap(True)
        layout.addWidget(self.next_label)

        action_row = QHBoxLayout()
        self.finish_button = QPushButton("Finish This Audit")
        self.finish_button.clicked.connect(self.start_guided_completion)
        self.open_button = QPushButton("Open Field")
        self.open_button.clicked.connect(self.open_current_field)
        action_row.addWidget(self.finish_button)
        action_row.addWidget(self.open_button)
        layout.addLayout(action_row)

        guided_row = QHBoxLayout()
        self.unknown_button = QPushButton("Mark Unknown / Not Checked")
        self.unknown_button.clicked.connect(self.mark_current_unknown)
        self.followup_button = QPushButton("Create Follow-Up")
        self.followup_button.clicked.connect(self.create_current_follow_up)
        guided_row.addWidget(self.unknown_button)
        guided_row.addWidget(self.followup_button)
        layout.addLayout(guided_row)

        tag_row = QHBoxLayout()
        self.tag_button = QPushButton("Tag Needs Review")
        self.tag_button.clicked.connect(self.tag_current_needs_review)
        self.skip_button = QPushButton("Skip")
        self.skip_button.clicked.connect(self.skip_current_field)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.next_field)
        tag_row.addWidget(self.tag_button)
        tag_row.addWidget(self.skip_button)
        tag_row.addWidget(self.next_button)
        layout.addLayout(tag_row)

        self.section_text = self._read_only_text(maximum_height=150)
        layout.addWidget(self._group("Section Completion", self.section_text))

        self.findings_text = self._read_only_text(maximum_height=135)
        layout.addWidget(self._group("Findings", self.findings_text))

        self.hidden_text = self._read_only_text(maximum_height=135)
        layout.addWidget(self._group("Hidden Field Reasons", self.hidden_text))
        layout.addStretch(1)

        self._update_action_buttons()

    def refresh(self, summary: AuditCoachSummary) -> None:
        selected_before = self.current_field()
        self.summary = summary
        self._guided_fields = list(summary.guided_fields)
        if selected_before in self._guided_fields:
            self._guided_index = self._guided_fields.index(selected_before)
        elif self._guided_index >= len(self._guided_fields):
            self._guided_index = 0
        self.progress_bar.setValue(summary.percent_complete)
        if summary.manual_completion_override:
            self.summary_label.setText(
                f"{summary.percent_complete}% complete by manual override. "
                f"{summary.verified_complete_count}/{summary.applicable_field_count} applicable fields treated complete."
            )
            detail = "Manual completion override applied"
            if summary.manual_completion_override_timestamp:
                detail += f" at {summary.manual_completion_override_timestamp}"
            if summary.manual_completion_override_user:
                detail += f" by {summary.manual_completion_override_user}"
            ignored = len(summary.ignored_empty_fields_at_override)
            if ignored:
                detail += f". {ignored} blank field(s) ignored."
            self.override_label.setText(detail)
            self.override_label.show()
        else:
            self.summary_label.setText(
                f"{summary.percent_complete}% verified complete. "
                f"{summary.verified_complete_count}/{summary.applicable_field_count} applicable fields verified."
            )
            self.override_label.setText("")
            self.override_label.hide()
        self.next_label.setText(self._next_text())
        self.section_text.setPlainText(self._section_lines(summary))
        self.findings_text.setPlainText(self._finding_lines(summary))
        self.hidden_text.setPlainText(self._hidden_reason_lines(summary))
        self._update_action_buttons()

    def start_guided_completion(self) -> None:
        self._guided_active = True
        self._guided_index = 0
        self.next_label.setText(self._next_text())
        self.open_current_field()
        self._update_action_buttons()

    def open_current_field(self) -> None:
        field = self.current_field()
        if field:
            self.audit_page.open_audit_coach_field(field)

    def mark_current_unknown(self) -> None:
        field = self.current_field()
        if field:
            self.audit_page.mark_audit_coach_field_unknown(field)

    def create_current_follow_up(self) -> None:
        field = self.current_field()
        if field:
            self.audit_page.create_audit_coach_follow_up(field)

    def tag_current_needs_review(self) -> None:
        field = self.current_field()
        if field:
            self.audit_page.tag_audit_coach_needs_review(field)

    def skip_current_field(self) -> None:
        self.next_field()

    def next_field(self) -> None:
        if not self._guided_fields:
            self._guided_index = 0
        else:
            self._guided_index = (self._guided_index + 1) % len(self._guided_fields)
        self.next_label.setText(self._next_text())
        self._update_action_buttons()

    def current_field(self) -> str:
        if not self.summary:
            return ""
        if self._guided_fields:
            return self._guided_fields[min(self._guided_index, len(self._guided_fields) - 1)]
        return self.summary.next_best_field

    def _next_text(self) -> str:
        if not self.summary:
            return "Coach summary is not ready yet."
        if self.summary.manual_completion_override:
            return "Manual completion override is applied. Blank fields from this audit no longer drive the completion percentage."
        field = self.current_field()
        if not field:
            if self.summary.can_finish:
                return "No applicable gaps remain. This audit is ready for final review."
            return "No missing fields remain, but review the findings before finalizing."
        status = self._status_for_field(field)
        state_label = STATE_LABELS.get(status.state, status.state) if status else "Action Needed"
        position = ""
        if self._guided_fields:
            position = f" ({self._guided_index + 1}/{len(self._guided_fields)})"
        return f"Next{position}: {field} - {state_label}. {self.summary.next_best_reason if field == self.summary.next_best_field else status.reason}"

    def _status_for_field(self, field: str):
        if not self.summary:
            return None
        for section in self.summary.sections:
            for status in section.fields:
                if status.field == field:
                    return status
        return None

    def _update_action_buttons(self) -> None:
        has_field = bool(self.current_field())
        has_guided = bool(self._guided_fields)
        for button in [self.open_button, self.unknown_button, self.followup_button, self.tag_button]:
            button.setEnabled(has_field)
        self.finish_button.setEnabled(has_guided)
        self.skip_button.setEnabled(has_guided)
        self.next_button.setEnabled(has_guided)

    def _read_only_text(self, *, maximum_height: int) -> QTextEdit:
        text = QTextEdit()
        text.setReadOnly(True)
        text.setMaximumHeight(maximum_height)
        text.setMinimumHeight(80)
        return text

    def _group(self, title: str, widget: QWidget) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(widget)
        return group

    def _section_lines(self, summary: AuditCoachSummary) -> str:
        lines: list[str] = []
        for section in summary.sections:
            lines.append(
                f"{section.name}: {section.verified_complete_count}/{section.applicable_count} verified "
                f"({section.percent_complete}%). Missing {section.missing_count}, "
                f"Unknown {section.unknown_count}, Follow-up {section.follow_up_count}, "
                f"N/A {section.not_applicable_count}, Conflict {section.stale_conflict_count}."
            )
        return "\n".join(lines) or "No audit sections available."

    def _finding_lines(self, summary: AuditCoachSummary) -> str:
        if not summary.findings:
            return "No coach findings."
        lines = []
        for finding in summary.findings[:12]:
            target = f" [{finding.field}]" if finding.field else ""
            lines.append(f"{finding.severity.title()}{target}: {finding.message}")
            if finding.action:
                lines.append(f"Action: {finding.action}")
        if len(summary.findings) > 12:
            lines.append(f"... {len(summary.findings) - 12} more finding(s).")
        return "\n".join(lines)

    def _hidden_reason_lines(self, summary: AuditCoachSummary) -> str:
        hidden = list(summary.not_applicable_fields)
        hidden.extend(
            status
            for section in summary.sections
            for status in section.fields
            if status.state == STATE_STALE_CONFLICT and not status.applies
        )
        if not hidden:
            return "No fields are currently non-applicable."
        return "\n".join(f"{status.field}: {status.reason}" for status in hidden)
