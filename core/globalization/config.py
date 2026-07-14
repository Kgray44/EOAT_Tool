from __future__ import annotations

import getpass
import os
import platform
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .app_metadata import CONFIG_SCHEMA_VERSION, load_app_metadata
from .install_identity import load_or_create_install_identity
from .runtime_paths import AtlasRuntimePaths, atomic_write_json, ensure_runtime_layout, get_runtime_paths, read_json
from .sqlite_store import SCHEMA_VERSION

NETWORK_ROOT = Path(r"\\example.invalid\VT\Plant4\Maintenance & Manufacturing Engineering\EOAT Atlas")
PRODUCT_NAME = "EOAT Atlas"
PRODUCT_SCOPE_NOTE = "minimalist/current EOAT Atlas only"
ACTIVE_UI_MODE = "minimalist"
RELEASE_ENTRY_POINT = "packaging/eoat_atlas_entry.py"

DEFAULT_SOURCE_PATHS: dict[str, str] = {
    "eoat_master_tracker": str(
        NETWORK_ROOT
        / "02_Data"
        / "Workbooks"
        / "Master_Tracker"
        / "01_EOAT_Audit"
        / "EOAT_Audit_Database"
        / "EOAT_Master_Tracker.xlsx"
    ),
    "press_capacity_workbook": str(
        NETWORK_ROOT
        / "02_Data"
        / "Workbooks"
        / "Press_Capacity"
        / "00_Project_Admin"
        / "reference_data"
        / "press_capacity.xlsx"
    ),
    "robot_workbook": str(
        NETWORK_ROOT
        / "02_Data"
        / "Workbooks"
        / "Robot_EOAT"
        / "01_EOAT_Audit"
        / "EOAT_Audit_Database"
        / "Robot_Info.xlsx"
    ),
    "photos_root": str(NETWORK_ROOT / "03_Shared_Assets" / "EOAT_Photos" / "01_EOAT_Audit" / "Cell_Photos"),
    "output_folder": str(NETWORK_ROOT / "04_Exports" / "PDF_Setup_Packets" / "06_Final_Handoff" / "Atlas_Exports"),
    "reference_docs_folder": str(NETWORK_ROOT / "03_Shared_Assets" / "Documents"),
}

LEGACY_DEFAULT_SOURCE_PATHS: dict[str, str] = {
    "output_folder": str(NETWORK_ROOT / "04_Atlas_Outputs"),
    "reference_docs_folder": str(NETWORK_ROOT / "03_Shared_Assets" / "Reference_Documents"),
}

DEFAULT_SHARED_PATHS: dict[str, str] = {
    "network_root": str(NETWORK_ROOT),
    "event_log_path": str(NETWORK_ROOT / "02_Data" / "Event_Log" / "Global_Events"),
    "pending_event_path": str(NETWORK_ROOT / "02_Data" / "Event_Log" / "Pending_Updates"),
    "backup_path": str(NETWORK_ROOT / "05_Backups" / "Workbook_Snapshots"),
    "lock_path": str(NETWORK_ROOT / "02_Data" / "Locks"),
    "export_root": str(NETWORK_ROOT / "04_Exports"),
    "setup_packet_export_root": str(NETWORK_ROOT / "04_Exports" / "PDF_Setup_Packets"),
    "document_root": str(NETWORK_ROOT / "03_Shared_Assets" / "Documents"),
}


