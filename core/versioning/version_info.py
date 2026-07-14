from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class VersionInfo:
    application_version: str
    release_id: str
    build_id: str
    build_date: str
    environment: str


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=4)
def get_version_info(root: str | Path | None = None) -> VersionInfo:
    repo = Path(root).resolve() if root is not None else repository_root()
    path = repo / "release_metadata.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Canonical release metadata is unavailable: {path}") from exc
    required = ("app_version", "release_id", "build_id")
    missing = [key for key in required if not str(payload.get(key) or "").strip()]
    if missing:
        raise RuntimeError(f"Canonical release metadata is missing: {', '.join(missing)}")
    return VersionInfo(
        application_version=str(payload["app_version"]),
        release_id=str(payload["release_id"]),
        build_id=str(payload["build_id"]),
        build_date=str(payload.get("build_date") or payload.get("build_timestamp") or ""),
        environment=str(payload.get("environment") or "development"),
    )
