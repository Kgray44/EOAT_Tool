from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

from core.audit_entries import load_audit_entry, save_audit_entry
from core.constants import DEFAULT_PROJECT_ROOT
from core.workbook_schema import get_expected_headers


FIELD_ARG_MAP = {
    "Audit ID": "audit_id",
    "Audit Date": "audit_date",
    "Auditor": "auditor",
    "Plant/Area": "plant_area",
    "Press/Machine #": "press",
    "Tool #": "tool",
    "Robot Type": "robot_type",
    "Robot Model/Controller": "robot_model",
    "Part Family": "part_family",
    "Part Name/Description": "part_name",
    "EOAT Type": "eoat_type",
    "Status": "status",
    "Priority": "priority",
    "Known Issues": "known_issues",
    "Notes": "notes",
    "Follow-Up Needed": "follow_up_needed",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add or update an EOAT Inventory audit entry.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--update", action="store_true", help="Allow updating an existing Audit ID.")
    parser.add_argument("--create-followup-action", action="store_true")
    parser.add_argument("--load-audit-id", help="Print an existing audit entry and exit.")
    for _field, arg_name in FIELD_ARG_MAP.items():
        parser.add_argument(f"--{arg_name.replace('_', '-')}", dest=arg_name, default="")
    return parser.parse_args()


def collect_interactive(project_root: str) -> dict[str, str]:
    print("Enter EOAT audit values. Leave optional fields blank.")
    entry: dict[str, str] = {}
    for field in get_expected_headers("EOAT Inventory"):
        entry[field] = input(f"{field}: ").strip()
    return entry


def entry_from_args(args: argparse.Namespace) -> dict[str, str]:
    entry = {field: getattr(args, arg_name, "") for field, arg_name in FIELD_ARG_MAP.items()}
    return {field: value for field, value in entry.items() if value}


def main() -> int:
    args = parse_args()
    if args.load_audit_id:
        entry = load_audit_entry(args.project_root, args.load_audit_id)
        if not entry:
            print(f"Audit ID not found: {args.load_audit_id}")
            return 1
        for key, value in entry.items():
            print(f"{key}: {value}")
        return 0
    entry = collect_interactive(args.project_root) if args.interactive else entry_from_args(args)
    result = save_audit_entry(
        args.project_root,
        entry,
        allow_update=args.update,
        create_followup_action=args.create_followup_action,
    )
    print(result.to_markdown())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
