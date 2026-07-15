from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.eoat_api.database.session import create_database_engine  # noqa: E402
from tests.fixtures.mysql_sanctioned import load_sanctioned_fixture  # noqa: E402


def main() -> int:
    if os.getenv("EOAT_DB_NAME") != "eoat_atlas_test":
        print("ERROR: sanctioned fixture loading is restricted to eoat_atlas_test.", file=sys.stderr)
        return 2
    with Session(create_database_engine(migration=True)) as session, session.begin():
        counts = load_sanctioned_fixture(session)
    print("Loaded sanctioned synthetic fixture: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
