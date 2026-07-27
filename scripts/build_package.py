from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.release.build_server_release import generate_release_metadata

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "EOAT_Atlas.spec"


def _git(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "Git provenance command failed")
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _generated_build_metadata() -> Path:
    dirty = _git("status", "--porcelain")
    if dirty and os.getenv("EOAT_ATLAS_ALLOW_DIRTY_BUILD") != "1":
        raise RuntimeError("Refusing to package a dirty tracked tree; exact source provenance would be ambiguous.")
    commit = os.getenv("GITHUB_SHA") or _git("rev-parse", "HEAD")
    branch = os.getenv("GITHUB_REF_NAME") or _git("branch", "--show-current")
    timestamp = datetime.now(timezone.utc).replace(microsecond=0)
    run_id = os.getenv("GITHUB_RUN_ID") or f"local-{timestamp.strftime('%Y%m%dT%H%M%SZ')}"
    payload = generate_release_metadata(ROOT, commit, branch_name=branch, build_timestamp=timestamp)
    payload.update({
        "release_id": os.getenv("EOAT_RELEASE_RELEASE_ID", payload.get("release_id", "")),
        "build_id": os.getenv("EOAT_RELEASE_BUILD_ID", payload.get("build_id", "")),
        "commit": os.getenv("EOAT_RELEASE_SOURCE_COMMIT", payload.get("commit", "")),
        "ci_run_id": run_id,
        "build_run_id": run_id,
        "dirty_tree": False,
        "artifact_sha256": None,
        "candidate_id": os.getenv("EOAT_RELEASE_CANDIDATE_ID", ""),
        "source_tree": os.getenv("EOAT_RELEASE_SOURCE_TREE", ""),
    })
    destination = ROOT / "build" / "release_metadata.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def _finalize_build_metadata(metadata_path: Path) -> None:
    package = ROOT / "dist" / "EOAT Atlas"
    executable = package / "EOAT Atlas.exe"
    if not executable.is_file():
        raise RuntimeError(f"Packaged executable is missing: {executable}")
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["artifact_sha256"] = _sha256(executable)
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    metadata_path.write_text(serialized, encoding="utf-8")
    packaged = list(package.rglob("release_metadata.json"))
    if len(packaged) != 1:
        raise RuntimeError(f"Expected one packaged release_metadata.json, found {len(packaged)}")
    packaged[0].write_text(serialized, encoding="utf-8")


def _write_package_manifest(metadata_path: Path) -> None:
    package = ROOT / "dist" / "EOAT Atlas"
    files = [path for path in sorted(package.rglob("*")) if path.is_file()]
    payload = {
        "manifest_schema_version": 1,
        "build": json.loads(metadata_path.read_text(encoding="utf-8")),
        "files": [
            {"path": path.relative_to(package).as_posix(), "size": path.stat().st_size, "sha256": _sha256(path)}
            for path in files
        ],
    }
    (package / "package_manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    if importlib.util.find_spec("PyInstaller") is None:
        print("PyInstaller is not installed. Install it with: python -m pip install pyinstaller")
        return 1
    try:
        metadata = _generated_build_metadata()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: package provenance generation failed: {exc}", file=sys.stderr)
        return 1
    env = os.environ.copy()
    env["EOAT_ATLAS_BUILD_METADATA"] = str(metadata)
    completed = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC_PATH)],
        cwd=ROOT,
        env=env,
        shell=False,
    )
    if completed.returncode:
        return completed.returncode
    try:
        _finalize_build_metadata(metadata)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: package provenance finalization failed: {exc}", file=sys.stderr)
        return 1
    _write_package_manifest(metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
