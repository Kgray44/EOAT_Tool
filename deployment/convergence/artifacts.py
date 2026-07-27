"""Reusable immutable artifact helpers for disposable release candidates."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from deployment.common import DeploymentError, sha256_file, utc_text, write_json_atomic


@dataclass(frozen=True)
class BuiltArtifact:
    path: Path
    locator: str
    sha256: str
    size_bytes: int
    manifest_path: Path | None = None


def candidate_locator(candidate_root: Path, path: Path) -> str:
    """Return a portable, candidate-relative locator or fail closed."""

    try:
        return path.resolve().relative_to(candidate_root.resolve()).as_posix()
    except ValueError as exc:
        raise DeploymentError("artifact is outside immutable candidate storage") from exc


def verify_source_bundle(
    bundle: Path, *, candidate_root: Path, commit: str, tree: str, base_commit: str, repository: Path
) -> BuiltArtifact:
    """Independently prove that a retained bundle resolves its exact source."""

    if not bundle.is_file() or len(sha256_file(bundle)) != 64:
        raise DeploymentError("candidate source bundle is missing or unreadable")
    with tempfile.TemporaryDirectory(prefix="eoat-bundle-verify-") as temporary:
        probe = Path(temporary) / "probe"
        init = subprocess.run(["git", "clone", "--quiet", "--shared", str(repository), str(probe)], text=True, capture_output=True, check=False)
        if init.returncode:
            raise DeploymentError("could not create isolated Git bundle verifier")
        verified = subprocess.run(["git", "bundle", "verify", str(bundle)], cwd=probe, text=True, capture_output=True, check=False)
        if verified.returncode:
            raise DeploymentError("candidate source bundle failed git bundle verification")
        fetched = subprocess.run(["git", "fetch", "--quiet", str(bundle), commit], cwd=probe, text=True, capture_output=True, check=False)
        if fetched.returncode:
            raise DeploymentError("candidate source bundle cannot fetch its declared commit")
        resolved = subprocess.run(["git", "rev-parse", "FETCH_HEAD"], cwd=probe, text=True, capture_output=True, check=False)
        resolved_tree = subprocess.run(["git", "rev-parse", f"{commit}^{{tree}}"], cwd=probe, text=True, capture_output=True, check=False)
        ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", base_commit, commit], cwd=probe, text=True, capture_output=True, check=False)
        if resolved.returncode or resolved.stdout.strip() != commit or resolved_tree.returncode or resolved_tree.stdout.strip() != tree or ancestry.returncode:
            raise DeploymentError("candidate source bundle does not prove declared commit, tree, and ancestry")
    receipt = candidate_root / "receipts" / "source-bundle-verification.json"
    write_json_atomic(receipt, {
        "schema_version": 1,
        "candidate_commit": commit,
        "candidate_tree": tree,
        "base_commit": base_commit,
        "bundle_locator": candidate_locator(candidate_root, bundle),
        "bundle_sha256": sha256_file(bundle),
        "verified_at_utc": utc_text(),
        "status": "PASS",
    })
    return BuiltArtifact(bundle, candidate_locator(candidate_root, bundle), sha256_file(bundle), bundle.stat().st_size, receipt)


def copy_release_notes(source: Path, *, candidate_root: Path, version: str) -> BuiltArtifact:
    """Copy governed release notes without retaining machine-specific paths."""

    if not source.is_file():
        raise DeploymentError("governed release notes are unavailable")
    content = source.read_text(encoding="utf-8")
    if version not in content:
        raise DeploymentError("governed release notes do not identify the candidate product version")
    forbidden = ("C:\\Users\\", "\\\\", "password=", "token=", "production deployment complete")
    if any(value.casefold() in content.casefold() for value in forbidden):
        raise DeploymentError("release notes contain private, secret, or production-claim content")
    destination = candidate_root / "core" / "release-notes" / f"EOAT-Atlas-{version}-release-notes.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_text(encoding="utf-8") != content:
        raise DeploymentError("refusing to overwrite immutable candidate release notes")
    if not destination.exists():
        shutil.copyfile(source, destination)
    return BuiltArtifact(destination, candidate_locator(candidate_root, destination), sha256_file(destination), destination.stat().st_size)


def build_web_package(static_root: Path, destination: Path) -> BuiltArtifact:
    """Package a built static site deterministically and validate its manifest."""

    index = static_root / "index.html"
    manifest = static_root / "web-static.manifest.json"
    if not index.is_file() or not manifest.is_file():
        raise DeploymentError("web static output must contain index.html and web-static.manifest.json")
    payload = _read_manifest(manifest)
    _validate_static_files(static_root, payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in static_root.rglob("*") if item.is_file()):
            relative = path.relative_to(static_root).as_posix()
            if _unsafe(relative):
                raise DeploymentError(f"unsafe web artifact path: {relative}")
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    validate_web_package(destination)
    return BuiltArtifact(destination, destination.name, sha256_file(destination), destination.stat().st_size, manifest)


def validate_web_package(archive_path: Path) -> None:
    seen: set[str] = set()
    with zipfile.ZipFile(archive_path) as archive:
        names = [entry.filename for entry in archive.infolist() if not entry.is_dir()]
        if "index.html" not in names or "web-static.manifest.json" not in names:
            raise DeploymentError("web package is missing required entry point or manifest")
        for name in names:
            if _unsafe(name) or name.casefold() in seen:
                raise DeploymentError(f"unsafe or duplicate web package path: {name}")
            seen.add(name.casefold())
            if name.startswith((".env", "node_modules/", ".pnpm-store/")):
                raise DeploymentError(f"prohibited web package member: {name}")


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentError("web static manifest is malformed") from exc
    if not isinstance(value, dict):
        raise DeploymentError("web static manifest must be an object")
    return value


def _validate_static_files(root: Path, payload: dict[str, object]) -> None:
    # ``deployment.web_release.build_web_static`` deliberately writes the
    # compact ``{relative_path: sha256}`` manifest consumed by deployment.
    # Accept that governed representation rather than inventing a second web
    # manifest schema inside the release train.
    files = payload.get("files")
    expected: set[str] = set()
    if isinstance(files, list):
        entries = ((str(raw.get("path") or ""), str(raw.get("sha256") or "")) for raw in files if isinstance(raw, dict))
    else:
        entries = ((str(path), str(digest)) for path, digest in payload.items())
    for relative, digest in entries:
        path = root / relative
        if _unsafe(relative) or not path.is_file() or len(digest) != 64:
            raise DeploymentError("web static manifest file identity is invalid")
        if sha256_file(path) != digest:
            raise DeploymentError("web static file hash does not match manifest")
        expected.add(relative)
    if not expected:
        raise DeploymentError("web static manifest has no file inventory")
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    # The manifest intentionally does not hash itself to avoid a circular
    # digest.  Its own integrity is covered by the immutable web archive.
    actual.discard("web-static.manifest.json")
    if actual != expected:
        raise DeploymentError("web static manifest does not exactly describe the package")


def _unsafe(name: str) -> bool:
    path = PurePosixPath(name)
    return not name or path.is_absolute() or ".." in path.parts or "\\" in name
