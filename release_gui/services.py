"""Small adapters over deployment modules; no release or deployment policy lives here."""

from __future__ import annotations

import json
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
        self._branches: list[str] | None = None
        self._commits_by_branch: dict[str, list[tuple[str, str]]] = {}

    def inspect_status(self) -> tuple[RepositoryStatus, OperationResult]:
        # The full CLI status makes many sequential Git calls and invokes
        # diagnostics. This selector needs an immediate local answer; the
        # existing packager still runs its complete readiness checks later.
        git = release_manager.Git(self.root)
        branch = git.output("branch", "--show-current") or "(detached)"
        commit = git.output("rev-parse", "HEAD").lower()
        clean = not bool(git.output("status", "--porcelain=v1").strip())
        version = self._version_at(git, commit)
        payload = {
            "tool_version": release_manager.TOOL_VERSION,
            "repository": {
                "root": str(self.root),
                "branch": branch,
                "commit": commit,
                "clean": clean,
                "version": version,
            },
            "ready_to_package": bool(clean and branch != "(detached)" and version),
        }
        payload["readiness"] = "READY" if payload.get("ready_to_package") else "NOT_READY"
        payload["selection_matches_checkout"] = True
        repo = payload["repository"]
        status = RepositoryStatus(
            str(repo["branch"]),
            str(repo["commit"]),
            repo.get("version"),
            clean,
            bool(payload["ready_to_package"]),
            payload,
        )
        return status, result_from_payload("repository status", payload, summary="Repository status refreshed")

    def repository_view(self) -> tuple[RepositoryStatus, OperationResult, list[str]]:
        """Return the current checkout plus safe, read-only branch/ref choices."""

        self._branches = None
        self._commits_by_branch.clear()
        status, result = self.inspect_status()
        branches = self.available_branches()
        return status, result, branches

    def available_branches(self) -> list[str]:
        if self._branches is not None:
            return self._branches
        output = release_manager.Git(self.root).output("for-each-ref", "--format=%(refname:short)", "refs/heads")
        self._branches = [line.strip() for line in output.splitlines() if line.strip()]
        return self._branches

    def commits_for_branch(self, branch: str) -> list[tuple[str, str]]:
        if branch not in self.available_branches():
            raise ValueError("Choose a branch from the repository list")
        if branch in self._commits_by_branch:
            return self._commits_by_branch[branch]
        output = release_manager.Git(self.root).output("log", "-n", "50", "--format=%H%x09%s", branch)
        commits: list[tuple[str, str]] = []
        for line in output.splitlines():
            commit, separator, subject = line.partition("\t")
            if separator and len(commit) == 40:
                commits.append((commit, subject))
        self._commits_by_branch[branch] = commits
        return commits

    def inspect_reference(self, branch: str, commit: str) -> tuple[RepositoryStatus, OperationResult]:
        if branch not in self.available_branches() or commit not in {
            item[0] for item in self.commits_for_branch(branch)
        }:
            raise ValueError("Choose a commit listed for the selected branch")
        current, _result = self.inspect_status()
        version = self._version_at(release_manager.Git(self.root), commit)
        selected_is_checkout = branch == current.branch and commit == current.commit
        raw = {
            "repository": current.raw["repository"],
            "selected": {"branch": branch, "commit": commit, "version": version},
            "ready_to_package": bool(selected_is_checkout and current.clean),
            "selection_matches_checkout": selected_is_checkout,
        }
        raw["readiness"] = "READY" if raw["ready_to_package"] else "NOT_READY"
        status = RepositoryStatus(branch, commit, version, current.clean, bool(raw["ready_to_package"]), raw)
        summary = (
            "Selected checkout is ready"
            if status.ready
            else "Selected reference is read-only; package the checked-out HEAD"
        )
        return status, result_from_payload("reference inspection", raw, summary=summary)

    @staticmethod
    def _version_at(git: Any, commit: str) -> str | None:
        try:
            version_payload = json.loads(git.output("show", f"{commit}:app/atlas/version.json"))
            return str(version_payload.get("version") or "") or None
        except (json.JSONDecodeError, ValueError):
            return None

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

    def package_software(self, version: str) -> OperationResult:
        """Run the existing active packager without pushing or publishing a release."""

        payload = release_manager.package(
            self.root,
            bump=None,
            explicit_version=version,
            dry_run=False,
            no_push=True,
            no_publish=True,
            allow_dirty=False,
            approved_exception=None,
        )
        return result_from_payload("package software", _plain(payload), summary="Software package completed")

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

    @property
    def default_config_path(self) -> Path:
        return self.root / "config" / "deployment_server.local.json"

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

    def update_server(self, config_path: Path, version: str, selected_commit: str) -> OperationResult:
        """Verify a published artifact matches source, then use the backend's stage/activate gates."""

        inspection = self.inspect_release(version)
        release = inspection.raw.get("release", {})
        release_commit = str(release.get("commit_sha") or "") if isinstance(release, dict) else ""
        if release_commit.lower() != selected_commit.lower():
            raise ValueError(
                "The verified release artifact does not match the selected source commit; server update was not attempted"
            )
        release_dir = Path(str(inspection.raw["release_dir"]))
        config = server_updater.load_server_config(config_path.resolve())
        staged = active_deployment.stage_release(self.root, release_dir, inspection.raw["manifest"], config)
        if staged.state != "STAGED_VALIDATED":
            raise ValueError(f"Backend staging did not permit activation (state: {staged.state})")
        activated = active_deployment.helper_operation(self.root, config, "activate", staged.deployment_id)
        raw = {
            "state": activated.state,
            "deployment_id": activated.deployment_id,
            "receipt_path": str(activated.receipt_path),
            "selected_source": {"version": version, "commit": selected_commit},
            "release_verification": inspection.raw,
            "stage": _plain(staged),
            "activation": _plain(activated),
        }
        return result_from_payload(
            "update server", raw, summary="Server update completed through backend transaction gates"
        )

    def deployment_operation(self, config_path: Path, deployment_id: str, operation: str) -> OperationResult:
        receipt = active_deployment.helper_operation(
            self.root, server_updater.load_server_config(config_path.resolve()), operation, deployment_id
        )
        return result_from_payload(operation, _plain(receipt), summary=f"{operation.title()} request completed")
