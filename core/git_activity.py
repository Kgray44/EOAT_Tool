from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

from .constants import DEFAULT_GIT_EXECUTABLE


def find_git_executable(configured_path: str | Path | None = None) -> tuple[Path | None, str | None]:
    candidates = []
    if configured_path:
        candidates.append(Path(configured_path))
    candidates.append(DEFAULT_GIT_EXECUTABLE)
    for candidate in candidates:
        if candidate.exists():
            return candidate, None
    found = shutil.which("git")
    if found:
        return Path(found), None
    return None, "Git executable was not found."


def _run_git(
    project_root: str | Path, args: list[str], configured_path: str | Path | None = None
) -> tuple[bool, str, str]:
    git_path, warning = find_git_executable(configured_path)
    if git_path is None:
        return False, "", warning or "Git executable was not found."
    try:
        completed = subprocess.run(
            [str(git_path), *args],
            cwd=Path(project_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return False, "", str(exc)
    ok = completed.returncode == 0
    stderr = completed.stderr.strip()
    return ok, completed.stdout.strip(), stderr


def is_git_repo(project_root: str | Path, configured_path: str | Path | None = None) -> tuple[bool, str | None]:
    ok, stdout, stderr = _run_git(project_root, ["rev-parse", "--is-inside-work-tree"], configured_path)
    if not ok:
        return False, stderr or "Not a Git repository."
    return stdout.lower() == "true", None


def get_git_status_short(
    project_root: str | Path, configured_path: str | Path | None = None
) -> tuple[list[str], str | None]:
    ok, stdout, stderr = _run_git(project_root, ["status", "--short"], configured_path)
    if not ok:
        return [], stderr
    return [line for line in stdout.splitlines() if line.strip()], None


def get_recent_commits_today(
    project_root: str | Path, configured_path: str | Path | None = None
) -> tuple[list[str], str | None]:
    today = date.today().isoformat()
    ok, stdout, stderr = _run_git(
        project_root,
        ["log", "--since", today, "--pretty=format:%h %ad %s", "--date=short"],
        configured_path,
    )
    if not ok:
        return [], stderr
    return [line for line in stdout.splitlines() if line.strip()], None
