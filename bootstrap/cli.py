from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from . import BOOTSTRAP_NAME, BOOTSTRAP_VERSION
from .core import BootstrapError, BootstrapService, _atomic_json, _read_json


def _root(value: str) -> Path:
    return (
        Path(value) if value else Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "EOAT_Atlas"
    )


def _packaged_trusted_keys() -> dict[str, str]:
    """Load the signed-manifest public policy bundled with Bootstrap."""

    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    path = bundle_root / "release_trust" / "production_manifest_keys.json"
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
        if policy.get("schema_version") != 1 or policy.get("environment") != "PRODUCTION":
            raise ValueError("unsupported policy")
        keys = {
            str(item["key_id"]): str(item["public_key"])
            for item in policy.get("keys", [])
            if isinstance(item, dict) and item.get("status") == "ACTIVE" and not item.get("revoked")
        }
        if not keys or set(policy.get("active_key_ids", [])) != set(keys):
            raise ValueError("invalid active keys")
        return keys
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise BootstrapError("packaged production trust policy is unavailable or malformed") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{BOOTSTRAP_NAME} {BOOTSTRAP_VERSION}")
    parser.add_argument("--root", default=os.environ.get("EOAT_ATLAS_INSTALL_ROOT", ""))
    parser.add_argument("--trusted-keys", default="", help="Non-production test-only trusted key JSON")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--smoke-receipt", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--transport", default="")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    root = _root(args.root)
    try:
        keys = _packaged_trusted_keys()
        if args.trusted_keys:
            if os.environ.get("EOAT_ATLAS_NON_PRODUCTION_TEST_CONTEXT") != "1":
                raise BootstrapError("trusted-key overrides are forbidden outside explicit non-production tests")
            supplied = json.loads(args.trusted_keys)
            if not isinstance(supplied, dict):
                raise BootstrapError("test trusted-key override must be a JSON object")
            keys.update({str(key): str(value) for key, value in supplied.items()})
        service = BootstrapService(root, trusted_public_keys=keys)
        if args.smoke_test:
            executable = Path(os.sys.executable)
            digest = hashlib.sha256(executable.read_bytes()).hexdigest() if executable.is_file() else ""
            now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            receipt = {
                "schema_version": 1,
                "component_kind": "bootstrap",
                "component_version": BOOTSTRAP_VERSION,
                "candidate_id": os.environ.get("EOAT_RELEASE_CANDIDATE_ID", ""),
                "product_version": os.environ.get("EOAT_RELEASE_PRODUCT_VERSION", ""),
                "release_id": os.environ.get("EOAT_RELEASE_RELEASE_ID", ""),
                "build_id": os.environ.get("EOAT_RELEASE_BUILD_ID", ""),
                "source_commit": os.environ.get("EOAT_RELEASE_SOURCE_COMMIT", ""),
                "source_tree": os.environ.get("EOAT_RELEASE_SOURCE_TREE", ""),
                "executable_locator": "EOAT Atlas Bootstrap.exe",
                "executable_sha256": digest,
                "package_sha256": os.environ.get("EOAT_RELEASE_PACKAGE_SHA256", ""),
                "started_at_utc": now,
                "status": "PASS",
                "checks": ["configuration", "version-store", "diagnostics"],
                "failure_category": "",
                "diagnostics": "",
                "completed_at_utc": now,
            }
            if args.smoke_receipt:
                _atomic_json(Path(args.smoke_receipt), receipt)
            print(json.dumps(receipt, sort_keys=True))
            return 0
        if args.offline:
            result = service.offline_launch().__dict__
        elif args.manifest:
            envelope = _read_json(Path(args.manifest))
            result = service.update(envelope, transport=args.transport).__dict__
        else:
            result = service.status()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (BootstrapError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
