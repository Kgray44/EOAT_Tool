from __future__ import annotations

import importlib.util
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import UserConfig
from .paths import resolve_project_paths
from .project_root_status import validate_project_root
from .release_readiness import collect_release_readiness, run_repo_safety_audit
from .scheduled_reports import get_scheduled_report_status
from .workbook_io import row_dicts
from .workbook_locks import detect_workbook_lock

PASS = "pass"
WARNING = "warning"
FAIL = "fail"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class AppHealthCheck:
    key: str
    label: str
    status: str
    details: str
    recommendation: str = ""
    severity: str = "info"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AppHealthSummary:
    checks: tuple[AppHealthCheck, ...]

    @property
    def status(self) -> str:
        if any(check.status == FAIL and check.severity == "blocker" for check in self.checks):
            return FAIL
        if any(check.status in {FAIL, WARNING} for check in self.checks):
            return WARNING
        if any(check.status == UNKNOWN for check in self.checks):
            return UNKNOWN
        return PASS

    @property
    def counts(self) -> dict[str, int]:
        counts = {PASS: 0, WARNING: 0, FAIL: 0, UNKNOWN: 0}
        for check in self.checks:
            counts[check.status] = counts.get(check.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "counts": self.counts, "checks": [check.to_dict() for check in self.checks]}


def run_app_health_checks(
    project_root: str | Path,
    *,
    config: UserConfig | None = None,
    check_repo_safety: bool = False,
    check_scheduled_tasks: bool = False,
) -> AppHealthSummary:
    paths = resolve_project_paths(project_root)
    checks: list[AppHealthCheck] = []
    checks.append(_python_check())
    checks.extend(_dependency_checks())
    checks.append(_pyside_check())

    root_status = validate_project_root(project_root)
    checks.append(
        AppHealthCheck(
            "project_root",
            "Project root exists",
            PASS if Path(project_root).exists() else FAIL,
            root_status.message,
            "Select or create a valid project root.",
            "blocker",
        )
    )
    checks.append(
        AppHealthCheck(
            "project_mode",
            "Demo vs real mode",
            PASS if root_status.mode in {"demo", "real"} else WARNING,
            root_status.mode_label,
            "Use demo mode for testing and real mode for plant work.",
        )
    )
    checks.append(
        AppHealthCheck(
            "master_workbook",
            "Master workbook exists",
            PASS if paths.master_workbook.exists() else FAIL,
            str(paths.master_workbook),
            "Create or restore EOAT_Master_Tracker.xlsx.",
            "blocker",
        )
    )

    lock = detect_workbook_lock(paths.master_workbook)
    checks.append(
        AppHealthCheck(
            "workbook_lock",
            "Workbook lock/open status",
            PASS if lock.can_write else WARNING if lock.exists else FAIL,
            lock.message,
            "Close workbook in Excel before write actions." if lock.locked else lock.error,
        )
    )

    missing_folders = [folder.name for folder in paths.expected_numbered_folders() if not folder.exists()]
    checks.append(
        AppHealthCheck(
            "required_folders",
            "Required folders",
            PASS if not missing_folders else WARNING,
            "All required folders found." if not missing_folders else ", ".join(missing_folders),
            "Run project setup or restore the missing folders.",
        )
    )

    checks.append(_config_check(config))
    checks.append(
        AppHealthCheck(
            "robot_info",
            "Robot_Info optional/found",
            PASS if paths.robot_info_workbook.exists() else UNKNOWN,
            str(paths.robot_info_workbook),
            "Robot_Info.xlsx is optional until robot-side pneumatic updates are used.",
        )
    )
    checks.append(
        AppHealthCheck(
            "annotation_db",
            "Annotation DB",
            PASS if paths.annotations_database.exists() else UNKNOWN,
            str(paths.annotations_database),
            "Create notes/tags once annotations are needed.",
        )
    )
    photo_count = _safe_row_count(paths.master_workbook, "Photo Index")
    checks.append(
        AppHealthCheck(
            "photo_index",
            "Photo index",
            PASS if photo_count > 0 else UNKNOWN,
            f"{photo_count} indexed photo row(s).",
            "Index photos or confirm photo evidence is not required.",
        )
    )

    scheduled = get_scheduled_report_status(project_root, check_tasks=check_scheduled_tasks)
    checks.extend(_scheduled_checks(scheduled, check_scheduled_tasks))

    checks.append(_folder_check("logs", "Logs", paths.logs, "Run any tool to create logs."))
    checks.append(
        _folder_check("cache", "Cache", paths.cache, "Cache is optional; it appears after cached workflows run.")
    )
    checks.append(_repo_safety_check(check_repo_safety))
    checks.append(_git_check())
    checks.append(_release_readiness_check())
    return AppHealthSummary(tuple(checks))


