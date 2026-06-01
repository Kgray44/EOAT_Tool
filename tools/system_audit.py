from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLKIT_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_ROOT))

from core.constants import DEFAULT_PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description="Run EOAT Command Center system audit.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--skip-cli-help", action="store_true")
    args = parser.parse_args()
    from core.system_audit import run_system_audit

    result = run_system_audit(args.project_root, check_cli_help=not args.skip_cli_help)
    print(result.to_markdown())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
