"""Thin, Phase-1-only adapters over the existing release and updater engines."""

from __future__ import annotations

import shutil
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deployment import release_manager, server_updater
from deployment.manifest import manifest_identity, validate_external_manifest

from .models import GuiStatus, OperationResult, map_status
from .redaction import redact_text, sanitize


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Path):
        return str(value)
    return value


def _timestamps() -> tuple[str, str]:
    value = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return value, value


def _result(
    tool: str, operation: str, payload: dict[str, Any], summary: str, *, started: str | None = None
) -> OperationResult:
    payload = sanitize(_plain(payload))
    blockers = tuple(str(item) for item in payload.get("blocking_failures", []) if item)
    nested = payload.get("server_inspection")
    if isinstance(nested, dict):
        blockers += tuple(str(item) for item in nested.get("blocking_failures", []) if item)
    warnings = tuple(str(item) for item in payload.get("warnings", []) if item)
    if isinstance(nested, dict):
        warnings += tuple(str(item) for item in nested.get("warnings", []) if item)
    raw_status = payload.get("final_status") or payload.get("overall_readiness") or payload.get("readiness")
    status = map_status(raw_status, has_blockers=bool(blockers), has_warnings=bool(warnings))
    end = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return OperationResult(tool, operation, status, summary, payload, blockers, warnings, started, end)


class ReleaseManagerAdapter:
    """Only read-only status/validation/dry-run packaging calls are exposed."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def status(self) -> OperationResult:
        started, _ = _timestamps()
        return _result(
            "packager",
            "status",
            release_manager.status_payload(self.root),
            "Release-manager status refreshed",
            started=started,
        )

    def validate(self) -> OperationResult:
        started, _ = _timestamps()
        checks, commands = release_manager.run_validation(self.root)
        payload = {"checks": _plain(checks), "commands": _plain(commands)}
        payload["final_status"] = (
            "PASSED" if not any(item["status"] == "FAIL" for item in payload["checks"]) else "FAILED"
        )
        return _result("packager", "validate", payload, "Release validation completed", started=started)

    def package_dry_run(self, proposed_version: str) -> OperationResult:
        started, _ = _timestamps()
        payload = release_manager.package(
            self.root,
            bump=None,
            explicit_version=proposed_version,
            dry_run=True,
            no_push=True,
            no_publish=True,
            allow_dirty=False,
            approved_exception=None,
        )
        return _result(
            "packager",
            "package-dry-run",
            payload,
            "Dry-run package completed; no repository or release mutation occurred",
            started=started,
        )


class ServerUpdaterAdapter:
    """Only the updater's safe inspection and dry-run APIs are exposed."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.cache_root = self.root / ".local" / "deployment-cache"

    def status(self) -> OperationResult:
        started, _ = _timestamps()
        payload = {
            "mode": "READ_ONLY_STATUS",
            "tool_version": server_updater.TOOL_VERSION,
            "github_cli_available": bool(shutil.which("gh")),
            "ssh_available": bool(shutil.which("ssh")),
            "active_mutations": "Disabled by this Phase 1 GUI",
            "final_status": "PASS",
        }
        return _result("updater", "status", payload, "Updater read-only status refreshed", started=started)

    def _approved_config(self, path: Path):
        resolved = path.resolve()
        approved_root = (self.root / "config").resolve()
        if (
            resolved.suffix.casefold() != ".json"
            or not resolved.is_file()
            or not resolved.is_relative_to(approved_root)
        ):
            raise ValueError("Choose an approved non-secret JSON configuration from this repository's config folder")
        payload = sanitize(__import__("json").loads(resolved.read_text(encoding="utf-8")))
        if "***REDACTED***" in str(payload):
            raise ValueError("Server configuration contains a secret-shaped field and is not permitted in the GUI")
        return resolved, server_updater.load_server_config(resolved)

    def load_config(self, path: Path) -> OperationResult:
        started, _ = _timestamps()
        resolved, config = self._approved_config(path)
        return _result(
            "updater",
            "load-config",
            {"config_path": str(resolved), "server": _plain(config), "final_status": "VALID"},
            "Approved non-secret server configuration loaded",
            started=started,
        )

    def inspect_server(self, path: Path) -> OperationResult:
        started, _ = _timestamps()
        _, config = self._approved_config(path)
        return _result(
            "updater",
            "inspect-server",
            server_updater.inspect_server_only(config),
            "Read-only server inspection completed",
            started=started,
        )

    def list_releases(self) -> OperationResult:
        started, _ = _timestamps()
        releases = server_updater.github_releases(self.root)
        eligible = []
        for release in releases:
            try:
                eligible.append(_plain(server_updater.select_release([release])))
            except Exception:
                continue
        return _result(
            "updater",
            "list-releases",
            {"releases": eligible, "final_status": "AVAILABLE" if eligible else "UNKNOWN"},
            "Eligible GitHub Releases listed",
            started=started,
        )

    def inspect_release(self, version: str | None) -> OperationResult:
        started, _ = _timestamps()
        directory, external = server_updater._resolve_local_or_github(
            self.root, release_dir=None, version=version, cache_root=self.cache_root
        )
        core, artifact = validate_external_manifest(external)
        return _result(
            "updater",
            "inspect-release",
            {
                "release": _plain(manifest_identity(core)),
                "artifact": artifact,
                "manifest": external,
                "cache_path": str(directory),
                "final_status": "VERIFIED",
            },
            "Release artifact and manifest verified",
            started=started,
        )

    def preflight(self, path: Path, version: str | None) -> OperationResult:
        started, _ = _timestamps()
        _, config = self._approved_config(path)
        directory, external = server_updater._resolve_local_or_github(
            self.root, release_dir=None, version=version, cache_root=self.cache_root
        )
        payload = server_updater.dry_run_receipt(self.root, directory, external, config)
        return _result("updater", "preflight", payload, "Read-only deployment preflight completed", started=started)


def failure_result(tool: str, operation: str, error: object) -> OperationResult:
    started, ended = _timestamps()
    return OperationResult(
        tool,
        operation,
        GuiStatus.FAILED,
        "Operation failed safely",
        {"error": redact_text(error)},
        (),
        (),
        started,
        ended,
    )
