"""Small adapters over deployment modules; no release or deployment policy lives here."""

from __future__ import annotations

import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from deployment import active_deployment, release_manager, server_updater
from deployment.manifest import manifest_identity, validate_external_manifest

from .models import OperationResult, RepositoryStatus, result_from_payload


def _plain(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


class ReleaseManagerService:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def inspect_status(self) -> tuple[RepositoryStatus, OperationResult]:
        backend_payload = release_manager.status_payload(self.root)
        # ``clean`` is a computed GitState property, rather than a dataclass
        # field, so ``asdict`` deliberately omits it. Preserve the backend's
        # authoritative computed value in the raw GUI response.
        backend_repository = backend_payload["repository"]
        payload = _plain(backend_payload)
        payload["repository"]["clean"] = bool(backend_repository.clean)
        repo = payload["repository"]
        status = RepositoryStatus(
            str(repo["branch"]),
            str(repo["commit"]),
            repo.get("version"),
            bool(repo["clean"]),
            bool(payload["ready_to_package"]),
            payload,
        )
        return status, result_from_payload("repository status", payload, summary="Repository status refreshed")

    def validate(self) -> OperationResult:
        checks, commands = release_manager.run_validation(self.root)
        raw = {"checks": _plain(checks), "commands": _plain(commands)}
        failed = [item for item in raw["checks"] if item.get("status") == "FAIL"]
        raw["final_status"] = "FAILED" if failed else "PASSED"
        return result_from_payload("validation", raw, summary="Release validation completed")

    def rehearse_package(self, version: str) -> OperationResult:
        payload = release_manager.package(
            self.root,
            bump=None,
            explicit_version=version,
            dry_run=True,
            no_push=True,
            no_publish=True,
            allow_dirty=False,
            approved_exception=None,
        )
        return result_from_payload("dry-run package", _plain(payload), summary="Dry-run package completed")

    def publish_release(
        self, version: str, *, allow_dirty: bool = False, exception: str | None = None
    ) -> OperationResult:
        payload = release_manager.package(
            self.root,
            bump=None,
            explicit_version=version,
            dry_run=False,
            no_push=False,
            no_publish=False,
            allow_dirty=allow_dirty,
            approved_exception=exception,
        )
        return result_from_payload("publish release", _plain(payload), summary="Release publication completed")


class ServerUpdaterService:
    def __init__(self, root: Path, *, cache_root: Path | None = None) -> None:
        self.root = root.resolve()
        self.cache_root = (cache_root or self.root / ".local" / "deployment-cache").resolve()

    def inspect_status(self, config_path: Path | None = None) -> OperationResult:
        raw = {
            "tool_version": server_updater.TOOL_VERSION,
            "mode": "READ_ONLY_STATUS",
            "cache_dir": str(self.cache_root),
            "server_configured": bool(config_path),
            "active_deployment_supported": True,
            "github_cli_available": bool(shutil.which("gh")),
            "ssh_available": bool(shutil.which("ssh")),
        }
        return result_from_payload("updater status", raw, summary="Updater status refreshed")

    def load_config(self, config_path: Path) -> OperationResult:
        config = server_updater.load_server_config(config_path.resolve())
        return result_from_payload(
            "configuration",
            {"config": _plain(config), "config_path": str(config_path.resolve()), "final_status": "VALID"},
            summary="Non-secret server configuration loaded",
        )

    def inspect_server(self, config_path: Path) -> OperationResult:
        config = server_updater.load_server_config(config_path.resolve())
        payload = server_updater.inspect_server_only(config)
        helper = {"available": False, "detail": "Not inspected"}
        if not payload.get("blocking_failures"):
            try:
                audit = active_deployment.PrivilegedHelperClient(config).audit_noninteractive_sudo()
                helper = {"available": True, "detail": _plain(audit)}
            except Exception as exc:
                helper = {"available": False, "detail": str(exc)}
                payload.setdefault("warnings", []).append(
                    "Privileged helper audit did not pass; staging remains disabled"
                )
        payload["privileged_helper"] = helper
        return result_from_payload(
            "server inspection", _plain(payload), summary="Read-only server inspection completed"
        )

    def list_releases(self) -> OperationResult:
        releases = server_updater.github_releases(self.root)
        raw = {"releases": _plain(releases), "eligible": []}
        for release in releases:
            try:
                selected = server_updater.select_release([release])
            except Exception:
                continue
            raw["eligible"].append(_plain(selected))
        raw["final_status"] = "AVAILABLE"
        return result_from_payload("release list", raw, summary="Eligible releases refreshed")

    def inspect_release(self, version: str | None = None, *, release_dir: Path | None = None) -> OperationResult:
        directory, external = server_updater._resolve_local_or_github(
            self.root, release_dir=release_dir, version=version, cache_root=self.cache_root
        )
        core, artifact = validate_external_manifest(external)
        raw = {
            "verification": "VERIFIED",
            "release": _plain(manifest_identity(core)),
            "artifact": artifact,
            "manifest": external,
            "cache_path": str(directory),
            "release_dir": str(directory),
        }
        return result_from_payload("release inspection", _plain(raw), summary="Release verification completed")

    def rehearse_deployment(self, config_path: Path, release_dir: Path) -> OperationResult:
        directory, external = server_updater._local_release(release_dir.resolve())
        payload = server_updater.dry_run_receipt(
            self.root, directory, external, server_updater.load_server_config(config_path.resolve())
        )
        return result_from_payload(
            "deployment rehearsal", _plain(payload), summary="Read-only deployment rehearsal completed"
        )

    def stage_release(self, config_path: Path, release_dir: Path) -> OperationResult:
        directory, external = server_updater._local_release(release_dir.resolve())
        receipt = active_deployment.stage_release(
            self.root, directory, external, server_updater.load_server_config(config_path.resolve())
        )
        return result_from_payload("stage release", _plain(receipt), summary="Staging submitted")

    def deployment_operation(self, config_path: Path, deployment_id: str, operation: str) -> OperationResult:
        receipt = active_deployment.helper_operation(
            self.root, server_updater.load_server_config(config_path.resolve()), operation, deployment_id
        )
        return result_from_payload(operation, _plain(receipt), summary=f"{operation.title()} request completed")
