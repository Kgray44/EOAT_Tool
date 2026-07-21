from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from release_tools.versioning import Version, bump_repository_version, validate_version_sources
from scripts.release.build_server_release import generate_release_metadata, resolve_source_commit

from .common import (
    CheckResult,
    CheckStatus,
    DeploymentError,
    redact_text,
    sha256_file,
    utc_now,
    utc_text,
    write_json_atomic,
)
from .manifest import external_manifest, manifest_core, validate_core, validate_external_manifest

ROOT = Path(__file__).resolve().parents[1]
TOOL_VERSION = "1.0.0"
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
REQUIRED_ARCHIVE_PATHS = {
    "server/alembic.ini",
    "server/eoat_api/app.py",
    "server/migrations/env.py",
    "app/atlas/version.json",
    "release_defaults.json",
    "requirements.lock",
    "release_metadata.json",
    "release_manifest.json",
}
FORBIDDEN_NAME = re.compile(
    r"(?:^|/)(?:\.env(?:\.|$)|id_rsa|id_ed25519|.*\.(?:pem|key)|credentials\.|secrets\.|runtime\.env|migration\.env)(?:/|$)",
    re.I,
)
FORBIDDEN_PATH = re.compile(
    r"(?:^|/)(?:\.git|__pycache__|\.pytest_cache|node_modules|\.venv|venv|dist|build|logs?|screenshots?)(?:/|$)", re.I
)
PRIVATE_KEY = re.compile(rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")
SECRET_TEXT = re.compile(
    rb"(?:gh[pous]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|(?:mysql|postgres(?:ql)?)://[^\s:@/]+:[^\s@/]+@)"
)
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class GitState:
    root: str
    branch: str
    commit: str
    upstream: str | None
    ahead: int | None
    behind: int | None
    modified: list[str]
    staged: list[str]
    untracked: list[str]
    conflicts: list[str]
    latest_tag: str | None
    version: str | None

    @property
    def clean(self) -> bool:
        return not (self.modified or self.staged or self.untracked or self.conflicts)


@dataclass(frozen=True)
class CommandRecord:
    command: list[str]
    exit_code: int
    started_at_utc: str
    ended_at_utc: str
    output: str


@dataclass(frozen=True)
class ArchiveBuild:
    archive: Path
    checksum: Path
    manifest: Path
    core: dict[str, Any]
    external: dict[str, Any]
    files: list[str]


class Git:
    def __init__(self, root: Path) -> None:
        self.root = root

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(["git", *args], cwd=self.root, text=True, capture_output=True, check=False)
        except OSError as exc:
            raise DeploymentError("Git executable is unavailable") from exc
        if check and result.returncode:
            raise DeploymentError(redact_text((result.stderr or result.stdout or "Git command failed").strip()))
        return result

    def output(self, *args: str) -> str:
        return self.run(*args).stdout.strip()


def _remote_repository(root: Path) -> str | None:
    remote = Git(root).run("remote", "get-url", "origin", check=False)
    if remote.returncode:
        return None
    match = re.search(r"github\.com[/:]([^/]+)/([^/\s]+?)(?:\.git)?$", remote.stdout.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


def inspect_git_state(root: Path) -> GitState:
    git = Git(root)
    root_text = git.output("rev-parse", "--show-toplevel")
    branch = git.output("branch", "--show-current") or "(detached)"
    commit = git.output("rev-parse", "HEAD").lower()
    upstream_result = git.run("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", check=False)
    upstream = upstream_result.stdout.strip() if upstream_result.returncode == 0 else None
    ahead = behind = None
    if upstream:
        relation = git.run("rev-list", "--left-right", "--count", f"{upstream}...HEAD", check=False)
        if relation.returncode == 0:
            try:
                behind, ahead = (int(value) for value in relation.stdout.split())
            except ValueError:
                pass
    modified = [line for line in git.output("diff", "--name-only").splitlines() if line]
    staged = [line for line in git.output("diff", "--cached", "--name-only").splitlines() if line]
    untracked = [line for line in git.output("ls-files", "--others", "--exclude-standard").splitlines() if line]
    conflicts = [line for line in git.output("diff", "--name-only", "--diff-filter=U").splitlines() if line]
    tag = git.run("describe", "--tags", "--abbrev=0", check=False)
    try:
        version = str(validate_version_sources(root))
    except (OSError, ValueError) as exc:
        version = None
    return GitState(
        root_text,
        branch,
        commit,
        upstream,
        ahead,
        behind,
        modified,
        staged,
        untracked,
        conflicts,
        tag.stdout.strip() or None,
        version,
    )


def _source_members(root: Path, commit: str) -> list[tuple[str, bytes, int]]:
    """Read only the existing server release content from one committed tree."""

    with tempfile.TemporaryDirectory(prefix="eoat-release-source-") as temporary:
        source_tar = Path(temporary) / "source.tar"
        result = Git(root).run(
            "archive", "--format=tar", f"--output={source_tar}", commit, "--", *SERVER_PATHS, check=False
        )
        if result.returncode:
            raise DeploymentError("Could not create Git archive for selected release content")
        members: list[tuple[str, bytes, int]] = []
        with tarfile.open(source_tar, "r") as archive:
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or "\\" in member.name:
                    raise DeploymentError(f"Unsafe path in Git archive: {member.name}")
                if member.isdir():
                    continue
                if not member.isfile():
                    raise DeploymentError(f"Deployment archive may only contain regular files: {member.name}")
                stream = archive.extractfile(member)
                if stream is None:
                    raise DeploymentError(f"Cannot read Git archive member: {member.name}")
                members.append((path.as_posix(), stream.read(), member.mode & 0o777))
    if not members:
        raise DeploymentError("The selected commit contains no server deployment content")
    return sorted(members, key=lambda item: item[0])


def _payload_digest(members: Iterable[tuple[str, bytes, int]]) -> str:
    digest = hashlib.sha256()
    for name, contents, mode in sorted(members, key=lambda item: item[0]):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(oct(mode).encode("ascii"))
        digest.update(b"\0")
        digest.update(contents)
        digest.update(b"\0")
    return digest.hexdigest()


def _scan_forbidden(members: Iterable[tuple[str, bytes, int]]) -> list[str]:
    findings: list[str] = []
    for name, contents, _mode in members:
        if FORBIDDEN_NAME.search(name) or FORBIDDEN_PATH.search(name):
            findings.append(f"forbidden path: {name}")
        if PRIVATE_KEY.search(contents):
            findings.append(f"private key material: {name}")
        if SECRET_TEXT.search(contents):
            findings.append(f"high-confidence secret pattern: {name}")
        if len(contents) > 50 * 1024 * 1024:
            findings.append(f"oversized file: {name}")
    return findings


def _tarinfo(name: str, contents: bytes, mode: int, timestamp: datetime) -> tarfile.TarInfo:
    item = tarfile.TarInfo(name)
    item.size = len(contents)
    item.mode = mode or 0o644
    item.mtime = int(timestamp.astimezone(timezone.utc).timestamp())
    item.uid = item.gid = 0
    item.uname = item.gname = "root"
    return item


def build_deployment_archive(
    root: Path, commit: str, output_dir: Path, *, branch: str, timestamp: datetime | None = None
) -> ArchiveBuild:
    """Build and immediately re-validate a deterministic Debian tarball.

    The manifest embedded in the tarball is its immutable core.  The external
    manifest adds the hash and size of the tarball itself, which cannot be
    embedded in that same tarball without a circular hash dependency.
    """

    timestamp = (timestamp or utc_now()).astimezone(timezone.utc).replace(microsecond=0)
    commit = resolve_source_commit(root, commit)
    members = _source_members(root, commit)
    findings = _scan_forbidden(members)
    if findings:
        raise DeploymentError("Release content safety scan failed: " + "; ".join(findings))
    present = {name for name, _contents, _mode in members}
    missing = sorted(REQUIRED_ARCHIVE_PATHS - present - {"release_metadata.json", "release_manifest.json"})
    if missing:
        raise DeploymentError("Deployment package is missing required files: " + ", ".join(missing))
    metadata = generate_release_metadata(root, commit, branch_name=branch, build_timestamp=timestamp)
    version = str(metadata["app_version"])
    payload_hash = _payload_digest(members)
    core = manifest_core(
        version=version,
        build_id=str(metadata["build_id"]),
        commit_sha=commit,
        branch=branch,
        created_at_utc=str(metadata["build_timestamp"]),
        payload_sha256=payload_hash,
        migration_revision=str(metadata["database_schema_revision"]),
        api_contract_version=str(metadata["api_contract_version"]),
    )
    archive_name = f"eoat-atlas-server-{version}-{commit[:7]}.tar.gz"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / archive_name
    with (
        archive_path.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=int(timestamp.timestamp())) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT) as archive,
    ):
        for name, contents, mode in members:
            archive.addfile(_tarinfo(name, contents, mode, timestamp), io.BytesIO(contents))
        metadata_bytes = json.dumps(metadata, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        manifest_bytes = json.dumps(core, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        archive.addfile(
            _tarinfo("release_metadata.json", metadata_bytes, 0o644, timestamp),
            io.BytesIO(metadata_bytes),
        )
        archive.addfile(
            _tarinfo("release_manifest.json", manifest_bytes, 0o644, timestamp),
            io.BytesIO(manifest_bytes),
        )
    archive_hash = sha256_file(archive_path)
    external = external_manifest(
        core, archive_name=archive_name, archive_sha256=archive_hash, size_bytes=archive_path.stat().st_size
    )
    checksum_path = output_dir / f"{archive_name}.sha256"
    manifest_path = output_dir / "release_manifest.json"
    checksum_path.write_text(f"{archive_hash}  {archive_name}\n", encoding="ascii", newline="\n")
    write_json_atomic(manifest_path, external)
    validate_deployment_archive(archive_path, manifest_path, checksum_path)
    return ArchiveBuild(
        archive_path, checksum_path, manifest_path, core, external, sorted(name for name, _, _ in members)
    )


def validate_deployment_archive(
    archive_path: Path, manifest_path: Path, checksum_path: Path | None = None
) -> dict[str, Any]:
    external = json.loads(manifest_path.read_text(encoding="utf-8"))
    core, artifact = validate_external_manifest(external)
    actual_hash = sha256_file(archive_path)
    if actual_hash != artifact["sha256"]:
        raise DeploymentError("Deployment artifact SHA-256 does not match manifest")
    if archive_path.name != artifact["filename"] or archive_path.stat().st_size != artifact["size_bytes"]:
        raise DeploymentError("Deployment artifact does not match manifest filename or size")
    if checksum_path:
        expected_line = f"{actual_hash}  {archive_path.name}"
        if checksum_path.read_text(encoding="ascii").strip() != expected_line:
            raise DeploymentError("Checksum file does not match deployment artifact")
    seen: set[str] = set()
    payload: list[tuple[str, bytes, int]] = []
    extractable: list[tuple[str, bytes, int]] = []
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                name = member.name
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name or not member.isfile():
                    raise DeploymentError(f"Unsafe archive member: {name}")
                if name in seen:
                    raise DeploymentError(f"Duplicate archive member: {name}")
                seen.add(name)
                stream = archive.extractfile(member)
                if stream is None:
                    raise DeploymentError(f"Unreadable archive member: {name}")
                contents = stream.read()
                extractable.append((name, contents, member.mode & 0o777))
                if name not in {"release_metadata.json", "release_manifest.json"}:
                    payload.append((name, contents, member.mode & 0o777))
                if FORBIDDEN_NAME.search(name) or FORBIDDEN_PATH.search(name):
                    raise DeploymentError(f"Forbidden archive member: {name}")
            missing = REQUIRED_ARCHIVE_PATHS - seen
            if missing:
                raise DeploymentError("Archive missing required files: " + ", ".join(sorted(missing)))
            embedded = json.loads(archive.extractfile("release_manifest.json").read())
            metadata = json.loads(archive.extractfile("release_metadata.json").read())
    except (OSError, tarfile.TarError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        if isinstance(exc, DeploymentError):
            raise
        raise DeploymentError("Release archive is unreadable or malformed") from exc
    if validate_core(embedded) != core:
        raise DeploymentError("Embedded and external release manifests disagree")
    if _payload_digest(payload) != core["payload_sha256"]:
        raise DeploymentError("Release payload digest does not match its manifest")
    if metadata.get("source_git_commit") != core["commit_sha"] or metadata.get("app_version") != core["version"]:
        raise DeploymentError("Generated release metadata does not match release manifest")
    # Do not use extractall: all member paths have already been normalized and
    # are written below only after proving they stay within an isolated root.
    with tempfile.TemporaryDirectory(prefix="eoat-release-validate-") as temporary:
        extracted_root = Path(temporary)
        for name, contents, mode in extractable:
            destination = (extracted_root / name).resolve()
            try:
                destination.relative_to(extracted_root.resolve())
            except ValueError as exc:
                raise DeploymentError(f"Unsafe extraction path: {name}") from exc
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents)
            if mode:
                destination.chmod(mode)
        smoke = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", str(extracted_root / "server")],
            text=True,
            capture_output=True,
            check=False,
        )
        if smoke.returncode:
            raise DeploymentError("Extracted deployment package failed Python compilation smoke validation")
    return external


def _run_check(root: Path, name: str, command: list[str]) -> CommandRecord:
    started = utc_text()
    try:
        completed = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
        output = redact_text(((completed.stdout or "") + (completed.stderr or ""))[-4000:])
        exit_code = completed.returncode
    except OSError as exc:
        output = redact_text(str(exc))
        exit_code = 127
    return CommandRecord(command, exit_code, started, utc_text(), output)


def validation_plan(root: Path) -> list[tuple[str, list[str]]]:
    plan = [
        (
            "compile",
            [sys.executable, "-m", "compileall", "-q", "server", "core", "release_tools", "deployment", "tools"],
        )
    ]
    ruff = _run_check(root, "ruff-availability", [sys.executable, "-m", "ruff", "--version"])
    if ruff.exit_code == 0:
        plan.append(
            ("ruff", [sys.executable, "-m", "ruff", "check", "server", "core", "release_tools", "deployment", "tools"])
        )
    plan.append(("migration-heads", [sys.executable, "-m", "alembic", "-c", "server/alembic.ini", "heads"]))
    test_paths = [
        "tests/test_versioning.py",
        "tests/test_release_system.py",
        "tests/test_release_propagation.py",
        "tests/test_release_readiness.py",
        "tests/test_server_release_builder.py",
        "tests/test_deployment_system.py",
    ]
    available = [path for path in test_paths if (root / path).is_file()]
    if available:
        plan.append(("release-tests", [sys.executable, "-m", "pytest", "-q", *available]))
    return plan


def run_validation(root: Path) -> tuple[list[CheckResult], list[CommandRecord]]:
    checks: list[CheckResult] = []
    commands: list[CommandRecord] = []
    try:
        version = str(validate_version_sources(root))
        checks.append(CheckResult("version-sources", CheckStatus.PASS, f"authoritative version {version}"))
    except (OSError, ValueError) as exc:
        checks.append(CheckResult("version-sources", CheckStatus.FAIL, redact_text(str(exc))))
    for name, command in validation_plan(root):
        record = _run_check(root, name, command)
        commands.append(record)
        checks.append(
            CheckResult(
                name,
                CheckStatus.PASS if record.exit_code == 0 else CheckStatus.FAIL,
                record.output or "command completed",
                record.started_at_utc,
                record.ended_at_utc,
                record.exit_code,
            )
        )
    return checks, commands


def _assert_ready(state: GitState, *, allow_dirty: bool, approved_exception: str | None) -> None:
    if state.conflicts:
        raise DeploymentError("Repository has merge conflicts: " + ", ".join(state.conflicts))
    if state.behind:
        raise DeploymentError(f"Repository is behind its upstream by {state.behind} commit(s)")
    if not state.clean and not allow_dirty:
        raise DeploymentError("Repository is dirty; use a clean worktree or an explicit documented exception")
    if not state.clean and (not approved_exception or not approved_exception.strip()):
        raise DeploymentError("A dirty-tree exception requires --approved-exception with a non-secret reason")


def _clone_for_dry_run(root: Path, version: Version) -> tuple[tempfile.TemporaryDirectory[str], Path, str]:
    temporary = tempfile.TemporaryDirectory(prefix="eoat-release-dry-run-")
    clone = Path(temporary.name) / "source"
    # A normal clone of a worktree whose object store is on a network share can
    # spend minutes copying unrelated history.  Shared objects retain the exact
    # selected source commit while keeping all dry-run writes in this temporary
    # clone.  The source repository is never modified.
    result = subprocess.run(
        ["git", "clone", "--quiet", "--shared", str(root), str(clone)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        temporary.cleanup()
        raise DeploymentError("Could not create isolated dry-run repository")
    operation_id = f"release-manager-dry-run-{version}"
    bump_repository_version(clone, explicit=str(version), operation_id=operation_id)
    subprocess.run(
        ["git", "add", "app/atlas/version.json", "release_history.json"], cwd=clone, check=True, capture_output=True
    )
    result = subprocess.run(
        [
            "git",
            "-c",
            "user.name=EOAT Atlas Release Manager",
            "-c",
            "user.email=release-manager@localhost",
            "commit",
            "-m",
            f"release: EOAT Atlas {version}",
        ],
        cwd=clone,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        temporary.cleanup()
        raise DeploymentError("Could not create isolated simulated release commit")
    return temporary, clone, Git(clone).output("rev-parse", "HEAD")


def _receipt_path(root: Path, operation: str) -> Path:
    return root / ".local" / "release-receipts" / f"{operation}-{utc_now().strftime('%Y%m%dT%H%M%SZ')}.json"


def _latest_github_release(root: Path) -> str | None:
    repository = _remote_repository(root)
    if not repository or not shutil.which("gh"):
        return None
    result = subprocess.run(
        [
            "gh",
            "release",
            "list",
            "--repo",
            repository,
            "--limit",
            "100",
            "--json",
            "tagName,isDraft,isPrerelease,publishedAt",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return None
    try:
        releases = json.loads(result.stdout)
        versions = [
            Version.parse(item["tagName"][1:])
            for item in releases
            if not item.get("isDraft") and not item.get("isPrerelease") and str(item.get("tagName", "")).startswith("v")
        ]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return f"v{max(versions)}" if versions else None


def status_payload(root: Path) -> dict[str, Any]:
    state = inspect_git_state(root)
    migration = _run_check(
        root, "migration-head", [sys.executable, "-m", "alembic", "-c", "server/alembic.ini", "heads"]
    )
    return {
        "tool_version": TOOL_VERSION,
        "repository": state,
        "latest_github_release": _latest_github_release(root),
        "release_tooling": [
            "scripts/release/build_server_release.py",
            "scripts/publish_release.py",
            "deployment/release_manager.py",
        ],
        "package_output_directories": [str(root / "dist" / "server"), str(root / ".local" / "release-artifacts")],
        "migration_head": redact_text(migration.output),
        "ready_to_package": state.clean and not state.behind and not state.conflicts and state.version is not None,
    }


def _print_payload(payload: Any, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                payload,
                default=lambda value: value.__dict__ if hasattr(value, "__dict__") else str(value),
                indent=2,
                sort_keys=True,
            )
        )
        return
    if isinstance(payload, dict) and "repository" in payload:
        state: GitState = payload["repository"]
        print(f"Repository: {state.root}")
        print(f"Branch: {state.branch} @ {state.commit}")
        print(
            f"Version: {state.version or 'INVALID'}; clean: {state.clean}; ahead/behind: {state.ahead}/{state.behind}"
        )
        print(
            f"Latest local tag: {state.latest_tag or 'none'}; GitHub release: {payload['latest_github_release'] or 'unavailable'}"
        )
        print(f"Ready to package: {payload['ready_to_package']}")
    else:
        print(json.dumps(payload, default=str, indent=2, sort_keys=True))


def _tag_and_publish(
    root: Path, state: GitState, build: ArchiveBuild, *, push: bool, publish: bool, receipt: dict[str, Any]
) -> None:
    git = Git(root)
    version = build.core["version"]
    tag = f"v{version}"
    existing = git.run("rev-parse", "--verify", f"refs/tags/{tag}", check=False)
    if existing.returncode == 0:
        target = git.output("rev-list", "-n", "1", tag)
        if target != build.core["commit_sha"]:
            raise DeploymentError(f"Refusing to overwrite existing tag {tag} at a different commit")
        receipt["tag_result"] = "already present at release commit"
    else:
        annotation = "\n".join(
            (
                f"EOAT Atlas {version}",
                f"Release ID: {build.core['release_id']}",
                f"Build ID: {build.core['build_id']}",
                f"Artifact: {build.archive.name}",
                f"SHA-256: {build.external['artifact']['sha256']}",
                f"Migration target: {build.core['database']['target_revision']}",
                f"Built UTC: {build.core['created_at_utc']}",
            )
        )
        git.run("tag", "-a", tag, "-m", annotation, build.core["commit_sha"])
        receipt["tag_result"] = "created"
    if push:
        git.run("fetch", "origin")
        refreshed = inspect_git_state(root)
        if refreshed.behind:
            raise DeploymentError("Refusing push because upstream advanced")
        git.run("push", "origin", state.branch)
        git.run("push", "origin", tag)
        receipt["push_result"] = "branch and annotated tag pushed"
    else:
        receipt["push_result"] = "not requested"
    if publish:
        repository = _remote_repository(root)
        if not repository or not shutil.which("gh"):
            raise DeploymentError("GitHub CLI or origin GitHub repository is unavailable")
        notes = "\n".join(
            (
                f"EOAT Atlas {version}",
                "",
                f"Release ID: `{build.core['release_id']}`",
                f"Build ID: `{build.core['build_id']}`",
                f"Commit: `{build.core['commit_sha']}`",
                f"SHA-256: `{build.external['artifact']['sha256']}`",
                f"Migration target: `{build.core['database']['target_revision']}`",
                "",
                "The deployment updater remains read-only in this implementation phase.",
            )
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as stream:
            notes_file = Path(stream.name)
            stream.write(notes)
        try:
            result = subprocess.run(
                [
                    "gh",
                    "release",
                    "create",
                    tag,
                    str(build.archive),
                    str(build.checksum),
                    str(build.manifest),
                    "--repo",
                    repository,
                    "--title",
                    f"EOAT Atlas {version}",
                    "--notes-file",
                    str(notes_file),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
        finally:
            notes_file.unlink(missing_ok=True)
        if result.returncode:
            receipt["github_release_result"] = "failed after Git state may have been published"
            raise DeploymentError(
                "GitHub release publication failed: " + redact_text((result.stderr or result.stdout).strip())
            )
        receipt["github_release_result"] = "published"
    else:
        receipt["github_release_result"] = "not requested"


def package(
    root: Path,
    *,
    bump: str | None,
    explicit_version: str | None,
    dry_run: bool,
    no_push: bool,
    no_publish: bool,
    allow_dirty: bool,
    approved_exception: str | None,
) -> dict[str, Any]:
    if bool(bump) == bool(explicit_version):
        raise DeploymentError("Specify exactly one of --bump or --version")
    state = inspect_git_state(root)
    _assert_ready(state, allow_dirty=allow_dirty, approved_exception=approved_exception)
    current = Version.parse(state.version or "")
    target = Version.parse(explicit_version) if explicit_version else current.bump(str(bump))
    if target <= current:
        raise DeploymentError(f"Release version {target} must be greater than current version {current}")
    tag = f"v{target}"
    if Git(root).run("rev-parse", "--verify", f"refs/tags/{tag}", check=False).returncode == 0:
        raise DeploymentError(f"Release tag {tag} already exists; it will not be reused")
    checks, commands = run_validation(root)
    if any(item.status == CheckStatus.FAIL for item in checks):
        raise DeploymentError("Release validation failed before packaging")
    started = utc_text()
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "tool_version": TOOL_VERSION,
        "operation": "package",
        "mode": "DRY_RUN" if dry_run else "ACTIVE_RELEASE_PACKAGING",
        "repository_root": str(root),
        "branch": state.branch,
        "starting_commit": state.commit,
        "version": str(target),
        "tag": tag,
        "approved_exception": approved_exception if allow_dirty else None,
        "validations": checks,
        "commands": commands,
        "started_at_utc": started,
    }
    if dry_run:
        temporary, clone, release_commit = _clone_for_dry_run(root, target)
        try:
            artifact_dir = Path(temporary.name) / "artifacts"
            build = build_deployment_archive(clone, release_commit, artifact_dir, branch=state.branch)
            receipt.update(
                {
                    "release_commit": release_commit,
                    "artifact": {
                        "filename": build.archive.name,
                        "sha256": build.external["artifact"]["sha256"],
                        "size_bytes": build.external["artifact"]["size_bytes"],
                    },
                    "manifest": build.external,
                    "artifact_files": build.files,
                    "git_operations": [
                        f"SIMULATED commit: release: EOAT Atlas {target}",
                        f"SIMULATED annotated tag: {tag}",
                        "SIMULATED push: origin branch and tag",
                    ],
                    "github_release_result": "SIMULATED publication",
                    "final_status": "DRY_RUN_SUCCEEDED",
                }
            )
        finally:
            temporary.cleanup()
    else:
        bump_repository_version(root, part=bump, explicit=explicit_version, operation_id=f"release-manager-{target}")
        changed = [line for line in Git(root).output("diff", "--name-only").splitlines() if line]
        allowed = {"app/atlas/version.json", "release_history.json"}
        unexpected = sorted(set(changed) - allowed)
        if unexpected:
            raise DeploymentError("Version preparation changed unexpected files: " + ", ".join(unexpected))
        Git(root).run("add", "--", "app/atlas/version.json", "release_history.json")
        Git(root).run("commit", "-m", f"release: EOAT Atlas {target}")
        release_commit = Git(root).output("rev-parse", "HEAD")
        build = build_deployment_archive(
            root, release_commit, root / ".local" / "release-artifacts" / str(target), branch=state.branch
        )
        receipt.update(
            {
                "release_commit": release_commit,
                "artifact": {
                    "filename": build.archive.name,
                    "sha256": build.external["artifact"]["sha256"],
                    "size_bytes": build.external["artifact"]["size_bytes"],
                },
                "manifest": build.external,
                "artifact_files": build.files,
                "commit_files": sorted(allowed),
            }
        )
        try:
            _tag_and_publish(
                root, inspect_git_state(root), build, push=not no_push, publish=not no_publish, receipt=receipt
            )
        except DeploymentError as exc:
            # A pushed commit/tag with a failed GitHub publication is a real,
            # recoverable partial state.  Preserve the evidence before the
            # exception reaches the CLI.
            receipt.update(
                {
                    "final_status": "FAILED_PARTIAL_PUBLICATION",
                    "failure_stage": "tag_push_or_github_publication",
                    "failure": redact_text(str(exc)),
                    "ended_at_utc": utc_text(),
                }
            )
            destination = _receipt_path(root, "release")
            write_json_atomic(destination, receipt)
            raise
        receipt["final_status"] = "SUCCEEDED"
    receipt["ended_at_utc"] = utc_text()
    if dry_run:
        # The returned JSON is the receipt.  Persisting it in the source tree
        # would make a supposedly non-mutating rehearsal leave an untracked
        # filesystem change behind.
        receipt["receipt_path"] = None
    else:
        destination = _receipt_path(root, "release")
        write_json_atomic(destination, receipt)
        receipt["receipt_path"] = str(destination)
    return receipt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EOAT Atlas Phase 1 release manager")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", dest="as_json")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Inspect repository and release readiness without mutation")
    subparsers.add_parser("validate", help="Run the release validation plan without mutation")
    package_parser = subparsers.add_parser("package", help="Prepare, validate, and optionally publish a release")
    group = package_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bump", choices=("patch", "minor", "major"))
    group.add_argument("--version", dest="explicit_version", metavar="MAJOR.MINOR.PATCH")
    package_parser.add_argument(
        "--dry-run", action="store_true", help="Use an isolated clone; do not modify this repository"
    )
    package_parser.add_argument("--no-push", action="store_true", help="Do not push an active release commit or tag")
    package_parser.add_argument(
        "--no-publish", action="store_true", help="Do not create a GitHub Release for an active release"
    )
    package_parser.add_argument(
        "--allow-dirty", action="store_true", help="Require a documented exception for a dirty tree"
    )
    package_parser.add_argument("--approved-exception", help="Non-secret reason recorded in the receipt")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "status":
            _print_payload(status_payload(root), args.as_json)
        elif args.command == "validate":
            checks, commands = run_validation(root)
            payload = {
                "checks": checks,
                "commands": commands,
                "passed": not any(check.status == CheckStatus.FAIL for check in checks),
            }
            _print_payload(payload, args.as_json)
            return 0 if payload["passed"] else 1
        else:
            result = package(
                root,
                bump=args.bump,
                explicit_version=args.explicit_version,
                dry_run=args.dry_run,
                no_push=args.no_push,
                no_publish=args.no_publish,
                allow_dirty=args.allow_dirty,
                approved_exception=args.approved_exception,
            )
            _print_payload(result, args.as_json)
    except (DeploymentError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {redact_text(str(exc))}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
