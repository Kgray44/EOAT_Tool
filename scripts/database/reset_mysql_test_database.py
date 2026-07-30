from __future__ import annotations

import argparse
import os
import subprocess
import sys

import pymysql

APPROVED_DATABASES = {"eoat_atlas_test"}
APPROVED_TEST_HOSTS = {"127.0.0.1", "::1", "localhost"}
MAX_MYSQL_USERNAME_LENGTH = 32


def _approved_test_host(value: str | None) -> str | None:
    host = str(value or "127.0.0.1").strip().casefold().strip("[]").rstrip(".")
    return host if host in APPROVED_TEST_HOSTS else None


def _validate_test_identity(user_name: str, *, field: str, parser: argparse.ArgumentParser) -> None:
    if not user_name.strip():
        parser.error(f"{field} is required.")
    if len(user_name) > MAX_MYSQL_USERNAME_LENGTH:
        parser.error(f"{field} exceeds the MySQL {MAX_MYSQL_USERNAME_LENGTH}-character limit.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset an approved EOAT Atlas MySQL test database through Alembic.")
    parser.add_argument("--database", default=os.getenv("EOAT_DB_NAME", "eoat_atlas_test"))
    args = parser.parse_args()
    if args.database not in APPROVED_DATABASES:
        parser.error(f"Refusing destructive reset for unapproved database '{args.database}'.")
    environment = os.environ.copy()
    environment["EOAT_DB_NAME"] = args.database
    host = _approved_test_host(environment.get("EOAT_DB_HOST"))
    if host is None:
        parser.error("Refusing destructive reset for a non-loopback database host.")
    environment["EOAT_DB_HOST"] = host
    required = (
        "EOAT_DB_ROOT_PASSWORD",
        "EOAT_DB_USER",
        "EOAT_DB_PASSWORD",
        "EOAT_DB_MIGRATION_USER",
        "EOAT_DB_MIGRATION_PASSWORD",
    )
    missing = [name for name in required if not environment.get(name)]
    if missing:
        parser.error(f"Missing required reset environment: {', '.join(missing)}")
    _validate_test_identity(environment["EOAT_DB_USER"], field="EOAT_DB_USER", parser=parser)
    _validate_test_identity(
        environment["EOAT_DB_MIGRATION_USER"], field="EOAT_DB_MIGRATION_USER", parser=parser
    )
    connection = pymysql.connect(
        host=host,
        port=int(environment.get("EOAT_DB_PORT", "3306")),
        user="root",
        password=environment["EOAT_DB_ROOT_PASSWORD"],
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            for user_name, password_name in (
                (environment["EOAT_DB_USER"], "EOAT_DB_PASSWORD"),
                (environment["EOAT_DB_MIGRATION_USER"], "EOAT_DB_MIGRATION_PASSWORD"),
            ):
                if user_name != "root":
                    cursor.execute(
                        "CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s",
                        (user_name, environment[password_name]),
                    )
            cursor.execute(f"DROP DATABASE IF EXISTS `{args.database}`")
            cursor.execute(f"CREATE DATABASE `{args.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
            if environment["EOAT_DB_MIGRATION_USER"] != "root":
                cursor.execute(
                    f"GRANT ALL PRIVILEGES ON `{args.database}`.* TO %s@'%%'",
                    (environment["EOAT_DB_MIGRATION_USER"],),
                )
            cursor.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{args.database}`.* TO %s@'%%'",
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
