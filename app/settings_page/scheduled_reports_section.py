from __future__ import annotations

try:
    from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
except ImportError:  # pragma: no cover
    QCheckBox = QComboBox = QFormLayout = QHBoxLayout = QLabel = QLineEdit = QPushButton = None

from core.settings_schema import (
    SCHEDULED_REPORT_DUPLICATE_POLICIES,
    SCHEDULED_REPORT_MISSED_RUN_POLICIES,
    SCHEDULED_REPORT_WEEKDAYS,
    default_scheduled_reports_config,
)

from .widgets import settings_group


def build_scheduled_reports_section(page, layout) -> None:
    group, group_layout = settings_group(
        page, "Scheduled Reports", "scheduled reports daily weekly time timezone duplicate missed dry run log"
    )
    form = QFormLayout()
    scheduled = dict(default_scheduled_reports_config())
    scheduled.update(dict(getattr(page.config, "scheduled_reports", {}) or {}))

    page.daily_reports_check = QCheckBox()
    page.daily_reports_check.setChecked(bool(scheduled.get("daily_enabled", True)))
    page.weekly_reports_check = QCheckBox()
    page.weekly_reports_check.setChecked(bool(scheduled.get("weekly_enabled", True)))
    page.daily_weekdays_edit = QLineEdit(
        ", ".join(scheduled.get("daily_weekdays") or default_scheduled_reports_config()["daily_weekdays"])
    )
    page.daily_report_time_edit = QLineEdit(str(scheduled.get("daily_time", "19:00")))
    page.weekly_weekday_combo = QComboBox()
    page.weekly_weekday_combo.addItems(SCHEDULED_REPORT_WEEKDAYS)
    weekly_index = page.weekly_weekday_combo.findText(str(scheduled.get("weekly_weekday", "Friday")))
    page.weekly_weekday_combo.setCurrentIndex(weekly_index if weekly_index >= 0 else 4)
    page.weekly_report_time_edit = QLineEdit(str(scheduled.get("weekly_time", "19:00")))
    page.schedule_timezone_edit = QLineEdit(str(scheduled.get("timezone", "America/New_York")))
    page.duplicate_policy_combo = QComboBox()
    page.duplicate_policy_combo.addItems(SCHEDULED_REPORT_DUPLICATE_POLICIES)
    duplicate_index = page.duplicate_policy_combo.findText(str(scheduled.get("duplicate_policy", "skip_existing")))
    page.duplicate_policy_combo.setCurrentIndex(duplicate_index if duplicate_index >= 0 else 0)
    page.missed_run_policy_combo = QComboBox()
    page.missed_run_policy_combo.addItems(SCHEDULED_REPORT_MISSED_RUN_POLICIES)
    missed_index = page.missed_run_policy_combo.findText(str(scheduled.get("missed_run_policy", "catch_up")))
    page.missed_run_policy_combo.setCurrentIndex(missed_index if missed_index >= 0 else 0)
    page.dry_run_folder_edit = QLineEdit(str(scheduled.get("dry_run_folder", "")))
    page.prevent_overwrite_check = QCheckBox()
    page.prevent_overwrite_check.setChecked(bool(scheduled.get("prevent_overwrite", True)))

    form.addRow("Daily enabled", page.daily_reports_check)
    form.addRow("Daily weekdays", page.daily_weekdays_edit)
    form.addRow("Daily time", page.daily_report_time_edit)
    form.addRow("Weekly enabled", page.weekly_reports_check)
    form.addRow("Weekly weekday", page.weekly_weekday_combo)
    form.addRow("Weekly time", page.weekly_report_time_edit)
    form.addRow("Timezone", page.schedule_timezone_edit)
    form.addRow("Duplicate policy", page.duplicate_policy_combo)
    form.addRow("Missed run policy", page.missed_run_policy_combo)
    form.addRow("Dry-run folder", page.dry_run_folder_edit)
    form.addRow("Prevent overwrite", page.prevent_overwrite_check)
    group_layout.addLayout(form)

    status = QLabel("Scheduled task status: Unknown until checked from the Scheduled Reports page.")
    status.setWordWrap(True)
    group_layout.addWidget(status)
    actions = QHBoxLayout()
    for label, callback in [
        ("Install/Repair Tasks", page.install_or_repair_scheduled_tasks),
        ("Open Scheduled Reports Page", page.open_scheduled_reports_page),
        ("Open Scheduled Tool Log", page.open_scheduled_log),
    ]:
        button = QPushButton(label)
        button.clicked.connect(callback)
        actions.addWidget(button)
    actions.addStretch(1)
    group_layout.addLayout(actions)
    layout.addWidget(group)
