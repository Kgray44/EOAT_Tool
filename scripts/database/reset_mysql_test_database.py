from __future__ import annotations

import argparse
import os
import subprocess
import sys

import pymysql

APPROVED_DATABASES = {"eoat_atlas_test"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset an approved EOAT Atlas MySQL test database through Alembic.")
    parser.add_argument("--database", default=os.getenv("EOAT_DB_NAME", "eoat_atlas_test"))
    args = parser.parse_args()
    if args.database not in APPROVED_DATABASES:
        parser.error(f"Refusing destructive reset for unapproved database '{args.database}'.")
    environment = os.environ.copy()
    environment["EOAT_DB_NAME"] = args.database
    required = ("EOAT_DB_ROOT_PASSWORD", "EOAT_DB_USER", "EOAT_DB_MIGRATION_USER")
    missing = [name for name in required if not environment.get(name)]
    if missing:
        parser.error(f"Missing required reset environment: {', '.join(missing)}")
    connection = pymysql.connect(
        host=environment.get("EOAT_DB_HOST", "127.0.0.1"),
        port=int(environment.get("EOAT_DB_PORT", "3306")),
        user="root",
        password=environment["EOAT_DB_ROOT_PASSWORD"],
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{args.database}`")
            cursor.execute(f"CREATE DATABASE `{args.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
            cursor.execute(
                f"GRANT ALL PRIVILEGES ON `{args.database}`.* TO %s@'127.0.0.1'",
                (environment["EOAT_DB_MIGRATION_USER"],),
            )
            cursor.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON `{args.database}`.* TO %s@'127.0.0.1'",
                (environment["EOAT_DB_USER"],),
            )
    finally:
        connection.close()
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "server/alembic.ini", "upgrade", "head"],
        env=environment,
        check=False,
    )
    if result.returncode:
        return result.returncode
    print(f"Reset {args.database} to the current Alembic head.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
