from __future__ import annotations

import subprocess

import pytest

from core.release_readiness import collect_release_readiness, commit_checklist_markdown, install_pre_commit_hook


def test_release_readiness_handles_missing_git_gracefully(tmp_path):
    (tmp_path / "README.md").write_text("# Readme\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "USAGE.md").write_text("# Usage\n", encoding="utf-8")
    (tmp_path / "examples" / "demo_project").mkdir(parents=True)

    summary = collect_release_readiness(tmp_path, git_executable="definitely-missing-git")

    assert summary.git_warning
    assert any(check.status == "unknown" for check in summary.checks)
    assert any(check.key == "readme_usage" and check.status == "pass" for check in summary.checks)
    assert any(check.key == "demo_project" and check.status == "pass" for check in summary.checks)


def test_commit_checklist_mentions_staged_safety_audit():
    checklist = commit_checklist_markdown()

    assert "repo_safety_audit.py --staged" in checklist
    assert "real workbooks" in checklist


def test_pre_commit_hook_installer_is_local_only(tmp_path):
    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git executable unavailable")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    result = install_pre_commit_hook(tmp_path)

    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    assert result.success is True
    assert hook.exists()
    assert "repo_safety_audit.py --staged" in hook.read_text(encoding="utf-8")
