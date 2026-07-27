from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import LAUNCHER_NAME

CONFIG_DIR_NAME = "EOAT Atlas Launcher"
APP_DIR_NAME = "EOAT Atlas"
INSTALLER_RUNTIME_DIR_NAME = "EOAT_Atlas"
CONFIG_FILE_NAME = "launcher_config.json"
INSTALL_METADATA_NAMES = ("install_metadata.json", "install.json")


@dataclass(frozen=True)
class SingleInstanceConfig:
    enabled: bool = True
    appProcessNames: list[str] = field(default_factory=lambda: ["EOAT Atlas.exe"])
    lockName: str = "EOATAtlasLauncher"

    @classmethod
    def from_dict(cls, data: Any) -> SingleInstanceConfig:
        if not isinstance(data, dict):
            return cls()
        names = data.get("appProcessNames")
        if isinstance(names, str):
            process_names = [names]
        elif isinstance(names, list):
            process_names = [str(item).strip() for item in names if str(item or "").strip()]
        else:
            process_names = ["EOAT Atlas.exe"]
        return cls(
            enabled=bool(data.get("enabled", True)),
            appProcessNames=process_names or ["EOAT Atlas.exe"],
            lockName=str(data.get("lockName") or "EOATAtlasLauncher").strip() or "EOATAtlasLauncher",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LauncherConfig:
    appInstallPath: str = ""
    appExecutableName: str = "EOAT Atlas.exe"
    appEntryPoint: str = ""
    channel: str = "stable"
    updateManifestPath: str = ""
    updateManifestUrl: str = ""
    releaseSetManifestPath: str = ""
    releaseSetManifestUrl: str = ""
    releaseArtifactTransport: str = ""
    trustedManifestKeys: dict[str, str] = field(default_factory=dict)
    revokedManifestKeyIds: list[str] = field(default_factory=list)
    networkRequiredPaths: list[Any] = field(default_factory=list)
    logLevel: str = "INFO"
    lastKnownGoodVersion: str = ""
    allowOfflineLaunch: bool = True
    singleInstance: SingleInstanceConfig = field(default_factory=SingleInstanceConfig)
    startupWaitSeconds: float = 2.0
    launchArguments: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Any) -> LauncherConfig:
        if not isinstance(data, dict):
            return cls()
        launch_args = data.get("launchArguments")
        if isinstance(launch_args, str):
            args = [launch_args]
        elif isinstance(launch_args, list):
            args = [str(item) for item in launch_args]
        else:
            args = []
        network_paths = data.get("networkRequiredPaths")
        if not isinstance(network_paths, list):
            network_paths = []
        trusted_keys = data.get("trustedManifestKeys")
        if not isinstance(trusted_keys, dict):
            trusted_keys = {}
        revoked_keys = data.get("revokedManifestKeyIds")
        if not isinstance(revoked_keys, list):
            revoked_keys = []
        try:
            startup_wait = float(data.get("startupWaitSeconds", 2.0))
        except (TypeError, ValueError):
            startup_wait = 2.0
        return cls(
            appInstallPath=str(data.get("appInstallPath") or "").strip(),
            appExecutableName=str(data.get("appExecutableName") or "EOAT Atlas.exe").strip(),
            appEntryPoint=str(data.get("appEntryPoint") or "").strip(),
            channel=str(data.get("channel") or "stable").strip() or "stable",
            updateManifestPath=str(data.get("updateManifestPath") or "").strip(),
            updateManifestUrl=str(data.get("updateManifestUrl") or "").strip(),
            releaseSetManifestPath=str(data.get("releaseSetManifestPath") or "").strip(),
            releaseSetManifestUrl=str(data.get("releaseSetManifestUrl") or "").strip(),
            releaseArtifactTransport=str(data.get("releaseArtifactTransport") or "").strip(),
            trustedManifestKeys={str(key): str(value) for key, value in trusted_keys.items() if str(key).strip() and str(value).strip()},
            revokedManifestKeyIds=[str(value) for value in revoked_keys if str(value).strip()],
            networkRequiredPaths=network_paths,
            logLevel=str(data.get("logLevel") or "INFO").strip().upper() or "INFO",
            lastKnownGoodVersion=str(data.get("lastKnownGoodVersion") or "").strip(),
            allowOfflineLaunch=bool(data.get("allowOfflineLaunch", True)),
            singleInstance=SingleInstanceConfig.from_dict(data.get("singleInstance")),
            startupWaitSeconds=max(0.0, min(startup_wait, 30.0)),
            launchArguments=args,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["singleInstance"] = self.singleInstance.to_dict()
        return data


@dataclass(frozen=True)
class ConfigLoadResult:
    config: LauncherConfig
    path: Path
    created: bool = False
    corrupt: bool = False
    error: str = ""


def default_config_dir() -> Path:
    override = os.environ.get("EOAT_ATLAS_LAUNCHER_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if root:
            return Path(root) / CONFIG_DIR_NAME
        return Path.home() / "AppData" / "Roaming" / CONFIG_DIR_NAME
    root = os.environ.get("XDG_CONFIG_HOME")
    if root:
        return Path(root) / "eoat-atlas-launcher"
    return Path.home() / ".config" / "eoat-atlas-launcher"


def default_log_dir() -> Path:
    override = os.environ.get("EOAT_ATLAS_LAUNCHER_LOG_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if root:
            return Path(root) / INSTALLER_RUNTIME_DIR_NAME / "logs"
        return Path.home() / "AppData" / "Local" / INSTALLER_RUNTIME_DIR_NAME / "logs"
    root = os.environ.get("XDG_STATE_HOME") or os.environ.get("XDG_CACHE_HOME")
    if root:
        return Path(root) / "eoat-atlas" / "logs"
    return Path.home() / ".local" / "state" / "eoat-atlas" / "logs"


def default_config_path() -> Path:
    return default_config_dir() / CONFIG_FILE_NAME


def default_config_template_path() -> Path:
    return Path(__file__).resolve().with_name("default_config.json")


def load_default_config_data() -> dict[str, Any]:
    try:
        data = json.loads(default_config_template_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    return LauncherConfig.from_dict(data).to_dict()


class ConfigLoader:
    def __init__(self, config_path: str | Path | None = None):
        self.path = Path(config_path).expanduser() if config_path is not None else default_config_path()

    def load(self, *, create_if_missing: bool = True) -> ConfigLoadResult:
        if not self.path.exists():
            config = LauncherConfig.from_dict(load_default_config_data())
            if create_if_missing:
                self.write(config, backup=False)
                return ConfigLoadResult(config=config, path=self.path, created=True)
            return ConfigLoadResult(config=config, path=self.path)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            return ConfigLoadResult(
                config=LauncherConfig.from_dict(load_default_config_data()),
                path=self.path,
                corrupt=True,
                error=str(exc),
            )
        if not isinstance(raw, dict):
            return ConfigLoadResult(
                config=LauncherConfig.from_dict(load_default_config_data()),
                path=self.path,
                corrupt=True,
                error="Config file must contain a JSON object.",
            )
        return ConfigLoadResult(config=LauncherConfig.from_dict(raw), path=self.path)

    def write(self, config: LauncherConfig, *, backup: bool = True) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if backup and self.path.exists():
            backup_existing_file(self.path)
        self.path.write_text(json.dumps(config.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        return self.path

    def install_metadata_paths(self) -> list[Path]:
        paths = [self.path.parent / name for name in INSTALL_METADATA_NAMES]
        if os.name == "nt":
            local_app_data = os.environ.get("LOCALAPPDATA")
            if local_app_data:
                runtime_root = Path(local_app_data) / INSTALLER_RUNTIME_DIR_NAME
                paths.extend(
                    [
                        runtime_root / "current_app.json",
                        runtime_root / "install_identity.json",
                        runtime_root / "config" / "global_config.json",
                    ]
                )
        return paths


def backup_existing_file(path: str | Path) -> Path:
    source = Path(path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = source.parent / "_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{source.stem}_{stamp}{source.suffix}.bak"
    shutil.copy2(source, target)
    return target


def write_install_metadata(config_dir: str | Path, app_install_path: str | Path) -> Path:
    target = Path(config_dir) / INSTALL_METADATA_NAMES[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "appName": "EOAT Atlas",
        "appInstallPath": str(Path(app_install_path).expanduser()),
        "registeredBy": LAUNCHER_NAME,
        "registeredAt": datetime.now().isoformat(timespec="seconds"),
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target
