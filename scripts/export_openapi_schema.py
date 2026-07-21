"""Export the EOAT Atlas FastAPI OpenAPI contract in a deterministic form.

This intentionally loads the authoritative FastAPI application; it does not duplicate
the Python models in the frontend. The committed JSON is an input to openapi-typescript.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export EOAT Atlas OpenAPI schema deterministically")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    from server.eoat_api.app import app

    schema = app.openapi()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Exported deterministic OpenAPI schema to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
