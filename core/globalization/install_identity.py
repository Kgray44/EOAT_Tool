from __future__ import annotations

import getpass
import os
import platform
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.resources import app_base_path, packaged_executable_dir

from .app_metadata import load_app_metadata
from .runtime_paths import AtlasRuntimePaths, atomic_write_json, ensure_runtime_layout, get_runtime_paths, read_json

IDENTITY_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class InstallIdentity:
    identity_schema_version: int
    install_id: str
    app_instance_id: str
    machine_name: str
    windows_user: str
    installed_by: str
    installed_at: str
    installer_version: str
    app_name: str
    app_version_at_install: str
    release_id_at_install: str
    build_id_at_install: str
    install_root: str
    runtime_root: str
    source_release_path: str
    environment: str
    generated_by: str
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_or_create_install_identity(runtime: AtlasRuntimePaths | None = None) -> InstallIdentity:
    paths = ensure_runtime_layout(runtime or get_runtime_paths())
    payload = read_json(paths.install_identity_path)
    identity = _identity_from_payload(payload, paths)
    if not paths.install_identity_path.exists() or payload != identity.to_dict():
        atomic_write_json(paths.install_identity_path, identity.to_dict())
    return identity


def _identity_from_payload(payload: dict[str, Any], runtime: AtlasRuntimePaths) -> InstallIdentity:
    metadata = load_app_metadata()
    now = datetime.now().isoformat(timespec="seconds")
    machine_name = str(payload.get("machine_name") or platform.node() or os.environ.get("COMPUTERNAME") or "unknown-machine")
    windows_user = str(payload.get("windows_user") or getpass.getuser())
    install_id = str(payload.get("install_id") or uuid4().hex)
    app_instance_id = str(payload.get("app_instance_id") or _default_app_instance_id(machine_name))
    installed_at = str(payload.get("installed_at") or payload.get("generated_at") or now)
    return InstallIdentity(
        identity_schema_version=max(int(payload.get("identity_schema_version") or 1), IDENTITY_SCHEMA_VERSION),
        install_id=install_id,
        app_instance_id=app_instance_id,
        machine_name=machine_name,
        windows_user=windows_user,
        installed_by=str(payload.get("installed_by") or windows_user),
        installed_at=installed_at,
        installer_version=str(payload.get("installer_version") or ""),
        app_name=str(payload.get("app_name") or metadata.app_name),
        app_version_at_install=str(payload.get("app_version_at_install") or metadata.app_version),
        release_id_at_install=str(payload.get("release_id_at_install") or metadata.release_id),
        build_id_at_install=str(payload.get("build_id_at_install") or metadata.build_id),
        install_root=str(payload.get("install_root") or packaged_executable_dir()),
        runtime_root=str(payload.get("runtime_root") or runtime.runtime_root),
        source_release_path=str(payload.get("source_release_path") or app_base_path()),
        environment=str(payload.get("environment") or metadata.environment),
        generated_by=str(payload.get("generated_by") or "dev_fallback"),
        generated_at=str(payload.get("generated_at") or now),
    )


def _default_app_instance_id(machine_name: str) -> str:
    safe_host = "".join(char if char.isalnum() or char == "-" else "-" for char in machine_name.upper()).strip("-")
    return f"{safe_host or 'EOAT-ATLAS'}_{uuid4().hex[:6].upper()}"


__all__ = ["IDENTITY_SCHEMA_VERSION", "InstallIdentity", "load_or_create_install_identity"]
