"""Build a self-contained EOAT Atlas portable Windows distribution.

This build-time utility never installs, changes system policy, or writes under
the user's EOAT runtime directory.  The resulting onedir package can be
extracted and launched by opening ``EOAT Atlas.exe`` directly.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DIST = ROOT / "dist"
PACKAGE_DIR = DIST / "EOAT Atlas"
EXECUTABLE_NAME = "EOAT Atlas.exe"
PROFILE_PATH = ROOT / "config" / "production.json"
REQUIRED_PROFILE = {
    "environment": "production",
    "backend": "mysql_api",
    "api_url": "http://eoat-atlas.gwplastics.com/api/v1",
    "writes_enabled": False,
    "expected_api_version": "1.4.0",
    "expected_schema_revision": "20260717_0007",
    "cache_filename": "eoat_atlas_api_cache.db",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def portable_name(version: str) -> str:
    return f"EOAT_Atlas_{version}_Portable"


def assert_clean_source() -> None:
    completed = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "Unable to inspect Git source state.")
    if completed.stdout.strip():
        raise RuntimeError("Portable production packaging requires a clean committed source tree.")


def load_profile() -> dict[str, object]:
    try:
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Production profile is unreadable: {PROFILE_PATH}") from exc
    if profile != REQUIRED_PROFILE:
        raise RuntimeError("Production profile does not match the approved portable client contract.")
    return profile


def locked_distribution_names() -> list[str]:
    names: set[str] = set()
    pattern = re.compile(r"^([A-Za-z0-9_.-]+)==")
    for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match:
            names.add(match.group(1))
    return sorted(names, key=str.casefold)


def _metadata_value(distribution: importlib.metadata.Distribution, field: str) -> str:
    return str(distribution.metadata.get(field) or "").strip()


def _license_files(distribution: importlib.metadata.Distribution) -> list[Path]:
    matches: list[Path] = []
    for entry in distribution.files or ():
        name = entry.name.casefold()
        if not any(token in name for token in ("license", "copying", "notice")):
            continue
        candidate = Path(distribution.locate_file(entry))
        if candidate.is_file():
            matches.append(candidate)
    return sorted(set(matches), key=lambda path: str(path).casefold())


def write_third_party_notices(destination: Path) -> None:
    """Write license/notices for locked runtime dependencies available to the builder."""

    sections = [
        "EOAT Atlas third-party notices",
        "",
        "This portable distribution is produced from the locked runtime dependency set.",
        "License text supplied by installed distributions is reproduced below when available.",
        "",
    ]
    missing: list[str] = []
    for requirement_name in locked_distribution_names():
        try:
            distribution = importlib.metadata.distribution(requirement_name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(requirement_name)
            continue
        name = _metadata_value(distribution, "Name") or requirement_name
        version = _metadata_value(distribution, "Version") or "unknown"
        license_name = _metadata_value(distribution, "License") or _metadata_value(distribution, "License-Expression")
        home_page = _metadata_value(distribution, "Home-page") or _metadata_value(distribution, "Project-URL")
        sections.extend(("=" * 78, f"{name} {version}", f"License: {license_name or 'See bundled license text.'}"))
        if home_page:
            sections.append(f"Project: {home_page}")
        license_files = _license_files(distribution)
        if not license_files:
            sections.append("No separate license file was exposed by this build environment's package metadata.")
        for license_file in license_files:
            sections.extend(("", f"--- {license_file.name} ---"))
            try:
                sections.append(license_file.read_text(encoding="utf-8", errors="replace").rstrip())
            except OSError as exc:
                sections.append(f"Unable to read bundled license file: {exc}")
        sections.append("")
    if missing:
        raise RuntimeError(
            "The build environment is missing locked runtime distributions needed for notices: " + ", ".join(missing)
        )
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        sections.extend(("=" * 78, "Python runtime", "", python_license.read_text(encoding="utf-8", errors="replace").rstrip(), ""))
    destination.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")


def write_portable_readme(destination: Path, version: str, profile: dict[str, object]) -> None:
    destination.write_text(
        "\n".join(
            (
                f"EOAT Atlas {version} Portable",
                "",
                "Launch EOAT Atlas.exe directly. No installer, PowerShell script, administrator privilege,",
                "or Python installation is required on the target workstation.",
                "",
                f"Production API: {profile['api_url']}",
                f"Required API contract: {profile['expected_api_version']}",
                f"Required database schema: {profile['expected_schema_revision']}",
                "Server writes: disabled",
                "Desktop data transport: HTTPS/HTTP API only; this client does not connect directly to MySQL.",
                "",
                "Runtime data is never stored beside this portable folder. The application preserves and uses:",
                r"%LOCALAPPDATA%\EOAT_Atlas\data\eoat_atlas_api_cache.db",
                "",
                "The portable package contains no user cache or development database. When the server is unavailable,",
                "the interface says 'Using cached data' and shows the last successful server refresh; it never claims",
                "that cached data is a live server connection.",
                "",
                "Extract the ZIP anywhere under your user profile and double-click EOAT Atlas.exe.",
            )
        )
        + "\n",
        encoding="utf-8",
    )


def release_metadata_path(package_dir: Path) -> Path:
    candidates = sorted(package_dir.rglob("release_metadata.json"))
    if len(candidates) != 1:
        raise RuntimeError(f"Expected exactly one bundled release_metadata.json, found {len(candidates)}")
    return candidates[0]


def write_portable_manifest(destination: Path, version: str, profile: dict[str, object]) -> None:
    executable = destination.parent / EXECUTABLE_NAME
    metadata_path = release_metadata_path(destination.parent)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload = {
        "portable_manifest_schema_version": 1,
        "application_version": version,
        "executable": {"path": EXECUTABLE_NAME, "size": executable.stat().st_size, "sha256": sha256(executable)},
        "production_profile": profile,
        "release_metadata": {
            "build_id": metadata.get("build_id"),
            "source_git_commit": metadata.get("source_git_commit"),
            "artifact_sha256": metadata.get("artifact_sha256"),
        },
        "runtime_cache": r"%LOCALAPPDATA%\EOAT_Atlas\data\eoat_atlas_api_cache.db",
        "installer_required": False,
        "powershell_required": False,
        "administrator_required": False,
        "python_required": False,
        "direct_mysql_connection": False,
    }
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_zip(portable_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        raise RuntimeError(f"Refusing to overwrite existing portable ZIP: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path in sorted(portable_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(portable_dir.parent).as_posix())


def _prepare_output_path(path: Path, *, replace_output: bool) -> None:
    if not path.exists():
        return
    if not replace_output:
        raise RuntimeError(f"Portable output already exists: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def build_portable_distribution(*, replace_output: bool = False) -> tuple[Path, Path]:
    assert_clean_source()
    profile = load_profile()
    from core.versioning import get_app_version

    version = get_app_version()
    portable_dir = DIST / portable_name(version)
    zip_path = DIST / f"{portable_dir.name}.zip"
    _prepare_output_path(portable_dir, replace_output=replace_output)
    _prepare_output_path(zip_path, replace_output=replace_output)

    subprocess.run([sys.executable, "scripts/build_package.py"], cwd=ROOT, check=True)
    executable = PACKAGE_DIR / EXECUTABLE_NAME
    if not executable.is_file():
        raise RuntimeError(f"Frozen executable was not produced: {executable}")
    shutil.copytree(PACKAGE_DIR, portable_dir)
    write_portable_readme(portable_dir / "PORTABLE_README.txt", version, profile)
    write_third_party_notices(portable_dir / "THIRD_PARTY_NOTICES.txt")
    write_portable_manifest(portable_dir / "portable_manifest.json", version, profile)
    write_zip(portable_dir, zip_path)
    return portable_dir, zip_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a directly runnable EOAT Atlas portable ZIP.")
    parser.add_argument(
        "--replace-output",
        action="store_true",
        help="Replace only this version's generated portable directory and ZIP under dist.",
    )
    args = parser.parse_args(argv)
    try:
        portable_dir, zip_path = build_portable_distribution(replace_output=args.replace_output)
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"FAIL portable build: {exc}", file=sys.stderr)
        return 1
    print(f"PASS portable directory: {portable_dir}")
    print(f"PASS portable ZIP: {zip_path}")
    print(f"PASS portable executable SHA-256: {sha256(portable_dir / EXECUTABLE_NAME)}")
    print(f"PASS portable ZIP SHA-256: {sha256(zip_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
