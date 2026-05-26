from __future__ import annotations

import subprocess
import sys

from core.constants import TOOLKIT_ROOT
from core.tool_registry import ToolRegistry

CLI_HELP_TIMEOUT_SECONDS = 60


def test_implemented_tool_cli_help():
    registry = ToolRegistry.load()
    scripts = sorted({tool.cli_module for tool in registry.implemented_tools() if tool.cli_module.startswith("tools/")})
    assert scripts
    for script in scripts:
        proc = subprocess.run(
            [sys.executable, str(TOOLKIT_ROOT / script), "--help"],
            cwd=TOOLKIT_ROOT,
            capture_output=True,
            text=True,
            timeout=CLI_HELP_TIMEOUT_SECONDS,
        )
        assert proc.returncode == 0, script
        assert "usage:" in (proc.stdout + proc.stderr).lower(), script
