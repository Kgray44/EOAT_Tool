from __future__ import annotations

import sys

from app.atlas.main import main


def _force_minimalist_ui(argv: list[str]) -> list[str]:
    cleaned: list[str] = []
    skip_next = False
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        lowered = arg.casefold()
        if lowered in {"--ui", "-ui"}:
            skip_next = True
            continue
        if lowered.startswith("--ui=") or lowered.startswith("-ui="):
            continue
        cleaned.append(arg)
    return [*cleaned, "--ui=minimalist"]


if __name__ == "__main__":
    sys.argv = _force_minimalist_ui(sys.argv)
    raise SystemExit(main())
