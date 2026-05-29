from __future__ import annotations

from core.constants import TOOLKIT_ROOT
from core.tool_registry import ToolRegistry


def test_implemented_registry_cli_modules_exist():
    registry = ToolRegistry.load()
    missing = []
    for tool in registry.implemented_tools():
        if tool.cli_module and tool.cli_module.startswith("tools/"):
            if not (TOOLKIT_ROOT / tool.cli_module).exists():
                missing.append(tool.cli_module)
    assert missing == []


def test_phase6_registry_entries_present():
    registry = ToolRegistry.load()
    for tool_id in ["system_audit", "workflow_runner", "project_backup"]:
        tool = registry.get(tool_id)
        assert tool is not None
        assert tool.implementation_status == "implemented"
