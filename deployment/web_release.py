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
from datetime import datetime, timezone
from pathlib import Path

from scripts.release.build_server_release import generate_release_metadata

from .common import DeploymentError

UNC_PATH = re.compile(rb"\\\\\\\\[A-Za-z0-9][A-Za-z0-9._-]{0,62}\\\\")


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
    with tempfile.TemporaryDirectory(
        prefix="eoat-web-release-",
        dir=root.parent,
        ignore_cleanup_errors=True,
    ) as temporary:
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
        for script in ("format:check", "lint", "typecheck", "test", "test:e2e", "build"):
            _run(web, pnpm, "run", script)
        dist = web / "dist"
        index = dist / "index.html"
        if not index.is_file() or not any((dist / "assets").glob("*")):
            raise DeploymentError("web production build is incomplete")
        files = [path for path in sorted(dist.rglob("*")) if path.is_file()]
        if any(path.suffix == ".map" for path in files):
            raise DeploymentError("web production build contains source maps")
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
    manifest = {path.relative_to(destination).as_posix(): _sha256(path) for path in sorted(destination.rglob("*")) if path.is_file()}
    (destination / "web-static.manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"files": manifest, "manifest_sha256": _sha256(destination / "web-static.manifest.json")}
