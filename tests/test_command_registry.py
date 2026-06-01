from __future__ import annotations

from dataclasses import dataclass

from app.command_registry import CommandRegistry, CommandSpec, build_dashboard_command_registry


@dataclass
class _Config:
    project_root: str


class _Window:
    def __init__(self, project_root):
        self.config = _Config(str(project_root))
        self.navigated: list[str] = []
        self.pages = {}

    def navigate_to_page(self, page_key: str) -> None:
        self.navigated.append(page_key)


def test_command_registry_contains_expected_commands(fake_project):
    registry = build_dashboard_command_registry(_Window(fake_project))
    ids = {command.command_id for command in registry.commands}

    assert "nav.home" in ids
    assert "nav.audit" in ids
    assert "nav.press_view" in ids
    assert "nav.fmea" in ids
    assert "nav.tool_registry" in ids
    assert "validation.run_foundation" in ids
    assert "scheduled_reports.generate_daily" in ids
    assert "scheduled_reports.generate_weekly" in ids
    assert "project.open_folder" in ids


def test_command_filtering_and_execution(fake_project):
    window = _Window(fake_project)
    registry = build_dashboard_command_registry(window)
    rows = registry.filter("press")

    assert any(command.command_id == "nav.press_view" for command in rows)
    assert registry.execute("nav.press_view") is True
    assert window.navigated == ["press_view"]


def test_file_modifying_commands_require_confirmation(fake_project):
    registry = build_dashboard_command_registry(_Window(fake_project))

    assert registry.get("validation.run_foundation").requires_confirmation is True
    assert registry.get("validation.run_foundation").writes_files is True
    assert registry.get("dashboard.deep_refresh").requires_confirmation is True
    assert registry.get("scheduled_reports.generate_daily").requires_confirmation is True
    assert registry.get("nav.home").requires_confirmation is False
    assert registry.validate() == []


def test_duplicate_command_ids_are_rejected():
    registry = CommandRegistry()
    registry.register(CommandSpec("demo", "Demo"))

    try:
        registry.register(CommandSpec("demo", "Demo Duplicate"))
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate command ID was accepted.")


def test_context_recent_and_disabled_command_metadata(fake_project):
    window = _Window(fake_project)
    registry = build_dashboard_command_registry(window)
    registry.register(
        CommandSpec("demo.disabled", "Disabled Demo", enabled=False, disabled_reason="Needs a selected audit.")
    )

    current_rows = registry.filter(current_page_key="workbook_health")
    assert current_rows[0].is_context_command("workbook_health")
    assert any(command.command_id == "validation.run_foundation" for command in current_rows[:5])

    assert registry.execute("nav.press_view") is True
    assert registry.recent_commands()[0].command_id == "nav.press_view"

    disabled = registry.get("demo.disabled")
    assert disabled.enabled is False
    assert disabled.disabled_reason == "Needs a selected audit."
    assert registry.execute("demo.disabled") is False
