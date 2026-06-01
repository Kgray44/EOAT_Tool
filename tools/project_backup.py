from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

from core.constants import DEFAULT_PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description="Create EOAT project backups.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--mode", choices=["workbook", "config", "reports-index", "light"], default="workbook")
    parser.add_argument("--include-photos", action="store_true")
    args = parser.parse_args()
    from core.project_backup import backup_project

    result = backup_project(args.project_root, mode=args.mode, include_photos=args.include_photos)
    print(result.to_markdown())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
