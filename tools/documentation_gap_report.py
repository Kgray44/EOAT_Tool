from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

from core.constants import DEFAULT_PROJECT_ROOT
from core.documentation_gaps import generate_documentation_gap_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an EOAT documentation gap report.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--no-csv", action="store_true")
    args = parser.parse_args()
    result = generate_documentation_gap_report(args.project_root, write_csv=not args.no_csv)
    print(result.to_markdown())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())