@dataclass(frozen=True)
class AtlasGlobalConfig:
    config_schema_version: int = CONFIG_SCHEMA_VERSION
    environment: str = "development"
    product_name: str = PRODUCT_NAME
    product_scope_note: str = PRODUCT_SCOPE_NOTE
    active_ui_mode: str = ACTIVE_UI_MODE
    release_entry_point: str = RELEASE_ENTRY_POINT
    write_mode: str = "disabled"
    app_instance_id: str = field(default_factory=lambda: _default_app_instance_id())
    install_id: str = ""
    computer_name: str = field(default_factory=lambda: platform.node() or os.environ.get("COMPUTERNAME", "unknown-computer"))
    machine_name: str = field(default_factory=lambda: platform.node() or os.environ.get("COMPUTERNAME", "unknown-computer"))
    windows_user: str = field(default_factory=lambda: getpass.getuser())
    installed_by: str = ""
    app_version: str = field(default_factory=lambda: load_app_metadata().app_version)
    release_id: str = field(default_factory=lambda: load_app_metadata().release_id)
    build_id: str = field(default_factory=lambda: load_app_metadata().build_id)
    git_commit: str = field(default_factory=lambda: load_app_metadata().git_commit)
    event_schema_version: int = field(default_factory=lambda: load_app_metadata().event_schema_version)
    minimum_supported_launcher_version: str = field(default_factory=lambda: load_app_metadata().minimum_supported_launcher_version)
    minimum_supported_installer_version: str = field(default_factory=lambda: load_app_metadata().minimum_supported_installer_version)
    installed_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    network_root: str = DEFAULT_SHARED_PATHS["network_root"]
    source_path_values: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SOURCE_PATHS))
    event_log_path: str = DEFAULT_SHARED_PATHS["event_log_path"]
    pending_event_path: str = DEFAULT_SHARED_PATHS["pending_event_path"]
    backup_path: str = DEFAULT_SHARED_PATHS["backup_path"]
    lock_path: str = DEFAULT_SHARED_PATHS["lock_path"]
    export_root: str = DEFAULT_SHARED_PATHS["export_root"]
    setup_packet_export_root: str = DEFAULT_SHARED_PATHS["setup_packet_export_root"]
    document_root: str = DEFAULT_SHARED_PATHS["document_root"]
    refresh_interval_seconds: int = 60
    cache_schema_version: int = SCHEMA_VERSION
    diagnostic_logging_level: str = "INFO"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def source_paths(self) -> dict[str, str]:
        paths = dict(DEFAULT_SOURCE_PATHS)
        paths.update({key: value for key, value in self.source_path_values.items() if str(value or "").strip()})
        return paths

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def writes_enabled(self) -> bool:
        return self.write_mode.casefold() == "enabled"

    def shadow_writes_enabled(self) -> bool:
        return self.write_mode.casefold() == "shadow"

    def sandbox_writes_enabled(self) -> bool:
        return self.write_mode.casefold() == "sandbox"


def load_or_create_global_config(runtime: AtlasRuntimePaths | None = None) -> AtlasGlobalConfig:
    paths = ensure_runtime_layout(runtime or get_runtime_paths())
    payload = read_json(paths.config_path)
    if not payload:
        payload = read_json(paths.runtime_root / "config.json")
    config = _config_from_payload(payload, paths)
    if not paths.config_path.exists() or payload != config.to_dict():
        atomic_write_json(paths.config_path, config.to_dict())
    return config


def save_global_config(config: AtlasGlobalConfig, runtime: AtlasRuntimePaths | None = None) -> AtlasGlobalConfig:
    paths = ensure_runtime_layout(runtime or get_runtime_paths())
    payload = config.to_dict()
    payload["write_mode"] = _normalized_write_mode(str(payload.get("write_mode", "disabled")))
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    saved = _config_from_payload(payload, paths)
    atomic_write_json(paths.config_path, saved.to_dict())
    return saved


