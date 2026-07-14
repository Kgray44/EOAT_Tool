from __future__ import annotations

import sys

from core import resources


def test_resource_path_uses_source_checkout():
    path = resources.resource_path("data_templates/workbook_schema.json")

    assert path.exists()
    assert "data_templates" in str(path)


def test_frozen_mode_uses_bundle_resources_and_user_data(monkeypatch, tmp_path):
    bundle_root = tmp_path / "bundle"
    user_root = tmp_path / "user-data"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(user_root))

    assert resources.app_base_path() == bundle_root
    assert resources.resource_path("data_templates/workbook_schema.json") == (
        bundle_root / "data_templates" / "workbook_schema.json"
    )
    assert resources.writable_config_path("local_config.json") == user_root / "config" / "local_config.json"
    assert resources.default_project_root() == user_root / "projects" / "demo_project"
