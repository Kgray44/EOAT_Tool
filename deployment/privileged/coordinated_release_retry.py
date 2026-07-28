#!/usr/bin/env python3
"""Root-owned, policy-pinned coordinated EOAT API/static-release activation.

This helper is deliberately narrow: it accepts only a root-owned JSON policy
whose hashes pin the server ZIP and the already sealed static bundle.  It is
used for zero-migration coordinated activation where the NGINX architecture is
already installed.  It never executes a migration or accepts caller commands.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import install_http_web_host as web

HELPER_VERSION = "1.3.0"
API_CURRENT = Path("/opt/eoat-atlas/current")
API_RELEASES = Path("/opt/eoat-atlas/releases")
WEB_CURRENT = Path("/var/www/eoat-atlas/current")
WEB_RELEASES = web.WEB_ROOT / "releases"
CONTROL_ROOT = Path("/var/lib/eoat-atlas-http-web-host")
SERVICE = "eoat-atlas.service"
RECEIPT_SCHEMA_VERSION = 2
TRANSACTION_ID = __import__("re").compile(r"coordinated-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}")
UPLOAD_ROOT = Path("/opt/eoat-atlas/incoming")
SEALED_ROOT = CONTROL_ROOT / "sealed-artifacts"


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


def _copy_sealed_file(source: Path, destination: Path, expected: str) -> dict[str, object]:
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
    return {"source": str(source), "sealed": str(destination), "sha256": actual, "size": size}


def seal_artifacts(value: dict[str, object]) -> dict[str, object]:
    """Copy approved uploads into a root-owned immutable coordinator zone."""
    archive = _upload_member(value["server_archive_path"])
    manifest = _upload_member(value["server_manifest_path"])
    bundle = _upload_member(value["bundle_path"], directory=True)
    policy_hash = _policy_digest(value)
    release = str(value["server_release_id"])
    if not __import__("re").fullmatch(r"[A-Za-z0-9._-]+", release):
        fail("sealed release identifier is invalid")
    SEALED_ROOT.mkdir(parents=True, mode=0o700)
    web.require_root_owned(SEALED_ROOT)
    web.require_root_chain(SEALED_ROOT)
    final = SEALED_ROOT / release
    receipt_path = final / "sealing-receipt.json"
    if final.exists():
        if final.is_symlink() or not receipt_path.is_file():
            fail("existing sealed artifact directory is unsafe")
        web.require_root_tree(final)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("policy_semantic_sha256") != policy_hash:
            fail("existing sealed artifacts are bound to a different policy")
        return receipt
    temporary = SEALED_ROOT / (".sealing-" + uuid.uuid4().hex)
    try:
        temporary.mkdir(mode=0o700)
        records = [
            _copy_sealed_file(archive, temporary / "server.zip", str(value["server_archive_sha256"])),
            _copy_sealed_file(manifest, temporary / "server.manifest.json", str(value["server_manifest_sha256"])),
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
            records.append(_copy_sealed_file(item, destination, web.sha256(item)))
        verified = web.verify_bundle(sealed_bundle, str(value["bundle_sha256"]))
        receipt = {
            "schema": 1,
            "application_version": value["application_version"],
            "source_commit": value["source_commit"],
            "coordinator_version": HELPER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "policy_semantic_sha256": policy_hash,
            "files": records,
            "sealed_bundle": str(sealed_bundle),
            "bundle_sha256": verified["bundle_sha256"],
        }
        (temporary / "sealing-receipt.json").write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        os.chmod(temporary / "sealing-receipt.json", 0o600)
        web.require_root_tree(temporary)
        os.replace(temporary, final)
        web.require_root_tree(final)
        return receipt
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        raise


def sealed_policy(value: dict[str, object]) -> dict[str, object]:
    receipt = seal_artifacts(value)
    result = dict(value)
    root = Path(str(receipt["sealed_bundle"])).parent
    result.update(
        server_archive_path=str(root / "server.zip"),
        server_manifest_path=str(root / "server.manifest.json"),
        bundle_path=str(receipt["sealed_bundle"]),
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


def _immutable_release(path_text: object, root: Path, field: str) -> Path:
    path = Path(str(path_text))
    if path.is_symlink() or not path.is_dir() or not _within(path, root):
        fail(f"receipt {field} is not an approved immutable release directory")
    web.require_root_chain(path)
    web.require_root_tree(path)
    return path.resolve()


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
    }
    if not required.issubset(receipt) or receipt["receipt_schema_version"] != RECEIPT_SCHEMA_VERSION:
        fail("transaction receipt schema is invalid")
    if receipt["state"] != "active" or receipt["activation_complete"] is not True:
        fail("transaction did not complete activation")
    if receipt["service"] != SERVICE or receipt["writes_enabled"] is not False:
        fail("transaction receipt violates governed rollback policy")
    _immutable_release(receipt["old_api"], API_RELEASES, "old_api")
    _immutable_release(receipt["old_web"], WEB_RELEASES, "old_web")
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
    old_api = _immutable_release(receipt["old_api"], API_RELEASES, "old_api")
    old_web = _immutable_release(receipt["old_web"], WEB_RELEASES, "old_web")
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
        "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
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


def acceptance_policy(value: dict[str, object], server: Path) -> dict[str, object]:
    """Bind shared HTTP checks to this transaction's immutable API target."""
    return {**value, "api_release": str(server.resolve())}


