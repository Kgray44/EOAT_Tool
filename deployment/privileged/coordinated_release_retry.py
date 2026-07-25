#!/usr/bin/env python3
"""Root-owned, policy-pinned coordinated EOAT API/static-release activation.

This helper is deliberately narrow: it accepts only a root-owned JSON policy
whose hashes pin the server ZIP and the already sealed static bundle.  It is
used for zero-migration coordinated activation where the NGINX architecture is
already installed.  It never executes a migration or accepts caller commands.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import install_http_web_host as web


HELPER_VERSION = "1.0.0"
API_CURRENT = Path("/opt/eoat-atlas/current")
API_RELEASES = Path("/opt/eoat-atlas/releases")
WEB_CURRENT = Path("/var/www/eoat-atlas/current")
CONTROL_ROOT = Path("/var/lib/eoat-atlas-http-web-host")
SERVICE = "eoat-atlas.service"


def fail(message: str) -> None:
    raise web.InstallError(message)


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
        subprocess.run(["/usr/bin/chown", "-R", "eoat-atlas:eoat-atlas", str(staging)], check=True)
        os.replace(staging, target)
    return target


def policy(path: Path) -> dict[str, object]:
    web.require_root_owned(Path(__file__).resolve(), executable=True)
    web.require_root_owned(path)
    web.require_root_chain(Path(__file__).resolve())
    web.require_root_chain(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "helper_sha256", "server_archive_path", "server_archive_sha256", "server_manifest_path", "server_manifest_sha256",
        "server_release_id", "bundle_path", "bundle_sha256", "application_version", "source_commit",
        "schema", "canonical_migration_sha256",
    }
    if not required.issubset(value) or web.sha256(Path(__file__).resolve()) != value["helper_sha256"]:
        fail("coordinated deployment policy or helper SHA-256 is invalid")
    return value


def wait_target(value: dict[str, object]) -> None:
    health = web.api_health(value)
    if health.get("application_version") != value["application_version"]:
        fail("active API version does not match coordinated release")


def activate(value: dict[str, object]) -> Path:
    web.require_root_chain(Path(str(value["bundle_path"])))
    web.require_root_tree(Path(str(value["bundle_path"])))
    verified = web.verify_bundle(Path(str(value["bundle_path"])), str(value["bundle_sha256"]))
    if verified["metadata"].get("application_version") != value["application_version"]:
        fail("web bundle version does not match coordinated policy")
    old_api, old_web = API_CURRENT.resolve(), WEB_CURRENT.resolve()
    transaction = CONTROL_ROOT / "transactions" / ("coordinated-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    transaction.mkdir(parents=True, mode=0o700)
    receipt = {"helper_version": HELPER_VERSION, "old_api": str(old_api), "old_web": str(old_web), "state": "started"}
    (transaction / "receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    server = None
    try:
        server = extract_server(value, transaction)
        frontend = web.stage_frontend(Path(str(value["bundle_path"])) / "web", str(verified["metadata"]["release_id"]))
        web.deployed_frontend_hashes(frontend, verified["manifest"])
        web.atomic_symlink(server, API_CURRENT)
        web.atomic_symlink(frontend, WEB_CURRENT)
        web.nginx_test_reload()
        subprocess.run(["/bin/systemctl", "restart", SERVICE], check=True)
        web.wait_api(value)
        wait_target(value)
        web.acceptance(frontend, value)
        receipt.update(state="active", new_api=str(server), new_web=str(frontend))
        (transaction / "receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return transaction
    except Exception as error:
        web.atomic_symlink(old_api, API_CURRENT)
        web.atomic_symlink(old_web, WEB_CURRENT)
        web.nginx_test_reload()
        subprocess.run(["/bin/systemctl", "restart", SERVICE], check=True)
        web.wait_api({"schema": value["schema"]})
        web.request_check("rollback_homepage", "http://" + web.HOST + "/", 200, contains="EOAT", excludes="Welcome to nginx!")
        receipt.update(state="rolled_back", failure=str(error), rollback_api=str(old_api), rollback_web=str(old_web))
        (transaction / "receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        fail("root execution is required")
    value = policy(args.policy)
    print(json.dumps({"transaction": str(activate(value))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except web.InstallError as error:
        print("EOAT_COORDINATED_DEPLOY_ERROR: " + str(error), flush=True)
        raise SystemExit(1)
