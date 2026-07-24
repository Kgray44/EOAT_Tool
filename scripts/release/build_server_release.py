from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.versioning.version_info import validate_release_metadata  # noqa: E402
from release_tools.versioning import Version, build_identifier  # noqa: E402

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
SECRET_KEY = re.compile(r"(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|ldap[_-]?bind)", re.I)
SERVER_PATHS = (
    "server",
    "core",
    "release_tools",
    "requirements.lock",
    "requirements.txt",
    "requirements.in",
    "pyproject.toml",
    "app/atlas/version.json",
    "release_defaults.json",
    "launcher/launcher_version.json",
    "installer/installer_config.json",
)
RELEVANT_PREFIXES = (
    "server/",
    "core/",
    "release_tools/",
    "scripts/release/",
    "requirements",
    "pyproject.toml",
    "app/atlas/version.json",
    "release_defaults.json",
    "launcher/launcher_version.json",
    "installer/installer_config.json",
)


class ReleaseBuildError(RuntimeError):
    pass


def _git(root: Path, *args: str, binary: bool = False) -> str | bytes:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=not binary, check=False
        )
    except OSError as exc:
        raise ReleaseBuildError("Git executable is unavailable") from exc
    if completed.returncode:
        stderr = completed.stderr.decode(errors="replace") if binary else completed.stderr
        raise ReleaseBuildError((stderr or "Git command failed").strip())
    return completed.stdout


def resolve_source_commit(root: Path, revision: str) -> str:
    if not (root / ".git").exists():
        raise ReleaseBuildError(f"Not a Git repository: {root}")
    commit = str(_git(root, "rev-parse", "--verify", f"{revision}^{{commit}}" )).strip().lower()
    if not FULL_SHA.fullmatch(commit):
        raise ReleaseBuildError(f"Git did not resolve a full commit for {revision!r}")
    return commit


def changed_paths(root: Path) -> list[str]:
    paths: set[str] = set()
    for args in (("diff", "--name-only"), ("diff", "--cached", "--name-only"), ("ls-files", "--others", "--exclude-standard")):
        output = str(_git(root, *args))
        paths.update(line.replace("\\", "/") for line in output.splitlines() if line.strip())
    return sorted(paths)


def relevant_dirty_paths(root: Path) -> list[str]:
    return [path for path in changed_paths(root) if path.startswith(RELEVANT_PREFIXES)]


def parse_build_timestamp(value: str | None) -> datetime:
    if value:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise ReleaseBuildError("--build-timestamp must use YYYY-MM-DDTHH:MM:SSZ") from exc
        return parsed
    return datetime.now(timezone.utc).replace(microsecond=0)


def _json_from_commit(root: Path, commit: str, path: str) -> dict[str, Any]:
    raw = _git(root, "show", f"{commit}:{path}", binary=True)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseBuildError(f"Selected commit contains invalid JSON at {path}") from exc
    if not isinstance(payload, dict):
        raise ReleaseBuildError(f"Selected commit JSON is not an object: {path}")
    return payload


def _assert_no_secret_fields(payload: dict[str, Any], *, label: str) -> None:
    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                child = f"{path}.{key}" if path else str(key)
                if SECRET_KEY.search(str(key)):
                    raise ReleaseBuildError(f"{label} contains forbidden secret field {child}")
                visit(nested, child)
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                visit(nested, f"{path}[{index}]")

    visit(payload, "")


