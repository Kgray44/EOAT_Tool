from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

from core.constants import DEFAULT_PROJECT_ROOT
from core.final_handoff import build_final_handoff_package


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a final EOAT handoff package.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--include-daily-reports", action="store_true")
    parser.add_argument("--include-weekly-reports", action="store_true", default=True)
    parser.add_argument("--include-mentor-briefs", action="store_true")
    parser.add_argument("--include-photo-files", action="store_true")
    parser.add_argument("--include-photos-index-only", action="store_true", help="Default behavior; actual photo files are only copied with --include-photo-files.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = build_final_handoff_package(
        args.project_root,
        include_daily_reports=args.include_daily_reports,
        include_weekly_reports=args.include_weekly_reports,
        include_mentor_briefs=args.include_mentor_briefs,
        include_photo_files=args.include_photo_files,
        dry_run=args.dry_run,
    )
    print(result.to_markdown())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
