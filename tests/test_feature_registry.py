from __future__ import annotations

from dataclasses import dataclass

from app.command_registry import build_dashboard_command_registry
from app.feature_registry import build_feature_registry


@dataclass
class _Config:
    project_root: str


class _Window:
    def __init__(self, project_root):
        self.config = _Config(str(project_root))
        self.pages = {}
        self.navigated: list[str] = []

    def navigate_to_page(self, page_key: str) -> None:
        self.navigated.append(page_key)


def test_feature_registry_derives_page_routes_and_search_terms():
    registry = build_feature_registry()

    machine = registry.get("machine_360")
    assert machine is not None
    assert machine.route == "page:machine_360"
    assert any(feature.key == "machine_360" for feature in registry.search("machine"))
    assert registry.get("tool_registry") is not None


def test_feature_registry_navigation_commands_are_complete(fake_project):
    features = build_feature_registry()
    commands = build_dashboard_command_registry(_Window(fake_project))

    warnings = features.validate(command_ids=[command.command_id for command in commands.commands])

    assert warnings == []
    assert commands.get("nav.fmea").display_name == "Open FMEA-Lite"
    assert commands.get("nav.tool_registry").display_name == "Open Tool Registry"
