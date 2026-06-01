from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from .logging import log_tool_run
from .result import ToolResult


def run_python_script(
    script_path: str | Path,
    args: list[str] | None = None,
    cwd: str | Path | None = None,
    tool_id: str = "python_script",
    tool_name: str = "Python Script",
    timeout_seconds: int | None = None,
    project_root_for_log: str | Path | None = None,
) -> ToolResult:
    started = time.perf_counter()
    script = Path(script_path)
    if not script.exists():
        result = ToolResult.fail(
            tool_id,
            tool_name,
            "Script does not exist.",
            errors=[str(script)],
            duration_seconds=time.perf_counter() - started,
        )
        if project_root_for_log:
            warning = log_tool_run(result, project_root_for_log)
            if warning:
                result.warnings.append(warning)
        return result

    command = [sys.executable, str(script), *(args or [])]
    try:
        completed = subprocess.run(
            command,
            cwd=Path(cwd) if cwd else script.parent,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        details = []
        if completed.stdout.strip():
            details.append(completed.stdout.strip())
        errors = [completed.stderr.strip()] if completed.stderr.strip() else []
        result = ToolResult(
            tool_id=tool_id,
            tool_name=tool_name,
            success=completed.returncode == 0,
            summary=f"Command exited with code {completed.returncode}.",
            details=details,
            errors=errors,
            metrics={"return_code": completed.returncode},
            duration_seconds=time.perf_counter() - started,
        )
    except subprocess.TimeoutExpired as exc:
        result = ToolResult.fail(
            tool_id,
            tool_name,
            "Command timed out.",
            errors=[str(exc)],
            duration_seconds=time.perf_counter() - started,
        )
    except OSError as exc:
        result = ToolResult.fail(
            tool_id,
            tool_name,
            "Command could not be started.",
            errors=[str(exc)],
            duration_seconds=time.perf_counter() - started,
        )

    if project_root_for_log:
        warning = log_tool_run(result, project_root_for_log)
        if warning:
            result.warnings.append(warning)
    return result
