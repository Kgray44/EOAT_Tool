"""Thin command-line entry point for the Phase 2 read-only server updater."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deployment.server_updater import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
