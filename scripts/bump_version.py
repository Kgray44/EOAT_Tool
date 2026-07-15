from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release_tools.versioning import bump_repository_version  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Increment the canonical EOAT Atlas application version")
    parser.add_argument("bump", nargs="?", choices=("patch", "minor", "major"))
    parser.add_argument("--set", dest="explicit_version", metavar="MAJOR.MINOR.PATCH")
    parser.add_argument(
        "--operation-id",
        help="Stable task/finalization identifier; repeating the same operation becomes a safe no-op",
    )
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if bool(args.bump) == bool(args.explicit_version):
        parser.error("specify exactly one of patch/minor/major or --set")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        previous, current, changed = bump_repository_version(
            args.root,
            part=args.bump,
            explicit=args.explicit_version,
            operation_id=args.operation_id,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: EOAT Atlas version was not updated: {exc}", file=sys.stderr)
        return 1
    print("EOAT Atlas version updated:" if changed else "EOAT Atlas version already updated for this operation:")
    print(f"  Previous: {previous}")
    print(f"  Current:  {current}")
    print(f"  Type:     {args.bump or 'explicit'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
