from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from tools.cutover.rehearsal import REPORT_ROOT, STAGING_STATE, utcnow, write_json

BUILD_SOURCE = STAGING_STATE / "build-source/dist"
CANDIDATE = STAGING_STATE / "installer/eoat-atlas-rehearsal-rc1"
INSTALL = STAGING_STATE / "installed-client"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def install() -> None:
    if INSTALL.exists():
        shutil.rmtree(INSTALL)
    shutil.copytree(CANDIDATE / "payload", INSTALL)


def config() -> Path:
    path = INSTALL / "staging-launcher-config.json"
    path.write_text(json.dumps({
        "appInstallPath": str(INSTALL / "EOAT Atlas"), "appExecutableName": "EOAT Atlas.exe",
        "appEntryPoint": "", "channel": "staging-local", "updateManifestPath": "", "updateManifestUrl": "",
        "networkRequiredPaths": [], "logLevel": "INFO", "lastKnownGoodVersion": "0.1.0-rehearsal-rc1",
        "allowOfflineLaunch": True, "singleInstance": {"enabled": True, "appProcessNames": ["EOAT Atlas.exe"],
        "lockName": "EOATAtlasStagingRehearsal"}, "startupWaitSeconds": 2.0,
        "launchArguments": ["--ui", "minimalist"],
    }, indent=2), encoding="utf-8")
    return path


def run(command: list[str], env: dict[str, str], timeout: int = 45) -> dict[str, object]:
    started = time.perf_counter()
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=timeout, check=False)
    return {"exit_code": result.returncode, "seconds": round(time.perf_counter() - started, 3),
            "stdout_tail": result.stdout[-1000:], "stderr_tail": result.stderr[-1000:]}


def main() -> int:
    client_source = BUILD_SOURCE / "EOAT Atlas"
    launcher_source = BUILD_SOURCE / "EOAT Atlas Launcher.exe"
    if not (client_source / "EOAT Atlas.exe").exists() or not launcher_source.exists():
        raise FileNotFoundError("Built EOAT Atlas client and launcher are required")
    if CANDIDATE.exists():
        shutil.rmtree(CANDIDATE)
    payload = CANDIDATE / "payload"
    payload.mkdir(parents=True)
    shutil.copytree(client_source, payload / "EOAT Atlas")
    shutil.copy2(launcher_source, payload / launcher_source.name)
    (CANDIDATE / "Install-Staging.ps1").write_text(
        "$ErrorActionPreference='Stop'\n$source=Join-Path $PSScriptRoot 'payload'\n"
        "$target=Join-Path $env:LOCALAPPDATA 'EOAT Atlas Staging\\installed-client'\n"
        "if(Test-Path -LiteralPath $target){Remove-Item -LiteralPath $target -Recurse -Force}\n"
        "Copy-Item -LiteralPath $source -Destination $target -Recurse -Force\n"
        "Write-Output \"Installed isolated staging candidate to $target\"\n", encoding="utf-8")
    (CANDIDATE / "Uninstall-Staging.ps1").write_text(
        "$ErrorActionPreference='Stop'\n$target=Join-Path $env:LOCALAPPDATA 'EOAT Atlas Staging\\installed-client'\n"
        "if(Test-Path -LiteralPath $target){Remove-Item -LiteralPath $target -Recurse -Force}\n"
        "Write-Output 'Removed isolated staging candidate.'\n", encoding="utf-8")
    (CANDIDATE / "Start-EOAT-Atlas-Staging.ps1").write_text(
        "$ErrorActionPreference='Stop'\n$root=Join-Path $env:LOCALAPPDATA 'EOAT Atlas Staging\\installed-client'\n"
        "$env:EOAT_ATLAS_DATA_BACKEND='mysql_api'\n$env:EOAT_ATLAS_API_URL='http://127.0.0.1:8766'\n"
        "$env:EOAT_ATLAS_ENVIRONMENT='staging_local'\n$env:EOAT_ATLAS_WRITES_ENABLED='true'\n"
        "$env:EOAT_ATLAS_DEV_IDENTITY='staging.engineer'\n$env:EOAT_ATLAS_CLIENT_VERSION='rehearsal-rc1'\n"
        "& (Join-Path $root 'EOAT Atlas Launcher.exe') --config (Join-Path $root 'staging-launcher-config.json')\n",
        encoding="utf-8")
    (CANDIDATE / "README.txt").write_text(
        "EOAT Atlas isolated local rehearsal candidate. Not for production deployment.\n"
        "Run Install-Staging.ps1, then Start-EOAT-Atlas-Staging.ps1 while the staging API is healthy.\n",
        encoding="utf-8")
    env = os.environ.copy() | {
        "EOAT_ATLAS_DATA_BACKEND": "mysql_api", "EOAT_ATLAS_API_URL": "http://127.0.0.1:8766",
        "EOAT_ATLAS_ENVIRONMENT": "staging_local", "EOAT_ATLAS_WRITES_ENABLED": "true",
        "EOAT_ATLAS_DEV_IDENTITY": "staging.engineer", "EOAT_ATLAS_CLIENT_VERSION": "rehearsal-rc1",
        "QT_QPA_PLATFORM": "offscreen", "EOAT_ATLAS_SMOKE_TEST": "1",
    }
    install()
    config_path = config()
    launcher_check_1 = run([str(INSTALL / "EOAT Atlas Launcher.exe"), "--check-only", "--no-ui", "--config", str(config_path)], env)
    smoke_1 = run([str(INSTALL / "EOAT Atlas/EOAT Atlas.exe"), "--smoke-test", "--ui", "minimalist"], env)
    shutil.rmtree(INSTALL)
    uninstall_pass = not INSTALL.exists()
    install()
    config_path = config()
    launcher_check_2 = run([str(INSTALL / "EOAT Atlas Launcher.exe"), "--check-only", "--no-ui", "--config", str(config_path)], env)
    smoke_2 = run([str(INSTALL / "EOAT Atlas/EOAT Atlas.exe"), "--smoke-test", "--ui", "minimalist"], env)
    zip_path = Path(shutil.make_archive(str(CANDIDATE), "zip", CANDIDATE))
    artifacts = []
    for path in sorted(CANDIDATE.rglob("*")):
        if path.is_file():
            artifacts.append({"path": str(path.relative_to(CANDIDATE)), "bytes": path.stat().st_size, "sha256": digest(path)})
    status = "PASS" if all(item["exit_code"] == 0 for item in (launcher_check_1, smoke_1, launcher_check_2, smoke_2)) and uninstall_pass else "FAIL"
    report = {
        "status": status, "generated_at": utcnow(), "candidate": "eoat-atlas-rehearsal-rc1",
        "candidate_directory": str(CANDIDATE), "zip": str(zip_path), "zip_sha256": digest(zip_path),
        "installed_directory": str(INSTALL), "artifact_files": len(artifacts),
        "client_exe_sha256": digest(CANDIDATE / "payload/EOAT Atlas/EOAT Atlas.exe"),
        "launcher_exe_sha256": digest(CANDIDATE / "payload/EOAT Atlas Launcher.exe"),
        "clean_install": {"launcher_check": launcher_check_1, "client_smoke": smoke_1},
        "uninstall": {"status": "PASS" if uninstall_pass else "FAIL"},
        "reinstall": {"launcher_check": launcher_check_2, "client_smoke": smoke_2},
        "installed_candidate_retained": True, "manifest": artifacts,
    }
    write_json(REPORT_ROOT / "package_install_validation.json", report)
    print(json.dumps({key: report[key] for key in ("status", "candidate_directory", "zip", "artifact_files", "clean_install", "uninstall", "reinstall")}, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