def generate_release_metadata(
    root: Path,
    commit: str,
    *,
    branch_name: str,
    build_timestamp: datetime,
) -> dict[str, Any]:
    defaults = _json_from_commit(root, commit, "release_defaults.json")
    version_payload = _json_from_commit(root, commit, "app/atlas/version.json")
    if version_payload.get("appName") != "EOAT Atlas":
        raise ReleaseBuildError("Canonical version source has the wrong appName")
    try:
        version = str(Version.parse(str(version_payload.get("version") or "")))
    except ValueError as exc:
        raise ReleaseBuildError("Canonical version source has an invalid version") from exc
    timestamp = build_timestamp.astimezone(timezone.utc).replace(microsecond=0)
    timestamp_text = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata = {
        **defaults,
        "metadata_role": "release_artifact",
        "app_version": version,
        "release_id": f"eoat-atlas-{version}",
        "build_id": build_identifier(version, commit, timestamp),
        "build_timestamp": timestamp_text,
        "build_date": timestamp.date().isoformat(),
        "branch_name": branch_name,
        "source_git_commit": commit,
        # Backward-compatible alias with explicit source-commit semantics.
        "git_commit": commit,
    }
    _assert_no_secret_fields(metadata, label="release metadata")
    validate_release_metadata(metadata, require_artifact=True)
    return metadata


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def migration_hashes(root: Path, commit: str) -> dict[str, str]:
    names = str(_git(root, "ls-tree", "-r", "--name-only", commit, "--", "server/migrations/versions")).splitlines()
    return {name: hashlib.sha256(_git(root, "show", f"{commit}:{name}", binary=True)).hexdigest() for name in names if name.endswith(".py")}


def archive_migration_hashes(archive_path: Path) -> dict[str, str]:
    with zipfile.ZipFile(archive_path) as archive:
        return {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if name.startswith("server/migrations/versions/") and name.endswith(".py")
        }


def _zip_info(name: str, timestamp: datetime, mode: int = 0o644) -> zipfile.ZipInfo:
    utc = timestamp.astimezone(timezone.utc)
    info = zipfile.ZipInfo(name, (max(1980, utc.year), utc.month, utc.day, utc.hour, utc.minute, utc.second))
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (mode & 0xFFFF) << 16
    return info


