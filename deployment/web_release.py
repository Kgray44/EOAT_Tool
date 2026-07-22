"""Deterministic, validation-first static web build for a server release."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from .common import DeploymentError


def _run(root: Path, *args: str) -> None:
    result = subprocess.run(list(args), cwd=root, text=True, capture_output=True, check=False)
    if result.returncode:
        raise DeploymentError(f"web release validation failed: {' '.join(args[:2])}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_web_static(root: Path, commit: str, destination: Path) -> dict[str, object]:
    """Build an exact committed web tree; Node is never included in the result."""
    npm = shutil.which("npm")
    if not npm:
        raise DeploymentError("npm is required to build the static web release")
    with tempfile.TemporaryDirectory(prefix="eoat-web-release-") as temporary:
        source = Path(temporary) / "source"
        source.mkdir()
        bundle = Path(temporary) / "source.tar"
        _run(root, "git", "archive", "--format=tar", f"--output={bundle}", commit)
        with tarfile.open(bundle) as archive:
            for member in archive.getmembers():
                target = (source / member.name).resolve()
                if not member.isfile() or not target.is_relative_to(source.resolve()):
                    raise DeploymentError("unsafe source member while preparing web release")
            archive.extractall(source, filter="data")
        web = source / "web"
        _run(web, npm, "ci")
        generated = web / "src" / "api" / "generated"
        before = {path.name: _sha256(path) for path in generated.glob("*") if path.is_file()}
        _run(web, npm, "run", "api:generate")
        after = {path.name: _sha256(path) for path in generated.glob("*") if path.is_file()}
        if before != after:
            raise DeploymentError("generated OpenAPI TypeScript contract is stale")
        for script in ("format:check", "lint", "typecheck", "test", "test:e2e", "build"):
            _run(web, npm, "run", script)
        dist = web / "dist"
        index = dist / "index.html"
        if not index.is_file() or not any((dist / "assets").glob("*")):
            raise DeploymentError("web production build is incomplete")
        files = [path for path in sorted(dist.rglob("*")) if path.is_file()]
        if any(path.suffix == ".map" for path in files):
            raise DeploymentError("web production build contains source maps")
        forbidden = (b"X-EOAT-Device-Token", b"EOAT_API_DEVICE_TOKEN", b"\\\\", b"mysql://")
        if any(token in path.read_bytes() for path in files for token in forbidden):
            raise DeploymentError("web production build contains a forbidden internal value")
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(dist, destination)
    manifest = {path.relative_to(destination).as_posix(): _sha256(path) for path in sorted(destination.rglob("*")) if path.is_file()}
    (destination / "web-static.manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"files": manifest, "manifest_sha256": _sha256(destination / "web-static.manifest.json")}
