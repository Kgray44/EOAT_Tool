from __future__ import annotations

import json

from core.config import UserConfig, load_config
from core.config_migration import migrate_config_data
from core.settings_schema import default_backups_config, default_scheduled_reports_config
from core.settings_validation import validate_settings_payload


def test_old_config_without_schema_loads_and_preserves_foundation_keys(tmp_path):
    config_path = tmp_path / "user_config.json"
    config_path.write_text(
        json.dumps(
            {
                "project_root": str(tmp_path / "EOAT_Project"),
                "audit_defaults": {"Auditor": "KG", "Status": "Audit Complete"},
                "connection_defaults": {"ATI": "Easy"},
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.config_schema_version == 2
    assert config.project_root == str(tmp_path / "EOAT_Project")
    assert config.audit_defaults["Auditor"] == "KG"
    assert config.connection_defaults["ATI"] == "Easy"
    assert config.scheduled_reports["daily_time"] == default_scheduled_reports_config()["daily_time"]
    assert config.backups["retention_days"] == default_backups_config()["retention_days"]


def test_migration_preserves_unknown_keys_and_is_idempotent():
    old_config = {
        "project_root": "C:/EOAT",
        "custom_local_key": {"keep": True},
        "scheduled_reports": {"daily_time": "18:15", "extra_schedule_key": "local"},
        "backups": {"retention_days": 14, "extra_backup_key": "local"},
        "connection_defaults": {"DoveTail": "Medium"},
    }

    once = migrate_config_data(old_config)
    twice = migrate_config_data(once)
    config = UserConfig.from_dict(once)

    assert once == twice
    assert config.extra_config["custom_local_key"] == {"keep": True}
    assert config.scheduled_reports["daily_time"] == "18:15"
    assert config.scheduled_reports["extra_schedule_key"] == "local"
    assert config.backups["retention_days"] == 14
    assert config.backups["extra_backup_key"] == "local"
    assert any(rule["id"] == "connection_default_dovetail" for rule in config.smart_default_rules)
    assert config.to_dict()["custom_local_key"] == {"keep": True}


def test_settings_validation_rejects_invalid_scheduled_time():
    payload = {
        "scheduled_reports": {**default_scheduled_reports_config(), "daily_time": "25:99"},
        "backups": default_backups_config(),
    }

    result = validate_settings_payload(payload)

    assert not result.ok
    assert any("Daily report time" in error for error in result.errors)


def test_settings_validation_rejects_invalid_backup_retention():
    payload = {
        "scheduled_reports": default_scheduled_reports_config(),
        "backups": {**default_backups_config(), "retention_days": "-1"},
    }

    result = validate_settings_payload(payload)

    assert not result.ok
    assert any("Backup retention days" in error for error in result.errors)
