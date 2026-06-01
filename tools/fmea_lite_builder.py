from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

from core.constants import DEFAULT_PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an EOAT FMEA-lite analysis report.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--apply-suggestions", action="store_true", help="Reserved for later; Phase 3 is report-only.")
    args = parser.parse_args()
    from core.fmea_analysis import generate_fmea_report

    result = generate_fmea_report(args.project_root)
    if args.apply_suggestions:
        result.warnings.append("--apply-suggestions is not implemented in Phase 3; workbook was not modified.")
    print(result.to_markdown())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
