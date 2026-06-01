from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

from core.constants import DEFAULT_PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate final EOAT project summary draft.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--include-docx", action="store_true")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    from core.final_summary import generate_final_project_summary

    result = generate_final_project_summary(args.project_root, include_docx=args.include_docx, notes=args.notes)
    print(result.to_markdown())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
