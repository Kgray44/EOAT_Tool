from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pymysql

REPO = Path(__file__).resolve().parents[2]
DEV_STATE = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "EOAT Atlas Development"
STAGING_STATE = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "EOAT Atlas Staging"
STAGING_DB = "eoat_atlas_staging_local"
RESTORE_DB = "eoat_atlas_staging_restore_check"
ALLOWED_DATABASES = {STAGING_DB, RESTORE_DB}
SOURCE_WORKBOOK = REPO / "EOAT_Standardization_Project/01_EOAT_Audit/EOAT_Audit_Database/EOAT_Master_Tracker.xlsx"
SOURCE_ROBOT = REPO / "EOAT_Standardization_Project/01_EOAT_Audit/EOAT_Audit_Database/Robot_Info.xlsx"
SOURCE_SQLITE = REPO / "EOAT_Standardization_Project/project_data/annotations.sqlite"
REPORT_ROOT = REPO / "reports/cutover_rehearsal"
EXPECTED_REVISION = "20260714_0004"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def run(command: list[str], *, env: dict[str, str], stdin: Path | None = None) -> float:
    started = time.perf_counter()
    source = stdin.open("rb") if stdin else None
    try:
        subprocess.run(command, cwd=REPO, env=env, stdin=source, check=True)
    finally:
        if source:
            source.close()
    return round(time.perf_counter() - started, 3)


def root_connection(dev: dict[str, str], database: str | None = None):
    return pymysql.connect(
        host=dev.get("EOAT_DB_HOST", "127.0.0.1"),
        port=int(dev.get("EOAT_DB_PORT", "3306")),
        user="root",
        password=dev["EOAT_DB_ROOT_PASSWORD"],
        database=database,
        autocommit=True,
        connect_timeout=5,
    )


