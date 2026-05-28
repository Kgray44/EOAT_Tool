from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scripts.repo_safety_audit import IMAGE_SUFFIXES, WORKBOOK_SUFFIXES, audit_repo, audit_staged_files, git_staged_files, is_allowed_data_artifact

from .constants import TOOLKIT_ROOT
from .result import ToolResult
from .safe_files import ensure_directory, safe_write_text

PASS = "pass"
FAIL = "fail"
WARNING = "warning"
UNKNOWN = "unknown"

TOOL_ID = "release_readiness"
TOOL_NAME = "Release Readiness"


@dataclass(frozen=True)
class ReleaseCheck:
    key: str
    label: str
    status: str
    details: str = ""
    severity: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReleaseReadinessSummary:
    checks: tuple[ReleaseCheck, ...]
    staged_files: tuple[str, ...]
    git_status: tuple[str, ...]
    branch: str
    git_warning: str = ""

    @property
    def ready(self) -> bool:
        return all(check.status == PASS for check in self.checks if check.severity == "blocker")

    def to_dict(self) -> dict[str, Any]:
        return {
            "checks": [check.to_dict() for check in self.checks],
            "staged_files": list(self.staged_files),
            "git_status": list(self.git_status),
            "branch": self.branch,
            "git_warning": self.git_warning,
            "ready": self.ready,
        }

    def to_markdown(self) -> str:
        lines = ["# Release Readiness", "", f"- Branch: {self.branch or 'Unknown'}", f"- Ready: {'Yes' if self.ready else 'No'}"]
        if self.git_warning:
            lines.append(f"- Git warning: {self.git_warning}")
        lines.extend(["", "## Checks", "| Check | Status | Details |", "| --- | --- | --- |"])
        lines.extend(f"| {check.label} | {check.status} | {check.details} |" for check in self.checks)
        lines.extend(["", "## Staged Files"])
        lines.extend([f"- {path}" for path in self.staged_files] or ["- None"])
        return "\n".join(lines) + "\n"


def collect_release_readiness(
    repo_root: str | Path = TOOLKIT_ROOT,
    *,
    git_executable: str = "git",
    include_staged_safety_scan: bool = True,
) -> ReleaseReadinessSummary:
    root = Path(repo_root).resolve()
    staged_paths, staged_warning = git_staged_files(root, git_executable)
    staged_rel = tuple(_relative_string(path, root) for path in staged_paths)
    staged_findings = audit_staged_files(root, git_executable) if include_staged_safety_scan and not staged_warning else []
    blocker_count = sum(1 for finding in staged_findings if finding.severity == "BLOCKER")
    warning_count = sum(1 for finding in staged_findings if finding.severity == "WARNING")
    git_status, git_status_warning = _git_status(root, git_executable)
    branch, branch_warning = _git_branch(root, git_executable)
    git_warning = staged_warning or git_status_warning or branch_warning or ""

    checks = [
        ReleaseCheck("tests", "Tests", UNKNOWN, "Not run in this readiness refresh.", "blocker"),
        ReleaseCheck(
            "repo_safety_audit",
            "Repo safety audit",
            UNKNOWN,
            "Run Repo Safety Audit for full working-tree safety status.",
            "blocker",
        ),
        ReleaseCheck(
            "app_smoke_test",
            "App smoke test",
            UNKNOWN if (root / "tests" / "test_ui_smoke.py").exists() else WARNING,
            "Smoke test is available; run tests." if (root / "tests" / "test_ui_smoke.py").exists() else "No app smoke test file found.",
            "warning",
        ),
    ]
    if staged_warning:
        checks.extend(
            [
                ReleaseCheck("staged_workbooks", "No real workbooks staged", UNKNOWN, staged_warning, "blocker"),
                ReleaseCheck("staged_photos", "No real photos staged", UNKNOWN, staged_warning, "blocker"),
                ReleaseCheck("staged_local_config", "No local config staged", UNKNOWN, staged_warning, "blocker"),
                ReleaseCheck("staged_generated_outputs", "No generated reports/logs/cache staged", UNKNOWN, staged_warning, "blocker"),
                ReleaseCheck("staged_safety_scan", "Staged safety scan", UNKNOWN, staged_warning, "blocker"),
            ]
        )
    else:
        checks.extend(
            [
                _staged_check("staged_workbooks", "No real workbooks staged", staged_paths, root, _is_unsafe_workbook),
                _staged_check("staged_photos", "No real photos staged", staged_paths, root, _is_unsafe_photo),
                _staged_check("staged_local_config", "No local config staged", staged_paths, root, _is_local_config),
                _staged_check("staged_generated_outputs", "No generated reports/logs/cache staged", staged_paths, root, _is_generated_output),
                ReleaseCheck(
                    "staged_safety_scan",
                    "Staged safety scan",
                    FAIL if blocker_count else WARNING if warning_count else PASS if include_staged_safety_scan else UNKNOWN,
                    (
                        f"Blockers: {blocker_count}; warnings: {warning_count}; staged files: {len(staged_paths)}"
                        if include_staged_safety_scan
                        else "Not run on page open. Use Show Staged Files or Run Repo Safety Audit before committing."
                    ),
                    "blocker",
                ),
            ]
        )
    checks.extend(
        [
            ReleaseCheck("readme_usage", "README/USAGE present", PASS if _readme_usage_present(root) else FAIL, "README.md and USAGE.md/docs/USAGE.md checked.", "blocker"),
            ReleaseCheck("demo_project", "Demo project present", PASS if (root / "examples" / "demo_project").exists() else FAIL, "examples/demo_project checked.", "blocker"),
            ReleaseCheck("git_status", "Git status visible", PASS if not git_status_warning else UNKNOWN, f"{len(git_status)} status line(s)." if not git_status_warning else git_status_warning, "warning"),
            ReleaseCheck("branch_status", "Branch status visible", PASS if branch else UNKNOWN, branch or branch_warning or "Branch unavailable.", "warning"),
        ]
    )
    return ReleaseReadinessSummary(tuple(checks), staged_rel, tuple(git_status), branch, git_warning)


