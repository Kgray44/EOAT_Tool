from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

from core.constants import DEFAULT_PROJECT_ROOT
from core.workflows import run_workflow


def main() -> int:
    parser = argparse.ArgumentParser(description="Run EOAT Command Center safe workflow.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--workflow", required=True, choices=["daily-start", "daily-end", "weekly-review", "final-review"])
    parser.add_argument("--week", type=int, default=1)
    parser.add_argument("--day", type=int, default=1)
    args = parser.parse_args()
    result = run_workflow(args.project_root, args.workflow, week=args.week, day=args.day)
    print(result.to_markdown())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
