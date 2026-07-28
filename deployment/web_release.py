"""Deterministic, validation-first static web build for a server release."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from scripts.release.build_server_release import generate_release_metadata

from .common import DeploymentError

UNC_PATH = re.compile(rb"\\\\\\\\[A-Za-z0-9][A-Za-z0-9._-]{0,62}\\\\")

_WEB_STAGING_PREFIX = "eoat-web-release-"
_WEB_STAGING_CLEANUP_ATTEMPTS = 5
_WEB_STAGING_CLEANUP_BACKOFF_SECONDS = 0.25
_WEB_STAGING_MAX_RETAINED_DIRECTORIES = 3
_WEB_STAGING_MAX_RETAINED_BYTES = 3 * 1024 * 1024 * 1024
_TRANSIENT_WINDOWS_CLEANUP_ERRORS = frozenset({5, 32, 145})


def _is_governed_staging_directory(parent: Path, candidate: Path) -> bool:
    """Return true only for a direct, non-link child owned by this builder."""
    try:
        return (
            candidate.parent.resolve() == parent.resolve()
            and candidate.is_dir()
            and not candidate.is_symlink()
            and candidate.name.startswith(_WEB_STAGING_PREFIX)
        )
    except OSError:
        return False


def _is_transient_cleanup_error(error: OSError) -> bool:
    return (getattr(error, "winerror", None) or error.errno) in _TRANSIENT_WINDOWS_CLEANUP_ERRORS


def _cleanup_web_staging_with_retry(
    parent: Path,
    staging: Path,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Remove one builder-owned staging tree with bounded Windows lock retries."""
    if not _is_governed_staging_directory(parent, staging):
        raise DeploymentError("refusing unsafe web staging cleanup target")
    last_error: OSError | None = None
    for attempt in range(1, _WEB_STAGING_CLEANUP_ATTEMPTS + 1):
        try:
            shutil.rmtree(staging)
            return {"status": "REMOVED", "attempts": attempt}
        except FileNotFoundError:
            return {"status": "REMOVED", "attempts": attempt}
        except OSError as error:
            last_error = error
            if not _is_transient_cleanup_error(error) or attempt == _WEB_STAGING_CLEANUP_ATTEMPTS:
                break
            sleep(_WEB_STAGING_CLEANUP_BACKOFF_SECONDS * attempt)
    category = "TRANSIENT_LOCK_EXHAUSTED" if last_error and _is_transient_cleanup_error(last_error) else "CLEANUP_FAILED"
    return {
        "status": "RETAINED",
        "attempts": _WEB_STAGING_CLEANUP_ATTEMPTS,
        "category": category,
        "diagnostic": "web staging cleanup retained one governed disposable directory; reconciliation is required",
    }


def _governed_staging_tree_size(directory: Path) -> int:
    total = 0
    for current, directories, files in os.walk(directory, followlinks=False):
        directories[:] = [entry for entry in directories if not (Path(current) / entry).is_symlink()]
        for entry in files:
            path = Path(current) / entry
            if not path.is_symlink():
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
    return total


def _reconcile_stale_web_staging(parent: Path, *, active: Path | None = None) -> None:
    """Bound retention without scanning or deleting outside the governed parent."""
    parent.mkdir(parents=True, exist_ok=True)
    candidates = [
        path for path in parent.iterdir() if _is_governed_staging_directory(parent, path) and path != active
    ]
    for candidate in sorted(candidates, key=lambda path: path.stat().st_mtime if path.exists() else 0):
        _cleanup_web_staging_with_retry(parent, candidate)
    retained = [path for path in parent.iterdir() if _is_governed_staging_directory(parent, path) and path != active]
    retained_size = sum(_governed_staging_tree_size(path) for path in retained)
    # Reserve one slot for the build that is about to create its own staging
    # tree.  A blocked cleanup must therefore stop before crossing the cap.
    if len(retained) >= _WEB_STAGING_MAX_RETAINED_DIRECTORIES or retained_size > _WEB_STAGING_MAX_RETAINED_BYTES:
        raise DeploymentError("web staging retention limit blocks another build; run governed staging reconciliation")


