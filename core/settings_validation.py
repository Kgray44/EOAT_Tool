from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .settings_schema import SCHEDULED_REPORT_DUPLICATE_POLICIES, SCHEDULED_REPORT_MISSED_RUN_POLICIES

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@dataclass(frozen=True)
class SettingsValidationResult:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_time(value: Any, field_label: str) -> list[str]:
    text = str(value or "").strip()
    if not TIME_RE.match(text):
        return [f"{field_label} must use 24-hour HH:MM format."]
    return []


def validate_non_negative_int(value: Any, field_label: str) -> list[str]:
    text = str(value or "").strip()
    try:
        parsed = int(text)
    except ValueError:
        return [f"{field_label} must be a non-negative whole number."]
    if parsed < 0:
        return [f"{field_label} must be a non-negative whole number."]
    return []


def validate_settings_payload(payload: dict[str, Any]) -> SettingsValidationResult:
    errors: list[str] = []
    scheduled = dict(payload.get("scheduled_reports") or {})
    backups = dict(payload.get("backups") or {})

    errors.extend(validate_time(scheduled.get("daily_time"), "Daily report time"))
    errors.extend(validate_time(scheduled.get("weekly_time"), "Weekly report time"))
    if scheduled.get("duplicate_policy") not in SCHEDULED_REPORT_DUPLICATE_POLICIES:
        errors.append("Duplicate policy is not recognized.")
    if scheduled.get("missed_run_policy") not in SCHEDULED_REPORT_MISSED_RUN_POLICIES:
        errors.append("Missed run policy is not recognized.")

    errors.extend(validate_non_negative_int(backups.get("retention_days"), "Backup retention days"))
    errors.extend(validate_non_negative_int(backups.get("newest_backups_per_workbook"), "Newest backups per workbook"))
    errors.extend(validate_non_negative_int(backups.get("light_backup_retention_count"), "Light backup retention"))
    errors.extend(validate_non_negative_int(backups.get("workbook_backup_retention_count"), "Workbook backup retention"))
    return SettingsValidationResult(errors=tuple(errors))


__all__ = [
    "SettingsValidationResult",
    "validate_non_negative_int",
    "validate_settings_payload",
    "validate_time",
]
