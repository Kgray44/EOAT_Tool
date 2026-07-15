from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from release_tools.versioning import Version

from .config import ConfigLoader, LauncherConfig, default_config_dir


@dataclass(frozen=True)
class ResolvedApp:
    found: bool
    install_path: Path | None = None
    executable_path: Path | None = None
    command: list[str] = field(default_factory=list)
    working_dir: Path | None = None
    source: str = ""
    install_mode: str = "unknown"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "installPath": str(self.install_path) if self.install_path else "",
            "executablePath": str(self.executable_path) if self.executable_path else "",
            "command": self.command,
            "workingDir": str(self.working_dir) if self.working_dir else "",
            "source": self.source,
            "installMode": self.install_mode,
            "message": self.message,
        }


@dataclass(frozen=True)
class VersionInfo:
    appName: str = "EOAT Atlas"
    version: str = ""
    buildDate: str = ""
    buildId: str = ""
    releaseId: str = ""
    channel: str = "stable"
    path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "appName": self.appName,
            "version": self.version,
            "buildDate": self.buildDate,
            "buildId": self.buildId,
            "releaseId": self.releaseId,
            "channel": self.channel,
            "path": str(self.path) if self.path else "",
        }


@dataclass(frozen=True)
class UpdateCheckResult:
    status: str
    message: str
    installedVersion: str = ""
    availableVersion: str = ""
    installedReleaseId: str = ""
    availableReleaseId: str = ""
    availableBuildId: str = ""
    source: str = ""
    error: str = ""

    @property
    def update_available(self) -> bool:
        return self.status == "update_available"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "installedVersion": self.installedVersion,
            "availableVersion": self.availableVersion,
            "installedReleaseId": self.installedReleaseId,
            "availableReleaseId": self.availableReleaseId,
            "availableBuildId": self.availableBuildId,
            "source": self.source,
            "error": self.error,
        }


@dataclass(frozen=True)
class ResourceStatus:
    label: str
    path: str
    available: bool
    required: bool
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "path": self.path,
            "available": self.available,
            "required": self.required,
            "error": self.error,
        }


@dataclass(frozen=True)
class ResourceCheckResult:
    statuses: list[ResourceStatus] = field(default_factory=list)

    @property
    def unavailable(self) -> list[ResourceStatus]:
        return [status for status in self.statuses if not status.available]

    @property
    def blocking(self) -> list[ResourceStatus]:
        return [status for status in self.unavailable if status.required]

    def to_dict(self) -> dict[str, Any]:
        return {
            "statuses": [status.to_dict() for status in self.statuses],
            "blocking": [status.to_dict() for status in self.blocking],
            "unavailable": [status.to_dict() for status in self.unavailable],
        }


@dataclass(frozen=True)
class LaunchResult:
    started: bool
    pid: int | None = None
    exitCode: int | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"started": self.started, "pid": self.pid, "exitCode": self.exitCode, "error": self.error}


class PathResolver:
    def __init__(self, config: LauncherConfig, config_loader: ConfigLoader | None = None):
        self.config = config
        self.config_loader = config_loader or ConfigLoader()

    def resolve(self, *, override_app_path: str | Path | None = None) -> ResolvedApp:
        candidates = self._candidate_paths(override_app_path=override_app_path)
        checked: list[str] = []
        for source, candidate in candidates:
            if not candidate:
                continue
            path = _expand_path(candidate)
            if str(path).casefold() in checked:
                continue
            checked.append(str(path).casefold())
            resolved = self._resolve_candidate(source, path)
            if resolved.found:
                return resolved
        message = "EOAT Atlas was not found. Check the launcher configuration or run repair with the correct app path."
        if checked:
            message = f"{message} Checked: {', '.join(str(item) for item in checked)}"
        return ResolvedApp(found=False, message=message)

    def _candidate_paths(self, *, override_app_path: str | Path | None) -> list[tuple[str, str | Path]]:
        candidates: list[tuple[str, str | Path]] = []
        if override_app_path:
            candidates.append(("command_line", override_app_path))
        if self.config.appInstallPath:
            candidates.append(("launcher_config", self.config.appInstallPath))
        candidates.extend(self._metadata_candidates())
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(("common_per_user", Path(local_app_data) / "EOAT Atlas"))
            candidates.append(("common_per_user_programs", Path(local_app_data) / "Programs" / "EOAT Atlas"))
        program_files = os.environ.get("PROGRAMFILES", "C:/Program Files")
        candidates.append(("future_program_files", Path(program_files) / "EOAT Atlas"))
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)")
        if program_files_x86:
            candidates.append(("future_program_files_x86", Path(program_files_x86) / "EOAT Atlas"))
        return candidates

    def _metadata_candidates(self) -> list[tuple[str, str | Path]]:
        candidates: list[tuple[str, str | Path]] = []
        for metadata_path in self.config_loader.install_metadata_paths():
            try:
                data = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            metadata_source = f"install_metadata:{metadata_path.name}"
            for key in ("appInstallPath", "app_install_path"):
                value = str(data.get(key) or "").strip()
                if value:
                    candidates.append((metadata_source, value))
            for key in ("appExecutablePath", "app_exe_path", "installed_app_path"):
                value = str(data.get(key) or "").strip()
                if value:
                    candidates.append((metadata_source, value))
        return candidates

    def _resolve_candidate(self, source: str, candidate: Path) -> ResolvedApp:
        if candidate.is_file():
            executable = candidate
            install_path = candidate.parent
            return ResolvedApp(
                found=True,
                install_path=install_path,
                executable_path=executable,
                command=[str(executable)],
                working_dir=install_path,
                source=source,
                install_mode=_install_mode(install_path),
            )
        install_path = candidate
        executable_name = self.config.appExecutableName or "EOAT Atlas.exe"
        executable = install_path / executable_name
        if executable.exists():
            return ResolvedApp(
                found=True,
                install_path=install_path,
                executable_path=executable,
                command=[str(executable)],
                working_dir=install_path,
                source=source,
                install_mode=_install_mode(install_path),
            )
        if self.config.appEntryPoint:
            entry = Path(self.config.appEntryPoint)
            entry_path = entry if entry.is_absolute() else install_path / entry
            if entry_path.exists():
                command = [str(entry_path)]
                if entry_path.suffix.casefold() == ".py":
                    command = [sys.executable, str(entry_path)]
                return ResolvedApp(
                    found=True,
                    install_path=install_path,
                    executable_path=entry_path,
                    command=command,
                    working_dir=install_path,
                    source=source,
                    install_mode=_install_mode(install_path),
                )
        return ResolvedApp(
            found=False,
            install_path=install_path,
            source=source,
            install_mode=_install_mode(install_path),
            message=f"Install folder was checked, but {executable_name} was not found.",
        )


