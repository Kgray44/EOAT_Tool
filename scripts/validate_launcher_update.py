from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release_tools.launcher import APP_EXE, update_and_launch


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("deployment_root", type=Path)
    parser.add_argument("local_root", type=Path)
    args = parser.parse_args()
    current = args.local_root / "current.json"
    state = json.loads(current.read_text(encoding="utf-8"))
    if state["version"] != "0.9.0":
        raise AssertionError("Packaged launcher did not install 0.9.0")
    before = current.stat().st_mtime_ns
    launches: list[Path] = []

    def smoke_launch(exe: Path) -> None:
        launches.append(exe)
        with tempfile.TemporaryDirectory(prefix="eoat_manual_smoke_") as runtime:
            env = os.environ.copy()
            env.update(EOAT_ATLAS_SMOKE_TEST="1", EOAT_ATLAS_SMOKE_RUNTIME_PROBE="1", EOAT_ATLAS_LOCALAPPDATA=runtime, QT_QPA_PLATFORM="offscreen")
            subprocess.run([str(exe), "--smoke-test"], env=env, check=True, timeout=120)

    action_equal = update_and_launch(args.deployment_root, args.local_root, launch=smoke_launch)
    if action_equal != "current" or current.stat().st_mtime_ns != before or len(launches) != 1:
        raise AssertionError("Equal-version launch redownloaded or launched incorrectly")
    action_offline = update_and_launch(args.deployment_root / "unavailable", args.local_root, launch=smoke_launch)
    if action_offline != "offline-fallback" or len(launches) != 2:
        raise AssertionError("Offline fallback did not launch exactly once")

    latest_path = args.deployment_root / "Manifests" / "latest.json"
    original_manifest = latest_path.read_bytes()
    old_dir = args.local_root / "app_versions" / "0.8.0"
    shutil.copytree(Path(state["path"]), old_dir)
    metadata = old_dir / "release_metadata.json"
    if not metadata.is_file():
        metadata = old_dir / "_internal" / "release_metadata.json"
    payload = json.loads(metadata.read_text(encoding="utf-8")); payload["app_version"] = "0.8.0"
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    current.write_text(json.dumps({"version": "0.8.0", "path": str(old_dir)}), encoding="utf-8")
    manifest = json.loads(original_manifest); manifest["sha256"] = "0" * 64
    latest_path.write_text(json.dumps(manifest), encoding="utf-8")
    try:
        action_bad = update_and_launch(args.deployment_root, args.local_root, launch=smoke_launch)
    finally:
        latest_path.write_bytes(original_manifest)
    if action_bad != "update-failed-fallback" or json.loads(current.read_text())["version"] != "0.8.0" or len(launches) != 3:
        raise AssertionError("Bad-checksum fallback damaged or replaced the prior local version")

    current_files = [p.name for p in (args.deployment_root / "Packages" / "Current").iterdir()]
    if current_files != ["EOAT-Atlas_v0.9.0.zip"]:
        raise AssertionError(f"Current package folder is not clean: {current_files}")
    print(json.dumps({"packaged_launcher_install": "passed", "equal_no_redownload": "passed", "app_smoke_launches": len(launches), "offline_fallback": "passed", "bad_checksum_fallback": "passed", "current_files": current_files}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
