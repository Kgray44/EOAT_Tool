from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.eoat_id_migration import run_eoat_id_prefix_migration


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate Cleanroom EOAT Assembly IDs from P4-EOAT-#### to CL-EOAT-####."
    )
    parser.add_argument("--workbook", required=True, help="Path to EOAT_Master_Tracker.xlsx.")
    parser.add_argument("--photo-root", help="Path to the EOAT photo root/archive folder.")
    parser.add_argument("--project-root", help="Path to the EOAT project root.")
    parser.add_argument("--report-dir", help="Directory for migration and validation reports.")
    parser.add_argument("--backup-dir", help="Directory for timestamped backups in apply mode.")
    parser.add_argument("--rebuild-indexes", action="store_true", help="Invalidate/rebuild app indexes and caches after apply.")
    parser.add_argument("--validate-only", action="store_true", help="Only run EOAT ID prefix validation reports.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview changes without modifying files.")
    mode.add_argument("--apply", action="store_true", help="Create backups and apply the migration.")
    parser.add_argument("--json", action="store_true", help="Print the full structured result as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.validate_only and not args.dry_run and not args.apply:
        parser.error("Choose --dry-run, --apply, or --validate-only.")
    result = run_eoat_id_prefix_migration(
        workbook_path=Path(args.workbook),
        photo_root=Path(args.photo_root) if args.photo_root else None,
        project_root=Path(args.project_root) if args.project_root else None,
        apply=bool(args.apply),
        report_dir=Path(args.report_dir) if args.report_dir else None,
        backup_dir=Path(args.backup_dir) if args.backup_dir else None,
        rebuild_indexes=bool(args.rebuild_indexes or args.apply),
        validate_only=bool(args.validate_only),
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"Mode: {'dry-run' if result.dry_run else 'apply'}")
        print(f"IDs mapped: {len(result.mappings)}")
        print(f"Workbook updates: {len(result.workbook_updates)}")
        print(f"Photo updates: {len(result.photo_updates)}")
        print(f"Cache/index updates: {len(result.cache_updates)}")
        print(f"Validation issues: {len(result.validation_issues)}")
        print(f"Migration report: {result.migration_report_md}")
        print(f"Validation report: {result.validation_report_md}")
        if result.backups:
            print(f"Backup folder: {result.backup_dir}")
        for warning in result.warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        for conflict in result.conflicts:
            print(f"CONFLICT: {conflict}", file=sys.stderr)
        for error in result.errors:
            print(f"ERROR: {error}", file=sys.stderr)
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
