"""Build real Windows packages and export an identity-bound attachment bundle.

This script is intentionally CI/developer-only. It accepts a retained unsigned
candidate receipt, builds from the checked-out exact commit, and emits no
production manifest, tag, or signing key.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _zip_tree(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in source.rglob("*") if item.is_file()):
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _identity(receipt: dict[str, Any]) -> dict[str, str]:
    working = receipt.get("working_release_set") or {}
    identity = working.get("identity") or {}
    result = {
        "candidate_id": str(receipt.get("candidate_id") or ""),
        "product_version": str(receipt.get("version") or ""),
        "release_id": str(identity.get("release_id") or ""),
        "build_id": str(identity.get("build_id") or ""),
        "source_commit": str(receipt.get("candidate_commit") or ""),
        "source_tree": str(receipt.get("candidate_tree") or ""),
    }
    if not all(result.values()):
        raise ValueError("candidate receipt does not provide complete schema-2 identity")
    return result


def _run(command: list[str], *, env: dict[str, str]) -> None:
    result = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if result.returncode:
        raise RuntimeError("Windows package build or smoke command failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a real EOAT Atlas Windows attachment bundle")
    parser.add_argument("--candidate-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = json.loads(args.candidate_receipt.read_text(encoding="utf-8"))
    identity = _identity(receipt)
    actual_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    actual_tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    if (actual_commit, actual_tree) != (identity["source_commit"], identity["source_tree"]):
        raise RuntimeError("Windows build checkout does not match the candidate source commit and tree")
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError("refusing to overwrite an immutable attachment output")
    output.mkdir(parents=True)
    env = os.environ.copy()
    env.update({
        "EOAT_RELEASE_CANDIDATE_ID": identity["candidate_id"], "EOAT_RELEASE_PRODUCT_VERSION": identity["product_version"],
        "EOAT_RELEASE_RELEASE_ID": identity["release_id"], "EOAT_RELEASE_BUILD_ID": identity["build_id"],
        "EOAT_RELEASE_SOURCE_COMMIT": identity["source_commit"], "EOAT_RELEASE_SOURCE_TREE": identity["source_tree"],
    })
    _run([sys.executable, "scripts/build_package.py"], env=env)
    desktop_dist = ROOT / "dist" / "EOAT Atlas"
    desktop_exe = desktop_dist / "EOAT Atlas.exe"
    desktop_zip = output / "desktop" / "EOAT-Atlas-desktop.zip"
    desktop_zip.parent.mkdir(parents=True)
    _zip_tree(desktop_dist, desktop_zip)
    env["EOAT_RELEASE_PACKAGE_SHA256"] = _sha256(desktop_zip)
    _run([str(desktop_exe), "--smoke-test", "--smoke-receipt", str(output / "desktop" / "smoke.json")], env=env)
    _copy(desktop_dist / "release_metadata.json", output / "desktop" / "release_metadata.json")
    _copy(desktop_dist / "package_manifest.json", output / "desktop" / "package_manifest.json")
    desktop_update = {"schema_version": 1, **identity, "component_kind": "desktop_update_manifest", "package_locator": "desktop/EOAT-Atlas-desktop.zip", "size_bytes": desktop_zip.stat().st_size, "sha256": _sha256(desktop_zip), "release_channel": "candidate"}
    (output / "desktop" / "update-manifest.json").write_text(json.dumps(desktop_update, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    _run([sys.executable, "scripts/build_launcher.py"], env=env)
    launcher_dist = ROOT / "dist" / "launcher"
    launcher_exe = launcher_dist / "EOAT Atlas Launcher.exe"
    launcher_zip = output / "launcher" / "EOAT-Atlas-launcher.zip"
    launcher_zip.parent.mkdir(parents=True)
    _zip_tree(launcher_dist, launcher_zip)
    env["EOAT_RELEASE_PACKAGE_SHA256"] = _sha256(launcher_zip)
    _run([str(launcher_exe), "--smoke-test", "--smoke-receipt", str(output / "launcher" / "smoke.json")], env=env)
    _copy(launcher_dist / "launcher_release_metadata.json", output / "launcher" / "release_metadata.json")
    _copy(launcher_dist / "launcher_package_manifest.json", output / "launcher" / "package_manifest.json")
    launcher_update = {"schema_version": 1, **identity, "component_kind": "launcher_update_manifest", "package_locator": "launcher/EOAT-Atlas-launcher.zip", "size_bytes": launcher_zip.stat().st_size, "sha256": _sha256(launcher_zip), "release_channel": "candidate"}
    (output / "launcher" / "update-manifest.json").write_text(json.dumps(launcher_update, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def component(kind: str, artifact: Path, *, metadata: str = "", package_manifest: str = "", smoke: str = "") -> dict[str, Any]:
        return {"kind": kind, "artifact": artifact.relative_to(output).as_posix(), "sha256": _sha256(artifact), "size_bytes": artifact.stat().st_size, "metadata": metadata, "package_manifest": package_manifest, "smoke_receipt": smoke, "target_locator": f"platform/windows/{kind}/{artifact.name}"}

    manifest = {
        "schema_version": 1, **identity, "platform": "windows", "workflow": {"run_id": os.getenv("GITHUB_RUN_ID", ""), "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", ""), "sha": os.getenv("GITHUB_SHA", "")},
        "components": [
            component("desktop", desktop_zip, metadata="desktop/release_metadata.json", package_manifest="desktop/package_manifest.json", smoke="desktop/smoke.json"),
            component("desktop_update_manifest", output / "desktop" / "update-manifest.json"),
            component("launcher", launcher_zip, metadata="launcher/release_metadata.json", package_manifest="launcher/package_manifest.json", smoke="launcher/smoke.json"),
            component("launcher_update_manifest", output / "launcher" / "update-manifest.json"),
        ],
    }
    (output / "attachment-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