def run_repo_safety_audit(repo_root: str | Path = TOOLKIT_ROOT, *, staged_only: bool = False, git_executable: str = "git") -> ToolResult:
    started = time.perf_counter()
    root = Path(repo_root).resolve()
    findings = audit_staged_files(root, git_executable) if staged_only else audit_repo(root)
    blockers = [finding.format(root) for finding in findings if finding.severity == "BLOCKER"]
    warnings = [finding.format(root) for finding in findings if finding.severity == "WARNING"]
    return ToolResult(
        tool_id=TOOL_ID,
        tool_name=TOOL_NAME,
        success=not blockers,
        summary=("Repo safety audit passed." if not blockers else "Repo safety audit found blockers."),
        details=[f"Scope: {'staged files' if staged_only else 'working tree'}", f"Blockers: {len(blockers)}", f"Warnings: {len(warnings)}", *blockers[:25]],
        warnings=warnings[:25],
        errors=blockers,
        metrics={"blockers": len(blockers), "warnings": len(warnings), "staged_only": staged_only},
        duration_seconds=time.perf_counter() - started,
    )


def run_release_tests(repo_root: str | Path = TOOLKIT_ROOT, *, smoke_only: bool = False, timeout_seconds: int = 600) -> ToolResult:
    started = time.perf_counter()
    root = Path(repo_root).resolve()
    command = [sys.executable, "-m", "pytest", "-q"]
    if smoke_only:
        command.append("tests/test_ui_smoke.py")
    try:
        completed = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=timeout_seconds)
    except (OSError, subprocess.SubprocessError) as exc:
        return ToolResult.fail(TOOL_ID, TOOL_NAME, "Could not run pytest.", errors=[str(exc)], duration_seconds=time.perf_counter() - started)
    output = "\n".join((completed.stdout or "", completed.stderr or "").splitlines()[-30:])
    return ToolResult(
        tool_id=TOOL_ID,
        tool_name=TOOL_NAME,
        success=completed.returncode == 0,
        summary="Tests passed." if completed.returncode == 0 else "Tests failed.",
        details=[f"Command: {' '.join(command)}", output],
        errors=[] if completed.returncode == 0 else [output],
        metrics={"returncode": completed.returncode, "smoke_only": smoke_only},
        duration_seconds=time.perf_counter() - started,
    )


def show_staged_files(repo_root: str | Path = TOOLKIT_ROOT, *, git_executable: str = "git") -> ToolResult:
    started = time.perf_counter()
    root = Path(repo_root).resolve()
    files, warning = git_staged_files(root, git_executable)
    if warning:
        return ToolResult.fail(TOOL_ID, TOOL_NAME, "Could not list staged files.", errors=[warning], duration_seconds=time.perf_counter() - started)
    rel = [_relative_string(path, root) for path in files]
    return ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Listed staged files.",
        details=rel or ["No staged files."],
        metrics={"staged_files": len(rel)},
        duration_seconds=time.perf_counter() - started,
    )


