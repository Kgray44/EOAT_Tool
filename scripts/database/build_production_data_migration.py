import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.database.production_data_migration import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
