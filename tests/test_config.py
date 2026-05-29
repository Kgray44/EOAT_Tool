from __future__ import annotations

from core.config import UserConfig, load_config, migrate_config_data, save_config
from core.constants import DEFAULT_PROJECT_ROOT


def test_config_load_missing_file_uses_defaults(tmp_path):
    config = load_config(tmp_path / "missing.json")

    assert config.project_root == str(DEFAULT_PROJECT_ROOT)
    assert config.debug_mode is False


def test_config_save_and_load_round_trip(tmp_path):
    path = tmp_path / "user_config.json"
    original = UserConfig(project_root=str(tmp_path), debug_mode=True, theme="dark", git_executable="git.exe")

    save_config(original, path)
    loaded = load_config(path)

    assert loaded.project_root == str(tmp_path)
    assert loaded.debug_mode is True
    assert loaded.theme == "dark"
    assert loaded.git_executable == "git.exe"
    assert loaded.config_schema_version == 2
    assert loaded.scheduled_reports["prevent_overwrite"] is True
    assert loaded.backup_policy["backup_before_workbook_migration"] is True


def test_missing_project_root_default_is_demo_project():
    config = load_config("missing-test-config.json")

    assert "examples" in config.project_root
    assert "demo_project" in config.project_root


def test_config_migration_adds_settings_foundation_sections():
    migrated = migrate_config_data({"theme": "dark", "connection_defaults": {"ATI": "Easy"}})
    config = UserConfig.from_dict(migrated)

    assert config.config_schema_version == 2
    assert config.theme == "dark"
    assert config.scheduled_reports["daily_time"] == "19:00"
    assert config.backup_policy["cleanup_requires_validation"] is True
    assert any(rule["id"] == "connection_default_ati" for rule in config.smart_default_rules)
