from __future__ import annotations

try:
    from PySide6.QtWidgets import QCheckBox, QFormLayout, QHBoxLayout, QPushButton, QLineEdit
except ImportError:  # pragma: no cover
    QCheckBox = QFormLayout = QHBoxLayout = QPushButton = QLineEdit = None

from core.settings_schema import default_backups_config

from .widgets import settings_group


def build_backups_section(page, layout) -> None:
    group, group_layout = settings_group(page, "Backups & Safety", "backup safety retention cleanup preview validation manager folder")
    form = QFormLayout()
    backups = dict(default_backups_config())
    backups.update(dict(getattr(page.config, "backups", {}) or getattr(page.config, "backup_policy", {}) or {}))

    page.backup_before_audit_save_check = QCheckBox()
    page.backup_before_audit_save_check.setChecked(bool(backups.get("backup_before_audit_save", True)))
    page.backup_before_compatibility_update_check = QCheckBox()
    page.backup_before_compatibility_update_check.setChecked(bool(backups.get("backup_before_compatibility_update", True)))
    page.backup_before_migration_check = QCheckBox()
    page.backup_before_migration_check.setChecked(bool(backups.get("backup_before_workbook_migration", True)))
    page.backup_before_repair_check = QCheckBox()
    page.backup_before_repair_check.setChecked(bool(backups.get("backup_before_bulk_repair", backups.get("backup_before_schema_repair", True))))
    page.retention_days_edit = QLineEdit(str(backups.get("retention_days", 7)))
    page.newest_backups_per_workbook_edit = QLineEdit(str(backups.get("newest_backups_per_workbook", 25)))
    page.keep_milestones_check = QCheckBox()
    page.keep_milestones_check.setChecked(bool(backups.get("keep_milestones", True)))
    page.cleanup_requires_preview_check = QCheckBox()
    page.cleanup_requires_preview_check.setChecked(bool(backups.get("cleanup_requires_preview", True)))
    page.cleanup_blocked_by_validation_check = QCheckBox()
    page.cleanup_blocked_by_validation_check.setChecked(bool(backups.get("cleanup_blocked_by_validation_blockers", True)))
    page.light_backup_retention_edit = QLineEdit(str(backups.get("light_backup_retention_count", 10)))
    page.workbook_backup_retention_edit = QLineEdit(str(backups.get("workbook_backup_retention_count", 20)))
    page.cleanup_requires_validation_check = page.cleanup_blocked_by_validation_check

    form.addRow("Backup before audit save", page.backup_before_audit_save_check)
    form.addRow("Backup before compatibility update", page.backup_before_compatibility_update_check)
    form.addRow("Backup before workbook migration", page.backup_before_migration_check)
    form.addRow("Backup before bulk repair", page.backup_before_repair_check)
    form.addRow("Retention days", page.retention_days_edit)
    form.addRow("Newest backups per workbook", page.newest_backups_per_workbook_edit)
    form.addRow("Keep milestones", page.keep_milestones_check)
    form.addRow("Cleanup requires preview", page.cleanup_requires_preview_check)
    form.addRow("Cleanup blocked by validation blockers", page.cleanup_blocked_by_validation_check)
    form.addRow("Light backup retention", page.light_backup_retention_edit)
    form.addRow("Workbook backup retention", page.workbook_backup_retention_edit)
    group_layout.addLayout(form)

    actions = QHBoxLayout()
    for label, callback in [
        ("Backup Workbook", page.backup_workbook),
        ("Create Light Project Backup", page.backup_light),
        ("Open Backup Manager", page.open_backup_manager_page),
        ("Open Backups Folder", page.open_backups),
    ]:
        button = QPushButton(label)
        button.clicked.connect(callback)
        actions.addWidget(button)
    actions.addStretch(1)
    group_layout.addLayout(actions)
    layout.addWidget(group)
