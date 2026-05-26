from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .constants import DEFAULT_PROJECT_ROOT, EXPECTED_NUMBERED_FOLDERS
from .paths import resolve_project_paths

ProjectDataMode = Literal["demo", "real", "missing", "invalid"]


@dataclass(frozen=True)
class ProjectRootStatus:
    project_root: Path
    mode: ProjectDataMode
    master_workbook: Path
    missing_items: list[str] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        return self.mode in {"demo", "real"}

    @property
    def mode_label(self) -> str:
        return {
            "demo": "Demo",
            "real": "Real",
            "missing": "Missing",
            "invalid": "Invalid",
        }[self.mode]

    @property
    def message(self) -> str:
        if self.mode == "demo":
            return "Demo project is active. This is synthetic sample data, not your real EOAT project."
        if self.mode == "real":
            return "Real project root is active. Real files stay outside GitHub; this path is stored only in local config."
        if self.mode == "missing":
            return f"Project root is missing: {self.project_root}"
        return "Project root is incomplete: " + "; ".join(self.missing_items)


def _normalized_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    try:
        return candidate.resolve()
    except OSError:
        return candidate.absolute()


def is_demo_project_root(path: str | Path) -> bool:
    return _normalized_path(path) == _normalized_path(DEFAULT_PROJECT_ROOT)


def validate_project_root(path: str | Path) -> ProjectRootStatus:
    project_root = Path(path).expanduser()
    paths = resolve_project_paths(project_root)
    missing: list[str] = []
    if not project_root.exists():
        return ProjectRootStatus(project_root=project_root, mode="missing", master_workbook=paths.master_workbook, missing_items=[f"Project root does not exist: {project_root}"])
    for folder_name in EXPECTED_NUMBERED_FOLDERS:
        folder = project_root / folder_name
        if not folder.exists():
            missing.append(f"Missing expected folder: {folder_name}")
    if not paths.master_workbook.exists():
        missing.append(f"Missing master workbook: {paths.master_workbook}")
    if missing:
        return ProjectRootStatus(project_root=project_root, mode="invalid", master_workbook=paths.master_workbook, missing_items=missing)
    return ProjectRootStatus(project_root=project_root, mode="demo" if is_demo_project_root(project_root) else "real", master_workbook=paths.master_workbook)


def project_data_mode(config_or_path) -> ProjectDataMode:
    path = getattr(config_or_path, "project_root", config_or_path)
    return validate_project_root(path).mode
