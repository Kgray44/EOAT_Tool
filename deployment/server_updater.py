from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from release_tools.versioning import Version

from .common import (
    DeploymentError,
    read_json_object,
    redact_text,
    utc_text,
    write_json_atomic,
)
from .manifest import manifest_identity, validate_external_manifest
from .release_manager import ROOT, validate_deployment_archive

TOOL_VERSION = "1.0.0"
TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")
SERVICE = re.compile(r"^[A-Za-z0-9_.@-]+\.service$")
HOSTNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LOGIN_PATH = re.compile(r"^[A-Za-z0-9_.-]+$")
DESTRUCTIVE_MIGRATION = re.compile(
    r"\b(?:drop_table|drop_column|alter_column|drop_index|execute\s*\(|op\.execute)\b", re.I
)
SIZE = re.compile(r"^(\d+(?:\.\d+)?)([KMGTPE]?)(?:i?B)?$", re.I)
HOST_KEY_FINGERPRINT = re.compile(r"Server host key: [^\r\n]*\b(SHA256:[A-Za-z0-9+/=]+)")


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str | None = None
    size: int | None = None


@dataclass(frozen=True)
class GitHubRelease:
    tag: str
    draft: bool
    prerelease: bool
    published_at: str | None
    assets: tuple[ReleaseAsset, ...]

    @property
    def version(self) -> Version:
        match = TAG.fullmatch(self.tag)
        if not match:
            raise DeploymentError(f"Invalid EOAT Atlas release tag: {self.tag}")
        return Version.parse(match.group(1))


@dataclass(frozen=True)
class ServerConfig:
    hostname: str
    port: int
    username: str | None
    application_root: str
    api_port: int
    services: tuple[str, ...]
    nginx_service: str | None
    mysql_login_path: str
    database_name: str
    deployment_lock: str


@dataclass(frozen=True)
class RemoteResult:
    operation: str
    command: tuple[str, ...]
    exit_code: int
    output: str


@dataclass(frozen=True)
class HostKeyStatus:
    known: bool
    fingerprint: str | None
    diagnostic: str | None


def _release_from_json(payload: dict[str, Any]) -> GitHubRelease:
    assets = tuple(
        ReleaseAsset(
            str(asset["name"]),
            str(asset.get("browser_download_url") or asset.get("url") or "") or None,
            int(asset["size"]) if isinstance(asset.get("size"), int) else None,
        )
        for asset in payload.get("assets", [])
        if isinstance(asset, dict) and asset.get("name")
    )
    return GitHubRelease(
        tag=str(payload.get("tag_name") or payload.get("tagName") or ""),
        draft=bool(payload.get("draft") or payload.get("isDraft")),
        prerelease=bool(payload.get("prerelease") or payload.get("isPrerelease")),
        published_at=str(payload.get("published_at") or payload.get("publishedAt") or "") or None,
        assets=assets,
    )


def select_release(
    releases: Iterable[GitHubRelease], requested_version: str | None = None, *, allow_prerelease: bool = False
) -> GitHubRelease:
    candidates: list[GitHubRelease] = []
    requested = Version.parse(requested_version) if requested_version else None
    for release in releases:
        try:
            version = release.version
        except ValueError:
            continue
        if release.draft or (release.prerelease and not allow_prerelease):
            continue
        names = {asset.name for asset in release.assets}
        archives = [name for name in names if name.endswith(".tar.gz")]
        if "release_manifest.json" not in names or len(archives) != 1 or f"{archives[0]}.sha256" not in names:
            continue
        if requested and version != requested:
            continue
        candidates.append(release)
    if not candidates:
        if requested:
            raise DeploymentError(f"No complete production-eligible GitHub Release exists for {requested}")
        raise DeploymentError("No complete production-eligible GitHub Release exists")
    return max(candidates, key=lambda release: release.version)


