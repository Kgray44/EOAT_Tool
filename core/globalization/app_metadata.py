from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.data_gateway.cache_repository import CACHE_SCHEMA_VERSION as API_CACHE_SCHEMA_VERSION
from core.resources import app_base_path, release_metadata_path
from core.versioning import get_app_version, get_release_info

from .sqlite_store import SCHEMA_VERSION

APP_NAME = "EOAT Atlas"
APP_VERSION = get_app_version()
RELEASE_ID = "eoat-atlas-unknown"
BUILD_ID = "unknown"
BUILD_DATE = "2026-07-10"
BUILD_TIMESTAMP = "2026-07-10T00:00:00"
EVENT_SCHEMA_VERSION = 1
CONFIG_SCHEMA_VERSION = 1
METADATA_SCHEMA_VERSION = 1
MINIMUM_SUPPORTED_LAUNCHER_VERSION = "0.1.0"
MINIMUM_SUPPORTED_INSTALLER_VERSION = "0.1.0"


@dataclass(frozen=True)
class AppMetadata:
    metadata_schema_version: int = METADATA_SCHEMA_VERSION
    app_name: str = APP_NAME
    app_version: str = APP_VERSION
    release_id: str = RELEASE_ID
    build_date: str = BUILD_DATE
    build_timestamp: str = BUILD_TIMESTAMP
    build_id: str = BUILD_ID
    git_commit: str = ""
    globalization_sqlite_schema_version: int = SCHEMA_VERSION
    api_cache_schema_version: int = int(API_CACHE_SCHEMA_VERSION)
    cache_schema_version: int = SCHEMA_VERSION
    event_schema_version: int = EVENT_SCHEMA_VERSION
    config_schema_version: int = CONFIG_SCHEMA_VERSION
    minimum_supported_launcher_version: str = MINIMUM_SUPPORTED_LAUNCHER_VERSION
    minimum_supported_installer_version: str = MINIMUM_SUPPORTED_INSTALLER_VERSION
    environment: str = "development"
    release_channel: str = "development"
    branch_name: str = ""
    database_schema_revision: str = ""
    api_contract_version: str = ""
    launcher_version: str = ""
    installer_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_app_metadata(repo_root: str | Path | None = None) -> AppMetadata:
    if repo_root is not None:
        root = Path(repo_root)
        metadata_path = root / "release_metadata.json"
        git_root = root
    else:
        metadata_path = release_metadata_path()
        git_root = app_base_path()
    return _load_app_metadata_cached(str(metadata_path), str(git_root))


@lru_cache(maxsize=8)
def _load_app_metadata_cached(metadata_path_text: str, git_root_text: str) -> AppMetadata:
    metadata_path = Path(metadata_path_text)
    git_root = Path(git_root_text)
    payload = _read_metadata_json(metadata_path)
    release = get_release_info(git_root)
    metadata = AppMetadata(
        metadata_schema_version=int(payload.get("metadata_schema_version") or METADATA_SCHEMA_VERSION),
        app_name=str(payload.get("app_name") or APP_NAME),
        app_version=release.application_version,
        release_id=release.release_id,
        build_date=str(payload.get("build_date") or BUILD_DATE),
        build_timestamp=str(payload.get("build_timestamp") or BUILD_TIMESTAMP),
        build_id=release.build_id,
        git_commit=str(release.commit_sha or os.environ.get("EOAT_ATLAS_GIT_COMMIT") or _git_commit(git_root)),
        globalization_sqlite_schema_version=int(
            payload.get("globalization_sqlite_schema_version") or payload.get("cache_schema_version") or SCHEMA_VERSION
        ),
        api_cache_schema_version=int(payload.get("api_cache_schema_version") or API_CACHE_SCHEMA_VERSION),
        cache_schema_version=int(
            payload.get("globalization_sqlite_schema_version") or payload.get("cache_schema_version") or SCHEMA_VERSION
        ),
        event_schema_version=int(payload.get("event_schema_version") or EVENT_SCHEMA_VERSION),
        config_schema_version=int(payload.get("config_schema_version") or CONFIG_SCHEMA_VERSION),
        minimum_supported_launcher_version=str(
            payload.get("minimum_supported_launcher_version") or MINIMUM_SUPPORTED_LAUNCHER_VERSION
        ),
        minimum_supported_installer_version=str(
            payload.get("minimum_supported_installer_version") or MINIMUM_SUPPORTED_INSTALLER_VERSION
        ),
        environment=release.environment,
        release_channel=release.release_channel,
        branch_name=release.branch_name,
        database_schema_revision=release.database_schema_revision,
        api_contract_version=release.api_contract_version,
        launcher_version=release.launcher_version,
        installer_version=release.installer_version,
    )
    return metadata


def _read_metadata_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _git_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(root),
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "BUILD_DATE",
    "BUILD_ID",
    "BUILD_TIMESTAMP",
    "CONFIG_SCHEMA_VERSION",
    "EVENT_SCHEMA_VERSION",
    "RELEASE_ID",
    "AppMetadata",
    "load_app_metadata",
]
