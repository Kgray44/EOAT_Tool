from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from release_tools.versioning import Version, build_identifier

from .compatibility import EXPECTED_API_VERSION, EXPECTED_SCHEMA_REVISION

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SECRET_KEY = re.compile(r"(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|ldap[_-]?bind)", re.I)


@dataclass(frozen=True)
class ReleaseInfo:
    application_version: str
    release_id: str
    build_id: str
    build_timestamp: str
    commit_sha: str
    source_git_commit: str
    branch_name: str
    release_channel: str
    database_schema_revision: str
    api_contract_version: str
    launcher_version: str
    installer_version: str
    build_date: str
    environment: str
    metadata_schema_version: int
    metadata_role: str

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)

    def provenance(self) -> dict[str, str]:
        # commit_sha is the database/API compatibility name. Its defined
        # meaning is the exact source commit used for this build.
        return {
            "application_version": self.application_version,
            "release_id": self.release_id,
            "build_id": self.build_id,
            "commit_sha": self.source_git_commit,
            "release_channel": self.release_channel,
            "database_schema_revision": self.database_schema_revision,
            "api_contract_version": self.api_contract_version,
            "launcher_version": self.launcher_version,
            "installer_version": self.installer_version,
        }


VersionInfo = ReleaseInfo


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _metadata_path(repo: Path) -> Path:
    override = os.environ.get("EOAT_ATLAS_RELEASE_METADATA", "").strip()
    return Path(override).expanduser().resolve() if override else repo / "release_metadata.json"


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Generated release metadata is unavailable or malformed: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Generated release metadata must be a JSON object: {path}")
    return payload


def _required_text(payload: dict[str, Any], field: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise RuntimeError(f"Generated release metadata is missing {field}")
    return value


def validate_release_metadata(payload: dict[str, Any], *, require_artifact: bool = True) -> ReleaseInfo:
    for key in payload:
        if _SECRET_KEY.search(str(key)):
            raise RuntimeError(f"Generated release metadata contains forbidden secret field {key!r}")
    if payload.get("app_name") != "EOAT Atlas":
        raise RuntimeError("Generated release metadata has an invalid app_name")
    try:
        version = str(Version.parse(_required_text(payload, "app_version")))
    except ValueError as exc:
        raise RuntimeError("Generated release metadata has an invalid app_version") from exc
    release_id = _required_text(payload, "release_id")
    if release_id != f"eoat-atlas-{version}":
        raise RuntimeError("Generated release metadata has an inconsistent release_id")
    source_commit = _required_text(payload, "source_git_commit").lower()
    git_commit = _required_text(payload, "git_commit").lower()
    if not _FULL_SHA.fullmatch(source_commit) or git_commit != source_commit:
        raise RuntimeError("git_commit must be the full source_git_commit compatibility alias")
    timestamp = _required_text(payload, "build_timestamp")
    if not _UTC_TIMESTAMP.fullmatch(timestamp):
        raise RuntimeError("Generated release metadata build_timestamp must be UTC ISO-8601")
    try:
        parsed_timestamp = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise RuntimeError("Generated release metadata has an invalid build_timestamp") from exc
    build_id = _required_text(payload, "build_id")
    expected_build_id = build_identifier(version, source_commit, parsed_timestamp)
    if build_id != expected_build_id:
        raise RuntimeError(f"Generated release metadata has an inconsistent build_id; expected {expected_build_id}")
    build_date = _required_text(payload, "build_date")
    if build_date != parsed_timestamp.date().isoformat():
        raise RuntimeError("Generated release metadata build_date does not match build_timestamp")
    schema_revision = _required_text(payload, "database_schema_revision")
    if schema_revision != EXPECTED_SCHEMA_REVISION:
        raise RuntimeError(f"Generated release metadata schema revision must be {EXPECTED_SCHEMA_REVISION}")
    api_version = _required_text(payload, "api_contract_version")
    if api_version != EXPECTED_API_VERSION:
        raise RuntimeError(f"Generated release metadata API contract must be {EXPECTED_API_VERSION}")
    role = _required_text(payload, "metadata_role")
    if require_artifact and role != "release_artifact":
        raise RuntimeError("Deployed release metadata must have metadata_role=release_artifact")
    try:
        schema_version = int(payload.get("metadata_schema_version"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Generated release metadata has an invalid metadata_schema_version") from exc
    if schema_version < 2:
        raise RuntimeError("Generated release metadata schema version is obsolete")
    return ReleaseInfo(
        application_version=version,
        release_id=release_id,
        build_id=build_id,
        build_timestamp=timestamp,
        commit_sha=source_commit,
        source_git_commit=source_commit,
        branch_name=_required_text(payload, "branch_name"),
        release_channel=_required_text(payload, "release_channel"),
        database_schema_revision=schema_revision,
        api_contract_version=api_version,
        launcher_version=_required_text(payload, "launcher_version"),
        installer_version=_required_text(payload, "installer_version"),
        build_date=build_date,
        environment=_required_text(payload, "environment"),
        metadata_schema_version=schema_version,
        metadata_role=role,
    )


def _git(repo: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, check=False, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Generated release metadata is missing and Git is unavailable") from exc
    if completed.returncode:
        raise RuntimeError("Generated release metadata is missing outside a valid source checkout")
    return completed.stdout.strip()


def _source_checkout_payload(repo: Path) -> dict[str, Any]:
    defaults = _read_object(repo / "release_defaults.json")
    version_data = _read_object(repo / "app" / "atlas" / "version.json")
    version = str(Version.parse(str(version_data.get("version") or "")))
    commit = _git(repo, "rev-parse", "HEAD").lower()
    branch = _git(repo, "branch", "--show-current") or "detached"
    commit_time = _git(repo, "show", "-s", "--format=%cI", commit)
    parsed = datetime.fromisoformat(commit_time.replace("Z", "+00:00")).astimezone(timezone.utc).replace(microsecond=0)
    timestamp = parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        **defaults,
        "metadata_role": "source_checkout",
        "app_version": version,
        "release_id": f"eoat-atlas-{version}",
        "build_id": build_identifier(version, commit, parsed),
        "build_timestamp": timestamp,
        "build_date": parsed.date().isoformat(),
        "source_git_commit": commit,
        "git_commit": commit,
        "branch_name": branch,
        "environment": "development",
        "release_channel": str(version_data.get("channel") or "development"),
    }


@lru_cache(maxsize=8)
def get_release_info(root: str | Path | None = None) -> ReleaseInfo:
    repo = Path(root).resolve() if root is not None else repository_root()
    path = _metadata_path(repo)
    if path.is_file():
        return validate_release_metadata(_read_object(path), require_artifact=True)
    return validate_release_metadata(_source_checkout_payload(repo), require_artifact=False)


get_version_info = get_release_info


def get_app_version(root: str | Path | None = None) -> str:
    return get_release_info(root).application_version


__all__ = [
    "ReleaseInfo",
    "VersionInfo",
    "get_app_version",
    "get_release_info",
    "get_version_info",
    "validate_release_metadata",
]