def create_archive(root: Path, commit: str, destination: Path, metadata: dict[str, Any], timestamp: datetime) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="eoat_server_release_") as temporary:
        source_tar = Path(temporary) / "source.tar"
        _git(root, "archive", "--format=tar", f"--output={source_tar}", commit, "--", *SERVER_PATHS)
        with tarfile.open(source_tar, "r") as source, zipfile.ZipFile(
            destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            members = sorted((member for member in source.getmembers() if member.isfile()), key=lambda item: item.name)
            for member in members:
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts:
                    raise ReleaseBuildError(f"Unsafe path in Git archive: {member.name}")
                extracted = source.extractfile(member)
                if extracted is None:
                    raise ReleaseBuildError(f"Could not read Git archive member: {member.name}")
                payload = (
                    _git(root, "show", f"{commit}:{path.as_posix()}", binary=True)
                    if path.as_posix().startswith("server/migrations/versions/") and path.suffix == ".py"
                    else extracted.read()
                )
                archive.writestr(_zip_info(path.as_posix(), timestamp, member.mode), payload)
            serialized = json.dumps(metadata, indent=2, sort_keys=True).encode("utf-8") + b"\n"
            archive.writestr(_zip_info("release_metadata.json", timestamp), serialized)


def validate_archive(
    archive_path: Path,
    *,
    expected_commit: str,
    expected_metadata: dict[str, Any],
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    if not archive_path.is_file():
        raise ReleaseBuildError(f"Release archive is missing: {archive_path}")
    if expected_sha256 and sha256_file(archive_path) != expected_sha256:
        raise ReleaseBuildError("Release archive checksum does not match the manifest")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            bad = archive.testzip()
            if bad:
                raise ReleaseBuildError(f"ZIP integrity failure at {bad}")
            names = archive.namelist()
            if names.count("release_metadata.json") != 1:
                raise ReleaseBuildError("Archive must contain exactly one root release_metadata.json")
            archived_metadata = json.loads(archive.read("release_metadata.json"))
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ReleaseBuildError("Release archive is unreadable or malformed") from exc
    info = validate_release_metadata(archived_metadata, require_artifact=True)
    if info.source_git_commit != expected_commit:
        raise ReleaseBuildError("Archive metadata names a different source commit")
    if archived_metadata != expected_metadata:
        raise ReleaseBuildError("Archive metadata differs from the generated build metadata")
    return archived_metadata


def build_server_release(args: argparse.Namespace) -> tuple[Path, Path, Path, dict[str, Any]]:
    root = args.root.resolve()
    commit = resolve_source_commit(root, args.source_commit)
    dirty = relevant_dirty_paths(root)
    if dirty:
        raise ReleaseBuildError("Relevant uncommitted files would make release intent ambiguous: " + ", ".join(dirty))
    timestamp = parse_build_timestamp(args.build_timestamp)
    head = str(_git(root, "rev-parse", "HEAD")).strip().lower()
    branch = args.branch_name or (str(_git(root, "branch", "--show-current")).strip() if head == commit else "")
    if not branch:
        raise ReleaseBuildError("--branch-name is required when building a commit other than HEAD")
    metadata = generate_release_metadata(root, commit, branch_name=branch, build_timestamp=timestamp)
    version = metadata["app_version"]
    archive_name = f"eoat-atlas-server-{version}-{commit[:7]}.zip"
    output_dir = args.output_dir.resolve()
    archive_path = output_dir / archive_name
    checksum_path = output_dir / f"{archive_name}.sha256"
    manifest_path = output_dir / f"{archive_path.stem}.manifest.json"
    create_archive(root, commit, archive_path, metadata, timestamp)
    archive_sha = sha256_file(archive_path)
    validate_archive(archive_path, expected_commit=commit, expected_metadata=metadata, expected_sha256=archive_sha)
    git_migrations = migration_hashes(root, commit)
    zip_migrations = archive_migration_hashes(archive_path)
    if git_migrations != zip_migrations:
        raise ReleaseBuildError("ZIP-embedded migration bytes differ from declared Git commit")
    manifest = {
        "manifest_schema_version": 1,
        "app_name": metadata["app_name"],
        "version": version,
        "release_id": metadata["release_id"],
        "build_id": metadata["build_id"],
        "build_timestamp": metadata["build_timestamp"],
        "branch_name": branch,
        "source_git_commit": commit,
        "archive_filename": archive_name,
        "archive_sha256": archive_sha,
        "database_schema_revision": metadata["database_schema_revision"],
        "api_contract_version": metadata["api_contract_version"],
        "launcher_version": metadata["launcher_version"],
        "installer_version": metadata["installer_version"],
        "environment": metadata["environment"],
        "release_channel": metadata["release_channel"],
        "migration_inventory": {
            path: {"git_blob_sha256": digest, "staged_file_sha256": zip_migrations[path], "zip_embedded_sha256": zip_migrations[path]}
            for path, digest in git_migrations.items()
        },
    }
    _assert_no_secret_fields(manifest, label="release manifest")
    checksum_path.write_text(f"{archive_sha}  {archive_name}\n", encoding="ascii", newline="\n")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    if sha256_file(archive_path) != manifest["archive_sha256"]:
        raise ReleaseBuildError("Final manifest checksum validation failed")
    if checksum_path.read_text(encoding="ascii").strip() != f"{archive_sha}  {archive_name}":
        raise ReleaseBuildError("Final checksum file validation failed")
    return archive_path, checksum_path, manifest_path, manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a deterministic EOAT Atlas server release from one Git commit")
    parser.add_argument("--source-commit", default="HEAD", help="Exact commit-ish to resolve and package")
    parser.add_argument("--branch-name", help="Branch recorded in generated metadata")
    parser.add_argument("--build-timestamp", help="UTC timestamp (YYYY-MM-DDTHH:MM:SSZ); defaults to current UTC")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist" / "server")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        archive, checksum, manifest, record = build_server_release(parse_args(argv))
    except (OSError, ReleaseBuildError, RuntimeError, ValueError) as exc:
        print(f"ERROR: server release build failed: {exc}", file=sys.stderr)
        return 1
    print(f"Built {record['release_id']} from {record['source_git_commit']}")
    print(f"Archive: {archive}")
    print(f"Checksum: {checksum}")
    print(f"Manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