def github_releases(root: Path) -> list[GitHubRelease]:
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=root, text=True, capture_output=True, check=False
    )
    match = re.search(r"github\.com[/:]([^/]+)/([^/\s]+?)(?:\.git)?$", remote.stdout.strip())
    if remote.returncode or not match:
        raise DeploymentError("Origin is not a GitHub repository; GitHub release discovery is unavailable")
    if not shutil.which("gh"):
        raise DeploymentError("GitHub CLI is unavailable")
    repository = f"{match.group(1)}/{match.group(2)}"
    result = subprocess.run(
        ["gh", "api", f"repos/{repository}/releases", "--paginate"], text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise DeploymentError(
            "GitHub release discovery failed: " + redact_text((result.stderr or result.stdout).strip())
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DeploymentError("GitHub release API returned invalid JSON") from exc
    if not isinstance(payload, list):
        raise DeploymentError("GitHub release API returned an unexpected document")
    return [_release_from_json(item) for item in payload if isinstance(item, dict)]


def _asset(release: GitHubRelease, name: str) -> ReleaseAsset:
    matches = [asset for asset in release.assets if asset.name == name]
    if len(matches) != 1:
        raise DeploymentError(f"Release {release.tag} must contain exactly one {name} asset")
    return matches[0]


def _github_download(root: Path, release: GitHubRelease, asset: ReleaseAsset, destination: Path) -> None:
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=root, text=True, capture_output=True, check=False
    )
    match = re.search(r"github\.com[/:]([^/]+)/([^/\s]+?)(?:\.git)?$", remote.stdout.strip())
    if remote.returncode or not match:
        raise DeploymentError("Origin is not a GitHub repository")
    temporary = destination.parent / f".{destination.name}.partial"
    temporary.unlink(missing_ok=True)
    result = subprocess.run(
        [
            "gh",
            "release",
            "download",
            release.tag,
            "--repo",
            f"{match.group(1)}/{match.group(2)}",
            "--pattern",
            asset.name,
            "--dir",
            str(destination.parent),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    generated = destination.parent / asset.name
    if result.returncode or not generated.is_file():
        generated.unlink(missing_ok=True)
        raise DeploymentError("GitHub asset download failed: " + redact_text((result.stderr or result.stdout).strip()))
    os.replace(generated, temporary)
    if asset.size is not None and temporary.stat().st_size != asset.size:
        temporary.unlink(missing_ok=True)
        raise DeploymentError(f"Downloaded {asset.name} size differs from GitHub metadata")
    os.replace(temporary, destination)


def _quarantine(path: Path) -> Path:
    target = path.with_name(f"{path.name}.corrupt-{utc_text().replace(':', '').replace('-', '')}")
    os.replace(path, target)
    return target


def cache_release(
    root: Path,
    release: GitHubRelease,
    cache_root: Path,
    *,
    downloader: Callable[[Path, GitHubRelease, ReleaseAsset, Path], None] = _github_download,
) -> Path:
    """Download only to a per-version cache and never trust an existing entry."""

    cache_dir = cache_root / str(release.version)
    manifest_path = cache_dir / "release_manifest.json"
    if manifest_path.exists():
        try:
            external = read_json_object(manifest_path)
            _core, artifact = validate_external_manifest(external)
            validate_deployment_archive(
                cache_dir / artifact["filename"], manifest_path, cache_dir / f"{artifact['filename']}.sha256"
            )
            return cache_dir
        except (DeploymentError, OSError):
            _quarantine(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=False)
    try:
        manifest_asset = _asset(release, "release_manifest.json")
        downloader(root, release, manifest_asset, manifest_path)
        external = read_json_object(manifest_path)
        core, artifact = validate_external_manifest(external)
        if f"v{core['version']}" != release.tag:
            raise DeploymentError("GitHub tag and manifest version disagree")
        archive_asset = _asset(release, str(artifact["filename"]))
        checksum_asset = _asset(release, f"{artifact['filename']}.sha256")
        downloader(root, release, archive_asset, cache_dir / archive_asset.name)
        downloader(root, release, checksum_asset, cache_dir / checksum_asset.name)
        validate_deployment_archive(cache_dir / archive_asset.name, manifest_path, cache_dir / checksum_asset.name)
        write_json_atomic(
            cache_dir / "verification.json",
            {"verified_at_utc": utc_text(), "tag": release.tag, "status": "PASS", "sha256": artifact["sha256"]},
        )
        return cache_dir
    except Exception:
        if cache_dir.exists():
            _quarantine(cache_dir)
        raise


def _local_release(release_dir: Path) -> tuple[Path, dict[str, Any]]:
    manifest_path = release_dir / "release_manifest.json"
    external = read_json_object(manifest_path)
    _core, artifact = validate_external_manifest(external)
    validate_deployment_archive(
        release_dir / artifact["filename"], manifest_path, release_dir / f"{artifact['filename']}.sha256"
    )
    return release_dir, external


def load_server_config(path: Path) -> ServerConfig:
    payload = read_json_object(path)
    server = payload.get("server", payload)
    if not isinstance(server, dict):
        raise DeploymentError("Server configuration must contain an object named server")
    hostname = str(server.get("hostname") or "")
    if not HOSTNAME.fullmatch(hostname) or hostname.lower().startswith("example") or "<" in hostname:
        raise DeploymentError("Server hostname is missing or unsafe")
    port = server.get("port", 22)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise DeploymentError("SSH port must be an integer between 1 and 65535")
    root = str(server.get("application_root") or "/opt/eoat-atlas")
    if root != "/opt/eoat-atlas":
        raise DeploymentError("Phase 2 only permits the approved /opt/eoat-atlas application root")
    username = server.get("username")
    if username is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", str(username)):
        raise DeploymentError("SSH username is unsafe")
    services = tuple(str(item) for item in server.get("services", []))
    if not all(SERVICE.fullmatch(service) for service in services):
        raise DeploymentError("Service names must be safe systemd .service unit names")
    nginx = server.get("nginx_service")
    if nginx is not None and not SERVICE.fullmatch(str(nginx)):
        raise DeploymentError("NGINX service name must be a safe systemd unit name")
    api_port = server.get("api_port", 8765)
    if not isinstance(api_port, int) or not 1 <= api_port <= 65535:
        raise DeploymentError("API port must be a safe integer")
    login_path = str(server.get("mysql_login_path") or "eoat-atlas-prod-runtime")
    database_name = str(server.get("database_name") or "eoat_atlas_prod")
    if not LOGIN_PATH.fullmatch(login_path) or not IDENTIFIER.fullmatch(database_name):
        raise DeploymentError("Database inspection settings are unsafe")
    deployment_lock = str(server.get("deployment_lock") or "/var/lock/eoat-atlas-deploy.lock")
    if deployment_lock != "/var/lock/eoat-atlas-deploy.lock":
        raise DeploymentError("Phase 2 only permits the approved deployment lock path")
    return ServerConfig(
        hostname,
        port,
        str(username) if username else None,
        root,
        api_port,
        services,
        str(nginx) if nginx else None,
        login_path,
        database_name,
        deployment_lock,
    )


def ssh_host_key_status(config: ServerConfig) -> HostKeyStatus:
    """Check trust before SSH and never add or replace a known-host entry."""

    lookup = f"[{config.hostname}]:{config.port}" if config.port != 22 else config.hostname
    try:
        known = subprocess.run(["ssh-keygen", "-F", lookup], text=True, capture_output=True, check=False)
    except OSError as exc:
        return HostKeyStatus(False, None, f"ssh-keygen is unavailable: {exc}")
    if known.returncode == 0:
        return HostKeyStatus(True, None, None)
    # ssh-keyscan is used solely to show an untrusted candidate fingerprint to
    # the operator.  Its output is never written to known_hosts or accepted.
    try:
        scanned = subprocess.run(
            ["ssh-keyscan", "-T", "5", "-p", str(config.port), config.hostname],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return HostKeyStatus(False, None, f"Host key is unknown and ssh-keyscan is unavailable: {exc}")
    if not scanned.returncode and scanned.stdout.strip():
        fingerprint = subprocess.run(
            ["ssh-keygen", "-lf", "-"], input=scanned.stdout, text=True, capture_output=True, check=False
        )
        if not fingerprint.returncode:
            lines = [line.strip() for line in fingerprint.stdout.splitlines() if line.strip()]
            if lines:
                return HostKeyStatus(False, " | ".join(lines[:3]), "Host key is not present in known_hosts")

    # Some legacy ssh-keyscan builds cannot negotiate modern server KEX
    # algorithms.  Fall back to a strict, authentication-disabled debug
    # handshake.  It never accepts or records the key and does not execute a
    # remote command; it can only expose the same untrusted fingerprint an
    # operator must verify out-of-band.
    host = f"{config.username}@{config.hostname}" if config.username else config.hostname
    strict_probe = [
        "ssh",
        "-vv",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "KbdInteractiveAuthentication=no",
        "-o",
        "NumberOfPasswordPrompts=0",
        "-o",
        "RequestTTY=no",
        "-o",
        "ConnectTimeout=8",
        "-p",
        str(config.port),
        host,
    ]
    try:
        probe = subprocess.run(strict_probe, text=True, capture_output=True, check=False)
    except OSError as exc:
        return HostKeyStatus(False, None, f"Host key is unknown and strict probe is unavailable: {exc}")
    fingerprints = HOST_KEY_FINGERPRINT.findall((probe.stdout or "") + "\n" + (probe.stderr or ""))
    if fingerprints:
        return HostKeyStatus(False, " | ".join(dict.fromkeys(fingerprints)), "Host key is not present in known_hosts")
    return HostKeyStatus(False, None, "Host key is unknown; no candidate fingerprint could be read safely")


class ReadonlySSH:
    """A deliberately small allowlist; it has no upload or write API."""

    def __init__(
        self, config: ServerConfig, *, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
    ) -> None:
        self.config = config
        self._runner = runner

    def _command(self, operation: str, value: str | None = None) -> list[str]:
        root = self.config.application_root
        static: dict[str, list[str]] = {
            "hostname": ["hostname"],
            "uname": ["uname", "-a"],
            "os-release": ["cat", "/etc/os-release"],
            "python": ["python3", "--version"],
            "mysql-version": ["mysql", "--version"],
            "time": ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ", "+%Z"],
            "memory": ["free", "-h"],
            "disk": ["df", "-h", root, "/tmp"],
            "layout": ["ls", "-ld", root, f"{root}/incoming", f"{root}/releases", f"{root}/current", f"{root}/shared"],
            "current-target": ["readlink", "-f", f"{root}/current"],
            "releases": [
                "find",
                f"{root}/releases",
                "-mindepth",
                "1",
                "-maxdepth",
                "1",
                "-type",
                "d",
                "-printf",
                "%f\\n",
            ],
            "incoming": [
                "find",
                f"{root}/incoming",
                "-mindepth",
                "1",
                "-maxdepth",
                "1",
                "-type",
                "f",
                "-printf",
                "%f\\n",
            ],
            "current-manifest": ["cat", f"{root}/current/release_manifest.json"],
            "lock": ["stat", "-c", "%n %U %G %a %Y", self.config.deployment_lock],
            "environment-metadata": ["stat", "-c", "%n %U %G %a", "/etc/eoat-atlas"],
            "database-revision": [
                "mysql",
                f"--login-path={self.config.mysql_login_path}",
                "--batch",
                "--skip-column-names",
                self.config.database_name,
                "-e",
                "SELECT version_num FROM alembic_version LIMIT 1",
            ],
        }
        if operation in static and value is None:
            return static[operation]
        if operation == "service" and value and SERVICE.fullmatch(value):
            return [
                "systemctl",
                "show",
                value,
                "--no-pager",
                "--property=LoadState,ActiveState,SubState,ExecStart,User,Group,WorkingDirectory,EnvironmentFiles,Restart,MainPID,ActiveEnterTimestamp",
            ]
        if operation == "health" and value and value in {"/api/v1/health", "/api/v1/version"}:
            return [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--max-time",
                "5",
                f"http://127.0.0.1:{self.config.api_port}{value}",
            ]
        raise DeploymentError(f"Read-only SSH operation is not allowlisted: {operation}")

    def execute(self, operation: str, value: str | None = None) -> RemoteResult:
        import shlex

        remote_args = self._command(operation, value)
        host = f"{self.config.username}@{self.config.hostname}" if self.config.username else self.config.hostname
        command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-p",
            str(self.config.port),
            host,
            shlex.join(remote_args),
        ]
        try:
            result = self._runner(command, text=True, capture_output=True, check=False)
            output = redact_text(((result.stdout or "") + (result.stderr or "")).strip())
            return RemoteResult(operation, tuple(remote_args), result.returncode, output[-6000:])
        except OSError as exc:
            return RemoteResult(operation, tuple(remote_args), 127, redact_text(str(exc)))


def migration_summary(archive: Path) -> dict[str, Any]:
    revisions: dict[str, str | None] = {}
    warnings: list[str] = []
    try:
        with tarfile.open(archive, "r:gz") as package:
            for member in package.getmembers():
                if (
                    not member.isfile()
                    or not member.name.startswith("server/migrations/versions/")
                    or not member.name.endswith(".py")
                ):
                    continue
                stream = package.extractfile(member)
                if stream is None:
                    continue
                source = stream.read().decode("utf-8", errors="replace")
                revision = re.search(r"^revision\s*(?::[^=]+)?=\s*[\"']([^\"']+)", source, re.M)
                down = re.search(r"^down_revision\s*(?::[^=]+)?=\s*(?:[\"']([^\"']+)[\"']|None)", source, re.M)
                if revision:
                    revisions[revision.group(1)] = down.group(1) if down and down.group(1) else None
                if DESTRUCTIVE_MIGRATION.search(source):
                    warnings.append(f"Potentially destructive migration syntax: {PurePosixPath(member.name).name}")
    except (OSError, tarfile.TarError) as exc:
        raise DeploymentError("Cannot inspect release migration graph") from exc
    children = {child for child in revisions.values() if child}
    heads = sorted(set(revisions) - children)
    return {
        "revisions": sorted(revisions),
        "heads": heads,
        "multiple_heads": len(heads) > 1,
        "destructive_warnings": warnings,
    }


def _service_result(remote: RemoteResult) -> dict[str, Any]:
    return {
        "status": "PASS" if remote.exit_code == 0 else "UNKNOWN",
        "output": remote.output,
        "command": list(remote.command),
    }


def _size_bytes(value: str) -> int | None:
    match = SIZE.fullmatch(value.strip())
    if not match:
        return None
    factor = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4, "P": 1024**5, "E": 1024**6}
    return int(float(match.group(1)) * factor[match.group(2).upper()])


def disk_space_preflight(df_output: str, artifact_bytes: int) -> dict[str, Any]:
    """Use a conservative estimate and state where server volumes are unknown."""

    estimate = {
        "artifact_download": artifact_bytes,
        "extracted_release": max(artifact_bytes * 3, 100 * 1024**2),
        "release_environment_and_dependencies": 300 * 1024**2,
        "temporary_staging": artifact_bytes,
        "database_backup": None,
        "retained_previous_release": 0,
        "safety_margin": 512 * 1024**2,
    }
    required = sum(value for value in estimate.values() if isinstance(value, int))
    filesystems: list[dict[str, Any]] = []
    for line in df_output.splitlines():
        columns = line.split()
        if len(columns) < 6 or columns[0].lower() == "filesystem":
            continue
        available = _size_bytes(columns[-3])
        if available is not None:
            filesystems.append({"filesystem": columns[0], "available_bytes": available, "mount": columns[-1]})
    if not filesystems:
        return {
            "status": "UNKNOWN",
            "required_bytes_excluding_database_backup": required,
            "estimates": estimate,
            "filesystems": [],
            "warning": "Could not parse approved df output",
        }
    minimum = min(item["available_bytes"] for item in filesystems)
    return {
        "status": "PASS" if minimum >= required else "FAIL",
        "required_bytes_excluding_database_backup": required,
        "estimates": estimate,
        "filesystems": filesystems,
        "warning": "Database backup and MySQL filesystem capacity remain unknown in Phase 2",
    }


def runtime_compatibility(remote: dict[str, RemoteResult], core: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    python = remote["python"].output
    python_match = re.search(r"Python\s+(\d+)\.(\d+)", python)
    if remote["python"].exit_code or not python_match:
        checks.append({"name": "python", "status": "UNKNOWN", "detail": "Python version was not readable"})
    elif (int(python_match.group(1)), int(python_match.group(2))) < (3, 13):
        checks.append(
            {
                "name": "python",
                "status": "FAIL",
                "detail": f"{python_match.group(0)} does not satisfy {core['runtime']['python']}",
            }
        )
    else:
        checks.append({"name": "python", "status": "PASS", "detail": python_match.group(0)})
    mysql = remote["mysql-version"].output
    mysql_match = re.search(r"(?:Ver\s+)?(\d+)\.(\d+)", mysql)
    if remote["mysql-version"].exit_code or not mysql_match:
        checks.append({"name": "mysql", "status": "UNKNOWN", "detail": "MySQL client version was not readable"})
    elif (int(mysql_match.group(1)), int(mysql_match.group(2))) < (8, 4):
        checks.append(
            {
                "name": "mysql",
                "status": "FAIL",
                "detail": f"MySQL {mysql_match.group(1)}.{mysql_match.group(2)} does not satisfy {core['runtime']['mysql']}",
            }
        )
    else:
        checks.append({"name": "mysql", "status": "PASS", "detail": mysql_match.group(0)})
    layout_status = "PASS" if remote["layout"].exit_code == 0 else "FAIL"
    checks.append(
        {
            "name": "application_root",
            "status": layout_status,
            "detail": "/opt/eoat-atlas inspected"
            if layout_status == "PASS"
            else "Application root layout was not readable",
        }
    )
    return {
        "checks": checks,
        "status": "FAIL"
        if any(item["status"] == "FAIL" for item in checks)
        else "UNKNOWN"
        if any(item["status"] == "UNKNOWN" for item in checks)
        else "PASS",
    }


def health_comparison(health: dict[str, dict[str, Any]], core: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    compared: dict[str, Any] = {}
    warnings: list[str] = []
    for path, item in health.items():
        if item["status"] != "PASS":
            compared[path] = {"status": item["status"], "detail": item["output"]}
            warnings.append(f"Health probe {path} did not complete")
            continue
        try:
            payload = json.loads(item["output"])
        except json.JSONDecodeError:
            compared[path] = {"status": "WARNING", "detail": "Health response was not JSON"}
            warnings.append(f"Health probe {path} returned non-JSON output")
            continue
        values = {
            key: payload.get(key)
            for key in ("application_version", "commit_sha", "migration_revision", "database_revision")
            if key in payload
        }
        compared[path] = {"status": "PASS", "values": values}
        if values.get("application_version") and values["application_version"] != core["version"]:
            warnings.append(
                f"Health probe {path} reports {values['application_version']} while target is {core['version']}"
            )
        if values.get("commit_sha") and values["commit_sha"] != core["commit_sha"]:
            warnings.append(f"Health probe {path} reports a commit different from the selected release")
    return compared, warnings


def _current_manifest(remote: RemoteResult) -> tuple[dict[str, Any] | None, str | None]:
    if remote.exit_code:
        return None, remote.output
    try:
        payload = json.loads(remote.output)
        try:
            core, _artifact = validate_external_manifest(payload)
            return core, None
        except DeploymentError:
            from .manifest import validate_core

            return validate_core(payload), None
    except (json.JSONDecodeError, DeploymentError) as exc:
        return None, f"Current manifest is unavailable or invalid: {exc}"


def future_deployment_plan(
    config: ServerConfig, core: dict[str, Any], migration: dict[str, Any]
) -> list[dict[str, Any]]:
    release_path = f"{config.application_root}/releases/{core['build_id']}"
    steps = [
        ("Acquire deployment lock", config.deployment_lock, "write-lock", "no Phase 2 execution"),
        ("Back up database", config.database_name, "database-backup", "requires an approved backup policy"),
        (
            "Upload verified artifact",
            f"{config.application_root}/incoming/{core['build_id']}.tar.gz",
            "file-upload",
            "upload is disabled in Phase 2",
        ),
        ("Verify server-side hash", f"{config.application_root}/incoming", "read-only", "verify before extraction"),
        (
            "Extract verified release",
            release_path,
            "filesystem-write",
            "safe extraction and ownership validation required",
        ),
        ("Create release environment", release_path, "dependency-install", "locked dependencies only"),
        ("Run migration", core["database"]["target_revision"], "database-write", "manual approval and backup required"),
        (
            "Atomically switch current symlink",
            f"{config.application_root}/current",
            "symlink-write",
            "pre-switch smoke must pass",
        ),
        (
            "Restart verified services",
            ", ".join(core["services"] or config.services) or "discover service units",
            "service-write",
            "post-switch health checks required",
        ),
        (
            "Record deployment receipt",
            f"{config.application_root}/shared",
            "filesystem-write",
            "release lock remains held until verification",
        ),
    ]
    return [
        {
            "step": name,
            "target": target,
            "command_category": category,
            "precondition": precondition,
            "phase_2_status": "NOT_EXECUTED",
            "rollback_implication": "Future Phase 3 design required",
        }
        for name, target, category, precondition in steps
    ]


def inspect_server(config: ServerConfig, core: dict[str, Any], archive: Path) -> dict[str, Any]:
    host_key = ssh_host_key_status(config)
    if not host_key.known:
        return {
            "server": {},
            "current_deployment": {"manifest": None, "error": "SSH inspection was not attempted"},
            "services": {},
            "health": {},
            "database": {"exit_code": None, "revision": None, "diagnostic": "SSH host key is not trusted"},
            "migration_preflight": migration_summary(archive),
            "deployment_lock": {"exit_code": None, "metadata": None, "diagnostic": "SSH host key is not trusted"},
            "ssh_host_key": host_key.__dict__,
            "future_deployment_plan": future_deployment_plan(config, core, migration_summary(archive)),
            "warnings": [host_key.diagnostic or "SSH host key is not trusted"],
            "blocking_failures": ["SSH host key is unknown or changed; inspection stopped before connection"],
            "readiness": "NOT_READY",
        }
    ssh = ReadonlySSH(config)
    identity_operations = (
        "hostname",
        "uname",
        "os-release",
        "python",
        "mysql-version",
        "time",
        "memory",
        "disk",
        "layout",
        "current-target",
        "releases",
        "incoming",
        "environment-metadata",
        "lock",
    )
    remote = {name: ssh.execute(name) for name in identity_operations}
    current_core, current_error = _current_manifest(ssh.execute("current-manifest"))
    services = tuple(
        dict.fromkeys(
            [*core.get("services", []), *config.services, *([config.nginx_service] if config.nginx_service else [])]
        )
    )
    service_state = {service: _service_result(ssh.execute("service", service)) for service in services}
    health = {path: _service_result(ssh.execute("health", path)) for path in core.get("health_checks", [])}
    health_status, health_warnings = health_comparison(health, core)
    database = ssh.execute("database-revision")
    migration = migration_summary(archive)
    disk = (
        disk_space_preflight(remote["disk"].output, archive.stat().st_size)
        if remote["disk"].exit_code == 0
        else {"status": "UNKNOWN", "warning": "Approved disk inspection command failed"}
    )
    runtime = runtime_compatibility(remote, core)
    warnings: list[str] = []
    blocking: list[str] = []
    if not services:
        warnings.append("No verified service units are configured or embedded in the release manifest")
    if current_error:
        warnings.append(current_error)
    if current_core:
        for field in ("version", "commit_sha"):
            if not current_core.get(field):
                warnings.append(f"Current deployment manifest has no {field}")
    if (
        database.exit_code == 0
        and database.output.strip()
        and database.output.strip() != core["database"]["target_revision"]
    ):
        warnings.append(
            f"Database revision {database.output.strip()} differs from target {core['database']['target_revision']}"
        )
    elif database.exit_code:
        warnings.append("Database migration revision could not be inspected with the approved read-only login path")
    if migration["multiple_heads"]:
        blocking.append("Downloaded release contains multiple Alembic heads")
    if core["database"]["target_revision"] not in migration["revisions"]:
        blocking.append("Downloaded release does not contain its declared Alembic target revision")
    if migration["destructive_warnings"]:
        warnings.extend(migration["destructive_warnings"])
    warnings.extend(health_warnings)
    if disk["status"] == "FAIL":
        blocking.append("Server free space is below the conservative future deployment estimate")
    elif disk["status"] == "UNKNOWN":
        warnings.append(str(disk["warning"]))
    if runtime["status"] == "FAIL":
        blocking.append("Server runtime is incompatible with the selected release")
    elif runtime["status"] == "UNKNOWN":
        warnings.append("Some server runtime compatibility facts could not be determined")
    if any(
        result.exit_code != 0
        for result in remote.values()
        if result.operation in {"hostname", "current-target", "disk"}
    ):
        blocking.append("Required server identity or filesystem inspection failed")
    readiness = "NOT_READY" if blocking else "READY_WITH_WARNINGS" if warnings else "READY_FOR_LATER_DEPLOYMENT"
    return {
        "server": {
            name: {"exit_code": result.exit_code, "output": result.output, "command": list(result.command)}
            for name, result in remote.items()
        },
        "current_deployment": {"manifest": current_core, "error": current_error},
        "services": service_state,
        "health": health,
        "health_comparison": health_status,
        "database": {
            "exit_code": database.exit_code,
            "revision": database.output if database.exit_code == 0 else None,
            "diagnostic": database.output if database.exit_code else None,
        },
        "disk_space_preflight": disk,
        "runtime_compatibility": runtime,
        "migration_preflight": migration,
        "deployment_lock": {
            "exit_code": remote["lock"].exit_code,
            "metadata": remote["lock"].output if remote["lock"].exit_code == 0 else None,
            "diagnostic": remote["lock"].output if remote["lock"].exit_code else None,
        },
        "ssh_host_key": host_key.__dict__,
        "future_deployment_plan": future_deployment_plan(config, core, migration),
        "warnings": warnings,
        "blocking_failures": blocking,
        "readiness": readiness,
    }


def dry_run_receipt(
    root: Path, release_dir: Path, external: dict[str, Any], config: ServerConfig | None
) -> dict[str, Any]:
    core, artifact = validate_external_manifest(external)
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "tool_version": TOOL_VERSION,
        "mode": "DRY_RUN_READ_ONLY",
        "declaration": "NO SERVER CHANGES WILL BE MADE",
        "started_at_utc": utc_text(),
        "selected_release": {**manifest_identity(core).__dict__, "github_tag": f"v{core['version']}"},
        "artifact": artifact,
        "artifact_verification": "PASS",
        "local_cache_path": str(release_dir),
        "mutating_operations_attempted": False,
        "production_files_modified": False,
        "production_artifact_uploaded": False,
        "production_symlink_changed": False,
        "production_service_restarted": False,
        "production_migration_executed": False,
        "production_database_written": False,
        "deployment_lock_changed": False,
        "production_package_installed": False,
    }
    if config:
        receipt["server_hostname"] = config.hostname
        receipt["server_inspection"] = inspect_server(config, core, release_dir / artifact["filename"])
        receipt["overall_readiness"] = receipt["server_inspection"]["readiness"]
    else:
        receipt["server_inspection"] = {
            "status": "UNKNOWN",
            "reason": "No non-secret server configuration was supplied; no SSH connection was attempted.",
        }
        receipt["overall_readiness"] = "UNKNOWN"
    receipt["ended_at_utc"] = utc_text()
    return receipt


def _print(payload: Any, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                payload,
                default=lambda value: value.__dict__ if hasattr(value, "__dict__") else str(value),
                indent=2,
                sort_keys=True,
            )
        )
        return
    if isinstance(payload, dict) and "overall_readiness" in payload:
        print("MODE: DRY-RUN / READ-ONLY")
        print("NO SERVER CHANGES WILL BE MADE")
        print(
            f"Selected release: {payload['selected_release']['version']} ({payload['selected_release']['commit_sha']})"
        )
        print(f"Artifact verification: {payload['artifact_verification']}")
        print(f"Overall readiness: {payload['overall_readiness']}")
    else:
        print(json.dumps(payload, default=str, indent=2, sort_keys=True))


def _write_receipt(root: Path, receipt: dict[str, Any]) -> Path:
    path = (
        root
        / ".local"
        / "deployment-preflight-receipts"
        / f"preflight-{utc_text().replace(':', '').replace('-', '')}.json"
    )
    write_json_atomic(path, receipt)
    return path


def _resolve_local_or_github(
    root: Path, *, release_dir: Path | None, version: str | None, cache_root: Path
) -> tuple[Path, dict[str, Any]]:
    if release_dir:
        return _local_release(release_dir.resolve())
    release = select_release(github_releases(root), version)
    directory = cache_release(root, release, cache_root)
    return _local_release(directory)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EOAT Atlas Phase 2 server updater (strict dry-run/read-only mode)")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--server-config", type=Path, help="Non-secret local server inspection configuration")
    parser.add_argument("--release-dir", type=Path, help="Verified local release assets for offline inspection")
    parser.add_argument("--cache-dir", type=Path, help="Local untracked GitHub release cache")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show strict read-only updater status")
    subparsers.add_parser("list-releases", help="List eligible GitHub Releases")
    inspect = subparsers.add_parser("inspect-release", help="Download/cache and verify a release without SSH")
    inspect.add_argument("--version", metavar="MAJOR.MINOR.PATCH")
    preflight = subparsers.add_parser("preflight", help="Perform a strict read-only deployment rehearsal")
    preflight.add_argument("--version", metavar="MAJOR.MINOR.PATCH")
    deploy_latest = subparsers.add_parser("deploy-latest", help="Alias for read-only latest-release preflight")
    deploy_latest.add_argument("--dry-run", action="store_true", required=True)
    deploy_version = subparsers.add_parser("deploy-version", help="Alias for read-only selected-release preflight")
    deploy_version.add_argument("version", metavar="MAJOR.MINOR.PATCH")
    deploy_version.add_argument("--dry-run", action="store_true", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    cache = (args.cache_dir or root / ".local" / "deployment-cache").resolve()
    try:
        if args.command == "status":
            payload = {
                "tool_version": TOOL_VERSION,
                "mode": "DRY_RUN_READ_ONLY",
                "server_configured": bool(args.server_config),
                "cache_dir": str(cache),
                "active_deployment_supported": False,
            }
            _print(payload, args.as_json)
            return 0
        if args.command == "list-releases":
            releases = select_release(github_releases(root))
            _print(
                {
                    "latest_eligible_release": releases.tag,
                    "version": str(releases.version),
                    "mode": "DRY_RUN_READ_ONLY",
                },
                args.as_json,
            )
            return 0
        version = getattr(args, "version", None)
        release_dir, external = _resolve_local_or_github(
            root, release_dir=args.release_dir, version=version, cache_root=cache
        )
        if args.command == "inspect-release":
            core, artifact = validate_external_manifest(external)
            _print(
                {
                    "mode": "DRY_RUN_READ_ONLY",
                    "release": manifest_identity(core).__dict__,
                    "artifact": artifact,
                    "verification": "PASS",
                    "cache_path": str(release_dir),
                },
                args.as_json,
            )
            return 0
        config = load_server_config(args.server_config.resolve()) if args.server_config else None
        receipt = dry_run_receipt(root, release_dir, external, config)
        path = _write_receipt(root, receipt)
        receipt["receipt_path"] = str(path)
        _print(receipt, args.as_json)
    except (DeploymentError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {redact_text(str(exc))}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
