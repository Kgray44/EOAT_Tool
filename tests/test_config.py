from __future__ import annotations

from core.config import UserConfig, load_config, save_config
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


def test_missing_project_root_default_is_demo_project():
    config = load_config("missing-test-config.json")

    assert "examples" in config.project_root
    assert "demo_project" in config.project_root
