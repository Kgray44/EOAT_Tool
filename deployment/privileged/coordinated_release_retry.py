#!/usr/bin/env python3
"""Root-owned, policy-pinned coordinated EOAT API/static-release activation.

This helper is deliberately narrow: it accepts only a root-owned JSON policy
whose hashes pin the server ZIP and the already sealed static bundle. It may
apply only that policy's deterministic, sealed Alembic traversal before paired
API/frontend activation; it never accepts caller-supplied migration commands.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import gzip
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:  # The installed coordinator is Linux-only; keeping import lazy helps CI collection on Windows.
    import grp
    import pwd
except ImportError:  # pragma: no cover - exercised by Linux deployment gates
    grp = None  # type: ignore[assignment]
    pwd = None  # type: ignore[assignment]

import install_http_web_host as web

HELPER_VERSION = "1.4.0"
API_CURRENT = Path("/opt/eoat-atlas/current")
API_RELEASES = Path("/opt/eoat-atlas/releases")
WEB_CURRENT = Path("/var/www/eoat-atlas/current")
WEB_RELEASES = web.WEB_ROOT / "releases"
CONTROL_ROOT = Path("/var/lib/eoat-atlas-http-web-host")
SERVICE = "eoat-atlas.service"
SYSTEM_PYTHON = Path("/usr/bin/python3").resolve()
SEALING_RECEIPT_SCHEMA_VERSION = 2
TRANSACTION_RECEIPT_SCHEMA_VERSION = 3
LEGACY_TRANSACTION_RECEIPT_SCHEMA_VERSION = 2
LEGACY_HELPER_VERSION = "1.3.1"
SUPPORTED_TRANSACTION_HELPER_VERSIONS = {"1.3.2", "1.3.3", "1.3.4", HELPER_VERSION}
LEGACY_APPLICATION_VERSION = "0.22.12"
LEGACY_SCHEMA = "20260721_0008"
TRANSACTION_ID = __import__("re").compile(r"coordinated-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}")
MIGRATION_REVISION = re.compile(r"\d{8}_\d{4}(?:_[A-Za-z0-9_-]+)?")
SHA256 = re.compile(r"[0-9a-f]{64}")
UPLOAD_ROOT = Path("/opt/eoat-atlas/incoming")
SEALED_ROOT = CONTROL_ROOT / "sealed-artifacts"
MIGRATION_ENVIRONMENT = Path("/etc/eoat-atlas/migration.env")
DEPLOYMENT_LOCK = Path("/var/lock/eoat-atlas-deploy.lock")
PRODUCTION_DATABASE = "eoat_atlas_prod"


@dataclass(frozen=True)
class SealedArtifacts:
    """Validated final paths for one immutable, coordinator-sealed release."""

    root: Path
    server_archive: Path
    server_manifest: Path
    bundle: Path
    receipt_path: Path
    policy_semantic_sha256: str
    bundle_sha256: str


def fail(message: str) -> None:
    raise web.InstallError(message)


def _policy_digest(value: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _upload_member(value: object, *, directory: bool = False) -> Path:
    path = Path(str(value))
    try:
        path.relative_to(UPLOAD_ROOT)
    except ValueError:
        fail("artifact source is outside the approved upload root")
    if path.is_symlink() or not path.exists() or (not path.is_dir() if directory else not path.is_file()):
        fail("artifact source is not an expected non-symlink upload member")
    return path


def _copy_sealed_file(source: Path, destination: Path, expected: str, sealed_relative: Path) -> dict[str, object]:
    before = source.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        fail("upload artifact must be a singly-linked regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    digest = hashlib.sha256()
    size = 0
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ):
            fail("upload artifact changed before opening")
        with os.fdopen(descriptor, "rb", closefd=True) as input_stream, destination.open("xb") as output:
            while block := input_stream.read(1024 * 1024):
                digest.update(block)
                size += len(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        after = source.lstat()
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ):
            fail("upload artifact changed during sealing")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    actual = digest.hexdigest()
    if actual != expected:
        destination.unlink(missing_ok=True)
        fail("sealed artifact SHA-256 does not match approved policy")
    os.chmod(destination, 0o640)
    return {"source": str(source), "sealed": str(sealed_relative), "sha256": actual, "size": size}


def _sealed_member(root: Path, value: object, *, directory: bool = False) -> Path:
    """Resolve a receipt-relative member without allowing receipt redirection."""
    if not isinstance(value, str):
        fail("sealed artifact receipt member is invalid")
    relative = Path(value)
    if not value or value.startswith(("/", "\\")) or relative.is_absolute() or ".." in relative.parts:
        fail("sealed artifact receipt member must be a relative non-traversing path")
    member = root / relative
    try:
        member.relative_to(root)
    except ValueError:
        fail("sealed artifact receipt member escapes the sealed release root")
    if member.is_symlink() or not member.exists() or (not member.is_dir() if directory else not member.is_file()):
        fail("sealed artifact receipt member is missing or unsafe")
    return member


def _validate_sealed_artifacts(value: dict[str, object], final: Path, policy_hash: str) -> SealedArtifacts:
    """Reopen only the fixed final release directory and verify its receipt."""
    release = str(value["server_release_id"])
    if final != SEALED_ROOT / release or final.is_symlink() or not final.is_dir():
        fail("existing sealed artifact directory is unsafe")
    web.require_root_chain(final)
    web.require_root_tree(final)
    receipt_path = final / "sealing-receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        fail("existing sealed artifact directory is unsafe")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"sealed artifact receipt is invalid: {error}")
    if receipt.get("schema") != SEALING_RECEIPT_SCHEMA_VERSION:
        if ".sealing-" in json.dumps(receipt, sort_keys=True):
            fail("sealed artifact receipt uses obsolete temporary-path schema and cannot be reused")
        fail("sealed artifact receipt schema is unsupported")
    if (
        receipt.get("application_version") != value["application_version"]
        or receipt.get("source_commit") != value["source_commit"]
        or receipt.get("coordinator_version") != HELPER_VERSION
        or receipt.get("policy_semantic_sha256") != policy_hash
        or receipt.get("sealed_release_id") != release
    ):
        fail("sealed artifact receipt does not match the approved policy or coordinator")
    archive = _sealed_member(final, receipt.get("server_archive"))
    manifest = _sealed_member(final, receipt.get("server_manifest"))
    bundle = _sealed_member(final, receipt.get("sealed_bundle"), directory=True)
    records = receipt.get("files")
    if not isinstance(records, list):
        fail("sealed artifact receipt file inventory is invalid")
    recorded: set[str] = set()
    for record in records:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("sha256"), str)
            or not isinstance(record.get("size"), int)
        ):
            fail("sealed artifact receipt file record is invalid")
        member = _sealed_member(final, record.get("sealed"))
        relative = str(member.relative_to(final))
        if relative in recorded:
            fail("sealed artifact receipt has duplicate file records")
        recorded.add(relative)
        if web.sha256(member) != record["sha256"] or member.stat().st_size != record["size"]:
            fail("sealed artifact receipt member no longer matches its recorded hash or size")
    required = {str(archive.relative_to(final)), str(manifest.relative_to(final))}
    if not required.issubset(recorded):
        fail("sealed artifact receipt does not record required server artifacts")
    verified = web.verify_bundle(bundle, str(value["bundle_sha256"]))
    if receipt.get("bundle_sha256") != verified["bundle_sha256"]:
        fail("sealed artifact receipt bundle hash does not match the verified bundle")
    return SealedArtifacts(
        root=final,
        server_archive=archive,
        server_manifest=manifest,
        bundle=bundle,
        receipt_path=receipt_path,
        policy_semantic_sha256=policy_hash,
        bundle_sha256=verified["bundle_sha256"],
    )


def seal_artifacts(value: dict[str, object]) -> SealedArtifacts:
    """Copy approved uploads into a root-owned immutable coordinator zone."""
    archive = _upload_member(value["server_archive_path"])
    manifest = _upload_member(value["server_manifest_path"])
    bundle = _upload_member(value["bundle_path"], directory=True)
    policy_hash = _policy_digest(value)
    release = str(value["server_release_id"])
    if not __import__("re").fullmatch(r"[A-Za-z0-9._-]+", release):
        fail("sealed release identifier is invalid")
    SEALED_ROOT.mkdir(parents=True, mode=0o700, exist_ok=True)
    web.require_root_owned(SEALED_ROOT)
    web.require_root_chain(SEALED_ROOT)
    final = SEALED_ROOT / release
    if final.exists():
        return _validate_sealed_artifacts(value, final, policy_hash)
    temporary = SEALED_ROOT / (".sealing-" + uuid.uuid4().hex)
    try:
        temporary.mkdir(mode=0o700)
        records = [
            _copy_sealed_file(
                archive, temporary / "server.zip", str(value["server_archive_sha256"]), Path("server.zip")
            ),
            _copy_sealed_file(
                manifest,
                temporary / "server.manifest.json",
                str(value["server_manifest_sha256"]),
                Path("server.manifest.json"),
            ),
        ]
        sealed_bundle = temporary / "bundle"
        sealed_bundle.mkdir(mode=0o700)
        for item in sorted(bundle.rglob("*")):
            relative = item.relative_to(bundle)
            if item.is_symlink() or not item.is_file():
                if item.is_dir():
                    (sealed_bundle / relative).mkdir(mode=0o700, parents=True, exist_ok=True)
                    continue
                fail("frontend upload bundle contains an unsafe member")
            destination = sealed_bundle / relative
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            # Bundle files are verified by the signed bundle manifest after copy.
            records.append(_copy_sealed_file(item, destination, web.sha256(item), Path("bundle") / relative))
        verified = web.verify_bundle(sealed_bundle, str(value["bundle_sha256"]))
        receipt = {
            "schema": SEALING_RECEIPT_SCHEMA_VERSION,
            "application_version": value["application_version"],
            "source_commit": value["source_commit"],
            "coordinator_version": HELPER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "policy_semantic_sha256": policy_hash,
            "sealed_release_id": release,
            "server_archive": "server.zip",
            "server_manifest": "server.manifest.json",
            "files": records,
            "sealed_bundle": "bundle",
            "bundle_sha256": verified["bundle_sha256"],
        }
        (temporary / "sealing-receipt.json").write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        os.chmod(temporary / "sealing-receipt.json", 0o600)
        web.require_root_tree(temporary)
        os.replace(temporary, final)
        if os.name != "nt" and hasattr(os, "O_DIRECTORY"):
            descriptor = os.open(SEALED_ROOT, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return _validate_sealed_artifacts(value, final, policy_hash)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        raise


def sealed_policy(value: dict[str, object]) -> dict[str, object]:
    sealed = seal_artifacts(value)
    result = dict(value)
    result.update(
        server_archive_path=str(sealed.server_archive),
        server_manifest_path=str(sealed.server_manifest),
        bundle_path=str(sealed.bundle),
    )
    return result


def safe_zip_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    for member in members:
        path = Path(member.filename)
        mode = member.external_attr >> 16
        if path.is_absolute() or ".." in path.parts or (mode & 0o170000) == 0o120000:
            fail(f"unsafe server archive member: {member.filename}")
    return members


def extract_server(policy: dict[str, object], transaction: Path) -> Path:
    archive = Path(str(policy["server_archive_path"]))
    if not archive.is_file() or web.sha256(archive) != policy["server_archive_sha256"]:
        fail("server archive SHA-256 does not match approved policy")
    external_manifest = Path(str(policy["server_manifest_path"]))
    if not external_manifest.is_file() or web.sha256(external_manifest) != policy["server_manifest_sha256"]:
        fail("server package manifest SHA-256 does not match approved policy")
    external = json.loads(external_manifest.read_text(encoding="utf-8"))
    if external.get("archive_sha256") != policy["server_archive_sha256"]:
        fail("server package manifest archive SHA-256 does not match approved policy")
    target = API_RELEASES / str(policy["server_release_id"])
    staging = API_RELEASES / (".staging-" + transaction.name)
    if target.exists() or staging.exists():
        fail("refusing to overwrite an existing API release")
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = safe_zip_members(bundle)
            staging.mkdir(mode=0o750)
            for member in members:
                if member.is_dir():
                    (staging / member.filename).mkdir(parents=True, exist_ok=True)
                    continue
                destination = staging / member.filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
            metadata_path = staging / "release_metadata.json"
            if not metadata_path.is_file():
                fail("extracted server release metadata is missing")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            for key, expected in {
                "app_version": policy["application_version"],
                "source_git_commit": policy["source_commit"],
                "database_schema_revision": policy["schema"],
            }.items():
                if metadata.get(key) != expected:
                    fail(f"server release metadata {key} does not match approved policy")
            inventory = external.get("migration_inventory", {})
            migration_record = inventory.get("server/migrations/versions/20260721_0008_data_state_freshness.py", {})
            if migration_record.get("zip_embedded_sha256") != policy["canonical_migration_sha256"]:
                fail("server package manifest canonical migration hash is invalid")
            migration = staging / "server/migrations/versions/20260721_0008_data_state_freshness.py"
            if not migration.is_file() or web.sha256(migration) != policy["canonical_migration_sha256"]:
                fail("extracted canonical migration SHA-256 does not match approved policy")
            old_venv = API_CURRENT.resolve() / "venv"
            if not old_venv.is_dir():
                fail("current API virtual environment is unavailable")
            (staging / "venv").symlink_to(old_venv)
            # The staged release links its interpreter to the already-active
            # immutable virtualenv.  Physical traversal is mandatory: following
            # that link would mutate the previous release during staging.
            subprocess.run(["/usr/bin/chown", "-hR", "eoat-atlas:eoat-atlas", str(staging)], check=True)
            os.replace(staging, target)
    except Exception:
        if staging.exists() or staging.is_symlink():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


def policy(path: Path) -> dict[str, object]:
    web.require_root_owned(Path(__file__).resolve(), executable=True)
    web.require_root_owned(path)
    web.require_root_chain(Path(__file__).resolve())
    web.require_root_chain(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        if path.read_bytes().startswith(b"\xef\xbb\xbf"):
            fail("coordinated policy must be UTF-8 without a BOM")
        raise
    required = {
        "helper_sha256",
        "web_helper_sha256",
        "server_archive_path",
        "server_archive_sha256",
        "server_manifest_path",
        "server_manifest_sha256",
        "server_release_id",
        "web_release_id",
        "bundle_path",
        "bundle_sha256",
        "application_version",
        "source_commit",
        "schema",
        "canonical_migration_sha256",
        "expected_active_api",
        "expected_active_web",
    }
    web_program = Path(web.__file__).resolve()
    if (
        not required.issubset(value)
        or web.sha256(Path(__file__).resolve()) != value["helper_sha256"]
        or web.sha256(web_program) != value["web_helper_sha256"]
    ):
        fail("coordinated deployment policy or helper SHA-256 is invalid")
    return value


def migration_plan(value: dict[str, object]) -> tuple[str, str, tuple[dict[str, str], ...]]:
    """Validate an optional policy-pinned migration traversal before mutation.

    The historical zero-migration policy shape remains valid.  Migration-bearing
    policies must make the exact starting head, target head, ordered revisions,
    and source-file hashes explicit; callers never supply executable commands.
    """
    raw = value.get("migration_plan")
    if raw is None:
        return str(value["schema"]), str(value["schema"]), ()
    if not isinstance(raw, dict):
        fail("migration plan is not an object")
    current, target, revisions = raw.get("current_schema"), raw.get("target_schema"), raw.get("revisions")
    if not isinstance(current, str) or not MIGRATION_REVISION.fullmatch(current):
        fail("migration plan current schema is invalid")
    if not isinstance(target, str) or target != value.get("schema") or not MIGRATION_REVISION.fullmatch(target):
        fail("migration plan target schema is invalid")
    if not isinstance(revisions, list):
        fail("migration plan revisions are invalid")
    checked: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in revisions:
        if not isinstance(item, dict):
            fail("migration plan revision is invalid")
        revision, sha256 = item.get("revision"), item.get("sha256")
        if (
            not isinstance(revision, str)
            or not MIGRATION_REVISION.fullmatch(revision)
            or not isinstance(sha256, str)
            or not SHA256.fullmatch(sha256)
            or revision in seen
        ):
            fail("migration plan revision identity is invalid")
        seen.add(revision)
        checked.append({"revision": revision, "sha256": sha256})
    if current == target:
        if checked:
            fail("zero-migration plan must not contain revisions")
    elif not checked or checked[-1]["revision"] != target:
        fail("migration plan does not deterministically reach the target schema")
    return current, target, tuple(checked)


def _archive_migration_graph(archive: zipfile.ZipFile) -> dict[str, tuple[str, ...]]:
    graph: dict[str, tuple[str, ...]] = {}
    for name in archive.namelist():
        if not name.startswith("server/migrations/versions/") or not name.endswith(".py"):
            continue
        try:
            tree = ast.parse(archive.read(name).decode("utf-8"), filename=name)
        except (SyntaxError, UnicodeDecodeError):
            fail("sealed archive migration source is unreadable")
        values: dict[str, object] = {}
        for node in tree.body:
            target_node = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target_node = node.targets[0]
            elif isinstance(node, ast.AnnAssign):
                target_node = node.target
            if isinstance(target_node, ast.Name) and target_node.id in {"revision", "down_revision"}:
                try:
                    values[target_node.id] = ast.literal_eval(node.value)
                except ValueError:
                    fail("sealed archive migration revision metadata is unsafe")
        revision, down = values.get("revision"), values.get("down_revision")
        if not isinstance(revision, str) or not MIGRATION_REVISION.fullmatch(revision):
            continue
        if isinstance(down, str):
            parents = (down,)
        elif isinstance(down, tuple) and all(isinstance(item, str) for item in down):
            parents = down
        elif down is None:
            parents = ()
        else:
            fail("sealed archive migration predecessor metadata is unsafe")
        if revision in graph or any(not MIGRATION_REVISION.fullmatch(parent) for parent in parents):
            fail("sealed archive migration graph is ambiguous")
        graph[revision] = parents
    return graph


def _migration_ancestors(graph: dict[str, tuple[str, ...]], revision: str, visiting: set[str] | None = None) -> set[str]:
    if revision not in graph:
        fail("sealed archive does not contain the approved current migration revision")
    visiting = set() if visiting is None else visiting
    if revision in visiting:
        fail("sealed archive migration graph contains a cycle")
    visiting.add(revision)
    result = {revision}
    for parent in graph[revision]:
        result.update(_migration_ancestors(graph, parent, visiting))
    visiting.remove(revision)
    return result


def validate_migration_archive(
    archive_path: Path, revisions: tuple[dict[str, str], ...], *, current: str | None = None
) -> None:
    """Prove every approved migration is present exactly once in the sealed API ZIP."""
    if not revisions:
        return
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            for item in revisions:
                prefix = f"server/migrations/versions/{item['revision']}_"
                matches = [name for name in names if name.startswith(prefix) and name.endswith(".py")]
                if len(matches) != 1:
                    fail("sealed archive does not contain exactly one approved migration revision")
                if hashlib.sha256(archive.read(matches[0])).hexdigest() != item["sha256"]:
                    fail("sealed archive migration hash does not match the approved policy")
            if current is not None:
                graph = _archive_migration_graph(archive)
                applied = _migration_ancestors(graph, current)
                for item in revisions:
                    revision = item["revision"]
                    if revision not in graph or revision in applied:
                        fail("sealed archive migration traversal is not a missing deterministic successor")
                    if not all(parent in applied for parent in graph[revision]):
                        fail("sealed archive migration traversal has a missing predecessor")
                    applied.add(revision)
    except zipfile.BadZipFile as error:
        fail(f"sealed archive cannot be inspected for migration evidence: {error}")


def _migration_environment() -> dict[str, str]:
    """Load only the fixed, root-owned local production migration profile."""
    try:
        info = MIGRATION_ENVIRONMENT.stat()
        if os.name != "nt" and (info.st_uid != 0 or info.st_mode & 0o077):
            fail("migration environment ownership or permissions are unsafe")
        raw = MIGRATION_ENVIRONMENT.read_text(encoding="utf-8")
    except OSError as error:
        fail("protected migration environment is unavailable")
        raise AssertionError from error  # pragma: no cover - fail always raises
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            fail("protected migration environment is malformed")
        key, item = line.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,80}", key) or "\x00" in item:
            fail("protected migration environment is malformed")
        item = item.strip()
        if item.startswith(("'", '"')):
            try:
                parsed = shlex.split(item, posix=True)
            except ValueError:
                fail("protected migration environment is malformed")
            if len(parsed) != 1:
                fail("protected migration environment is malformed")
            item = parsed[0]
        values[key] = item
    if values.get("EOAT_API_ENVIRONMENT", "production").casefold() != "production":
        fail("migration environment is not production")
    if values.get("EOAT_API_WRITES_ENABLED", "false").casefold() in {"1", "true", "yes", "on"}:
        fail("migration environment enables writes")
    user = values.get("EOAT_DB_MIGRATION_USER") or values.get("EOAT_MIGRATION_DB_USER") or values.get("EOAT_DB_USER")
    if not user or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", user):
        fail("migration account is unavailable")
    if values.get("EOAT_DB_NAME") != PRODUCTION_DATABASE:
        fail("migration environment database is not the fixed production database")
    if values.get("EOAT_DB_HOST") != "127.0.0.1" or values.get("EOAT_DB_PORT") != "3306":
        fail("migration environment must use the fixed local MySQL endpoint")
    values["EOAT_MIGRATION_DB_USER"] = user
    return {
        "HOME": "/root",
        "LANG": "C.UTF-8",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        **values,
    }


def _mysql_option_value(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _root_socket_environment() -> dict[str, str]:
    return {"HOME": "/root", "LANG": "C.UTF-8", "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}


@contextlib.contextmanager
def _mysql_defaults(environment: dict[str, str]):
    """Yield a one-use root-only client option file without serializing secrets."""
    password = (
        environment.get("EOAT_DB_MIGRATION_PASSWORD")
        or environment.get("EOAT_MIGRATION_DB_PASSWORD")
        or environment.get("EOAT_DB_PASSWORD")
    )
    if password is None:
        fail("migration account password is unavailable")
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=MIGRATION_ENVIRONMENT.parent, prefix=".eoat-mysql-", delete=False
        ) as stream:
            path = Path(stream.name)
            stream.write("[client]\n")
            stream.write(f"user={_mysql_option_value(environment['EOAT_MIGRATION_DB_USER'])}\n")
            stream.write(f"password={_mysql_option_value(password)}\n")
            stream.write(f"host={_mysql_option_value(environment['EOAT_DB_HOST'])}\n")
            stream.write(f"port={_mysql_option_value(environment['EOAT_DB_PORT'])}\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(path, 0o600)
        yield path
    except OSError:
        fail("secure MySQL defaults file is unavailable")
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def _run_governed(command: list[str], *, environment: dict[str, str], cwd: Path | None = None, purpose: str) -> subprocess.CompletedProcess[str]:
    """Run a fixed command, retaining only a non-sensitive failure category."""
    result = subprocess.run(command, text=True, capture_output=True, check=False, cwd=cwd, env=environment)
    if result.returncode:
        output = f"{result.stderr or ''}\n{result.stdout or ''}".casefold()
        if "access denied" in output or "error 1045" in output:
            category = "database authentication or authorization failed"
        elif "command denied" in output or "couldn't execute" in output or "could not execute" in output:
            category = "required database privilege unavailable"
        elif "can't connect" in output or "connection refused" in output:
            category = "database connectivity failed"
        elif "no space left" in output or "got errno" in output:
            category = "approved backup storage write failed"
        else:
            category = f"approved command exited nonzero (exit status {result.returncode})"
        fail(f"approved command failed: {purpose} ({category})")
    return result


def _staged_alembic_command(server: Path, action: str, target: str | None = None) -> list[str]:
    python = server / "venv" / "bin" / "python"
    config = server / "server" / "alembic.ini"
    if not python.is_file() or not config.is_file() or server.parent != API_RELEASES:
        fail("verified staged migration environment is unavailable")
    command = [str(python), "-m", "alembic", "-c", str(config), action]
    if target is not None:
        command.append(target)
    return command


def _staged_alembic_current(server: Path, environment: dict[str, str]) -> str:
    result = _run_governed(
        _staged_alembic_command(server, "current"),
        environment=environment,
        cwd=server,
        purpose="approved migration revision query",
    )
    matches = re.findall(r"\b\d{8}_\d{4}(?:_[A-Za-z0-9_-]+)?\b", result.stdout or "")
    if len(matches) != 1:
        fail("migration revision query returned an unexpected result")
    return matches[0]


def _backup_path(transaction: Path) -> Path:
    path = transaction / "pre-migration.sql.gz"
    if path.exists() or path.is_symlink() or path.parent != transaction:
        fail("production backup path is unsafe or already exists")
    return path


def create_and_verify_backup(transaction: Path) -> dict[str, object]:
    """Create a compressed fixed-production backup and validate its evidence."""
    environment = _migration_environment()
    target = _backup_path(transaction)
    partial = transaction / "pre-migration.sql.partial"
    if partial.exists() or partial.is_symlink():
        fail("production backup partial path is unsafe")
    try:
        identity = "migration_account"
        with _mysql_defaults(environment) as defaults:
            _run_governed(
                ["/usr/bin/mysql", f"--defaults-extra-file={defaults}", "--batch", "--skip-column-names", "--execute", "SELECT 1", PRODUCTION_DATABASE],
                environment=environment,
                purpose="approved migration database connection probe",
            )
            _run_governed(
                ["/usr/bin/mysql", f"--defaults-extra-file={defaults}", "--batch", "--skip-column-names", "--execute", "SHOW TABLES; SHOW EVENTS; SHOW TRIGGERS", PRODUCTION_DATABASE],
                environment=environment,
                purpose="approved backup metadata privilege probe",
            )
            stored = _run_governed(
                [
                    "/usr/bin/mysql", f"--defaults-extra-file={defaults}", "--batch", "--skip-column-names", "--execute",
                    "SELECT (SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE()), (SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA = DATABASE())",
                    PRODUCTION_DATABASE,
                ],
                environment=environment,
                purpose="approved backup completeness probe",
            )
            counts = re.fullmatch(r"\s*(\d+)\s+(\d+)\s*", stored.stdout or "")
            if not counts:
                fail("approved backup completeness probe returned an unexpected result")
            if counts.group(1) == counts.group(2) == "0":
                _run_governed(
                    ["/usr/bin/mysqldump", f"--defaults-extra-file={defaults}", "--single-transaction", "--no-tablespaces", f"--result-file={partial}", PRODUCTION_DATABASE],
                    environment=environment,
                    purpose="approved production backup",
                )
            else:
                root = _root_socket_environment()
                _run_governed(
                    ["/usr/bin/mysql", "--protocol=socket", "--batch", "--skip-column-names", "--execute", "SELECT 1", PRODUCTION_DATABASE],
                    environment=root,
                    purpose="approved root socket backup identity probe",
                )
                _run_governed(
                    ["/usr/bin/mysqldump", "--protocol=socket", "--single-transaction", "--no-tablespaces", "--routines", "--events", f"--result-file={partial}", PRODUCTION_DATABASE],
                    environment=root,
                    purpose="approved root socket production backup",
                )
                identity = "root_local_socket"
        if not partial.is_file() or partial.stat().st_size < 16:
            fail("production backup is empty or incomplete")
        with partial.open("rb") as source, gzip.open(target, "wb") as compressed:
            shutil.copyfileobj(source, compressed)
        os.chmod(target, 0o600)
        with gzip.open(target, "rb") as stream:
            if not stream.read(4096):
                fail("production backup verification failed")
        digest = web.sha256(target)
        if target.stat().st_size < 16 or not SHA256.fullmatch(digest):
            fail("production backup verification failed")
        return {
            "path": str(target), "sha256": digest, "size_bytes": target.stat().st_size, "identity": identity, "verified": True
        }
    except (OSError, web.InstallError):
        partial.unlink(missing_ok=True)
        raise
    finally:
        partial.unlink(missing_ok=True)


def restore_backup(backup: object) -> None:
    """Restore only the receipt-bound verified backup to the fixed database."""
    if not isinstance(backup, dict):
        fail("verified deployment backup is unavailable")
    path = Path(str(backup.get("path") or ""))
    if (
        path.parent.parent != CONTROL_ROOT / "transactions"
        or path.name != "pre-migration.sql.gz"
        or path.is_symlink()
        or not path.is_file()
        or web.sha256(path) != backup.get("sha256")
    ):
        fail("backup restoration checksum validation failed")
    if backup.get("identity") == "root_local_socket":
        environment = _root_socket_environment()
        command = ["/usr/bin/mysql", "--protocol=socket", PRODUCTION_DATABASE]
        defaults_context: contextlib.AbstractContextManager[Path | None] = contextlib.nullcontext(None)
    elif backup.get("identity") == "migration_account":
        environment = _migration_environment()
        defaults_context = _mysql_defaults(environment)
        command = ["/usr/bin/mysql", PRODUCTION_DATABASE]
    else:
        fail("backup restoration identity is invalid")
    with defaults_context as defaults, gzip.open(path, "rb") as stream:
        if defaults is not None:
            command.insert(1, f"--defaults-extra-file={defaults}")
        result = subprocess.run(command, stdin=stream, stderr=subprocess.PIPE, check=False, env=environment)
    if result.returncode:
        fail("approved backup restoration failed")


def apply_migration_plan(server: Path, plan: tuple[str, str, tuple[dict[str, str], ...]], backup: dict[str, object]) -> dict[str, object]:
    """Apply the one sealed, policy-pinned traversal and verify its exact head."""
    current, target, revisions = plan
    if not revisions:
        return {"current_schema": current, "target_schema": target, "applied": False}
    environment = _migration_environment()
    if _staged_alembic_current(server, environment) != current:
        fail("production schema does not match the approved migration-plan start")
    try:
        _run_governed(
            _staged_alembic_command(server, "upgrade", target),
            environment=environment,
            cwd=server,
            purpose="approved multi-revision production migration",
        )
        if _staged_alembic_current(server, environment) != target:
            fail("approved migration did not reach the policy target revision")
    except Exception:
        try:
            restore_backup(backup)
        except Exception:
            fail("migration failed and verified backup restoration failed")
        if _staged_alembic_current(server, environment) != current:
            fail("migration failed and backup did not restore the approved starting revision")
        raise
    return {
        "current_schema": current,
        "target_schema": target,
        "revisions": [item["revision"] for item in revisions],
        "applied": True,
    }


@contextlib.contextmanager
def deployment_lock():
    """Hold the one fixed deployment lock for the entire mutation window."""
    if os.name == "nt":  # pragma: no cover - production helper is Linux-only
        fail("deployment locking requires the Linux coordinator host")
    try:
        import fcntl

        descriptor = os.open(DEPLOYMENT_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (ImportError, OSError):
        fail("deployment lock is already held or unavailable")
    try:
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def wait_target(value: dict[str, object]) -> None:
    health = web.api_health(value)
    if health.get("application_version") != value["application_version"]:
        fail("active API version does not match coordinated release")


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _direct_release(path_text: object, root: Path, field: str) -> Path:
    path = Path(str(path_text))
    if (
        not path.is_absolute()
        or ".." in path.parts
        or path.is_symlink()
        or not path.is_dir()
        or path.parent != root
        or path == root
    ):
        fail(f"receipt {field} is not a direct approved release directory")
    return path


def _service_identity() -> tuple[int, int]:
    """Return the fixed service account only on the Linux coordinator host."""
    if pwd is None or grp is None:
        fail("service-owned API release validation requires the Linux coordinator host")
    try:
        account = pwd.getpwnam("eoat-atlas")
        group = grp.getgrnam("eoat-atlas")
    except KeyError:
        fail("configured EOAT Atlas service account is unavailable")
    if account.pw_gid != group.gr_gid:
        fail("configured EOAT Atlas service account/group identity is inconsistent")
    return account.pw_uid, group.gr_gid


def _safe_mode(path: Path, info: os.stat_result, *, owner_uid: int, owner_gid: int) -> None:
    if info.st_uid != owner_uid or info.st_gid != owner_gid:
        fail(f"service-owned API release ownership is invalid: {path}")
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        fail(f"service-owned API release contains group/world writable content: {path}")


def _api_release_parent_chain(service_gid: int) -> None:
    """Validate the governed root/service-group release-root boundary.

    The API payload itself is deliberately owned by eoat-atlas.  Its release
    root and ancestors remain root-owned, non-writable control points and may
    use the fixed service group for read/execute access.
    """
    current = API_RELEASES
    while current != current.parent:
        if current.is_symlink() or not current.is_dir():
            fail("API release root chain is unsafe")
        info = current.lstat()
        if not _api_release_parent_is_safe(info, service_gid):
            fail(f"API release root ownership is invalid: {current}")
        current = current.parent


def _api_release_parent_is_safe(info: os.stat_result, service_gid: int) -> bool:
    return (
        info.st_uid == 0
        and info.st_gid in {0, service_gid}
        and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    )


def _legacy_transaction_path(transaction_id: str) -> tuple[Path, Path]:
    """Return only a direct, root-governed transaction receipt path."""
    if not TRANSACTION_ID.fullmatch(transaction_id):
        fail("transaction identifier is invalid")
    transactions = CONTROL_ROOT / "transactions"
    transaction = transactions / transaction_id
    receipt_path = transaction / "receipt.json"
    if (
        transaction.is_symlink()
        or receipt_path.is_symlink()
        or not transaction.is_dir()
        or not receipt_path.is_file()
        or not _within(transaction, transactions)
    ):
        fail("transaction receipt is not a direct governed receipt")
    web.require_root_chain(transactions)
    web.require_root_chain(transaction)
    web.require_root_owned(receipt_path)
    return transaction, receipt_path


def _load_legacy_schema2_transaction(transaction_id: str) -> tuple[Path, dict[str, object]]:
    """Load the one historical receipt shape eligible for no-op reconciliation."""
    transaction, receipt_path = _legacy_transaction_path(transaction_id)
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"transaction receipt is malformed: {error}")
    if not isinstance(receipt, dict):
        fail("transaction receipt is malformed")
    required = {
        "receipt_schema_version",
        "helper_version",
        "state",
        "activation_complete",
        "old_api",
        "old_web",
        "new_api",
        "new_web",
        "schema",
        "service",
        "writes_enabled",
    }
    if not required.issubset(receipt):
        fail("legacy transaction receipt is incomplete")
    if receipt["receipt_schema_version"] != LEGACY_TRANSACTION_RECEIPT_SCHEMA_VERSION:
        fail("legacy reconciliation supports only transaction receipt schema 2")
    if receipt["helper_version"] != LEGACY_HELPER_VERSION:
        fail("legacy transaction helper identity is invalid")
    if receipt["state"] != "active" or receipt["activation_complete"] is not True:
        fail("legacy transaction did not complete activation")
    if receipt["service"] != SERVICE or receipt["writes_enabled"] is not False:
        fail("legacy transaction violates governed rollback policy")
    if receipt["schema"] != LEGACY_SCHEMA:
        fail("legacy transaction schema is not the governed compatibility schema")
    old_api = _direct_release(receipt["old_api"], API_RELEASES, "old_api")
    old_web = _direct_release(receipt["old_web"], WEB_RELEASES, "old_web")
    new_api = _direct_release(receipt["new_api"], API_RELEASES, "new_api")
    new_web = _direct_release(receipt["new_web"], WEB_RELEASES, "new_web")
    if old_api == new_api or old_web == new_web:
        fail("legacy transaction old and new release targets must differ")
    service_uid, service_gid = _service_identity()
    _api_release_parent_chain(service_gid)
    _safe_mode(new_api, new_api.lstat(), owner_uid=service_uid, owner_gid=service_gid)
    web.require_root_chain(new_web)
    web.require_root_tree(new_web)
    return transaction, receipt


def _require_legacy_current_targets(receipt: dict[str, object]) -> tuple[Path, Path]:
    old_api = _direct_release(receipt["old_api"], API_RELEASES, "old_api")
    old_web = _direct_release(receipt["old_web"], WEB_RELEASES, "old_web")
    if (
        not API_CURRENT.is_symlink()
        or not WEB_CURRENT.is_symlink()
        or API_CURRENT.resolve() != old_api
        or WEB_CURRENT.resolve() != old_web
    ):
        fail("legacy transaction is not already physically rolled back to both old targets")
    return old_api, old_web


def _require_no_newer_unfinished_transaction(transaction: Path) -> None:
    """Refuse to reconcile historical evidence across a later unknown state."""
    transactions = CONTROL_ROOT / "transactions"
    for candidate in sorted(transactions.iterdir()):
        # This root deliberately retains older non-coordinator deployment
        # evidence. Only direct governed coordinator IDs are part of this
        # helper's recovery state machine.
        if not TRANSACTION_ID.fullmatch(candidate.name):
            continue
        if candidate == transaction or candidate.name <= transaction.name:
            continue
        if candidate.is_symlink() or not candidate.is_dir():
            fail("newer transaction inventory is unsafe")
        receipt_path = candidate / "receipt.json"
        if receipt_path.is_symlink() or not receipt_path.is_file():
            fail("newer transaction receipt is unsafe")
        web.require_root_chain(candidate)
        web.require_root_owned(receipt_path)
        try:
            newer = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            fail(f"newer transaction receipt is malformed: {error}")
        if not isinstance(newer, dict) or newer.get("state") != "rolled_back":
            fail("newer deployment or recovery transaction remains unresolved")


def _data_state_singleton() -> dict[str, object]:
    """Read the one production data-state table without configuration access."""
    discovery = subprocess.run(
        [
            "/usr/bin/mysql",
            "-N",
            "-e",
            "SELECT table_schema FROM information_schema.tables "
            "WHERE table_name='data_state' ORDER BY table_schema",
        ],
        text=True,
        capture_output=True,
    )
    schemas = [line.strip() for line in discovery.stdout.splitlines() if line.strip()]
    if discovery.returncode or len(schemas) != 1 or not re.fullmatch(r"[A-Za-z0-9_]+", schemas[0]):
        fail("unable to prove a unique governed data_state table")
    schema = schemas[0]
    count_result = subprocess.run(
        ["/usr/bin/mysql", "-N", "-e", f"SELECT COUNT(*) FROM `{schema}`.data_state"],
        text=True,
        capture_output=True,
    )
    if count_result.returncode or count_result.stdout.strip() != "1":
        fail("data_state singleton integrity check failed")
    return {"schema": schema, "count": 1}


def _legacy_runtime_evidence(transaction: Path, receipt: dict[str, object]) -> dict[str, object]:
    """Produce fresh evidence for a schema-2 receipt without modifying it."""
    old_api, old_web = _require_legacy_current_targets(receipt)
    _require_no_newer_unfinished_transaction(transaction)
    if Path("/var/lock/eoat-atlas-deploy.lock").exists():
        fail("deployment lock is present")
    _, api_attestation = _api_release_attestation(old_api, "old_api")
    _, web_attestation = _web_release_attestation(old_web, "old_web")
    health = web.api_health({"schema": LEGACY_SCHEMA})
    if (
        health.get("application_version") != LEGACY_APPLICATION_VERSION
        or health.get("release_id") != f"eoat-atlas-{LEGACY_APPLICATION_VERSION}"
    ):
        fail("active API product identity is not the governed legacy release")
    nginx = subprocess.run(["/usr/sbin/nginx", "-t"], text=True, capture_output=True)
    if nginx.returncode:
        fail("nginx validation failed for legacy reconciliation")
    services: dict[str, str] = {}
    for unit in (SERVICE, "nginx.service"):
        result = subprocess.run(["/bin/systemctl", "is-active", unit], text=True, capture_output=True)
        if result.returncode or result.stdout.strip() != "active":
            fail(f"required service is not active: {unit}")
        services[unit] = "active"
    return {
        "rollback_api": str(old_api),
        "rollback_web": str(old_web),
        "active_pointer_identities": {
            "api": {"path": str(API_CURRENT), "target": str(old_api)},
            "web": {"path": str(WEB_CURRENT), "target": str(old_web)},
        },
        "api_attestation": api_attestation,
        "web_attestation": web_attestation,
        "application_version": LEGACY_APPLICATION_VERSION,
        "schema": LEGACY_SCHEMA,
        "writes_enabled": False,
        "api_health": health,
        "nginx_validation": "passed",
        "service_states": services,
        "data_state": _data_state_singleton(),
    }


def _metadata_identity(path: Path, release: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"API release metadata is invalid: {error}")
    if not isinstance(payload, dict):
        fail("API release metadata is invalid")
    version = payload.get("app_version")
    source = payload.get("source_git_commit")
    schema = payload.get("database_schema_revision")
    release_id = payload.get("release_id")
    if (
        not isinstance(version, str)
        or not re.fullmatch(r"\d+\.\d+\.\d+", version)
        or not isinstance(source, str)
        or not re.fullmatch(r"[0-9a-f]{40}", source.lower())
        or not isinstance(schema, str)
        or not re.fullmatch(r"\d{8}_\d{4}(?:_[A-Za-z0-9_-]+)?", schema)
        or release_id != f"eoat-atlas-{version}"
        or not release.name.startswith(f"eoat-atlas-server-{version}-")
    ):
        fail("API release metadata does not match its governed release identity")
    return {
        "metadata_sha256": web.sha256(path),
        "application_version": version,
        "source_commit": source.lower(),
        "schema": schema,
        "release_id": release_id,
    }


def _api_release_attestation(path_text: object, field: str) -> tuple[Path, dict[str, object]]:
    """Validate and identify a service-owned immutable API release.

    This is intentionally separate from root-tree validation.  It is the only
    approved exception for API payloads created by extract_server(), which
    applies eoat-atlas:eoat-atlas ownership before the release is made active.
    """
    path = _direct_release(path_text, API_RELEASES, field)
    service_uid, service_gid = _service_identity()
    _api_release_parent_chain(service_gid)
    root_info = path.lstat()
    _safe_mode(path, root_info, owner_uid=service_uid, owner_gid=service_gid)
    metadata_path = path / "release_metadata.json"
    if metadata_path.is_symlink() or not metadata_path.is_file():
        fail("API release metadata is missing or unsafe")
    inventory: dict[str, str] = {}
    venv: dict[str, str] | None = None
    for current, directories, files in os.walk(path, followlinks=False):
        directory = Path(current)
        for name in [*directories, *files]:
            member = directory / name
            relative = member.relative_to(path).as_posix()
            info = member.lstat()
            if stat.S_ISLNK(info.st_mode):
                raw_target = os.readlink(member)
                resolved = member.resolve(strict=False)
                if relative == "venv":
                    if (
                        not raw_target
                        or not resolved.is_dir()
                        or not _within(resolved, API_RELEASES)
                        or resolved.name != "venv"
                        or resolved.parent.parent != API_RELEASES
                    ):
                        fail("API release virtual-environment linkage is unsafe")
                    venv = {"path": relative, "target": str(resolved)}
                    continue
                embedded_root = path / "venv"
                approved_embedded_python = (
                    member.parent == embedded_root / "bin"
                    and re.fullmatch(r"python(?:3(?:\.\d+)?)?", member.name) is not None
                    and resolved == SYSTEM_PYTHON
                )
                if (
                    venv is not None
                    and venv.get("embedded") is True
                    and relative.startswith("venv/")
                    and raw_target
                    and (_within(resolved, embedded_root) or approved_embedded_python)
                ):
                    continue
                fail(f"unsafe API release symlink: {member}")
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                fail(f"unsafe API release member: {member}")
            _safe_mode(member, info, owner_uid=service_uid, owner_gid=service_gid)
            if relative == "venv" and stat.S_ISDIR(info.st_mode):
                # Predates coordinator-managed release extraction. The legacy
                # rollback release embeds a hardened venv instead of linking
                # to a sibling immutable venv; retain it only after the same
                # ownership and non-writability traversal above succeeds.
                venv = {"path": relative, "target": str(member), "embedded": True}
            if stat.S_ISREG(info.st_mode):
                inventory[relative] = web.sha256(member)
    if venv is None:
        fail("API release virtual-environment linkage is missing")
    metadata = _metadata_identity(metadata_path, path)
    identity = {
        "path": str(path),
        **metadata,
        "uid": root_info.st_uid,
        "gid": root_info.st_gid,
        "mode": stat.S_IMODE(root_info.st_mode),
        "venv": venv,
        "tree_sha256": hashlib.sha256(
            json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    return path, identity


def _web_release_attestation(path_text: object, field: str) -> tuple[Path, dict[str, object]]:
    path = _direct_release(path_text, WEB_RELEASES, field)
    web.require_root_chain(path)
    web.require_root_tree(path)
    inventory = {
        member.relative_to(path).as_posix(): web.sha256(member)
        for member in sorted(path.rglob("*"))
        if member.is_file()
    }
    root_info = path.lstat()
    return path, {
        "path": str(path),
        "uid": root_info.st_uid,
        "gid": root_info.st_gid,
        "mode": stat.S_IMODE(root_info.st_mode),
        "frontend_generation": path.name,
        "tree_sha256": hashlib.sha256(
            json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def _require_attestation(actual: dict[str, object], expected: object, field: str) -> None:
    if not isinstance(expected, dict) or actual != expected:
        fail(f"receipt {field} no longer matches its activation attestation")


def _transaction_receipt(transaction_id: str) -> tuple[Path, dict[str, object]]:
    """Load only a direct, root-owned receipt under the governed root."""
    if not TRANSACTION_ID.fullmatch(transaction_id):
        fail("transaction identifier is invalid")
    transactions = CONTROL_ROOT / "transactions"
    transaction = transactions / transaction_id
    receipt_path = transaction / "receipt.json"
    if (
        transaction.is_symlink()
        or receipt_path.is_symlink()
        or not transaction.is_dir()
        or not receipt_path.is_file()
        or not _within(transaction, transactions)
    ):
        fail("transaction receipt is not a direct governed receipt")
    web.require_root_chain(transactions)
    web.require_root_chain(transaction)
    web.require_root_owned(receipt_path)
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail("transaction receipt is malformed")
    if not isinstance(receipt, dict):
        fail("transaction receipt is malformed")
    required = {
        "receipt_schema_version",
        "helper_version",
        "state",
        "activation_complete",
        "old_api",
        "old_web",
        "new_api",
        "new_web",
        "schema",
        "service",
        "writes_enabled",
        "old_api_attestation",
        "old_web_attestation",
        "active_pointer_identities",
    }
    schema_version = receipt.get("receipt_schema_version")
    if schema_version == 2:
        fail("transaction receipt schema 2 lacks rollback attestations; preserved fallback evidence is required")
    if (
        not required.issubset(receipt)
        or schema_version != TRANSACTION_RECEIPT_SCHEMA_VERSION
        or receipt["helper_version"] not in SUPPORTED_TRANSACTION_HELPER_VERSIONS
    ):
        fail("transaction receipt schema is invalid")
    if receipt["state"] != "active" or receipt["activation_complete"] is not True:
        fail("transaction did not complete activation")
    if receipt["service"] != SERVICE or receipt["writes_enabled"] is not False:
        fail("transaction receipt violates governed rollback policy")
    old_api, api_attestation = _api_release_attestation(receipt["old_api"], "old_api")
    old_web, web_attestation = _web_release_attestation(receipt["old_web"], "old_web")
    _require_attestation(api_attestation, receipt["old_api_attestation"], "old_api")
    _require_attestation(web_attestation, receipt["old_web_attestation"], "old_web")
    pointers = receipt["active_pointer_identities"]
    if (
        not isinstance(pointers, dict)
        or pointers.get("api") != {"path": str(API_CURRENT), "target": str(old_api)}
        or pointers.get("web") != {"path": str(WEB_CURRENT), "target": str(old_web)}
    ):
        fail("transaction receipt active-pointer identity is invalid")
    return transaction, receipt


def _rollback_receipt_path(transaction: Path) -> Path:
    return transaction / "post-activation-rollback.json"


def post_activation_rollback(transaction_id: str) -> dict[str, object]:
    """Restore the exact prior immutable targets from an activated receipt.

    This intentionally has no policy/archive/migration input.  Its sole
    authority is one validated receipt beneath the root-owned transaction
    directory, and it only touches the already governed API/web symlinks and
    the fixed API service.
    """
    transaction, receipt = _transaction_receipt(transaction_id)
    old_api, api_attestation = _api_release_attestation(receipt["old_api"], "old_api")
    old_web, web_attestation = _web_release_attestation(receipt["old_web"], "old_web")
    _require_attestation(api_attestation, receipt["old_api_attestation"], "old_api")
    _require_attestation(web_attestation, receipt["old_web_attestation"], "old_web")
    rollback_receipt = _rollback_receipt_path(transaction)
    if rollback_receipt.exists() or rollback_receipt.is_symlink():
        if rollback_receipt.is_symlink() or not rollback_receipt.is_file():
            fail("rollback receipt is unsafe")
        prior = json.loads(rollback_receipt.read_text(encoding="utf-8"))
        if not isinstance(prior, dict) or prior.get("state") != "rolled_back":
            fail("rollback receipt is malformed")
        if API_CURRENT.resolve() != old_api or WEB_CURRENT.resolve() != old_web:
            fail("already rolled-back transaction no longer has its prior targets active")
        health = web.api_health({"schema": receipt["schema"]})
        if health.get("writes_enabled") is not False:
            fail("already rolled-back transaction has writes enabled")
        return {"transaction": transaction_id, "state": "rolled_back", "idempotent": True}
    web.atomic_symlink(old_api, API_CURRENT)
    web.atomic_symlink(old_web, WEB_CURRENT)
    web.nginx_test_reload()
    subprocess.run(["/bin/systemctl", "restart", SERVICE], check=True)
    web.wait_api({"schema": receipt["schema"]})
    if API_CURRENT.resolve() != old_api or WEB_CURRENT.resolve() != old_web:
        fail("post-activation rollback did not restore both prior release targets")
    web.request_check(
        "post_activation_rollback_homepage",
        "http://" + web.HOST + "/",
        200,
        contains="EOAT",
        excludes="Welcome to nginx!",
    )
    health = web.api_health({"schema": receipt["schema"]})
    if health.get("writes_enabled") is not False:
        fail("post-activation rollback did not preserve writes-disabled state")
    evidence = {
        "receipt_schema_version": TRANSACTION_RECEIPT_SCHEMA_VERSION,
        "transaction": transaction_id,
        "state": "rolled_back",
        "rollback_api": str(old_api),
        "rollback_web": str(old_web),
        "rollback_frontend_generation": old_web.name,
        "helper_version": HELPER_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        descriptor = os.open(rollback_receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return post_activation_rollback(transaction_id)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
    return {"transaction": transaction_id, "state": "rolled_back", "idempotent": False}


def _legacy_reconciliation_receipt(transaction: Path) -> Path:
    return transaction / "post-activation-rollback.json"


def _validate_legacy_reconciliation(
    path: Path, transaction_id: str, evidence: dict[str, object]
) -> None:
    if path.is_symlink() or not path.is_file():
        fail("legacy reconciliation receipt is unsafe")
    info = path.lstat()
    web.require_root_owned(path)
    if stat.S_IMODE(info.st_mode) != 0o600:
        fail("legacy reconciliation receipt ownership or mode is invalid")
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"legacy reconciliation receipt is malformed: {error}")
    expected = {
        "receipt_schema_version": TRANSACTION_RECEIPT_SCHEMA_VERSION,
        "transaction": transaction_id,
        "original_transaction_schema": LEGACY_TRANSACTION_RECEIPT_SCHEMA_VERSION,
        "state": "rolled_back",
        "reconciliation_mode": "legacy_already_rolled_back",
        "pointer_mutation_performed": False,
        "service_restart_performed": False,
        "nginx_reload_performed": False,
        "helper_version": HELPER_VERSION,
        "reason": "LEGACY_SCHEMA2_TRANSACTION_ALREADY_PHYSICALLY_ROLLED_BACK",
    }
    if not isinstance(prior, dict) or any(prior.get(key) != value for key, value in expected.items()):
        fail("legacy reconciliation receipt conflicts with governed evidence")
    for key in (
        "rollback_api",
        "rollback_web",
        "active_pointer_identities",
        "api_attestation",
        "web_attestation",
        "application_version",
        "schema",
        "writes_enabled",
        "api_health",
        "nginx_validation",
        "service_states",
        "data_state",
    ):
        if prior.get(key) != evidence.get(key):
            fail("legacy reconciliation receipt no longer matches current governed evidence")


def reconcile_legacy_rollback(transaction_id: str) -> dict[str, object]:
    """Record only a proven schema-2 rollback that is already physically active.

    This compatibility action deliberately cannot alter pointers, services,
    NGINX, database state, or the original receipt.  It is limited to the
    historical 1.3.1/schema-2 transaction form and emits fresh attestations in
    a separate, exclusively created recovery record.
    """
    transaction, receipt = _load_legacy_schema2_transaction(transaction_id)
    evidence = _legacy_runtime_evidence(transaction, receipt)
    path = _legacy_reconciliation_receipt(transaction)
    if path.exists() or path.is_symlink():
        _validate_legacy_reconciliation(path, transaction_id, evidence)
        return {"transaction": transaction_id, "state": "rolled_back", "idempotent": True}
    payload = {
        "receipt_schema_version": TRANSACTION_RECEIPT_SCHEMA_VERSION,
        "transaction": transaction_id,
        "original_transaction_schema": LEGACY_TRANSACTION_RECEIPT_SCHEMA_VERSION,
        "state": "rolled_back",
        "reconciliation_mode": "legacy_already_rolled_back",
        "pointer_mutation_performed": False,
        "service_restart_performed": False,
        "nginx_reload_performed": False,
        **evidence,
        "helper_version": HELPER_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "diagnostics": [
            "schema-2 receipt retained unchanged",
            "live API and web pointers already matched recorded old targets",
        ],
        "reason": "LEGACY_SCHEMA2_TRANSACTION_ALREADY_PHYSICALLY_ROLLED_BACK",
    }
    encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return reconcile_legacy_rollback(transaction_id)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(path, 0o600)
        if os.name != "nt" and hasattr(os, "O_DIRECTORY"):
            parent_descriptor = os.open(transaction, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent_descriptor)
            finally:
                os.close(parent_descriptor)
    except Exception:
        # Do not remove a partially created recovery record: it is evidence of
        # an interrupted operation and must fail closed on the next attempt.
        raise
    _validate_legacy_reconciliation(path, transaction_id, evidence)
    return {"transaction": transaction_id, "state": "rolled_back", "idempotent": False}


def acceptance_policy(value: dict[str, object], server: Path) -> dict[str, object]:
    """Bind shared HTTP checks to this transaction's immutable API target."""
    return {**value, "api_release": str(server.resolve())}


