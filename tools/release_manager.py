"""Thin command-line entry point for the Phase 1 EOAT Atlas release manager."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deployment.release_manager import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
