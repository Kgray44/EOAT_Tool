from __future__ import annotations

import importlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .analysis_common import write_timestamped_report
from .config import load_config
from .constants import TOOLKIT_ROOT
from .git_activity import is_git_repo
from .logging import log_tool_run, read_recent_activity
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import safe_write_text
from .tool_registry import ToolRegistry
from .validation import validate_project_foundation

TOOL_ID = "system_audit"
TOOL_NAME = "EOAT Command Center System Audit"

REQUIRED_IMPORTS = ["PySide6", "openpyxl", "pandas", "matplotlib", "docx", "pytest"]

EXPECTED_APP_PAGES = [
    "home.py",
    "settings.py",
    "tool_registry.py",
    "workbook_health.py",
    "reports.py",
    "schedule.py",
    "audit.py",
    "photos.py",
    "audit_progress.py",
    "issue_analysis.py",
    "standards_docs.py",
    "fmea.py",
    "pilot_candidates.py",
    "kpi_dashboard.py",
    "pm_checklists.py",
    "bom_spares.py",
    "handoff.py",
]

EXPECTED_CORE_MODULES = [
    "config.py",
    "paths.py",
    "result.py",
    "logging.py",
    "safe_files.py",
    "workbook_io.py",
    "validation.py",
    "tool_registry.py",
    "system_audit.py",
    "workflows.py",
    "project_backup.py",
]


def _check_import(module: str) -> tuple[bool, str]:
    try:
        importlib.import_module(module)
        return True, f"Import OK: {module}"
    except Exception as exc:
        return False, f"Import failed: {module} ({exc})"


def _file_check(folder: Path, expected: list[str], label: str) -> tuple[list[str], list[str]]:
    details: list[str] = []
    warnings: list[str] = []
    for name in expected:
        path = folder / name
        if path.exists():
            details.append(f"Found {label}: {path}")
        else:
            warnings.append(f"Missing {label}: {path}")
    return details, warnings


def _cli_help_check(script: Path) -> tuple[bool, str]:
    if not script.exists():
        return False, f"Missing CLI script: {script}"
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=TOOLKIT_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
    except Exception as exc:
        return False, f"CLI help failed for {script.name}: {exc}"
    if proc.returncode == 0 and "usage:" in (proc.stdout + proc.stderr).lower():
        return True, f"CLI help OK: {script.name}"
    return False, f"CLI help returned {proc.returncode}: {script.name}"


def run_system_audit(project_root: str | Path, check_cli_help: bool = True, log_activity: bool = True) -> ToolResult:
    start = time.perf_counter()
    paths = resolve_project_paths(project_root)
    details: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []
    metrics: dict[str, Any] = {}

    for module in REQUIRED_IMPORTS:
        ok, message = _check_import(module)
        (details if ok else warnings).append(message)

    page_details, page_warnings = _file_check(TOOLKIT_ROOT / "app" / "pages", EXPECTED_APP_PAGES, "app page")
    core_details, core_warnings = _file_check(TOOLKIT_ROOT / "core", EXPECTED_CORE_MODULES, "core module")
    details.extend(page_details + core_details)
    warnings.extend(page_warnings + core_warnings)

    for folder in ["tests", "docs", "tools", "app", "core", "data_templates"]:
        path = TOOLKIT_ROOT / folder
        if path.exists():
            details.append(f"Found toolkit folder: {path}")
        else:
            warnings.append(f"Missing toolkit folder: {path}")

    try:
        config = load_config()
        details.append(f"Config loaded. Configured project root: {config.project_root}")
    except Exception as exc:
        errors.append(f"Config load failed: {exc}")

    try:
        registry = ToolRegistry.load()
        tools = registry.list_tools()
        metrics["registered_tools"] = len(tools)
        metrics["implemented_tools"] = len(registry.implemented_tools())
        details.append(f"Tool registry loaded with {len(tools)} tools.")
        if check_cli_help:
            for tool in tools:
                if tool.cli_module and tool.cli_module.startswith("tools/"):
                    ok, message = _cli_help_check(TOOLKIT_ROOT / tool.cli_module)
                    (details if ok else warnings).append(message)
    except Exception as exc:
        errors.append(f"Tool registry failed: {exc}")

    try:
        test_path = paths.activity_logs / "_system_audit_write_test.txt"
        safe_write_text(test_path, "system audit write test\n", overwrite=True)
        details.append(f"Safe file helper write OK: {test_path}")
        test_path.unlink(missing_ok=True)
    except Exception as exc:
        warnings.append(f"Safe file helper write test failed: {exc}")

    foundation = validate_project_foundation(project_root)
    details.extend(foundation.details)
    warnings.extend(foundation.warnings)
    errors.extend(foundation.errors)
    metrics.update({f"foundation_{key}": value for key, value in foundation.metrics.items()})

    for label, folder in {
        "validation reports": paths.validation_reports,
        "daily reports": paths.daily_reports,
        "weekly reports": paths.weekly_reports,
        "activity logs": paths.activity_logs,
        "handoff": paths.final_handoff,
    }.items():
        if folder.exists():
            details.append(f"Readable project folder: {label} -> {folder}")
        else:
            warnings.append(f"Missing project folder: {label} -> {folder}")

    activities, activity_warning = read_recent_activity(project_root, limit=5)
    metrics["recent_activity_entries"] = len(activities)
    if activity_warning:
        warnings.append(activity_warning)
    else:
        details.append(f"Recent activity entries readable: {len(activities)}")

    git_repo, git_warning = is_git_repo(project_root)
    metrics["git_repo_detected"] = git_repo
    if git_repo:
        details.append("Git repository detected.")
    elif git_warning:
        warnings.append(f"Git not detected or unavailable: {git_warning}")

    success = not errors
    summary = "System audit completed." if success else "System audit completed with errors."
    result = ToolResult(
        tool_id=TOOL_ID,
        tool_name=TOOL_NAME,
        success=success,
        summary=summary,
        details=details,
        warnings=warnings,
        errors=errors,
        metrics=metrics,
        duration_seconds=time.perf_counter() - start,
    )
    if paths.project_root.exists():
        try:
            report = write_timestamped_report(paths.validation_reports, "System_Audit", result.to_markdown())
            result.files_created.append(str(report))
            result.output_reports.append(str(report))
        except Exception as exc:
            result.warnings.append(f"Could not write system audit report: {exc}")
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result
