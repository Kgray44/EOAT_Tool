"""Build and verify deterministic, static-only EOAT Atlas HTTP web bundles."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import re
from pathlib import Path

ALLOWED_TOP_LEVEL = {"bundle.json", "manifest.json", "nginx", "web"}
FORBIDDEN_CONTENT = ("EOAT_API_DEVICE_TOKEN", "X-EOAT-Device-Token", "mysql://")
DEVELOPMENT_API_URL = re.compile(rb"https?://(?:localhost|127[.]0[.]0[.]1)(?::[0-9]+)?/api(?:/|[^A-Za-z0-9_-])", re.I)
FORBIDDEN_PATH_PARTS = {"node_modules"}
FORBIDDEN_SUFFIXES = {".map", ".env", ".pem", ".key"}


class BundleError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(items: dict[str, str]) -> str:
    payload = json.dumps(items, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _files(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or (path.exists() and not (path.is_file() or path.is_dir())):
            raise BundleError(f"bundle contains unsafe member: {path}")
        if path.is_file() and path.name not in {"manifest.json", "bundle.json"}:
            relative = path.relative_to(root).as_posix()
            if relative.split("/", 1)[0] not in {"nginx", "web"}:
                raise BundleError(f"unexpected bundle member: {relative}")
            if any(part in FORBIDDEN_PATH_PARTS for part in Path(relative).parts) or path.suffix.lower() in FORBIDDEN_SUFFIXES:
                raise BundleError(f"forbidden bundle path: {relative}")
            content = path.read_bytes()
            # The NGINX template necessarily names its server-only variable;
            # only browser-served files are prohibited from carrying secrets.
            if relative.startswith("web/") and (any(token.encode("ascii") in content for token in FORBIDDEN_CONTENT) or DEVELOPMENT_API_URL.search(content)):
                raise BundleError(f"forbidden bundle content: {relative}")
            result[relative] = sha256(path)
    return result


def _assert_bundle_tree(root: Path) -> None:
    """Reject every member not explicitly described by the bundle contract."""
    expected_directories = {"nginx", "web"}
    actual_directories = {item.name for item in root.iterdir() if item.is_dir() and not item.is_symlink()}
    actual_files = {item.name for item in root.iterdir() if item.is_file() and not item.is_symlink()}
    if actual_directories != expected_directories or actual_files != {"bundle.json", "manifest.json"}:
        raise BundleError("bundle has unexpected top-level members")
    for item in root.rglob("*"):
        if item.is_symlink() or not (item.is_file() or item.is_dir()):
            raise BundleError(f"bundle contains unsafe member: {item}")
    template = root / "nginx" / "eoat-atlas-http-web.conf.template"
    if set((root / "nginx").iterdir()) != {template}:
        raise BundleError("bundle nginx directory has unexpected members")


def create_bundle(static_root: Path, template: Path, destination: Path, *, release_id: str, app_version: str) -> dict[str, str]:
    if destination.exists():
        raise BundleError("bundle destination must not already exist")
    if not (static_root / "index.html").is_file():
        raise BundleError("compiled frontend has no index.html")
    destination.mkdir(parents=True, mode=0o750)
    (destination / "web").mkdir()
    shutil.copytree(static_root, destination / "web", dirs_exist_ok=True, symlinks=False)
    nginx = destination / "nginx"
    nginx.mkdir()
    shutil.copyfile(template, nginx / "eoat-atlas-http-web.conf.template")
    manifest = _files(destination)
    (destination / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    metadata = {
        "schema": 1,
        "release_id": release_id,
        "application_version": app_version,
        "api_upstream": "127.0.0.1:8765",
        "server_name": "eoat-atlas.gwplastics.com",
        "content_sha256": _canonical(manifest),
    }
    (destination / "bundle.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"bundle_sha256": _canonical({**manifest, "bundle.json": sha256(destination / "bundle.json"), "manifest.json": sha256(destination / "manifest.json")}), "content_sha256": metadata["content_sha256"]}


def verify_bundle(root: Path, expected_bundle_sha256: str | None = None) -> dict[str, object]:
    if not root.is_dir():
        raise BundleError("bundle root is not a directory")
    _assert_bundle_tree(root)
    for required in (root / "bundle.json", root / "manifest.json", root / "nginx" / "eoat-atlas-http-web.conf.template", root / "web" / "index.html"):
        if not required.is_file():
            raise BundleError(f"bundle is missing {required.name}")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest != _files(root):
        raise BundleError("bundle file manifest does not match")
    metadata = json.loads((root / "bundle.json").read_text(encoding="utf-8"))
    if metadata.get("content_sha256") != _canonical(manifest):
        raise BundleError("bundle content identity does not match")
    bundle_sha = _canonical({**manifest, "bundle.json": sha256(root / "bundle.json"), "manifest.json": sha256(root / "manifest.json")})
    if expected_bundle_sha256 and bundle_sha != expected_bundle_sha256:
        raise BundleError("bundle SHA-256 does not match approved value")
    return {"metadata": metadata, "bundle_sha256": bundle_sha, "manifest": manifest}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--static-root", type=Path, required=True)
    build.add_argument("--template", type=Path, required=True)
    build.add_argument("--destination", type=Path, required=True)
    build.add_argument("--release-id", required=True)
    build.add_argument("--application-version", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--expected-sha256")
    args = parser.parse_args()
    result = create_bundle(args.static_root, args.template, args.destination, release_id=args.release_id, app_version=args.application_version) if args.command == "build" else verify_bundle(args.bundle, args.expected_sha256)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