class VersionReader:
    def read(self, install_path: str | Path | None) -> VersionInfo | None:
        if install_path is None:
            return None
        root = Path(install_path)
        for candidate in self._candidate_version_files(root):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            return VersionInfo(
                appName=str(data.get("appName") or data.get("app_name") or "EOAT Atlas"),
                version=str(data.get("version") or data.get("app_version") or ""),
                buildDate=str(data.get("buildDate") or data.get("build_date") or data.get("build_timestamp") or ""),
                buildId=str(data.get("buildId") or data.get("build_id") or data.get("release_id") or ""),
                releaseId=str(data.get("releaseId") or data.get("release_id") or ""),
                channel=str(data.get("channel") or data.get("environment") or "stable"),
                path=candidate,
            )
        return None

    def _candidate_version_files(self, root: Path) -> list[Path]:
        return [
            root / "release_metadata.json",
            root / "version.json",
            root / "_internal" / "version.json",
            root / "_internal" / "release_metadata.json",
            root / "_internal" / "app" / "atlas" / "version.json",
            root / "app" / "atlas" / "version.json",
        ]


class UpdateChecker:
    def __init__(self, config: LauncherConfig):
        self.config = config

    def check(self, installed: VersionInfo | None, install_path: str | Path | None = None) -> UpdateCheckResult:
        source = self.config.updateManifestPath or self.config.updateManifestUrl
        if not source:
            return UpdateCheckResult(status="not_configured", message="No update manifest is configured.")
        if installed is None or not installed.version:
            return UpdateCheckResult(status="unknown", message="Installed version could not be read.", source=source)
        try:
            manifest = self._read_manifest(source, install_path=install_path)
        except (OSError, json.JSONDecodeError, urllib.error.URLError) as exc:
            return UpdateCheckResult(
                status="unavailable",
                message="The update manifest could not be reached.",
                installedVersion=installed.version,
                source=source,
                error=str(exc),
            )
        available = str(manifest.get("latest_version") or manifest.get("version") or "").strip()
        if not available:
            return UpdateCheckResult(
                status="invalid",
                message="The update manifest did not include a version.",
                installedVersion=installed.version,
                source=source,
            )
        try:
            installed_version = Version.parse(installed.version)
            available_version = Version.parse(available)
            minimum = Version.parse(str(manifest.get("minimum_supported_version") or "0.0.0"))
        except ValueError as exc:
            return UpdateCheckResult(
                status="invalid",
                message="The update manifest contains malformed semantic-version metadata.",
                installedVersion=installed.version,
                source=source,
                error=str(exc),
            )
        release_id = str(manifest.get("release_id") or "")
        build_id = str(manifest.get("build_id") or "")
        if "latest_version" in manifest and (release_id != f"eoat-atlas-{available_version}" or not build_id):
            return UpdateCheckResult(
                status="invalid",
                message="The deployment manifest release/build identity is inconsistent.",
                installedVersion=installed.version,
                source=source,
            )
        if available_version > installed_version:
            return UpdateCheckResult(
                status="update_available",
                message=(
                    "A required EOAT Atlas update is available."
                    if installed_version < minimum
                    else "A newer EOAT Atlas version is available."
                ),
                installedVersion=installed.version,
                availableVersion=available,
                installedReleaseId=installed.releaseId,
                availableReleaseId=release_id,
                availableBuildId=build_id,
                source=source,
            )
        if installed_version > available_version:
            return UpdateCheckResult(
                status="newer_local",
                message="The installed EOAT Atlas version is newer; automatic downgrade is blocked.",
                installedVersion=installed.version,
                availableVersion=available,
                installedReleaseId=installed.releaseId,
                availableReleaseId=release_id,
                availableBuildId=build_id,
                source=source,
            )
        return UpdateCheckResult(
            status="current",
            message="Installed EOAT Atlas version is current.",
            installedVersion=installed.version,
            availableVersion=available,
            installedReleaseId=installed.releaseId,
            availableReleaseId=release_id,
            availableBuildId=build_id,
            source=source,
        )

    def _read_manifest(self, source: str, *, install_path: str | Path | None) -> dict[str, Any]:
        if source.casefold().startswith(("http://", "https://")):
            with urllib.request.urlopen(source, timeout=5) as response:
                data = response.read().decode("utf-8")
            raw = json.loads(data)
        else:
            path = _expand_path(source)
            if not path.is_absolute() and install_path is not None:
                path = Path(install_path) / path
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        return raw if isinstance(raw, dict) else {}