def preflight(value: dict[str, object]) -> dict[str, object]:
    """Read-only identity and service checks before staging or activation."""
    migration_current, migration_target, migration_revisions = migration_plan(value)
    if not _within(Path(str(value["bundle_path"])), SEALED_ROOT):
        fail("preflight requires already-sealed coordinator artifacts")
    archive = Path(str(value["server_archive_path"]))
    manifest = Path(str(value["server_manifest_path"]))
    bundle = Path(str(value["bundle_path"]))
    web.require_root_chain(archive)
    web.require_root_chain(manifest)
    web.require_root_chain(bundle)
    web.require_root_tree(bundle)
    if web.sha256(archive) != value["server_archive_sha256"]:
        fail("server archive SHA-256 does not match approved policy")
    if web.sha256(manifest) != value["server_manifest_sha256"]:
        fail("server package manifest SHA-256 does not match approved policy")
    validate_migration_archive(archive, migration_revisions, current=migration_current)
    verified = web.verify_bundle(bundle, str(value["bundle_sha256"]))
    if verified["metadata"].get("application_version") != value["application_version"]:
        fail("web bundle version does not match coordinated policy")
    if (
        str(API_CURRENT.resolve()) != value["expected_active_api"]
        or str(WEB_CURRENT.resolve()) != value["expected_active_web"]
    ):
        fail("active release targets differ from the approved pre-activation policy")
    health = web.api_health({**value, "schema": migration_current})
    if migration_revisions:
        environment = _migration_environment()
        if _staged_alembic_current(API_CURRENT.resolve(), environment) != migration_current:
            fail("production schema does not match the approved migration-plan start")
    if not web.api_loopback_only() or not web.mysql_loopback_only() or not web.listener_policy(value):
        fail("API, MySQL, or listener policy failed")
    nginx = subprocess.run(["/usr/sbin/nginx", "-t"], text=True, capture_output=True)
    if nginx.returncode:
        fail("nginx -t failed before coordinated deployment")
    return {
        "helper_version": HELPER_VERSION,
        "server_archive_sha256": value["server_archive_sha256"],
        "server_manifest_sha256": value["server_manifest_sha256"],
        "web_bundle_sha256": verified["bundle_sha256"],
        "active_api": str(API_CURRENT.resolve()),
        "active_web": str(WEB_CURRENT.resolve()),
        "api_health": health,
        "nginx_worker_user": web.nginx_worker_user(),
        "migration": {
            "current_schema": migration_current,
            "target_schema": migration_target,
            "revisions": migration_revisions,
        },
    }


