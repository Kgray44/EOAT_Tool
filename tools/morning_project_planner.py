from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

from core.constants import DEFAULT_PROJECT_ROOT
from core.morning_planner import generate_morning_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a daily EOAT project morning plan.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--day", type=int, required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--detail-level", choices=["todo", "summary", "debug"], default="todo")
    args = parser.parse_args()
    result = generate_morning_plan(args.project_root, week=args.week, day=args.day, notes=args.notes, detail_level=args.detail_level)
    print(result.to_markdown())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
