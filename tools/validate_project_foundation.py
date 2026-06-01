from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

from core.constants import DEFAULT_PROJECT_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the EOAT project foundation.")
    parser.add_argument(
        "--project-root", default=str(DEFAULT_PROJECT_ROOT), help="Path to EOAT_Standardization_Project."
    )
    parser.add_argument("--no-report", action="store_true", help="Run validation without writing a Markdown report.")
    parser.add_argument("--no-log", action="store_true", help="Run validation without writing to the activity log.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    from core.validation import run_foundation_validation

    result = run_foundation_validation(
        args.project_root,
        write_report=not args.no_report,
        log_activity=not args.no_log,
    )
    print(result.to_markdown())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
