from __future__ import annotations

import sys

from app.atlas.main import main


def _ensure_ui_mode(argv: list[str]) -> None:
    if any(arg.casefold() in {"--ui", "-ui"} or arg.casefold().startswith(("--ui=", "-ui=")) for arg in argv):
        return
    argv.append("--ui=minimalist")


if __name__ == "__main__":
    _ensure_ui_mode(sys.argv)
    raise SystemExit(main())
