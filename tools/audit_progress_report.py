from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

from core.audit_progress import calculate_audit_progress, generate_audit_progress_report
from core.constants import DEFAULT_PROJECT_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an EOAT audit progress report.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--metrics-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.metrics_only:
        summary, error = calculate_audit_progress(args.project_root)
        if error:
            print(error.to_markdown())
            return 1
        assert summary is not None
        print(summary.to_markdown())
        return 0
    result = generate_audit_progress_report(args.project_root)
    print(result.to_markdown())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())

