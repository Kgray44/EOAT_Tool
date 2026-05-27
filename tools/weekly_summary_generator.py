from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

from core.constants import DEFAULT_PROJECT_ROOT
from core.schedule import resolve_project_day_for_project
from core.weekly_summary import generate_weekly_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a weekly EOAT project summary.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--week", type=int)
    parser.add_argument("--notes", default="")
    parser.add_argument("--scheduled", action="store_true", help="Run in scheduled/noninteractive mode.")
    parser.add_argument("--dry-run", action="store_true", help="Write test output only in the project Test_Reports folder.")
    parser.add_argument("--output-dir", help="Optional output folder for the generated weekly summary.")
    parser.add_argument("--date", dest="report_date", help="Report date in YYYY-MM-DD format.")
    parser.add_argument("--verbose", action="store_true", help="Print structured execution details.")
    args = parser.parse_args()
    week = args.week or resolve_project_day_for_project(args.project_root).week
    result = generate_weekly_summary(
        args.project_root,
        week=week,
        notes=args.notes,
        scheduled=args.scheduled,
        output_dir=args.output_dir,
        report_date=args.report_date,
        dry_run=args.dry_run,
    )
    print(result.to_markdown())
    if args.verbose:
        import json

        print(
            json.dumps(
                {
                    "success": result.success,
                    "report_type": "weekly",
                    "scheduled": bool(args.scheduled),
                    "dry_run": bool(args.dry_run),
                    "output_path": result.output_reports[0] if result.output_reports else "",
                    "warnings": result.warnings,
                    "errors": result.errors,
                },
                indent=2,
            )
        )
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