def _python_check() -> AppHealthCheck:
    version = platform.python_version()
    ok = sys.version_info >= (3, 10)
    return AppHealthCheck(
        "python_version", "Python version", PASS if ok else FAIL, version, "Use Python 3.10+.", "blocker"
    )


def _dependency_checks() -> list[AppHealthCheck]:
    checks: list[AppHealthCheck] = []
    for name in ["openpyxl", "pandas", "PIL"]:
        checks.append(
            AppHealthCheck(
                f"dependency_{name}",
                f"Dependency: {name}",
                PASS if importlib.util.find_spec(name) else FAIL,
                "Available" if importlib.util.find_spec(name) else "Missing",
                f"Install {name}.",
                "blocker",
            )
        )
    for name in ["qrcode", "reportlab"]:
        checks.append(
            AppHealthCheck(
                f"optional_dependency_{name}",
                f"Optional dependency: {name}",
                PASS if importlib.util.find_spec(name) else UNKNOWN,
                "Available" if importlib.util.find_spec(name) else "Missing optional dependency.",
                f"Install {name} only if printable/scannable exports require it.",
            )
        )
    return checks


def _pyside_check() -> AppHealthCheck:
    return AppHealthCheck(
        "pyside_import",
        "PySide import",
        PASS if importlib.util.find_spec("PySide6") else FAIL,
        "PySide6 available." if importlib.util.find_spec("PySide6") else "PySide6 missing.",
        "Install PySide6 for the desktop app.",
        "blocker",
    )


def _config_check(config: UserConfig | None) -> AppHealthCheck:
    if config is None:
        return AppHealthCheck(
            "config_valid", "Config valid", UNKNOWN, "No config object supplied.", "Open Settings to load local config."
        )
    missing = []
    if not config.project_root:
        missing.append("project_root")
    if config.theme not in {"light", "dark"}:
        missing.append("theme")
    return AppHealthCheck(
        "config_valid",
        "Config valid",
        PASS if not missing else WARNING,
        "OK" if not missing else f"Unexpected config values: {', '.join(missing)}",
        "Review Settings.",
    )


def _scheduled_checks(status: dict[str, Any], checked: bool) -> list[AppHealthCheck]:
    checks: list[AppHealthCheck] = []
    for key in ["daily", "weekly"]:
        task = status.get(key, {}).get("task", {})
        installed = task.get("installed", "Unknown")
        result = task.get("last_result_description") or task.get("warning") or "Not checked."
        check_status = PASS if installed is True else WARNING if installed is False else UNKNOWN
        checks.append(
            AppHealthCheck(
                f"scheduled_{key}",
                f"{key.title()} scheduled task",
                check_status,
                f"Installed: {installed}; last result: {result}",
                "Use Scheduled Reports page to install or repair tasks."
                if checked
                else "Run with scheduled task checking enabled for installed/last-result status.",
            )
        )
    return checks


def _folder_check(key: str, label: str, path: Path, recommendation: str) -> AppHealthCheck:
    return AppHealthCheck(key, label, PASS if path.exists() else UNKNOWN, str(path), recommendation)


def _repo_safety_check(run_check: bool) -> AppHealthCheck:
    if not run_check:
        return AppHealthCheck(
            "repo_safety_audit",
            "Repo safety audit",
            UNKNOWN,
            "Not run in this health refresh.",
            "Run repo safety audit before release.",
        )
    result = run_repo_safety_audit(Path.cwd())
    return AppHealthCheck(
        "repo_safety_audit",
        "Repo safety audit",
        PASS if result.success else FAIL,
        result.summary,
        "; ".join(result.errors[:3]),
        "blocker",
    )


def _git_check() -> AppHealthCheck:
    try:
        completed = subprocess.run(
            ["git", "status", "--short"], capture_output=True, text=True, timeout=10, check=False
        )
    except Exception as exc:
        return AppHealthCheck("git", "Git", UNKNOWN, str(exc), "Install Git or set git executable.")
    return AppHealthCheck(
        "git",
        "Git",
        PASS if completed.returncode == 0 else WARNING,
        completed.stdout.strip() or completed.stderr.strip() or "Working tree clean.",
    )


def _release_readiness_check() -> AppHealthCheck:
    try:
        readiness = collect_release_readiness(Path.cwd(), include_staged_safety_scan=False)
    except Exception as exc:
        return AppHealthCheck(
            "release_readiness", "Release readiness", UNKNOWN, str(exc), "Open Release Readiness page."
        )
    return AppHealthCheck(
        "release_readiness",
        "Release readiness",
        PASS if readiness.ready else WARNING,
        f"Branch: {readiness.branch}; ready: {readiness.ready}",
        "Run readiness checks before handoff.",
    )


def _safe_row_count(workbook_path: Path, sheet_name: str) -> int:
    try:
        return len(row_dicts(workbook_path, sheet_name))
    except Exception:
        return 0


__all__ = ["AppHealthCheck", "AppHealthSummary", "run_app_health_checks"]
