from __future__ import annotations

import pytest

from app.command_registry import CommandRegistry, CommandSpec
from app.widgets.command_palette import CommandPalette
from tests.ui.helpers import table_text


pytestmark = pytest.mark.usability


def test_command_palette_filters_commands(qapp, fake_project):
    registry = CommandRegistry(
        [
            CommandSpec("nav.home", "Open Home", category="Navigation"),
            CommandSpec("nav.audit", "Open EOAT Audit", aliases=("audit",), category="Navigation"),
            CommandSpec("settings.open", "Open Settings", category="Settings"),
        ]
    )
    palette = CommandPalette(registry, str(fake_project))
    palette.show()

    palette.query_edit.setText("audit")
    qapp.processEvents()

    text = table_text(palette.command_table)
    assert "Open EOAT Audit" in text
    assert "Open Settings" not in text


def test_dashboard_exposes_ctrl_k_command_palette(qapp, fake_config, monkeypatch):
    import app.widgets.command_palette as command_palette_module
    from app.dashboard_ui import DashboardWindow

    called = {"count": 0}

    def fake_exec(self):
        called["count"] += 1
        return 0

    monkeypatch.setattr(command_palette_module.CommandPalette, "exec", fake_exec)
    window = DashboardWindow(fake_config)
    window.show()

    assert window.command_palette_shortcut.key().toString() == "Ctrl+K"
    window.open_command_palette()
    assert called["count"] == 1
