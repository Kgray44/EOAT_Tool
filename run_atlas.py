from __future__ import annotations

import sys

CANONICAL_REPOSITORY = (
    r"\\example.invalid\VT/Sanitized/Example\My Documents\KG_Nolato_Summer_2026_Globalized_Development"
)


def main() -> int:
    print(
        "This EOAT Atlas repository is archived.\n\n"
        f"Use:\n{CANONICAL_REPOSITORY}\n\n"
        "Run:\npython run_atlas.py",
        file=sys.stderr,
    )
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
