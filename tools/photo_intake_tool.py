from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

from core.constants import DEFAULT_PROJECT_ROOT

PHOTO_VIEW_TYPES = [
    "Overall",
    "Overall EOAT",
    "Robot Connection",
    "Tool Connection",
    "EOAT-Side Pneumatic Circuits",
    "EOAT-Side Pneumatics",
    "Robot-Side Pneumatics",
    "Vacuum Cups / Grippers",
    "Grippers",
    "Vacuum Cups",
    "Cylinders",
    "Tubing Routing",
    "Sensors",
    "Sensor Mounting",
    "Quick Disconnects",
    "Mounting Hardware",
    "Cable Management",
    "Wear / Damage",
    "Wear/Damage",
    "Tool Label / ID Plate",
    "Process Binder Reference",
    "Process Binder/Documentation Reference",
    "Other",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Intake and index EOAT photos.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--list-incoming", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--move", action="store_true", help="Move instead of copy. Copy is safer default.")
    parser.add_argument("--photos", nargs="*", default=[])
    parser.add_argument("--plant-area", default="")
    parser.add_argument("--press", default="")
    parser.add_argument("--date-taken", default="")
    parser.add_argument("--view-type", choices=PHOTO_VIEW_TYPES, default="Overall")
    parser.add_argument("--related-audit-id", default="")
    parser.add_argument("--related-issue-id", default="")
    parser.add_argument("--eoat-assembly-id", default="")
    parser.add_argument("--tool-number", default="")
    parser.add_argument("--linked-audit-field", default="")
    parser.add_argument("--description", default="")
    parser.add_argument("--notes", default="")
    return parser.parse_args()


def collect_interactive(args: argparse.Namespace) -> argparse.Namespace:
    from core.photo_indexing import list_incoming_photos

    incoming = list_incoming_photos(args.project_root)
    print("Incoming photos:")
    for index, photo in enumerate(incoming, start=1):
        print(f"{index}. {photo}")
    selected = input("Photo numbers to intake, comma separated: ").strip()
    indexes = [int(item.strip()) for item in selected.split(",") if item.strip().isdigit()]
    args.photos = [str(incoming[index - 1]) for index in indexes if 0 < index <= len(incoming)]
    args.plant_area = input("Plant/Area: ").strip()
    args.press = input("Press/Machine #: ").strip()
    args.date_taken = input("Date Taken (YYYY-MM-DD): ").strip()
    print("View types:")
    for view in PHOTO_VIEW_TYPES:
        print(f"- {view}")
    args.view_type = input("EOAT Area Shown: ").strip() or "Overall"
    args.related_audit_id = input("Related Audit ID: ").strip()
    args.related_issue_id = input("Related Issue ID: ").strip()
    args.eoat_assembly_id = input("EOAT Assembly ID: ").strip()
    args.tool_number = input("Tool #: ").strip()
    args.linked_audit_field = input("Linked Audit Field: ").strip()
    args.description = input("Description: ").strip()
    args.notes = input("Notes: ").strip()
    args.move = input("Move originals instead of copy? Type YES to move: ").strip() == "YES"
    return args


def main() -> int:
    args = parse_args()
    from core.photo_indexing import intake_photos, list_incoming_photos, preview_photo_intake

    if args.list_incoming:
        for photo in list_incoming_photos(args.project_root):
            print(photo)
        return 0
    if args.interactive:
        args = collect_interactive(args)
    if args.preview:
        plan = preview_photo_intake(
            args.project_root,
            args.photos,
            args.plant_area,
            args.press,
            args.date_taken,
            args.view_type,
            eoat_assembly_id=args.eoat_assembly_id,
            tool_number=args.tool_number,
        )
        for item in plan:
            print(f"{item.source} -> {item.target}")
        return 0
    result = intake_photos(
        args.project_root,
        args.photos,
        args.plant_area,
        args.press,
        args.date_taken,
        args.view_type,
        related_audit_id=args.related_audit_id,
        related_issue_id=args.related_issue_id,
        eoat_assembly_id=args.eoat_assembly_id,
        tool_number=args.tool_number,
        linked_audit_field=args.linked_audit_field,
        description=args.description,
        notes=args.notes,
        copy_mode=not args.move,
    )
    print(result.to_markdown())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
