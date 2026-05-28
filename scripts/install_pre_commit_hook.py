from __future__ import annotations

import argparse
from pathlib import Path

from core.constants import TOOLKIT_ROOT
from core.release_readiness import install_pre_commit_hook


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the local EOAT Command Center pre-commit safety hook.")
    parser.add_argument("--root", default=str(TOOLKIT_ROOT), help="Repository root. Defaults to this checkout.")
    parser.add_argument("--git", default="git", help="Git executable.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing local hook after backing it up.")
    args = parser.parse_args(argv)

    result = install_pre_commit_hook(Path(args.root), git_executable=args.git, force=args.force)
    print(result.to_markdown())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
