from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.constants import TOOLKIT_ROOT
from core.tool_registry import ToolRegistry

CLI_HELP_TIMEOUT_SECONDS = 60


def test_implemented_tool_cli_help():
    registry = ToolRegistry.load()
    scripts = sorted({tool.cli_module for tool in registry.implemented_tools() if tool.cli_module.startswith("tools/")})
    assert scripts

    def run_help(script: str) -> tuple[str, int, str]:
        proc = subprocess.run(
            [sys.executable, str(TOOLKIT_ROOT / script), "--help"],
            cwd=TOOLKIT_ROOT,
            capture_output=True,
            text=True,
            timeout=CLI_HELP_TIMEOUT_SECONDS,
        )
        return script, proc.returncode, proc.stdout + proc.stderr

    workers = min(8, len(scripts))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run_help, script) for script in scripts]
        for future in as_completed(futures):
            script, returncode, output = future.result()
            assert returncode == 0, script
            assert "usage:" in output.lower(), script