def preflight(value: dict[str, object]) -> dict[str, object]:
    """Read-only identity and service checks before staging or activation."""
    if not _within(Path(str(value["bundle_path"])), SEALED_ROOT):
        value = sealed_policy(value)
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
    verified = web.verify_bundle(bundle, str(value["bundle_sha256"]))
    if verified["metadata"].get("application_version") != value["application_version"]:
        fail("web bundle version does not match coordinated policy")
    if (
        str(API_CURRENT.resolve()) != value["expected_active_api"]
        or str(WEB_CURRENT.resolve()) != value["expected_active_web"]
    ):
        fail("active release targets differ from the approved pre-activation policy")
    health = web.api_health(value)
    if not web.api_loopback_only() or not web.mysql_loopback_only() or not web.no_tls_listener():
        fail("API, MySQL, or HTTP-only listener policy failed")
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
    }


def activate(value: dict[str, object]) -> Path:
    value = sealed_policy(value)
    preflight(value)
    web.require_root_chain(Path(str(value["bundle_path"])))
    web.require_root_tree(Path(str(value["bundle_path"])))
    verified = web.verify_bundle(Path(str(value["bundle_path"])), str(value["bundle_sha256"]))
    if verified["metadata"].get("application_version") != value["application_version"]:
        fail("web bundle version does not match coordinated policy")
    old_api, old_web = API_CURRENT.resolve(), WEB_CURRENT.resolve()
    transaction = (
        CONTROL_ROOT
        / "transactions"
        / ("coordinated-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    )
    transaction.mkdir(parents=True, mode=0o700)
    receipt = {
        "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
        "helper_version": HELPER_VERSION,
        "old_api": str(old_api),
        "old_web": str(old_web),
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
    }
    (transaction / "receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    server = None
    try:
        server = extract_server(value, transaction)
        frontend = web.stage_frontend(Path(str(value["bundle_path"])) / "web", str(value["web_release_id"]))
        web.deployed_frontend_hashes(frontend, verified["manifest"])
        web.atomic_symlink(server, API_CURRENT)
        web.atomic_symlink(frontend, WEB_CURRENT)
        web.nginx_test_reload()
        subprocess.run(["/bin/systemctl", "restart", SERVICE], check=True)
        web.wait_api(value)
        wait_target(value)
        # The shared HTTP acceptance helper also asserts the API release
        # symlink.  Bind that invariant to this just-activated immutable
        # target rather than requiring a second policy field.
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
        web.atomic_symlink(old_api, API_CURRENT)
        web.atomic_symlink(old_web, WEB_CURRENT)
        web.nginx_test_reload()
        subprocess.run(["/bin/systemctl", "restart", SERVICE], check=True)
        web.wait_api({"schema": value["schema"]})
        if API_CURRENT.resolve() != old_api or WEB_CURRENT.resolve() != old_web:
            fail("rollback did not restore both prior release targets")
        web.request_check(
            "rollback_homepage", "http://" + web.HOST + "/", 200, contains="EOAT", excludes="Welcome to nginx!"
        )
        rollback_health = web.api_health({"schema": value["schema"]})
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "activate", "post-activation-rollback"))
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--transaction")
    args = parser.parse_args()
    if os.geteuid() != 0:
        fail("root execution is required")
    if args.action == "post-activation-rollback":
        if args.policy is not None or not args.transaction:
            fail("post-activation rollback requires only a governed transaction identifier")
        print(json.dumps(post_activation_rollback(args.transaction), sort_keys=True))
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
