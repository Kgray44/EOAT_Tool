from __future__ import annotations

from core.config import UserConfig, load_config, save_config
from core.constants import DEFAULT_PROJECT_ROOT
from core.paths import resolve_project_paths
from core.project_root_status import is_demo_project_root, project_data_mode, validate_project_root
from tests.fixtures.fake_project import create_minimal_fake_project


def test_no_config_defaults_to_demo_project(tmp_path):
    config = load_config(tmp_path / "missing_local_config.json")

    assert config.project_root == str(DEFAULT_PROJECT_ROOT)
    assert project_data_mode(config) == "demo"


def test_demo_project_root_is_detected_as_demo():
    status = validate_project_root(DEFAULT_PROJECT_ROOT)

    assert is_demo_project_root(DEFAULT_PROJECT_ROOT)
    assert status.mode == "demo"
    assert "synthetic sample data" in status.message


def test_valid_synthetic_project_outside_examples_is_real(fake_project):
    status = validate_project_root(fake_project)

    assert status.mode == "real"
    assert status.is_usable
    assert status.master_workbook == resolve_project_paths(fake_project).master_workbook


def test_missing_workbook_is_invalid_with_clear_message(tmp_path):
    root = create_minimal_fake_project(tmp_path)

    status = validate_project_root(root)

    assert status.mode == "invalid"
    assert not status.is_usable
    assert any("Missing master workbook" in item for item in status.missing_items)
    assert "Project root is incomplete" in status.message


def test_save_config_persists_selected_project_root_to_local_config_path(tmp_path):
    selected_root = tmp_path / "Private_EOAT_Project"
    config_path = tmp_path / "config" / "local_config.json"
    config = UserConfig(project_root=str(selected_root), theme="dark")

    saved_path = save_config(config, config_path)
    loaded = load_config(config_path)

    assert saved_path == config_path
    assert loaded.project_root == str(selected_root)
    assert loaded.theme == "dark"


def test_usage_docs_explain_demo_and_real_project_switching():
    readme = open("README.md", encoding="utf-8").read()
    usage = open("USAGE.md", encoding="utf-8").read()

    assert "Demo mode" in readme
    assert "Choose Real Project Folder" in readme
    assert "config/local_config.json" in usage
    assert "EOAT_Master_Tracker.xlsx" in usage