def staging_environment(*, reset: bool) -> dict[str, object]:
    dev = read_env(DEV_STATE / "database.env")
    STAGING_STATE.mkdir(parents=True, exist_ok=True)
    env_path = STAGING_STATE / "staging.env"
    existing = read_env(env_path) if env_path.exists() else {}
    migration_password = existing.get("EOAT_DB_MIGRATION_PASSWORD") or secrets.token_hex(24)
    runtime_password = existing.get("EOAT_DB_PASSWORD") or secrets.token_hex(24)
    with root_connection(dev) as connection, connection.cursor() as cursor:
        if reset:
            cursor.execute(f"DROP DATABASE IF EXISTS `{STAGING_DB}`")
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{STAGING_DB}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        )
        for user, password in (("eoat_staging_migrator", migration_password), ("eoat_staging_runtime", runtime_password)):
            cursor.execute(f"CREATE USER IF NOT EXISTS '{user}'@'127.0.0.1' IDENTIFIED BY %s", (password,))
            cursor.execute(f"ALTER USER '{user}'@'127.0.0.1' IDENTIFIED BY %s", (password,))
        cursor.execute(f"GRANT ALL PRIVILEGES ON `{STAGING_DB}`.* TO 'eoat_staging_migrator'@'127.0.0.1'")
        cursor.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{STAGING_DB}`.* "
            "TO 'eoat_staging_runtime'@'127.0.0.1'"
        )
    values = {
        "EOAT_DB_HOST": dev.get("EOAT_DB_HOST", "127.0.0.1"),
        "EOAT_DB_PORT": dev.get("EOAT_DB_PORT", "3306"),
        "EOAT_DB_NAME": STAGING_DB,
        "EOAT_DB_USER": "eoat_staging_runtime",
        "EOAT_DB_PASSWORD": runtime_password,
        "EOAT_DB_MIGRATION_USER": "eoat_staging_migrator",
        "EOAT_DB_MIGRATION_PASSWORD": migration_password,
        "EOAT_DB_DRIVER": "pymysql",
    }
    env_path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    command_env = os.environ.copy() | values
    seconds = run([sys.executable, "-m", "alembic", "-c", "server/alembic.ini", "upgrade", "head"], env=command_env)
    with pymysql.connect(
        host=values["EOAT_DB_HOST"], port=int(values["EOAT_DB_PORT"]), user=values["EOAT_DB_USER"],
        password=values["EOAT_DB_PASSWORD"], database=STAGING_DB, connect_timeout=5,
    ) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        revision = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s", (STAGING_DB,))
        tables = cursor.fetchone()[0]
    result = {
        "status": "PASS" if revision == EXPECTED_REVISION else "FAIL",
        "database": STAGING_DB,
        "host": values["EOAT_DB_HOST"],
        "schema_revision": revision,
        "table_count_including_alembic": tables,
        "separate_runtime_and_migration_accounts": True,
        "secrets_location": str(env_path),
        "migration_seconds": seconds,
        "generated_at": utcnow(),
    }
    write_json(REPORT_ROOT / "staging_environment.json", result)
    return result


def freeze_sources() -> dict[str, object]:
    rehearsal_id = str(uuid4())
    target = STAGING_STATE / "rehearsals" / rehearsal_id / "frozen_source"
    target.mkdir(parents=True)
    sources = [SOURCE_WORKBOOK, SOURCE_ROBOT, SOURCE_SQLITE]
    photo_root = REPO / "EOAT_Standardization_Project/01_EOAT_Audit/Cell_Photos"
    sources.extend(sorted(path for path in photo_root.rglob("*") if path.is_file()))
    records = []
    for source in sources:
        if not source.exists():
            raise FileNotFoundError(source)
        destination = target / source.relative_to(REPO / "EOAT_Standardization_Project")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        destination.chmod(0o444)
        records.append(
            {
                "source": str(source), "frozen_copy": str(destination), "size": source.stat().st_size,
                "modified_utc": datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat(),
                "sha256": sha256(source), "copy_sha256": sha256(destination),
            }
        )
    manifest = {
        "status": "PASS" if all(x["sha256"] == x["copy_sha256"] for x in records) else "FAIL",
        "rehearsal_id": rehearsal_id,
        "created_at": utcnow(),
        "frozen_source_directory": str(target),
        "originals_are_authoritative": False,
        "files": records,
        "photo_files": len(records) - 3,
    }
    write_json(REPORT_ROOT / "frozen_source_manifest.json", manifest)
    write_json(target.parent / "manifest.json", manifest)
    return manifest


ISSUE_DISPOSITIONS = {
    "POSSIBLE_PART_NOT_CONFIRMED": "SAFE_TO_DEFER",
    "INSTALLATION_DATE_UNKNOWN": "DISPLAY_AS_UNKNOWN",
    "CURRENT_LOCATION_UNKNOWN": "DISPLAY_AS_UNKNOWN",
    "MISSING_MACHINE": "DISPLAY_AS_UNKNOWN",
    "MISSING_TOOL": "DISPLAY_AS_UNKNOWN",
    "AMBIGUOUS_MACHINE_VALUE": "DISPLAY_AS_UNKNOWN",
    "CONFLICTING_CURRENT_ASSIGNMENT": "DISPLAY_AS_UNKNOWN",
    "CONFLICTING_EOAT_ATTRIBUTE": "DISPLAY_AS_UNKNOWN",
    "PLACEHOLDER_PHOTO_ROW": "NOT_APPLICABLE",
}


def classify_issues(import_report: Path) -> dict[str, object]:
    report = json.loads(import_report.read_text(encoding="utf-8"))
    rows = []
    for issue in report.get("issues", []):
        code = issue["issue_code"]
        disposition = ISSUE_DISPOSITIONS.get(code, "BLOCKER")
        rows.append({
            "issue_id": issue["issue_id"], "issue_code": code, "source_sheet": issue.get("source_sheet"),
            "source_row": issue.get("source_row"), "entity": issue.get("affected_entity_identifier"),
            "disposition": disposition, "reason": issue.get("current_proposed_action", ""),
        })
    output = REPORT_ROOT / "migration_issue_classification.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["issue_id"])
        writer.writeheader()
        writer.writerows(rows)
    dispositions = Counter(row["disposition"] for row in rows)
    result = {
        "status": "PASS" if not dispositions.get("BLOCKER") else "FAIL",
        "generated_at": utcnow(), "source_report": str(import_report), "issues": len(rows),
        "by_code": dict(Counter(row["issue_code"] for row in rows)), "by_disposition": dict(dispositions),
        "blockers": dispositions.get("BLOCKER", 0), "csv": str(output),
    }
    write_json(REPORT_ROOT / "migration_issue_classification.json", result)
    return result


def database_counts(env: dict[str, str], database: str) -> dict[str, int]:
    tables = [
        "plants", "areas", "eoats", "machines", "tools", "robots", "eoat_machine_compatibility",
        "eoat_tool_compatibility", "tool_machine_compatibility", "audit_records", "documents", "photos",
        "tags", "annotation_targets", "entity_tags", "annotations", "annotation_target_links", "import_batches",
        "import_rows", "import_issues", "change_audit_log", "change_feed",
    ]
    values: dict[str, int] = {}
    with pymysql.connect(
        host=env["EOAT_DB_HOST"], port=int(env["EOAT_DB_PORT"]), user=env["EOAT_DB_USER"],
        password=env["EOAT_DB_PASSWORD"], database=database, connect_timeout=5,
    ) as connection, connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
            values[table] = cursor.fetchone()[0]
    return values


def backup_restore_check() -> dict[str, object]:
    staging = read_env(STAGING_STATE / "staging.env")
    dev = read_env(DEV_STATE / "database.env")
    mysql_bin = DEV_STATE / "mysql-8.4.9-winx64/bin"
    artifact = STAGING_STATE / "backups" / f"{STAGING_DB}-{datetime.now():%Y%m%d-%H%M%S}.sql"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    dump_env = os.environ.copy() | {"MYSQL_PWD": staging["EOAT_DB_MIGRATION_PASSWORD"]}
    started = time.perf_counter()
    with artifact.open("wb") as stream:
        subprocess.run(
            [str(mysql_bin / "mysqldump.exe"), "--host=127.0.0.1", "--port=3306",
             f"--user={staging['EOAT_DB_MIGRATION_USER']}", "--single-transaction", "--no-tablespaces", "--routines", "--triggers",
             "--set-gtid-purged=OFF", STAGING_DB], stdout=stream, env=dump_env, check=True,
        )
    backup_seconds = round(time.perf_counter() - started, 3)
    before = database_counts(staging, STAGING_DB)
    with root_connection(dev) as connection, connection.cursor() as cursor:
        cursor.execute(f"DROP DATABASE IF EXISTS `{RESTORE_DB}`")
        cursor.execute(f"CREATE DATABASE `{RESTORE_DB}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
        cursor.execute(f"GRANT ALL PRIVILEGES ON `{RESTORE_DB}`.* TO 'eoat_staging_migrator'@'127.0.0.1'")
        cursor.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{RESTORE_DB}`.* "
            "TO 'eoat_staging_runtime'@'127.0.0.1'"
        )
    restore_env = dump_env.copy()
    started = time.perf_counter()
    with artifact.open("rb") as stream:
        subprocess.run(
            [str(mysql_bin / "mysql.exe"), "--host=127.0.0.1", "--port=3306",
             f"--user={staging['EOAT_DB_MIGRATION_USER']}", RESTORE_DB], stdin=stream, env=restore_env, check=True,
        )
    restore_seconds = round(time.perf_counter() - started, 3)
    after = database_counts(staging, RESTORE_DB)
    with root_connection(dev) as connection, connection.cursor() as cursor:
        cursor.execute(f"DROP DATABASE `{RESTORE_DB}`")
    result = {
        "status": "PASS" if before == after else "FAIL", "generated_at": utcnow(),
        "database": STAGING_DB, "restore_database": RESTORE_DB, "backup_path": str(artifact),
        "backup_sha256": sha256(artifact), "backup_bytes": artifact.stat().st_size,
        "backup_seconds": backup_seconds, "restore_seconds": restore_seconds,
        "source_counts": before, "restored_counts": after, "restore_database_removed": True,
    }
    write_json(REPORT_ROOT / "backup_restore_validation.json", result)
    return result


def create_session(manifest: Path, status: str) -> dict[str, object]:
    staging = read_env(STAGING_STATE / "staging.env")
    source = json.loads(manifest.read_text(encoding="utf-8"))
    session_uuid = source["rehearsal_id"]
    workbook_hash = next(item["sha256"] for item in source["files"] if item["source"].endswith(".xlsx"))
    with pymysql.connect(
        host=staging["EOAT_DB_HOST"], port=int(staging["EOAT_DB_PORT"]), user=staging["EOAT_DB_USER"],
        password=staging["EOAT_DB_PASSWORD"], database=STAGING_DB, autocommit=True,
    ) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO cutover_sessions "
            "(cutover_uuid,environment,source_checksum,source_snapshot_timestamp,database_schema_revision,"
            "api_version,client_version,started_at,status,rollback_deadline,source_system) "
            "VALUES (%s,'staging_local',%s,UTC_TIMESTAMP(6),%s,'1.3.0','rehearsal-rc1',UTC_TIMESTAMP(6),%s,"
            "DATE_ADD(UTC_TIMESTAMP(6),INTERVAL 24 HOUR),'eoat_atlas_cutover_rehearsal') "
            "ON DUPLICATE KEY UPDATE status=VALUES(status), "
            "authority_enabled_at=IF(VALUES(status) IN ('AUTHORITY_ENABLED','MONITORING','COMPLETED'),"
            "COALESCE(authority_enabled_at,UTC_TIMESTAMP(6)),authority_enabled_at), "
            "completed_at=IF(VALUES(status)='COMPLETED',UTC_TIMESTAMP(6),completed_at), updated_at=UTC_TIMESTAMP(6)",
            (session_uuid, workbook_hash, EXPECTED_REVISION, status),
        )
        cursor.execute("SELECT id,status,start_change_feed_cursor FROM cutover_sessions WHERE cutover_uuid=%s", (session_uuid,))
        row = cursor.fetchone()
    result = {"status": "PASS", "cutover_uuid": session_uuid, "database_id": row[0], "session_status": row[1],
              "start_change_feed_cursor": row[2], "generated_at": utcnow()}
    write_json(REPORT_ROOT / "cutover_session.json", result)
    return result


def verify() -> dict[str, object]:
    staging = read_env(STAGING_STATE / "staging.env")
    counts = database_counts(staging, STAGING_DB)
    with pymysql.connect(
        host=staging["EOAT_DB_HOST"], port=int(staging["EOAT_DB_PORT"]), user=staging["EOAT_DB_USER"],
        password=staging["EOAT_DB_PASSWORD"], database=STAGING_DB,
    ) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        revision = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM information_schema.referential_constraints WHERE constraint_schema=%s", (STAGING_DB,))
        foreign_keys = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=%s", (STAGING_DB,))
        indexes = cursor.fetchone()[0]
    result = {"status": "PASS" if revision == EXPECTED_REVISION else "FAIL", "generated_at": utcnow(),
              "database": STAGING_DB, "schema_revision": revision, "foreign_keys": foreign_keys,
              "index_columns": indexes, "counts": counts}
    write_json(REPORT_ROOT / "staging_verification.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="EOAT Atlas isolated local cutover rehearsal utility")
    sub = parser.add_subparsers(dest="command", required=True)
    environment = sub.add_parser("environment")
    environment.add_argument("--reset", action="store_true")
    sub.add_parser("freeze")
    classify = sub.add_parser("classify")
    classify.add_argument("--import-report", type=Path, required=True)
    sub.add_parser("backup-restore")
    session = sub.add_parser("session")
    session.add_argument("--manifest", type=Path, required=True)
    session.add_argument("--status", default="SOURCE_FROZEN")
    sub.add_parser("verify")
    args = parser.parse_args()
    if args.command == "environment":
        result = staging_environment(reset=args.reset)
    elif args.command == "freeze":
        result = freeze_sources()
    elif args.command == "classify":
        result = classify_issues(args.import_report)
    elif args.command == "backup-restore":
        result = backup_restore_check()
    elif args.command == "session":
        result = create_session(args.manifest, args.status)
    else:
        result = verify()
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
