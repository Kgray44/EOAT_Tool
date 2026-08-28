"""Generate a deterministic coordinator policy from sealed release inputs.

The resulting JSON is still only accepted after root ownership and helper-hash
validation on the production host.  This generator deliberately has no SSH,
sudo, service, database, or activation capability.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = re.compile(r"\d{8}_\d{4}(?:_[A-Za-z0-9_-]+)?")
SHA256 = re.compile(r"[0-9a-f]{64}")
FULL_SHA = re.compile(r"[0-9a-f]{40}")


class PolicyError(RuntimeError):
    pass


def parse_bool(value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError("expected a boolean value")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyError("server release manifest is unreadable") from error
    if not isinstance(value, dict):
        raise PolicyError("server release manifest is not an object")
    required = {
        "archive_sha256",
        "source_git_commit",
        "version",
        "database_schema_revision",
        "api_contract_version",
        "migration_inventory",
    }
    if not required.issubset(value):
        raise PolicyError("server release manifest is incomplete")
    return value


def archive_migrations(archive: Path) -> dict[str, tuple[str, str]]:
    values: dict[str, tuple[str, str]] = {}
    try:
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if not name.startswith("server/migrations/versions/") or not name.endswith(".py"):
                    continue
                payload = bundle.read(name)
                try:
                    tree = ast.parse(payload.decode("utf-8"), filename=name)
                except (SyntaxError, UnicodeDecodeError) as error:
                    raise PolicyError("server archive migration source is unreadable") from error
                revision = None
                for node in tree.body:
                    target_node = None
                    if isinstance(node, ast.Assign) and len(node.targets) == 1:
                        target_node = node.targets[0]
                    elif isinstance(node, ast.AnnAssign):
                        target_node = node.target
                    if isinstance(target_node, ast.Name) and target_node.id == "revision":
                        try:
                            revision = ast.literal_eval(node.value)
                        except ValueError as error:
                            raise PolicyError("server archive migration revision is unsafe") from error
                if not isinstance(revision, str) or not MIGRATION.fullmatch(revision):
                    continue
                if revision in values:
                    raise PolicyError("server archive has ambiguous migration revisions")
                values[revision] = (name, hashlib.sha256(payload).hexdigest())
    except (OSError, zipfile.BadZipFile) as error:
        raise PolicyError("server release archive is unreadable") from error
    return values


def generate(args: argparse.Namespace) -> dict[str, object]:
    manifest = read_manifest(args.server_manifest)
    archive_sha = sha256(args.server_archive)
    if archive_sha != manifest["archive_sha256"]:
        raise PolicyError("server archive does not match its release manifest")
    target = manifest["database_schema_revision"]
    if not isinstance(target, str) or not MIGRATION.fullmatch(target):
        raise PolicyError("server release manifest target schema is invalid")
    revisions = [item.strip() for item in args.migration_revisions.split(",") if item.strip()]
    if not MIGRATION.fullmatch(args.current_schema):
        raise PolicyError("migration current schema is invalid")
    if args.current_schema == target:
        if revisions:
            raise PolicyError("zero-migration release must not name migration revisions")
    elif not revisions or revisions[-1] != target or len(set(revisions)) != len(revisions):
        raise PolicyError("migration revisions must be unique and end at the release schema")
    if args.write_transition == "preserve_current" and args.writes_required_before != args.writes_required_after:
        raise PolicyError("preserve write-state policy must require the same state before and after activation")
    if args.write_transition == "enable" and args.writes_required_after is not True:
        raise PolicyError("enable write-state policy must require writes enabled after activation")
    if args.write_transition == "disable" and args.writes_required_after is not False:
        raise PolicyError("disable write-state policy must require writes disabled after activation")
    archived = archive_migrations(args.server_archive)
    plan: list[dict[str, str]] = []
    for revision in revisions:
        member = archived.get(revision)
        if member is None:
            raise PolicyError("server archive lacks an approved migration revision")
        plan.append({"revision": revision, "sha256": member[1]})
    canonical = archived.get("20260721_0008")
    if canonical is None:
        raise PolicyError("server archive lacks the canonical production migration")
    policy_root = PurePosixPath(args.policy_artifact_root)
    if not policy_root.is_absolute() or ".." in policy_root.parts:
        raise PolicyError("policy artifact root must be an absolute non-traversing POSIX path")
    for field, value in {"expected_active_api": args.expected_active_api, "expected_active_web": args.expected_active_web}.items():
        if not PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts:
            raise PolicyError(f"{field} must be absolute")
    coordinator = ROOT / "deployment" / "privileged" / "coordinated_release_retry.py"
    web_helper = ROOT / "deployment" / "privileged" / "install_http_web_host.py"
    value = {
        "helper_sha256": sha256(coordinator),
        "web_helper_sha256": sha256(web_helper),
        "server_archive_path": str(policy_root / args.server_archive.name),
        "server_archive_sha256": archive_sha,
        "server_manifest_path": str(policy_root / args.server_manifest.name),
        "server_manifest_sha256": sha256(args.server_manifest),
        "server_release_id": f"eoat-atlas-server-{manifest['version']}-{str(manifest['source_git_commit'])[:7]}",
        "web_release_id": args.web_release_id,
        "bundle_path": str(policy_root / args.bundle_path.name),
        "bundle_sha256": args.bundle_sha256,
        "application_version": manifest["version"],
        "api_contract_version": manifest["api_contract_version"],
        "source_commit": manifest["source_git_commit"],
        "schema": target,
        "canonical_migration_sha256": canonical[1],
        "expected_active_api": args.expected_active_api,
        "expected_active_web": args.expected_active_web,
        "tls_listener_policy": args.tls_listener_policy,
        "migration_plan": {"current_schema": args.current_schema, "target_schema": target, "revisions": plan},
        "write_state": {
            "transition": args.write_transition,
            "required_before": args.writes_required_before,
            "required_after": args.writes_required_after,
        },
    }
    if not SHA256.fullmatch(args.bundle_sha256) or not FULL_SHA.fullmatch(str(manifest["source_git_commit"])):
        raise PolicyError("bundle or source identity is invalid")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-archive", type=Path, required=True)
    parser.add_argument("--server-manifest", type=Path, required=True)
    parser.add_argument("--bundle-path", type=Path, required=True)
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--web-release-id", required=True)
    parser.add_argument("--expected-active-api", required=True)
    parser.add_argument("--expected-active-web", required=True)
    parser.add_argument("--current-schema", required=True)
    parser.add_argument("--migration-revisions", required=True)
    parser.add_argument("--write-transition", choices=("preserve_current", "enable", "disable"), required=True)
    parser.add_argument("--writes-required-before", type=parse_bool, required=True)
    parser.add_argument("--writes-required-after", type=parse_bool, required=True)
    parser.add_argument("--policy-artifact-root", default="/opt/eoat-atlas/incoming")
    parser.add_argument("--tls-listener-policy", choices=("http_only", "approved_self_signed_existing"), default="http_only")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = generate(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except PolicyError as error:
        print("EOAT_COORDINATED_POLICY_ERROR: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
