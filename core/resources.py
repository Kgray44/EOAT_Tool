from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DATA_DIR_NAME = "EOAT Command Center"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_base_path() -> Path:
    """Return the bundled resource root in PyInstaller, or the source checkout root."""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_path(relative_path: str | Path) -> Path:
    """Return an absolute path to a bundled read-only resource."""
    return app_base_path() / Path(relative_path)


def user_data_dir() -> Path:
    """Return the per-user writable folder for packaged app settings and caches."""
    override = os.environ.get("EOAT_COMMAND_CENTER_USER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if root:
            return Path(root) / APP_DATA_DIR_NAME
        return Path.home() / "AppData" / "Local" / APP_DATA_DIR_NAME
    root = os.environ.get("XDG_CONFIG_HOME")
    if root:
        return Path(root) / "eoat-command-center"
    return Path.home() / ".config" / "eoat-command-center"


def writable_config_path(filename: str) -> Path:
    return user_data_dir() / "config" / filename


def default_project_root() -> Path:
    if is_frozen():
        return user_data_dir() / "projects" / "demo_project"
    return resource_path("examples/demo_project")
