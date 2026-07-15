from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from release_tools.versioning import Version


@dataclass(frozen=True)
class ReleaseInfo:
    application_version: str
    release_id: str
    build_id: str
    build_timestamp: str
    commit_sha: str
    branch_name: str
    release_channel: str
    database_schema_revision: str
    api_contract_version: str
    launcher_version: str
    installer_version: str
    build_date: str
    environment: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    def provenance(self) -> dict[str, str]:
        return {
            "application_version": self.application_version,
            "release_id": self.release_id,
            "build_id": self.build_id,
            "commit_sha": self.commit_sha,
            "release_channel": self.release_channel,
            "database_schema_revision": self.database_schema_revision,
            "api_contract_version": self.api_contract_version,
            "launcher_version": self.launcher_version,
            "installer_version": self.installer_version,
        }


VersionInfo = ReleaseInfo


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=4)
def get_release_info(root: str | Path | None = None) -> ReleaseInfo:
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
    application_version = str(Version.parse(str(payload["app_version"])))
    expected_release_id = f"eoat-atlas-{application_version}"
    if payload["release_id"] != expected_release_id:
        raise RuntimeError(
            f"Canonical release metadata has mismatched release_id: expected {expected_release_id!r}"
        )
    return ReleaseInfo(
        application_version=application_version,
        release_id=str(payload["release_id"]),
        build_id=str(payload["build_id"]),
        build_timestamp=str(payload.get("build_timestamp") or ""),
        commit_sha=str(payload.get("git_commit") or ""),
        branch_name=str(payload.get("branch_name") or ""),
        release_channel=str(payload.get("release_channel") or payload.get("environment") or "development"),
        database_schema_revision=str(payload.get("database_schema_revision") or ""),
        api_contract_version=str(payload.get("api_contract_version") or ""),
        launcher_version=str(payload.get("launcher_version") or ""),
        installer_version=str(payload.get("installer_version") or ""),
        build_date=str(payload.get("build_date") or payload.get("build_timestamp") or ""),
        environment=str(payload.get("environment") or "development"),
    )


get_version_info = get_release_info


def get_app_version(root: str | Path | None = None) -> str:
    return get_release_info(root).application_version
