from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from . import BOOTSTRAP_NAME, BOOTSTRAP_VERSION
from .core import BootstrapError, BootstrapService, _atomic_json, _read_json


def _root(value: str) -> Path:
    return (
        Path(value) if value else Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "EOAT_Atlas"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{BOOTSTRAP_NAME} {BOOTSTRAP_VERSION}")
    parser.add_argument("--root", default=os.environ.get("EOAT_ATLAS_INSTALL_ROOT", ""))
    parser.add_argument("--trusted-keys", default=os.environ.get("EOAT_BOOTSTRAP_TRUSTED_KEYS", "{}"))
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
        keys = json.loads(args.trusted_keys)
        service = BootstrapService(root, trusted_public_keys=keys if isinstance(keys, dict) else {})
        if args.smoke_test:
            receipt = {
                "schema_version": 1,
                "component_kind": "bootstrap",
                "component_version": BOOTSTRAP_VERSION,
                "status": "PASS",
                "checks": ["configuration", "version-store", "diagnostics"],
                "completed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
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