def _config_from_payload(payload: dict[str, Any], runtime: AtlasRuntimePaths | None = None) -> AtlasGlobalConfig:
    paths = runtime or get_runtime_paths()
    metadata = load_app_metadata()
    identity = load_or_create_install_identity(paths)
    source_paths = dict(DEFAULT_SOURCE_PATHS)
    raw_paths = payload.get("source_paths") or payload.get("source_path_values") or {}
    if isinstance(raw_paths, dict):
        for key, value in raw_paths.items():
            text = str(value or "").strip()
            if not text:
                continue
            if LEGACY_DEFAULT_SOURCE_PATHS.get(str(key)) == text:
                continue
            source_paths[str(key)] = text
    computer_name = str(payload.get("computer_name") or platform.node() or os.environ.get("COMPUTERNAME", "unknown-computer"))
    machine_name = str(payload.get("machine_name") or identity.machine_name or computer_name)
    return AtlasGlobalConfig(
        config_schema_version=int(payload.get("config_schema_version") or CONFIG_SCHEMA_VERSION),
        environment=str(payload.get("environment") or identity.environment or metadata.environment),
        product_name=str(payload.get("product_name") or PRODUCT_NAME),
        product_scope_note=str(payload.get("product_scope_note") or PRODUCT_SCOPE_NOTE),
        active_ui_mode=str(payload.get("active_ui_mode") or ACTIVE_UI_MODE),
        release_entry_point=str(payload.get("release_entry_point") or RELEASE_ENTRY_POINT),
        write_mode=_normalized_write_mode(str(payload.get("write_mode") or "disabled")),
        app_instance_id=str(payload.get("app_instance_id") or identity.app_instance_id or _default_app_instance_id(computer_name)),
        install_id=str(payload.get("install_id") or identity.install_id),
        computer_name=computer_name,
        machine_name=machine_name,
        windows_user=str(payload.get("windows_user") or identity.windows_user or getpass.getuser()),
        installed_by=str(payload.get("installed_by") or identity.installed_by),
        app_version=str(payload.get("app_version") or metadata.app_version),
        release_id=str(payload.get("release_id") or metadata.release_id),
        build_id=str(payload.get("build_id") or metadata.build_id),
        git_commit=str(payload.get("git_commit") or metadata.git_commit),
        event_schema_version=int(payload.get("event_schema_version") or metadata.event_schema_version),
        minimum_supported_launcher_version=str(
            payload.get("minimum_supported_launcher_version") or metadata.minimum_supported_launcher_version
        ),
        minimum_supported_installer_version=str(
            payload.get("minimum_supported_installer_version") or metadata.minimum_supported_installer_version
        ),
        installed_at=str(payload.get("installed_at") or identity.installed_at or payload.get("created_at") or datetime.now().isoformat(timespec="seconds")),
        network_root=str(payload.get("network_root") or DEFAULT_SHARED_PATHS["network_root"]),
        source_path_values=source_paths,
        event_log_path=str(payload.get("event_log_path") or DEFAULT_SHARED_PATHS["event_log_path"]),
        pending_event_path=str(payload.get("pending_event_path") or DEFAULT_SHARED_PATHS["pending_event_path"]),
        backup_path=str(payload.get("backup_path") or DEFAULT_SHARED_PATHS["backup_path"]),
        lock_path=str(payload.get("lock_path") or DEFAULT_SHARED_PATHS["lock_path"]),
        export_root=str(payload.get("export_root") or DEFAULT_SHARED_PATHS["export_root"]),
        setup_packet_export_root=str(payload.get("setup_packet_export_root") or DEFAULT_SHARED_PATHS["setup_packet_export_root"]),
        document_root=str(payload.get("document_root") or DEFAULT_SHARED_PATHS["document_root"]),
        refresh_interval_seconds=int(payload.get("refresh_interval_seconds") or 60),
        cache_schema_version=int(payload.get("cache_schema_version") or SCHEMA_VERSION),
        diagnostic_logging_level=str(payload.get("diagnostic_logging_level") or "INFO"),
        created_at=str(payload.get("created_at") or datetime.now().isoformat(timespec="seconds")),
        updated_at=str(payload.get("updated_at") or datetime.now().isoformat(timespec="seconds")),
    )


def _normalized_write_mode(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in {"enabled", "sandbox", "shadow"}:
        return normalized
    return "disabled"


def _default_app_instance_id(computer_name: str | None = None) -> str:
    host = str(computer_name or platform.node() or os.environ.get("COMPUTERNAME") or "ATLAS").upper()
    safe_host = "".join(char if char.isalnum() or char == "-" else "-" for char in host).strip("-") or "ATLAS"
    return f"{safe_host}_{uuid4().hex[:4].upper()}"
