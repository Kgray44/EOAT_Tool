"""Build the authoritative EOAT Atlas launcher with immutable provenance."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "Git provenance command failed")
    return completed.stdout.strip()


def main() -> int:
    if _git("status", "--porcelain") and os.getenv("EOAT_ATLAS_ALLOW_DIRTY_BUILD") != "1":
        print("ERROR: refusing launcher build from a dirty tracked tree", file=sys.stderr)
        return 1
    completed = subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(ROOT / "dist" / "launcher"),
        "--workpath", str(ROOT / "build" / "launcher"),
        str(ROOT / "EOAT_Atlas_Launcher.spec"),
    ], cwd=ROOT, check=False)
    if completed.returncode:
        return completed.returncode
    executable = ROOT / "dist" / "launcher" / "EOAT Atlas Launcher.exe"
    if not executable.is_file():
        print("ERROR: expected authoritative launcher executable was not built", file=sys.stderr)
        return 1
    version = json.loads((ROOT / "app" / "atlas" / "version.json").read_text(encoding="utf-8"))
    launcher = json.loads((ROOT / "launcher" / "launcher_version.json").read_text(encoding="utf-8"))
    metadata = {
        "schema_version": 1,
        "component_kind": "launcher",
        "component_version": str(launcher["launcher_version"]),
        "product_version": str(version["version"]),
        "release_id": os.getenv("EOAT_RELEASE_RELEASE_ID", ""),
        "build_id": os.getenv("EOAT_RELEASE_BUILD_ID", ""),
        "candidate_id": os.getenv("EOAT_RELEASE_CANDIDATE_ID", ""),
        "source_commit": os.getenv("EOAT_RELEASE_SOURCE_COMMIT", _git("rev-parse", "HEAD")),
        "source_tree": os.getenv("EOAT_RELEASE_SOURCE_TREE", _git("rev-parse", "HEAD^{tree}")),
        "serviced_product_release_policy": "signed-release-set-only",
        "artifact_sha256": _sha256(executable),
    }
    metadata_path = executable.with_name("launcher_release_metadata.json")
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = [path for path in sorted(executable.parent.rglob("*")) if path.is_file()]
    manifest = {
        "manifest_schema_version": 1,
        "metadata": metadata,
        "files": [{"path": path.relative_to(executable.parent).as_posix(), "size": path.stat().st_size, "sha256": _sha256(path)} for path in files],
    }
    executable.with_name("launcher_package_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