def install_pre_commit_hook(repo_root: str | Path = TOOLKIT_ROOT, *, git_executable: str = "git", force: bool = False) -> ToolResult:
    started = time.perf_counter()
    root = Path(repo_root).resolve()
    git_dir, warning = _git_dir(root, git_executable)
    if warning or git_dir is None:
        return ToolResult.fail(TOOL_ID, TOOL_NAME, "Could not locate .git directory.", errors=[warning or "Unknown git error"], duration_seconds=time.perf_counter() - started)
    hooks = ensure_directory(git_dir / "hooks")
    hook_path = hooks / "pre-commit"
    text = """#!/bin/sh
set -eu
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
echo "Running EOAT staged repo safety audit..."
python scripts/repo_safety_audit.py --staged
"""
    if hook_path.exists() and not force:
        return ToolResult.fail(
            TOOL_ID,
            TOOL_NAME,
            "Pre-commit hook already exists.",
            errors=["Use force=True only after reviewing the existing local hook."],
            duration_seconds=time.perf_counter() - started,
        )
    saved = safe_write_text(hook_path, text, overwrite=force)
    try:
        os.chmod(saved, 0o755)
    except OSError:
        pass
    return ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Installed local pre-commit safety hook.",
        details=[str(saved), "The hook runs scripts/repo_safety_audit.py --staged."],
        files_created=[str(saved)],
        duration_seconds=time.perf_counter() - started,
    )


def commit_checklist_markdown() -> str:
    return "\n".join(
        [
            "# EOAT Commit Checklist",
            "",
            "- Run tests or document the last known failing test.",
            "- Run `python scripts/repo_safety_audit.py --staged` before commit.",
            "- Confirm no real workbooks, photos, reports, logs, cache files, or local configs are staged.",
            "- Confirm README/USAGE and maintenance docs are current.",
            "- Confirm generated real outputs stay in the private project root, not the repo.",
            "- Review branch and staged file list before pushing.",
            "",
        ]
    )


def _staged_check(key: str, label: str, staged_paths: list[Path], root: Path, predicate) -> ReleaseCheck:
    offenders = [_relative_string(path, root) for path in staged_paths if predicate(path, root)]
    return ReleaseCheck(key, label, FAIL if offenders else PASS, "; ".join(offenders[:5]) if offenders else "No offenders staged.", "blocker")


def _is_unsafe_workbook(path: Path, root: Path) -> bool:
    return path.suffix.lower() in WORKBOOK_SUFFIXES and not is_allowed_data_artifact(path, root)


def _is_unsafe_photo(path: Path, root: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES and not _relative_string(path, root).startswith(("examples/demo_project/", "templates/", "tests/", "data_templates/", "docs/"))


def _is_local_config(path: Path, root: Path) -> bool:
    rel = _relative_string(path, root).lower()
    return rel in {"config/local_config.json", "config/user_config.json", "config/config.json", "local_config.json", "user_config.json"} or rel.endswith(".local.json")


def _is_generated_output(path: Path, root: Path) -> bool:
    parts = {part.lower().replace("-", "_").replace(" ", "_") for part in Path(_relative_string(path, root)).parts}
    return bool(parts & {"reports", "logs", "cache", "backups", "_backups", "exports", "snapshots", "activity_logs", "validation_reports"})


def _readme_usage_present(root: Path) -> bool:
    return (root / "README.md").exists() and ((root / "USAGE.md").exists() or (root / "docs" / "USAGE.md").exists())


def _git_status(root: Path, git_executable: str) -> tuple[list[str], str | None]:
    try:
        completed = subprocess.run([git_executable, "status", "--short"], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return [], str(exc)
    if completed.returncode != 0:
        return [], completed.stderr.strip() or str(completed.returncode)
    return completed.stdout.splitlines(), None


def _git_branch(root: Path, git_executable: str) -> tuple[str, str | None]:
    try:
        completed = subprocess.run([git_executable, "rev-parse", "--abbrev-ref", "HEAD"], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return "", str(exc)
    if completed.returncode != 0:
        return "", completed.stderr.strip() or str(completed.returncode)
    return completed.stdout.strip(), None


def _git_dir(root: Path, git_executable: str) -> tuple[Path | None, str | None]:
    try:
        completed = subprocess.run([git_executable, "rev-parse", "--git-dir"], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if completed.returncode != 0:
        return None, completed.stderr.strip() or str(completed.returncode)
    path = Path(completed.stdout.strip())
    return (root / path).resolve() if not path.is_absolute() else path, None


def _relative_string(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


__all__ = [
    "FAIL",
    "PASS",
    "UNKNOWN",
    "WARNING",
    "ReleaseCheck",
    "ReleaseReadinessSummary",
    "collect_release_readiness",
    "commit_checklist_markdown",
    "install_pre_commit_hook",
    "run_release_tests",
    "run_repo_safety_audit",
    "show_staged_files",
]