def activate(value: dict[str, object]) -> Path:
    with deployment_lock():
        value = sealed_policy(value)
        preflight_evidence = preflight(value)
        migration = migration_plan(value)
        migration_current, _, migration_revisions = migration
        web.require_root_chain(Path(str(value["bundle_path"])))
        web.require_root_tree(Path(str(value["bundle_path"])))
        verified = web.verify_bundle(Path(str(value["bundle_path"])), str(value["bundle_sha256"]))
        if verified["metadata"].get("application_version") != value["application_version"]:
            fail("web bundle version does not match coordinated policy")
        old_api, old_api_attestation = _api_release_attestation(API_CURRENT.resolve(), "active_api")
        old_web, old_web_attestation = _web_release_attestation(WEB_CURRENT.resolve(), "active_web")
        transaction = (
            CONTROL_ROOT
            / "transactions"
            / ("coordinated-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
        )
        transaction.mkdir(parents=True, mode=0o700)
        receipt = {
            "receipt_schema_version": TRANSACTION_RECEIPT_SCHEMA_VERSION,
            "helper_version": HELPER_VERSION,
            "old_api": str(old_api),
            "old_web": str(old_web),
            "old_api_attestation": old_api_attestation,
            "old_web_attestation": old_web_attestation,
            "active_pointer_identities": {
                "api": {"path": str(API_CURRENT), "target": str(old_api)},
                "web": {"path": str(WEB_CURRENT), "target": str(old_web)},
            },
            "source_commit": value["source_commit"],
            "application_version": value["application_version"],
            "server_archive_sha256": value["server_archive_sha256"],
            "server_manifest_sha256": value["server_manifest_sha256"],
            "web_bundle_sha256": value["bundle_sha256"],
            "schema": value["schema"],
            "service": SERVICE,
            "writes_enabled": False,
            "activation_complete": False,
            "state": "started",
            "preflight": preflight_evidence,
        }
        (transaction / "receipt.json").write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        backup: dict[str, object] = {"database": "NOT_REQUIRED", "verified": True}
        migration_complete = False
        try:
            if migration_revisions:
                backup = create_and_verify_backup(transaction)
                receipt["backup"] = backup
                (transaction / "receipt.json").write_text(
                    json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
                )
            server = extract_server(value, transaction)
            frontend = web.stage_frontend(Path(str(value["bundle_path"])) / "web", str(value["web_release_id"]))
            web.deployed_frontend_hashes(frontend, verified["manifest"])
            receipt["migration"] = apply_migration_plan(server, migration, backup)
            migration_complete = bool(migration_revisions)
            web.atomic_symlink(server, API_CURRENT)
            web.atomic_symlink(frontend, WEB_CURRENT)
            web.nginx_test_reload()
            subprocess.run(["/bin/systemctl", "restart", SERVICE], check=True)
            web.wait_api(value)
            wait_target(value)
            # The shared HTTP acceptance helper also asserts the API release
            # symlink. Bind that invariant to this just-activated immutable target.
            web.acceptance(frontend, acceptance_policy(value, server))
            receipt.update(
                state="active",
                activation_complete=True,
                new_api=str(server),
                new_web=str(frontend),
                frontend_generation=frontend.name,
            )
            (transaction / "receipt.json").write_text(
                json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
            return transaction
        except Exception as error:
            # Restore a matching API/web pair first. Writes are already governed
            # off, and the service is restarted only after its database is back
            # at the old release's exact schema.
            web.atomic_symlink(old_api, API_CURRENT)
            web.atomic_symlink(old_web, WEB_CURRENT)
            if migration_complete:
                try:
                    restore_backup(backup)
                    environment = _migration_environment()
                    if _staged_alembic_current(old_api, environment) != migration_current:
                        fail("rollback backup did not restore the approved starting revision")
                except web.InstallError:
                    receipt.update(state="manual_intervention_required", failure="activation failed; backup recovery failed")
                    (transaction / "receipt.json").write_text(
                        json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
                    )
                    raise
            web.nginx_test_reload()
            subprocess.run(["/bin/systemctl", "restart", SERVICE], check=True)
            web.wait_api({"schema": migration_current})
            if API_CURRENT.resolve() != old_api or WEB_CURRENT.resolve() != old_web:
                fail("rollback did not restore both prior release targets")
            web.request_check(
                "rollback_homepage", "http://" + web.HOST + "/", 200, contains="EOAT", excludes="Welcome to nginx!"
            )
            rollback_health = web.api_health({"schema": migration_current})
            if rollback_health.get("writes_enabled") is not False:
                fail("rollback did not restore writes-disabled state")
            receipt.update(
                state="rolled_back",
                failure=str(error),
                rollback_api=str(old_api),
                rollback_web=str(old_web),
                activation_complete=False,
            )
            (transaction / "receipt.json").write_text(
                json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        nargs="?",
        choices=("preflight", "activate", "post-activation-rollback", "reconcile-legacy-rollback"),
    )
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--transaction")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)
    if args.version:
        if args.action is not None or args.policy is not None or args.transaction is not None:
            parser.error("--version does not accept an action, policy, or transaction")
        print(json.dumps({"helper_version": HELPER_VERSION}, sort_keys=True))
        return 0
    if args.action is None:
        parser.error("an action is required")
    if os.geteuid() != 0:
        fail("root execution is required")
    if args.action == "post-activation-rollback":
        if args.policy is not None or not args.transaction:
            fail("post-activation rollback requires only a governed transaction identifier")
        print(json.dumps(post_activation_rollback(args.transaction), sort_keys=True))
        return 0
    if args.action == "reconcile-legacy-rollback":
        if args.policy is not None or not args.transaction:
            fail("legacy reconciliation requires only a governed transaction identifier")
        print(json.dumps(reconcile_legacy_rollback(args.transaction), sort_keys=True))
        return 0
    if args.policy is None or args.transaction is not None:
        fail("preflight and activate require only a governed policy")
    value = policy(args.policy)
    if args.action == "preflight":
        print(json.dumps(preflight(value), sort_keys=True))
    else:
        print(json.dumps({"transaction": str(activate(value))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except web.InstallError as error:
        print("EOAT_COORDINATED_DEPLOY_ERROR: " + str(error), flush=True)
        raise SystemExit(1) from None
