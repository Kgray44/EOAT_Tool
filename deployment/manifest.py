from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from release_tools.versioning import Version

from .common import DeploymentError, canonical_json, sha256_bytes

MANIFEST_SCHEMA_VERSION = 1
APPLICATION_NAME = "EOAT Atlas"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
PRODUCTION_APPLICATION_SERVICES = ("eoat-atlas.service",)
PRODUCTION_HEALTH_CHECKS = ("/api/v1/health", "/api/v1/version", "/api/v1/schema-status")
PRODUCTION_PUBLIC_HEALTH_ENDPOINT = {
    "scheme": "http",
    "hostname": "eoat-atlas.gwplastics.com",
    "port": 80,
    "paths": list(PRODUCTION_HEALTH_CHECKS),
}


@dataclass(frozen=True)
class ReleaseIdentity:
    version: str
    release_id: str
    build_id: str
    commit_sha: str
    branch: str
    created_at_utc: str


def manifest_core(
    *,
    version: str,
    build_id: str,
    commit_sha: str,
    branch: str,
    created_at_utc: str,
    payload_sha256: str,
    migration_revision: str,
    api_contract_version: str,
    host_templates: dict[str, dict[str, str]] | None = None,
    services: list[str] | None = None,
) -> dict[str, Any]:
    Version.parse(version)
    if not FULL_SHA.fullmatch(commit_sha):
        raise DeploymentError("Release manifest commit must be a full lowercase SHA-1")
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "application": APPLICATION_NAME,
        "version": version,
        "release_id": f"eoat-atlas-{version}",
        "build_id": build_id,
        "commit_sha": commit_sha,
        "branch": branch,
        "created_at_utc": created_at_utc,
        # This digest covers the deployable payload, excluding generated
        # manifests.  It makes the embedded and external manifests comparable
        # without an impossible self-reference to the enclosing tarball hash.
        "payload_sha256": payload_sha256,
        "database": {
            "migration_system": "alembic",
            "minimum_compatible_revision": migration_revision,
            "target_revision": migration_revision,
            "migration_required": True,
        },
        "runtime": {"python": ">=3.13", "mysql": ">=8.4"},
        # These are the verified production API unit and its read-only local
        # probes.  The reverse proxy remains server configuration because it
        # is not part of the application payload.  Its approved endpoint is
        # nevertheless recorded so the updater can reject an unsafe implicit
        # HTTPS assumption or a host/port mismatch.
        "services": services or list(PRODUCTION_APPLICATION_SERVICES),
        "health_checks": list(PRODUCTION_HEALTH_CHECKS),
        "public_health_endpoint": dict(PRODUCTION_PUBLIC_HEALTH_ENDPOINT),
        "api_contract_version": api_contract_version,
        # These digests bind the root-side web host installer to files in the
        # immutable release, rather than to a caller supplied configuration.
        "host_templates": host_templates or {},
    }


def external_manifest(
    core: dict[str, Any], *, archive_name: str, archive_sha256: str, size_bytes: int
) -> dict[str, Any]:
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_core": core,
        "embedded_manifest_sha256": sha256_bytes(canonical_json(core)),
        "artifact": {
            "filename": archive_name,
            "format": "tar.gz",
            "sha256": archive_sha256,
            "size_bytes": size_bytes,
        },
    }


