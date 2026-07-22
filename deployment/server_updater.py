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
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
SERVICE = re.compile(r"^[A-Za-z0-9_.@-]+\.service$")
HOSTNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LOGIN_PATH = re.compile(r"^[A-Za-z0-9_.-]+$")
DESTRUCTIVE_MIGRATION = re.compile(
    r"\b(?:drop_table|drop_column|alter_column|drop_index|execute\s*\(|op\.execute)\b", re.I
)
SIZE = re.compile(r"^(\d+(?:\.\d+)?)([KMGTPE]?)(?:i?B)?$", re.I)
HOST_KEY_FINGERPRINT = re.compile(r"Server host key: [^\r\n]*\b(SHA256:[A-Za-z0-9+/=]+)")
DISCOVERED_SERVICE = re.compile(r"^\s*([A-Za-z0-9_.@-]+\.service)\s+")
INSPECTION_HEALTH_PATHS = ("/api/v1/health", "/api/v1/version", "/api/v1/schema-status")
HTTP_ONLY_TLS_WARNING = (
    "Production currently exposes the internal EOAT Atlas reverse proxy over HTTP port 80 only. "
    "TLS/HTTPS on port 443 is not configured. This does not block Phase 3 release deployment automation, "
    "but HTTPS should be addressed before broad browser/mobile rollout or exposure beyond the currently approved internal network."
)


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
    public_hostname: str | None = None
    public_scheme: str = "http"
    public_port: int = 80


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