class ResourceChecker:
    def __init__(self, config: LauncherConfig):
        self.config = config

    def check(self) -> ResourceCheckResult:
        statuses = [self._check_one(item) for item in self.config.networkRequiredPaths]
        return ResourceCheckResult(statuses=statuses)

    def _check_one(self, item: Any) -> ResourceStatus:
        if isinstance(item, str):
            label = Path(item).name or item
            raw_path = item
            required = not self.config.allowOfflineLaunch
        elif isinstance(item, dict):
            raw_path = str(item.get("path") or "").strip()
            label = str(item.get("label") or Path(raw_path).name or raw_path or "Shared resource")
            required = bool(item.get("required", not self.config.allowOfflineLaunch))
        else:
            return ResourceStatus(label="Invalid resource entry", path="", available=False, required=False)
        if not raw_path:
            return ResourceStatus(label=label, path="", available=False, required=required, error="Path is blank.")
        path = _expand_path(raw_path)
        try:
            available = path.exists()
        except OSError as exc:
            return ResourceStatus(label=label, path=str(path), available=False, required=required, error=str(exc))
        return ResourceStatus(label=label, path=str(path), available=available, required=required)


class SingleInstanceGuard:
    def __init__(self, lock_name: str, *, lock_dir: str | Path | None = None):
        self.lock_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in lock_name)
        self.lock_dir = Path(lock_dir) if lock_dir is not None else default_config_dir()
        self.lock_path = self.lock_dir / f"{self.lock_name}.lock"
        self._handle: Any = None

    def acquire(self) -> bool:
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self._handle = self.lock_path.open("a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.release()
            return False
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(str(os.getpid()))
        self._handle.flush()
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self._handle.close()
        self._handle = None

    def __enter__(self) -> SingleInstanceGuard:
        self.acquire()
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.release()


class AppLauncher:
    def start(self, resolved: ResolvedApp, config: LauncherConfig) -> LaunchResult:
        if not resolved.found or not resolved.command:
            return LaunchResult(started=False, error=resolved.message or "EOAT Atlas executable was not resolved.")
        command = [*resolved.command, *config.launchArguments]
        try:
            process = subprocess.Popen(command, cwd=str(resolved.working_dir or resolved.install_path), shell=False)
        except OSError as exc:
            return LaunchResult(started=False, error=str(exc))
        if config.startupWaitSeconds > 0:
            try:
                exit_code = process.wait(timeout=config.startupWaitSeconds)
            except subprocess.TimeoutExpired:
                return LaunchResult(started=True, pid=process.pid)
            if exit_code not in (0, None):
                return LaunchResult(started=False, pid=process.pid, exitCode=exit_code, error="EOAT Atlas exited during startup.")
            return LaunchResult(started=True, pid=process.pid, exitCode=exit_code)
        return LaunchResult(started=True, pid=process.pid)


def is_app_process_running(process_names: list[str]) -> bool:
    names = [name for name in process_names if name.strip()]
    if not names or os.name != "nt":
        return False
    for name in names:
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        output = completed.stdout.casefold()
        if name.casefold() in output and "no tasks are running" not in output:
            return True
    return False


def _expand_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(value).strip().strip('"'))))


def _install_mode(path: Path) -> str:
    text = str(path).casefold()
    local_app_data = os.environ.get("LOCALAPPDATA", "").casefold()
    user_profile = os.environ.get("USERPROFILE", "").casefold()
    program_files = os.environ.get("PROGRAMFILES", "C:/Program Files").casefold()
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "").casefold()
    if local_app_data and text.startswith(local_app_data):
        return "per-user"
    if user_profile and text.startswith(user_profile):
        return "per-user"
    if text.startswith(program_files) or (program_files_x86 and text.startswith(program_files_x86)):
        return "it-managed"
    return "custom"


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for token in version.replace("-", ".").split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        if digits == "":
            parts.append(0)
        else:
            parts.append(int(digits))
    return tuple(parts or [0])