def validate_core(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DeploymentError("Embedded release manifest must be an object")
    required = {
        "schema_version",
        "application",
        "version",
        "release_id",
        "build_id",
        "commit_sha",
        "branch",
        "created_at_utc",
        "payload_sha256",
        "database",
        "runtime",
        "services",
        "health_checks",
        "public_health_endpoint",
        "api_contract_version",
        "host_templates",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise DeploymentError("Release manifest missing fields: " + ", ".join(missing))
    if payload["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise DeploymentError("Unsupported embedded release manifest schema")
    if payload["application"] != APPLICATION_NAME:
        raise DeploymentError("Release manifest application is not EOAT Atlas")
    version = str(payload["version"])
    Version.parse(version)
    if payload["release_id"] != f"eoat-atlas-{version}":
        raise DeploymentError("Release ID does not match manifest version")
    if not isinstance(payload["build_id"], str) or not payload["build_id"].startswith(f"eoat-atlas-{version}-"):
        raise DeploymentError("Build ID does not match manifest version")
    if not isinstance(payload["commit_sha"], str) or not FULL_SHA.fullmatch(payload["commit_sha"]):
        raise DeploymentError("Release manifest has an invalid commit SHA")
    if not isinstance(payload["payload_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", payload["payload_sha256"]):
        raise DeploymentError("Release manifest has an invalid payload digest")
    database = payload["database"]
    if (
        not isinstance(database, dict)
        or database.get("migration_system") != "alembic"
        or not database.get("target_revision")
    ):
        raise DeploymentError("Release manifest has invalid Alembic metadata")
    runtime = payload["runtime"]
    if not isinstance(runtime, dict) or not runtime.get("python") or not runtime.get("mysql"):
        raise DeploymentError("Release manifest has invalid runtime metadata")
    if not isinstance(payload["services"], list) or not all(isinstance(item, str) for item in payload["services"]):
        raise DeploymentError("Release manifest services must be a list of unit names")
    if not isinstance(payload["health_checks"], list) or not all(
        isinstance(item, str) and item.startswith("/") for item in payload["health_checks"]
    ):
        raise DeploymentError("Release manifest health checks must be absolute HTTP paths")
    templates = payload["host_templates"]
    if not isinstance(templates, dict):
        raise DeploymentError("Release manifest host templates must be an object")
    for name, entry in templates.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            raise DeploymentError("Release manifest host template is invalid")
        path, value = entry.get("path"), entry.get("sha256")
        if not isinstance(path, str) or path.startswith("/") or ".." in path.split("/"):
            raise DeploymentError("Release manifest host template path is unsafe")
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise DeploymentError("Release manifest host template digest is invalid")
    public_health = payload["public_health_endpoint"]
    if (
        not isinstance(public_health, dict)
        or public_health.get("scheme") not in {"http", "https"}
        or not isinstance(public_health.get("hostname"), str)
        or not public_health["hostname"]
        or not isinstance(public_health.get("port"), int)
        or not 1 <= public_health["port"] <= 65535
        or public_health.get("paths") != payload["health_checks"]
    ):
        raise DeploymentError("Release manifest has invalid public health endpoint metadata")
    return payload


def validate_external_manifest(payload: object) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict):
        raise DeploymentError("External release manifest must be an object")
    if payload.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION:
        raise DeploymentError("Unsupported external release manifest schema")
    core = validate_core(payload.get("manifest_core"))
    if payload.get("embedded_manifest_sha256") != sha256_bytes(canonical_json(core)):
        raise DeploymentError("External manifest does not match its embedded manifest digest")
    artifact = payload.get("artifact")
    if not isinstance(artifact, dict):
        raise DeploymentError("External manifest has no artifact section")
    if (
        artifact.get("format") != "tar.gz"
        or not isinstance(artifact.get("filename"), str)
        or not artifact["filename"].endswith(".tar.gz")
    ):
        raise DeploymentError("External manifest requires a .tar.gz server artifact")
    if not isinstance(artifact.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]):
        raise DeploymentError("External manifest has an invalid artifact SHA-256")
    if not isinstance(artifact.get("size_bytes"), int) or artifact["size_bytes"] <= 0:
        raise DeploymentError("External manifest has an invalid artifact size")
    return core, artifact


def manifest_identity(core: dict[str, Any]) -> ReleaseIdentity:
    validated = validate_core(core)
    return ReleaseIdentity(
        version=str(validated["version"]),
        release_id=str(validated["release_id"]),
        build_id=str(validated["build_id"]),
        commit_sha=str(validated["commit_sha"]),
        branch=str(validated["branch"]),
        created_at_utc=str(validated["created_at_utc"]),
    )
