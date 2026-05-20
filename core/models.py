from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectStatus:
    project_root: str
    project_root_exists: bool
    master_workbook_exists: bool
    git_repo_detected: bool

