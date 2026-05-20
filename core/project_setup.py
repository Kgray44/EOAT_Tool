from __future__ import annotations

from pathlib import Path

from .constants import TOOLKIT_ROOT
from .logging import log_tool_run
from .result import ToolResult
from .tool_runner import run_python_script


def run_project_setup_safe(project_root: str | Path, dry_run: bool = False) -> ToolResult:
    script = TOOLKIT_ROOT / "setup_eoat_project.py"
    args = ["--project-root", str(project_root), "--safe"]
    if dry_run:
        args.append("--dry-run")
    result = run_python_script(
        script,
        args=args,
        cwd=TOOLKIT_ROOT,
        tool_id="project_setup",
        tool_name="EOAT Project Setup Tool",
        timeout_seconds=120,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result