def _run(root: Path, *args: str) -> None:
    result = subprocess.run(list(args), cwd=root, text=True, capture_output=True, check=False)
    if result.returncode:
        raw = ((result.stdout or "") + "\n" + (result.stderr or "")).strip().replace("\r", " ").replace("\n", " ")
        detail = raw if len(raw) <= 3800 else raw[:1900] + " ... " + raw[-1900:]
        raise DeploymentError(f"web release validation failed: {' '.join(args[:2])}: {detail or 'no diagnostic output'}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _frontend_release_identity(source: Path, web: Path, dist: Path, commit: str) -> None:
    """Write build facts into static metadata without making them source truth."""
    descriptor = dist / "frontend-release.json"
    try:
        payload = json.loads(descriptor.read_text(encoding="utf-8")) if descriptor.is_file() else {}
    except json.JSONDecodeError as exc:
        raise DeploymentError("frontend release descriptor is invalid") from exc
    version = json.loads((source / "app" / "atlas" / "version.json").read_text(encoding="utf-8")).get("version")
    node = subprocess.run(["node", "--version"], text=True, capture_output=True, check=False)
    if node.returncode:
        raise DeploymentError("cannot determine Node version for frontend release")
    payload.update(
        {
            "schema": 1,
            "ui_generation": payload.get("ui_generation", "legacy"),
            "source_commit": commit,
            "application_version": version,
            "node_version": node.stdout.strip(),
            "package_lock_sha256": _sha256(web / "package-lock.json"),
            "build_command": "pnpm run build",
        }
    )
    descriptor.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _commit_timestamp(root: Path, commit: str) -> datetime:
    result = subprocess.run(
        ["git", "show", "-s", "--format=%cI", commit], cwd=root, text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise DeploymentError("cannot determine the source commit timestamp for the web release")
    try:
        return datetime.fromisoformat(result.stdout.strip().replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise DeploymentError("source commit timestamp is invalid for the web release") from exc


def _normalize_generated_line_endings(directory: Path) -> None:
    """Keep deterministic generated-contract checks independent of Windows EOLs."""
    for path in directory.glob("*"):
        if path.is_file():
            content = path.read_bytes()
            normalized = content.replace(b"\r\n", b"\n")
            if normalized != content:
                path.write_bytes(normalized)


def _normalize_web_source_line_endings(directory: Path) -> None:
    """Normalize the disposable archive before deterministic web validation."""
    for path in directory.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            normalized = content.replace(b"\r\n", b"\n")
            if normalized != content:
                path.write_bytes(normalized)


def build_web_static(root: Path, commit: str, destination: Path) -> dict[str, object]:
    """Build an exact committed web tree; Node is never included in the result."""
    pnpm = shutil.which("pnpm")
    if not pnpm and os.environ.get("PNPM_HOME"):
        candidate = Path(os.environ["PNPM_HOME"]) / ("pnpm.cmd" if os.name == "nt" else "pnpm")
        if candidate.is_file():
            pnpm = str(candidate)
    if not pnpm:
        raise DeploymentError("pnpm 11.9.0 is required to build the static web release")
    # Node's package manager can briefly retain Windows handles in the
    # disposable archive.  A failed cleanup must not invalidate a completed
    # deterministic artifact or touch the source worktree.
    # Keep the disposable web tree beside the isolated candidate checkout.
    # Vitest/Vite resolve their virtual ``/@vite/env`` module through URL-like
    # paths.  Windows can render the default user temporary root with an 8.3
    # segment (for example ``RUNNER~1``), which Vite then fails to resolve.
    # Candidate staging is an ignored, candidate-local workspace path and is
    # therefore both isolated from the canonical checkout and safe for Vite.
    # Candidate roots are intentionally nested beneath durable receipt
    # storage.  Keep this disposable archive root short on Windows so deeply
    # nested, committed static fixtures cannot exceed the Win32 path limit.
    # It remains adjacent to (and isolated from) the candidate checkout.
    temporary_parent = root.parent / "w"
    temporary_parent.mkdir(parents=True, exist_ok=True)
    _reconcile_stale_web_staging(temporary_parent)
    temporary = Path(tempfile.mkdtemp(prefix=_WEB_STAGING_PREFIX, dir=temporary_parent))
    cleanup: dict[str, object] = {}
    try:
        source = Path(temporary) / "source"
        source.mkdir()
        bundle = Path(temporary) / "source.tar"
        _run(root, "git", "archive", "--format=tar", f"--output={bundle}", commit)
        with tarfile.open(bundle) as archive:
            for member in archive.getmembers():
                target = (source / member.name).resolve()
                if not target.is_relative_to(source.resolve()):
                    raise DeploymentError("unsafe source member while preparing web release")
                # ``git archive`` emits directory entries as well as ordinary
                # files.  Directories are safe to extract after their path is
                # checked; links and special members are never accepted.
                if not (member.isdir() or member.isfile()):
                    raise DeploymentError("unsafe source member while preparing web release")
            archive.extractall(source, filter="data")
        # The archived source is deliberately not a Git checkout.  The API
        # contract exporter imports version metadata while loading FastAPI, so
        # supply generated metadata for this exact commit only in the
        # disposable build tree.
        metadata = generate_release_metadata(
            root,
            commit,
            branch_name="web-release-build",
            build_timestamp=_commit_timestamp(root, commit),
        )
        (source / "release_metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        web = source / "web"
        _normalize_web_source_line_endings(web)
        package = json.loads((web / "package.json").read_text(encoding="utf-8"))
        if package.get("packageManager") != "pnpm@11.9.0":
            raise DeploymentError("web package manager must be pinned to pnpm@11.9.0")
        version = subprocess.run([pnpm, "--version"], text=True, capture_output=True, check=False)
        if version.returncode or version.stdout.strip() != "11.9.0":
            raise DeploymentError("the active pnpm version is not the pinned 11.9.0 release")
        _run(web, pnpm, "install", "--frozen-lockfile")
        generated = web / "src" / "api" / "generated"
        _normalize_generated_line_endings(generated)
        before = {path.name: _sha256(path) for path in generated.glob("*") if path.is_file()}
        _run(web, pnpm, "run", "api:generate")
        _normalize_generated_line_endings(generated)
        after = {path.name: _sha256(path) for path in generated.glob("*") if path.is_file()}
        if before != after:
            raise DeploymentError("generated OpenAPI TypeScript contract is stale")
        # A release package is built from a Git archive, which intentionally
        # has no mutable E2E fixture/runtime context.  Browser acceptance is
        # a separate required final-integration gate against a disposable
        # server; keeping it out of this hermetic builder avoids conflating a
        # fixture-only failure with static-package validity.
        scripts = ["format:check", "lint", "typecheck", "test", "build"]
        frontend_release = web / "public" / "frontend-release.json"
        if frontend_release.is_file():
            generation = json.loads(frontend_release.read_text(encoding="utf-8")).get("ui_generation")
            if generation == "mirrorline":
                scripts.insert(4, "theme:check")
        for script in scripts:
            _run(web, pnpm, "run", script)
        dist = web / "dist"
        index = dist / "index.html"
        if not index.is_file() or not any((dist / "assets").glob("*")):
            raise DeploymentError("web production build is incomplete")
        files = [path for path in sorted(dist.rglob("*")) if path.is_file()]
        if any(path.suffix == ".map" for path in files):
            raise DeploymentError("web production build contains source maps")
        _frontend_release_identity(source, web, dist, commit)
        files = [path for path in sorted(dist.rglob("*")) if path.is_file()]
        forbidden = (b"X-EOAT-Device-Token", b"EOAT_API_DEVICE_TOKEN", b"mysql://")
        if any(token in path.read_bytes() for path in files for token in forbidden) or any(
            UNC_PATH.search(path.read_bytes()) for path in files
        ):
            raise DeploymentError("web production build contains a forbidden internal value")
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(dist, destination)
        # Release identity is a separately cache-controlled static document.
        # It is generated from the same exact source commit as the bundle and
        # lets the browser compare the web bytes with /release-status before
        # normal API operations begin.
        identity = {
            "product_version": str(metadata.get("app_version") or metadata.get("application_version") or metadata.get("version") or ""),
            "release_id": str(metadata.get("release_id") or ""),
            "build_id": str(metadata.get("build_id") or ""),
            "candidate_id": str(metadata.get("candidate_id") or "") or None,
            "source_commit": str(metadata.get("source_git_commit") or metadata.get("source_commit") or ""),
            "source_tree": str(metadata.get("source_tree") or "") or None,
            "release_set_digest": str(metadata.get("release_set_digest") or "") or None,
        }
        if not all(identity[key] for key in ("product_version", "release_id", "build_id", "source_commit")):
            raise DeploymentError("exact web build metadata lacks a safe release identity")
        (destination / "release_identity.json").write_text(
            json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest = {
            path.relative_to(destination).as_posix(): _sha256(path)
            for path in sorted(destination.rglob("*"))
            if path.is_file()
        }
        (destination / "web-static.manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        result = {"files": manifest, "manifest_sha256": _sha256(destination / "web-static.manifest.json")}
    finally:
        # Do not replace the original build exception with a cleanup error.
        # A successful package may retain only its exact governed staging tree,
        # with a bounded redacted receipt for the next build to reconcile.
        cleanup = _cleanup_web_staging_with_retry(temporary_parent, temporary)
    if cleanup.get("status") == "RETAINED":
        result["staging_cleanup"] = cleanup
    return result
