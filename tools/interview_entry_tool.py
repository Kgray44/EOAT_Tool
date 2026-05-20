from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

from core.constants import DEFAULT_PROJECT_ROOT
from core.interview_entries import INTERVIEW_QUESTIONS, save_interview_entry
from core.workbook_schema import get_expected_headers


FIELD_ARG_MAP = {
    "Interview ID": "interview_id",
    "Date": "date",
    "Person Interviewed": "person",
    "Role/Department": "role",
    "Shift": "shift",
    "Plant/Area": "plant_area",
    "Press/Machine #": "press",
    "Main Question/Topic": "topic",
    "Notes": "notes",
    "Known EOAT Issues Mentioned": "known_issues",
    "Suggested Improvements": "suggested_improvements",
    "Follow-Up Needed": "follow_up_needed",
    "Follow-Up Owner": "follow_up_owner",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add an operator/technician interview note.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--create-followup-action", action="store_true")
    parser.add_argument("--questions", action="store_true", help="Print suggested interview questions and exit.")
    for _field, arg_name in FIELD_ARG_MAP.items():
        parser.add_argument(f"--{arg_name.replace('_', '-')}", dest=arg_name, default="")
    return parser.parse_args()


def collect_interactive() -> dict[str, str]:
    print("Suggested questions:")
    for question in INTERVIEW_QUESTIONS:
        print(f"- {question}")
    print("\nEnter interview values. Leave optional fields blank.")
    return {field: input(f"{field}: ").strip() for field in get_expected_headers("Interview Notes")}


def entry_from_args(args: argparse.Namespace) -> dict[str, str]:
    return {field: getattr(args, arg_name, "") for field, arg_name in FIELD_ARG_MAP.items() if getattr(args, arg_name, "")}


def main() -> int:
    args = parse_args()
    if args.questions:
        for question in INTERVIEW_QUESTIONS:
            print(question)
        return 0
    entry = collect_interactive() if args.interactive else entry_from_args(args)
    result = save_interview_entry(args.project_root, entry, create_followup_action=args.create_followup_action)
    print(result.to_markdown())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())

