from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

from core.constants import DEFAULT_PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate EOAT PM checklist drafts.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--audit-id", default=None)
    parser.add_argument("--press", default=None)
    parser.add_argument("--all", action="store_true", help="Generate checklists for all audited EOAT rows.")
    parser.add_argument("--generic", action="store_true", help="Generate generic vacuum/mechanical/hybrid templates.")
    parser.add_argument("--docx", action="store_true", help="Also generate DOCX files when python-docx is available.")
    parser.add_argument("--excel", action="store_true", help="Reserved for future Excel checklist output.")
    args = parser.parse_args()
    formats = ["markdown"]
    if args.docx:
        formats.append("docx")
    if args.excel:
        formats.append("excel")
    from core.pm_checklists import generate_pm_checklists

    result = generate_pm_checklists(
        args.project_root,
        audit_id=args.audit_id,
        press=args.press,
        all_audited=args.all,
        generic=args.generic,
        formats=formats,
    )
    print(result.to_markdown())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