def release_tag_commit(root: Path, release: GitHubRelease, core: dict[str, Any]) -> str:
    """Resolve the actual immutable remote annotated tag, not GitHub's default target field."""
    if not TAG.fullmatch(release.tag):
        raise DeploymentError("GitHub release has an unsafe tag name")
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "origin", f"refs/tags/{release.tag}", f"refs/tags/{release.tag}^{{}}"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise DeploymentError("Could not resolve the remote release tag: " + redact_text(result.stderr.strip()))
    refs: dict[str, str] = {}
    for line in result.stdout.splitlines():
        try:
            commit, ref = line.split("\t", 1)
        except ValueError:
            continue
        refs[ref] = commit.lower()
    dereferenced = refs.get(f"refs/tags/{release.tag}^{{}}")
    if not dereferenced or not re.fullmatch(r"[0-9a-f]{40}", dereferenced):
        raise DeploymentError(f"Release tag {release.tag} is missing or is not annotated")
    if dereferenced != str(core.get("commit_sha") or "").lower():
        raise DeploymentError(
            f"Release tag {release.tag} resolves to {dereferenced}, not manifest commit {core.get('commit_sha')}"
        )
    return dereferenced


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
            core, artifact = validate_external_manifest(external)
            release_tag_commit(root, release, core)
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
        tag_commit = release_tag_commit(root, release, core)
        archive_asset = _asset(release, str(artifact["filename"]))
        checksum_asset = _asset(release, f"{artifact['filename']}.sha256")
        downloader(root, release, archive_asset, cache_dir / archive_asset.name)
        downloader(root, release, checksum_asset, cache_dir / checksum_asset.name)
        validate_deployment_archive(cache_dir / archive_asset.name, manifest_path, cache_dir / checksum_asset.name)
        write_json_atomic(
            cache_dir / "verification.json",
            {
                "verified_at_utc": utc_text(),
                "tag": release.tag,
                "tag_commit": tag_commit,
                "manifest_commit": core["commit_sha"],
                "status": "PASS",
                "sha256": artifact["sha256"],
            },
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
    public_hostname = server.get("public_hostname")
    if public_hostname is not None and not HOSTNAME.fullmatch(str(public_hostname)):
        raise DeploymentError("Public reverse-proxy hostname is unsafe")
    public_scheme = str(server.get("public_scheme") or "http").casefold()
    if public_scheme not in {"http", "https"}:
        raise DeploymentError("Public reverse-proxy scheme must be http or https")
    public_port = server.get("public_port", 80)
    if not isinstance(public_port, int) or not 1 <= public_port <= 65535:
        raise DeploymentError("Public reverse-proxy port must be a safe integer")
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
        str(public_hostname) if public_hostname else None,
        public_scheme,
        public_port,
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
            "time": ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
            "timezone": ["timedatectl", "show", "--property=Timezone", "--value"],
            "memory": ["free", "-h"],
            "disk": ["df", "-h", root, "/tmp"],
            "layout": ["ls", "-ld", root, f"{root}/incoming", f"{root}/releases", f"{root}/current", f"{root}/shared"],
            "current-content": [
                "find",
                "-H",
                f"{root}/current",
                "-mindepth",
                "1",
                "-maxdepth",
                "1",
                "-printf",
                "%f %y\n",
            ],
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
            "current-metadata": ["cat", f"{root}/current/release_metadata.json"],
            "shared-layout": [
                "find",
                f"{root}/shared",
                "-mindepth",
                "1",
                "-maxdepth",
                "2",
                "-printf",
                "%p %y\n",
            ],
            "release-evidence": [
                "find",
                f"{root}/shared/release-evidence",
                "-mindepth",
                "1",
                "-maxdepth",
                "1",
                "-type",
                "f",
                "-printf",
                "%f\n",
            ],
            "lock": ["stat", "-c", "%n %U %G %a %Y", self.config.deployment_lock],
            "environment-metadata": ["stat", "-c", "%n %U %G %a", "/etc/eoat-atlas"],
            "environment-files": [
                "stat",
                "-c",
                "%n %U %G %a",
                "/etc/eoat-atlas/runtime.env",
                "/etc/eoat-atlas/migration.env",
            ],
            "service-units": ["systemctl", "list-units", "--type=service", "--all", "--no-legend", "--no-pager"],
            "service-unit-files": [
                "systemctl",
                "list-unit-files",
                "--type=service",
                "--no-legend",
                "--no-pager",
            ],
            "listeners": ["ss", "-ltn"],
            "nginx-metadata": [
                "stat",
                "-c",
                "%n %U %G %a",
                "/etc/nginx/nginx.conf",
                "/etc/nginx/sites-enabled",
            ],
            "reverse-proxy-root": [
                "curl",
                "--silent",
                "--show-error",
                "--max-time",
                "5",
                "--write-out",
                "\n__EOAT_HTTP_STATUS=%{http_code} __EOAT_RESPONSE_SECONDS=%{time_total}\n",
                "http://127.0.0.1/",
            ],
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
        if operation == "health" and value and value in INSPECTION_HEALTH_PATHS:
            return [
                "curl",
                "--silent",
                "--show-error",
                "--max-time",
                "5",
                "--write-out",
                "\n__EOAT_HTTP_STATUS=%{http_code} __EOAT_RESPONSE_SECONDS=%{time_total}\n",
                f"http://127.0.0.1:{self.config.api_port}{value}",
            ]
        if (
            operation == "reverse-proxy-health"
            and value
            and value in INSPECTION_HEALTH_PATHS
            and self.config.public_hostname
        ):
            endpoint = f"{self.config.public_scheme}://{self.config.public_hostname}:{self.config.public_port}{value}"
            return [
                "curl",
                "--silent",
                "--show-error",
                "--max-time",
                "5",
                "--resolve",
                f"{self.config.public_hostname}:{self.config.public_port}:127.0.0.1",
                "--write-out",
                "\n__EOAT_HTTP_STATUS=%{http_code} __EOAT_RESPONSE_SECONDS=%{time_total}\n",
                endpoint,
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
            result = self._runner(
                command,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )
            output = redact_text(((result.stdout or "") + (result.stderr or "")).strip())
            if operation in {"service-units", "service-unit-files"}:
                # Unit lists are naturally ordered and EOAT entries occur near
                # the beginning.  Keep their leading metadata instead of
                # losing it to the generic diagnostic tail cap.
                output = output[:20000]
            else:
                output = output[-6000:]
            return RemoteResult(operation, tuple(remote_args), result.returncode, output)
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


def _http_probe_output(output: str) -> tuple[str, dict[str, Any]]:
    match = re.search(
        r"\n__EOAT_HTTP_STATUS=(?P<status>\d{3}) __EOAT_RESPONSE_SECONDS=(?P<seconds>[0-9.]+)\s*$",
        output,
    )
    if not match:
        return output, {"http_status": None, "response_seconds": None}
    return (
        output[: match.start()].strip(),
        {"http_status": int(match.group("status")), "response_seconds": float(match.group("seconds"))},
    )


def _health_result(remote: RemoteResult) -> dict[str, Any]:
    """Interpret a safe GET without treating a protected endpoint as an outage."""
    result = _service_result(remote)
    body, timing = _http_probe_output(remote.output)
    result.update(timing)
    if remote.exit_code or timing["http_status"] is None:
        return result
    if timing["http_status"] == 200:
        result["status"] = "PASS"
        return result
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and payload.get("error_code") == "DEVICE_AUTH_NOT_CONFIGURED":
        result["status"] = "SECURED_UNAVAILABLE"
        return result
    result["status"] = "FAIL"
    return result


def health_comparison(health: dict[str, dict[str, Any]], core: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    compared: dict[str, Any] = {}
    warnings: list[str] = []
    for path, item in health.items():
        body, timing = _http_probe_output(str(item["output"]))
        if item["status"] == "SECURED_UNAVAILABLE":
            compared[path] = {"status": item["status"], "detail": body, **timing}
            warnings.append(
                f"Health probe {path} requires production device authentication; /api/v1/health supplies schema state"
            )
            continue
        if item["status"] != "PASS":
            compared[path] = {"status": item["status"], "detail": body, **timing}
            warnings.append(f"Health probe {path} did not complete")
            continue
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            compared[path] = {"status": "WARNING", "detail": "Health response was not JSON", **timing}
            warnings.append(f"Health probe {path} returned non-JSON output")
            continue
        values = {
            key: payload.get(key)
            for key in (
                "application_version",
                "release_id",
                "build_id",
                "server_revision",
                "commit_sha",
                "current_schema_revision",
                "database_schema_revision",
                "migration_revision",
                "database_revision",
                "database_reachable",
                "compatible",
            )
            if key in payload
        }
        compared[path] = {"status": "PASS", "values": values, **timing}
        if values.get("application_version") and values["application_version"] != core["version"]:
            compared[path]["target_version"] = core["version"]
            compared[path]["version_matches_target"] = False
        elif values.get("application_version"):
            compared[path]["target_version"] = core["version"]
            compared[path]["version_matches_target"] = True
        if values.get("commit_sha") and values["commit_sha"] != core["commit_sha"]:
            warnings.append(f"Health probe {path} reports a commit different from the selected release")
    return compared, warnings


def migration_execution_warnings(migration: dict[str, Any], requirement: dict[str, Any]) -> list[str]:
    """Historical destructive syntax is irrelevant when the target schema is already current."""
    if requirement.get("status") == "NOT_REQUIRED":
        return []
    return [str(warning) for warning in migration.get("destructive_warnings", [])]


def migration_requirement(
    health: dict[str, dict[str, Any]], database: RemoteResult, core: dict[str, Any]
) -> dict[str, Any]:
    """Determine whether a migration is needed without treating a failed direct query as a write permission."""

    target = str(core["database"]["target_revision"])
    if database.exit_code == 0 and database.output.strip():
        current = database.output.strip()
        return {
            "status": "NOT_REQUIRED" if current == target else "REQUIRED",
            "current_revision": current,
            "target_revision": target,
            "source": "mysql_login_path",
        }
    for path in ("/api/v1/schema-status", "/api/v1/health"):
        item = health.get(path)
        if not item or item.get("status") != "PASS":
            continue
        body, _timing = _http_probe_output(str(item.get("output") or ""))
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        current = str(payload.get("current_revision") or payload.get("current_schema_revision") or "")
        if current:
            return {
                "status": "NOT_REQUIRED" if current == target else "REQUIRED",
                "current_revision": current,
                "target_revision": target,
                "source": path,
                "direct_database_query": "UNAVAILABLE",
            }
    return {
        "status": "UNKNOWN",
        "current_revision": None,
        "target_revision": target,
        "source": None,
        "direct_database_query": "UNAVAILABLE" if database.exit_code else "EMPTY",
    }


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


def _current_metadata(remote: RemoteResult) -> tuple[dict[str, Any] | None, str | None]:
    """Read the legacy release metadata used by production releases before Phase 1."""

    if remote.exit_code:
        return None, remote.output
    try:
        payload = json.loads(remote.output)
    except json.JSONDecodeError as exc:
        return None, f"Current release metadata is unavailable or invalid: {exc}"
    if not isinstance(payload, dict):
        return None, "Current release metadata is not an object"
    version = str(payload.get("app_version") or "")
    try:
        Version.parse(version)
    except ValueError:
        return None, "Current release metadata has an invalid application version"
    release_id = str(payload.get("release_id") or "")
    build_id = str(payload.get("build_id") or "")
    commit = str(payload.get("source_git_commit") or payload.get("git_commit") or "")
    if not release_id or not build_id or not FULL_SHA.fullmatch(commit):
        return None, "Current release metadata lacks a release ID, build ID, or full source commit"
    return (
        {
            "version": version,
            "release_id": release_id,
            "build_id": build_id,
            "commit_sha": commit,
            "created_at_utc": str(payload.get("build_timestamp") or "") or None,
            "migration_revision": str(payload.get("database_schema_revision") or "") or None,
            "api_contract_version": str(payload.get("api_contract_version") or "") or None,
            "environment": str(payload.get("environment") or "") or None,
        },
        None,
    )


def _current_deployment(manifest: RemoteResult, metadata: RemoteResult) -> tuple[dict[str, Any], list[str]]:
    core, manifest_error = _current_manifest(manifest)
    release_metadata, metadata_error = _current_metadata(metadata)
    warnings: list[str] = []
    if core:
        return {
            "primary_source": "release_manifest",
            "manifest": core,
            "metadata": release_metadata,
            "identity": manifest_identity(core).__dict__,
            "error": None,
        }, warnings
    if release_metadata:
        warnings.append("Current release uses legacy release_metadata.json; no release_manifest.json is present")
        return {
            "primary_source": "release_metadata",
            "manifest": None,
            "metadata": release_metadata,
            "identity": release_metadata,
            "error": None,
        }, warnings
    return {
        "primary_source": None,
        "manifest": None,
        "metadata": None,
        "identity": None,
        "error": manifest_error or metadata_error,
    }, warnings


def _discovered_service_names(
    units: RemoteResult, config: ServerConfig, core: dict[str, Any] | None = None
) -> tuple[str, ...]:
    names: list[str] = []
    if core:
        names.extend(str(item) for item in core.get("services", []))
    names.extend(config.services)
    if config.nginx_service:
        names.append(config.nginx_service)
    if units.exit_code == 0:
        for line in units.output.splitlines():
            match = DISCOVERED_SERVICE.match(line)
            if not match:
                continue
            name = match.group(1)
            if name == "nginx.service" or name.startswith("eoat-") or "atlas" in name:
                names.append(name)
    return tuple(dict.fromkeys(names))


def _result_payload(remote: RemoteResult) -> dict[str, Any]:
    return {"exit_code": remote.exit_code, "output": remote.output, "command": list(remote.command)}


def truth_reconciliation(
    current: dict[str, Any],
    remote: dict[str, RemoteResult],
    services: dict[str, dict[str, Any]],
    health: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compare independent deployment facts without silently choosing one."""

    checks: list[dict[str, str]] = []
    violations: list[str] = []
    identity = current.get("identity") or {}
    current_target = remote["current-target"].output if remote["current-target"].exit_code == 0 else ""
    version = str(identity.get("version") or "")
    commit = str(identity.get("commit_sha") or "")
    if version and commit and current_target:
        expected_markers = (version, commit[:7])
        if all(marker in current_target for marker in expected_markers):
            checks.append({"source": "current_symlink", "status": "PASS", "detail": current_target})
        else:
            detail = "Current symlink target does not match release metadata version/commit"
            checks.append({"source": "current_symlink", "status": "FAIL", "detail": detail})
            violations.append(detail)
    else:
        checks.append(
            {"source": "current_symlink", "status": "UNKNOWN", "detail": "Insufficient symlink or identity data"}
        )

    app_services = [result for name, result in services.items() if name.startswith("eoat-") or "atlas" in name]
    if app_services and any("/opt/eoat-atlas/current" in str(result.get("output") or "") for result in app_services):
        checks.append({"source": "systemd", "status": "PASS", "detail": "EOAT service executes from current symlink"})
    elif app_services:
        detail = "EOAT service does not expose an ExecStart or working directory under current"
        checks.append({"source": "systemd", "status": "FAIL", "detail": detail})
        violations.append(detail)
    else:
        checks.append({"source": "systemd", "status": "UNKNOWN", "detail": "No EOAT service was discovered"})

    health_item = health.get("/api/v1/health")
    payload: dict[str, Any] | None = None
    if health_item and health_item.get("status") == "PASS":
        body, _timing = _http_probe_output(str(health_item.get("output") or ""))
        try:
            loaded = json.loads(body)
            payload = loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError:
            payload = None
    if payload is None:
        checks.append({"source": "health", "status": "UNKNOWN", "detail": "Health identity response was unavailable"})
    else:
        mismatches = [
            field
            for field, health_field in (
                ("version", "application_version"),
                ("release_id", "release_id"),
                ("build_id", "build_id"),
            )
            if identity.get(field) and payload.get(health_field) != identity.get(field)
        ]
        if mismatches:
            detail = "Health identity differs from current release metadata: " + ", ".join(mismatches)
            checks.append({"source": "health", "status": "FAIL", "detail": detail})
            violations.append(detail)
        else:
            checks.append(
                {"source": "health", "status": "PASS", "detail": "Health identity agrees with current release metadata"}
            )
        metadata_environment = identity.get("environment")
        health_environment = payload.get("environment")
        if metadata_environment and health_environment and metadata_environment != health_environment:
            detail = (
                f"Environment mismatch: release metadata is {metadata_environment!r} "
                f"but health reports {health_environment!r}"
            )
            checks.append({"source": "environment", "status": "FAIL", "detail": detail})
            violations.append(detail)
        elif metadata_environment or health_environment:
            checks.append(
                {"source": "environment", "status": "PASS", "detail": str(metadata_environment or health_environment)}
            )
        metadata_revision = identity.get("migration_revision")
        health_revision = payload.get("current_schema_revision")
        if metadata_revision and health_revision and metadata_revision != health_revision:
            detail = "Health schema revision differs from current release metadata"
            checks.append({"source": "migration", "status": "FAIL", "detail": detail})
            violations.append(detail)
        elif metadata_revision and health_revision:
            checks.append({"source": "migration", "status": "PASS", "detail": str(health_revision)})
    return {"checks": checks, "violations": violations}


def public_health_compatibility(config: ServerConfig, core: dict[str, Any]) -> dict[str, Any]:
    """Ensure the selected artifact declares the same approved public probe."""
    expected = core.get("public_health_endpoint")
    observed = {
        "scheme": config.public_scheme,
        "hostname": config.public_hostname,
        "port": config.public_port,
        "paths": core.get("health_checks", []),
    }
    if not isinstance(expected, dict):
        return {
            "status": "UNKNOWN",
            "detail": "Release manifest has no public health endpoint metadata",
            "observed": observed,
        }
    manifest_hostname = expected.get("hostname")
    # Release artifacts intentionally use the IANA-reserved example.invalid
    # hostname so a tracked manifest never publishes an environment endpoint.
    # The real public host is an approved, untracked deployment configuration.
    # It is safe to accept that substitution because reverse-proxy probes use
    # --resolve to 127.0.0.1; scheme, port, and paths remain exact contracts.
    if isinstance(manifest_hostname, str) and manifest_hostname.casefold().endswith(".example.invalid"):
        if not observed["hostname"]:
            return {
                "status": "UNKNOWN",
                "detail": "Release manifest uses a placeholder hostname; deployment configuration must supply the approved host",
                "expected": expected,
                "observed": observed,
            }
        differences = [key for key in ("scheme", "port", "paths") if expected.get(key) != observed.get(key)]
        return {
            "status": "PASS" if not differences else "FAIL",
            "detail": "Release manifest placeholder hostname is supplied by the approved deployment configuration"
            if not differences
            else "Public health endpoint differs from release manifest: " + ", ".join(differences),
            "expected": expected,
            "observed": observed,
            "hostname_source": "deployment_configuration",
        }
    differences = [key for key in ("scheme", "hostname", "port", "paths") if expected.get(key) != observed.get(key)]
    return {
        "status": "PASS" if not differences else "FAIL",
        "detail": "Public health endpoint agrees with release manifest"
        if not differences
        else "Public health endpoint differs from release manifest: " + ", ".join(differences),
        "expected": expected,
        "observed": observed,
    }


def _reverse_proxy_result(result: RemoteResult, config: ServerConfig, path: str) -> dict[str, Any]:
    probe = _health_result(result)
    body, _timing = _http_probe_output(result.output)
    return {
        **probe,
        "url": f"{config.public_scheme}://{config.public_hostname}:{config.public_port}{path}",
        "body_excerpt": body[-1000:],
    }


def _reverse_proxy_inspection(
    ssh: ReadonlySSH, config: ServerConfig, paths: Iterable[str], fallback: RemoteResult
) -> dict[str, Any]:
    if not config.public_hostname:
        body, timing = _http_probe_output(fallback.output)
        return {**_service_result(fallback), "body_excerpt": body[-1000:], **timing}
    probes = {path: _reverse_proxy_result(ssh.execute("reverse-proxy-health", path), config, path) for path in paths}
    return {
        "endpoint": {
            "scheme": config.public_scheme,
            "hostname": config.public_hostname,
            "port": config.public_port,
        },
        "probes": probes,
    }


def _reverse_proxy_warnings(config: ServerConfig, proxy: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if config.public_hostname:
        for path, probe in proxy.get("probes", {}).items():
            if probe.get("status") == "SECURED_UNAVAILABLE":
                warnings.append(
                    f"Public reverse-proxy health probe {path} requires production device authentication; "
                    "/api/v1/health supplies schema state"
                )
                continue
            if probe.get("status") != "PASS" or probe.get("http_status") != 200:
                warnings.append(f"Public reverse-proxy health probe {path} did not return HTTP 200")
        if config.public_scheme == "http" and config.public_port == 80:
            warnings.append(HTTP_ONLY_TLS_WARNING)
    elif "Welcome to nginx!" in str(proxy.get("body_excerpt") or ""):
        warnings.append("Nginx is active but its local root serves the default page, not EOAT Atlas")
    return warnings


def inspect_server_only(config: ServerConfig) -> dict[str, Any]:
    """Inspect the verified server without selecting or downloading a release."""

    host_key = ssh_host_key_status(config)
    if not host_key.known:
        return {
            "mode": "READ_ONLY_SERVER_INSPECTION",
            "declaration": "NO SERVER CHANGES WILL BE MADE",
            "ssh_host_key": host_key.__dict__,
            "warnings": [host_key.diagnostic or "SSH host key is not trusted"],
            "blocking_failures": ["SSH host key is unknown or changed; inspection stopped before connection"],
            "readiness": "NOT_READY",
        }
    ssh = ReadonlySSH(config)
    operations = (
        "hostname",
        "uname",
        "os-release",
        "python",
        "mysql-version",
        "time",
        "timezone",
        "memory",
        "disk",
        "layout",
        "current-target",
        "current-content",
        "releases",
        "incoming",
        "shared-layout",
        "release-evidence",
        "environment-metadata",
        "environment-files",
        "lock",
        "service-units",
        "service-unit-files",
        "listeners",
        "nginx-metadata",
        "reverse-proxy-root",
    )
    remote = {name: ssh.execute(name) for name in operations}
    current, current_warnings = _current_deployment(ssh.execute("current-manifest"), ssh.execute("current-metadata"))
    service_names = _discovered_service_names(remote["service-units"], config)
    services = {name: _service_result(ssh.execute("service", name)) for name in service_names}
    health = {path: _health_result(ssh.execute("health", path)) for path in INSPECTION_HEALTH_PATHS}
    database = ssh.execute("database-revision")
    truth = truth_reconciliation(current, remote, services, health)
    proxy = _reverse_proxy_inspection(ssh, config, INSPECTION_HEALTH_PATHS, remote["reverse-proxy-root"])
    warnings = list(current_warnings)
    if current["error"]:
        warnings.append(str(current["error"]))
    if database.exit_code:
        warnings.append("Database migration revision could not be queried with the configured read-only login path")
    if remote["lock"].exit_code:
        warnings.append("Configured deployment lock is not present or not readable")
    warnings.extend(_reverse_proxy_warnings(config, proxy))
    return {
        "mode": "READ_ONLY_SERVER_INSPECTION",
        "declaration": "NO SERVER CHANGES WILL BE MADE",
        "server": {name: _result_payload(result) for name, result in remote.items()},
        "current_deployment": current,
        "services": services,
        "health": health,
        "reverse_proxy": proxy,
        "truth_reconciliation": truth,
        "database": {
            "exit_code": database.exit_code,
            "revision": database.output if database.exit_code == 0 else None,
            "diagnostic": database.output if database.exit_code else None,
        },
        "deployment_lock": {
            "exit_code": remote["lock"].exit_code,
            "metadata": remote["lock"].output if remote["lock"].exit_code == 0 else None,
            "diagnostic": remote["lock"].output if remote["lock"].exit_code else None,
        },
        "ssh_host_key": host_key.__dict__,
        "warnings": warnings,
        "blocking_failures": truth["violations"],
        "readiness": "NOT_READY"
        if truth["violations"]
        else "READY_WITH_WARNINGS"
        if warnings
        else "READY_FOR_LATER_DEPLOYMENT",
    }


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
        "timezone",
        "memory",
        "disk",
        "layout",
        "current-target",
        "current-content",
        "releases",
        "incoming",
        "shared-layout",
        "release-evidence",
        "environment-metadata",
        "environment-files",
        "lock",
        "service-units",
        "service-unit-files",
        "listeners",
        "nginx-metadata",
        "reverse-proxy-root",
    )
    remote = {name: ssh.execute(name) for name in identity_operations}
    current_deployment, current_warnings = _current_deployment(
        ssh.execute("current-manifest"), ssh.execute("current-metadata")
    )
    services = _discovered_service_names(remote["service-units"], config, core)
    service_state = {service: _service_result(ssh.execute("service", service)) for service in services}
    health = {path: _health_result(ssh.execute("health", path)) for path in core.get("health_checks", [])}
    health_status, health_warnings = health_comparison(health, core)
    database = ssh.execute("database-revision")
    truth = truth_reconciliation(current_deployment, remote, service_state, health)
    public_health = public_health_compatibility(config, core)
    migration_requirement_result = migration_requirement(health, database, core)
    migration = migration_summary(archive)
    disk = (
        disk_space_preflight(remote["disk"].output, archive.stat().st_size)
        if remote["disk"].exit_code == 0
        else {"status": "UNKNOWN", "warning": "Approved disk inspection command failed"}
    )
    runtime = runtime_compatibility(remote, core)
    warnings = list(current_warnings)
    blocking: list[str] = []
    if not services:
        warnings.append("No verified service units are configured or embedded in the release manifest")
    if current_deployment["error"]:
        warnings.append(str(current_deployment["error"]))
    current_identity = current_deployment["identity"]
    if current_identity:
        for field in ("version", "commit_sha"):
            if not current_identity.get(field):
                warnings.append(f"Current deployment identity has no {field}")
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
    if migration_requirement_result["status"] == "UNKNOWN":
        warnings.append("Migration requirement could not be determined from the direct query or health endpoints")
    if migration["multiple_heads"]:
        blocking.append("Downloaded release contains multiple Alembic heads")
    if core["database"]["target_revision"] not in migration["revisions"]:
        blocking.append("Downloaded release does not contain its declared Alembic target revision")
    warnings.extend(migration_execution_warnings(migration, migration_requirement_result))
    warnings.extend(health_warnings)
    blocking.extend(truth["violations"])
    if public_health["status"] == "FAIL":
        blocking.append(str(public_health["detail"]))
    elif public_health["status"] == "UNKNOWN":
        warnings.append(str(public_health["detail"]))
    reverse_proxy = _reverse_proxy_inspection(ssh, config, core.get("health_checks", []), remote["reverse-proxy-root"])
    warnings.extend(_reverse_proxy_warnings(config, reverse_proxy))
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
        "server": {name: _result_payload(result) for name, result in remote.items()},
        "current_deployment": current_deployment,
        "services": service_state,
        "health": health,
        "health_comparison": health_status,
        "public_health_compatibility": public_health,
        "truth_reconciliation": truth,
        "reverse_proxy": reverse_proxy,
        "database": {
            "exit_code": database.exit_code,
            "revision": database.output if database.exit_code == 0 else None,
            "diagnostic": database.output if database.exit_code else None,
        },
        "disk_space_preflight": disk,
        "runtime_compatibility": runtime,
        "migration_preflight": migration,
        "migration_requirement": migration_requirement_result,
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
    receipt["receipt_path"] = str(path)
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
    parser = argparse.ArgumentParser(
        description="EOAT Atlas release updater (read-only preflight plus explicit Phase 3 controls)"
    )
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--server-config", type=Path, help="Non-secret local server inspection configuration")
    parser.add_argument("--release-dir", type=Path, help="Verified local release assets for offline inspection")
    parser.add_argument("--cache-dir", type=Path, help="Local untracked GitHub release cache")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show strict read-only updater status")
    subparsers.add_parser("inspect-server", help="Inspect the configured server without selecting a release")
    subparsers.add_parser("list-releases", help="List eligible GitHub Releases")
    inspect = subparsers.add_parser("inspect-release", help="Download/cache and verify a release without SSH")
    inspect.add_argument("--version", metavar="MAJOR.MINOR.PATCH")
    preflight = subparsers.add_parser("preflight", help="Perform a strict read-only deployment rehearsal")
    preflight.add_argument("--version", metavar="MAJOR.MINOR.PATCH")
    deploy_latest = subparsers.add_parser("deploy-latest", help="Preflight latest release or explicitly stage it")
    latest_mode = deploy_latest.add_mutually_exclusive_group(required=True)
    latest_mode.add_argument("--dry-run", action="store_true")
    latest_mode.add_argument("--stage-only", action="store_true", help="Stage after all checks; never activate")
    deploy_version = subparsers.add_parser("deploy-version", help="Preflight selected release or explicitly stage it")
    deploy_version.add_argument("version", metavar="MAJOR.MINOR.PATCH")
    version_mode = deploy_version.add_mutually_exclusive_group(required=True)
    version_mode.add_argument("--dry-run", action="store_true")
    version_mode.add_argument("--stage-only", action="store_true", help="Stage after all checks; never activate")
    for command, description in (
        ("activate", "Activate an already staged deployment"),
        ("rollback", "Roll back an activated deployment"),
        ("recover", "Inspect a locked interrupted deployment"),
        ("abort", "Abort a pre-activation deployment"),
        ("deployment-status", "Read a deployment transaction state"),
    ):
        active = subparsers.add_parser(command, help=description)
        active.add_argument("deployment_id", metavar="DEPLOYMENT_ID")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    cache = (args.cache_dir or root / ".local" / "deployment-cache").resolve()
    try:
        if args.command == "status":
            payload = {
                "tool_version": TOOL_VERSION,
                "mode": "READ_ONLY_STATUS",
                "server_configured": bool(args.server_config),
                "cache_dir": str(cache),
                "active_deployment_supported": True,
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
        if args.command == "inspect-server":
            if not args.server_config:
                raise DeploymentError("inspect-server requires a non-secret --server-config")
            receipt = inspect_server_only(load_server_config(args.server_config.resolve()))
            receipt["receipt_path"] = str(_write_receipt(root, receipt))
            _print(receipt, args.as_json)
            return 0
        if args.command in {"activate", "rollback", "recover", "abort", "deployment-status"}:
            if not args.server_config:
                raise DeploymentError(f"{args.command} requires a non-secret --server-config")
            from .active_deployment import helper_operation

            operation = "status" if args.command == "deployment-status" else args.command
            result = helper_operation(
                root, load_server_config(args.server_config.resolve()), operation, args.deployment_id
            )
            _print(
                {
                    "mode": operation.upper(),
                    "deployment_id": result.deployment_id,
                    "state": result.state,
                    "receipt_path": str(result.receipt_path),
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
        if getattr(args, "stage_only", False):
            if not config:
                raise DeploymentError("--stage-only requires a non-secret --server-config")
            from .active_deployment import stage_release

            result = stage_release(root, release_dir, external, config)
            _print(
                {
                    "mode": "STAGE_ONLY",
                    "deployment_id": result.deployment_id,
                    "state": result.state,
                    "receipt_path": str(result.receipt_path),
                },
                args.as_json,
            )
            return 0
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
