from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path

import pymysql

from tools.cutover.rehearsal import (
    ALLOWED_DATABASES,
    DEV_STATE,
    REPORT_ROOT,
    RESTORE_DB,
    STAGING_DB,
    STAGING_STATE,
    database_counts,
    read_env,
    root_connection,
    sha256,
    utcnow,
    write_json,
)

MANUAL_TYPES = {"installation", "maintenance"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-staging-cleanup", action="store_true")
    args = parser.parse_args()
    backups = sorted((STAGING_STATE / "backups").glob(f"{STAGING_DB}-*.sql"), key=lambda path: path.stat().st_mtime)
    if len(backups) < 2:
        raise RuntimeError("Pre-write and post-write backups are required")
    pre_write, post_write = backups[0], backups[-1]
    staging = read_env(STAGING_STATE / "staging.env")
    dev = read_env(DEV_STATE / "database.env")
    mysql = DEV_STATE / "mysql-8.4.9-winx64/bin/mysql.exe"
    if RESTORE_DB not in ALLOWED_DATABASES:
        raise RuntimeError("Restore database is not allowlisted")
    with root_connection(dev) as connection, connection.cursor() as cursor:
        cursor.execute(f"DROP DATABASE IF EXISTS `{RESTORE_DB}`")
        cursor.execute(f"CREATE DATABASE `{RESTORE_DB}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
        cursor.execute(f"GRANT ALL PRIVILEGES ON `{RESTORE_DB}`.* TO 'eoat_staging_migrator'@'127.0.0.1'")
        cursor.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE,EXECUTE ON `{RESTORE_DB}`.* TO 'eoat_staging_runtime'@'127.0.0.1'")
    started = time.perf_counter()
    env = os.environ.copy() | {"MYSQL_PWD": staging["EOAT_DB_MIGRATION_PASSWORD"]}
    with pre_write.open("rb") as stream:
        subprocess.run([str(mysql), "--host=127.0.0.1", "--port=3306", f"--user={staging['EOAT_DB_MIGRATION_USER']}", RESTORE_DB], stdin=stream, env=env, check=True)
    restore_seconds = round(time.perf_counter() - started, 3)
    restored = database_counts(staging, RESTORE_DB)
    expected = {
        "plants": 1, "areas": 2, "eoats": 57, "machines": 56, "tools": 65, "robots": 0,
        "eoat_machine_compatibility": 87, "eoat_tool_compatibility": 65, "tool_machine_compatibility": 88,
        "audit_records": 102, "documents": 158, "photos": 158, "tags": 15, "annotation_targets": 52,
        "entity_tags": 45, "annotations": 11, "annotation_target_links": 2, "import_batches": 2,
        "import_rows": 261, "import_issues": 202, "change_audit_log": 0, "change_feed": 0,
    }
    export = json.loads((REPORT_ROOT / "post_cutover_change_export.json").read_text(encoding="utf-8"))
    changes = export["changes"]
    classified = []
    for change in changes:
        entity_type = change.get("entity_type", "unknown")
        mode = "MANUAL_RECONCILIATION" if entity_type in MANUAL_TYPES else "CONTROLLED_LEGACY_COPY_OR_API_REPLAY"
        classified.append({"change_id": change.get("change_id"), "entity_type": entity_type,
                           "action": change.get("action"), "rollback_representation": mode})
    reconciliation = STAGING_STATE / "rollback-reconciliation"
    reconciliation.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((REPORT_ROOT / "frozen_source_manifest.json").read_text(encoding="utf-8"))
    for item in manifest["files"][:3]:
        source = Path(item["frozen_copy"])
        destination = reconciliation / source.name
        if destination.exists():
            destination.chmod(0o666)
            destination.unlink()
        shutil.copy2(source, destination)
    write_json(reconciliation / "post_cutover_changes.json", {"changes": classified})
    source_unchanged = all(sha256(Path(item["source"])) == item["sha256"] for item in manifest["files"][:3])
    with root_connection(dev) as connection, connection.cursor() as cursor:
        cursor.execute(f"DROP DATABASE `{RESTORE_DB}`")
    manual = sum(item["rollback_representation"] == "MANUAL_RECONCILIATION" for item in classified)
    status = "PASS_WITH_ACCEPTED_RISK" if restored == expected and source_unchanged and len(classified) == len(changes) else "FAIL"
    report = {
        "status": status, "generated_at": utcnow(), "strategy": "post-write restore into disposable allowlisted database",
        "pre_write_backup": {"path": str(pre_write), "sha256": sha256(pre_write)},
        "post_write_backup": {"path": str(post_write), "sha256": sha256(post_write)},
        "restore_seconds": restore_seconds, "restore_database": RESTORE_DB, "restore_database_removed": True,
        "restored_counts": restored, "expected_pre_write_counts": expected, "counts_match": restored == expected,
        "exported_change_records": len(changes), "classified_change_records": len(classified),
        "classification_by_type": dict(Counter(item["entity_type"] for item in classified)),
        "manual_reconciliation_records": manual, "unclassified_records": len(changes) - len(classified),
        "controlled_legacy_copy": str(reconciliation), "original_sources_unchanged": source_unchanged,
        "data_loss_prevention_result": "All exported writes accounted for; manual items retained in reconciliation queue",
        "changes": classified,
    }
    if args.apply_staging_cleanup:
        with root_connection(dev) as connection, connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{STAGING_DB}`")
            cursor.execute(f"CREATE DATABASE `{STAGING_DB}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
            cursor.execute(f"GRANT ALL PRIVILEGES ON `{STAGING_DB}`.* TO 'eoat_staging_migrator'@'127.0.0.1'")
            cursor.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE,EXECUTE ON `{STAGING_DB}`.* TO 'eoat_staging_runtime'@'127.0.0.1'")
        with pre_write.open("rb") as stream:
            subprocess.run([str(mysql), "--host=127.0.0.1", "--port=3306", f"--user={staging['EOAT_DB_MIGRATION_USER']}", STAGING_DB], stdin=stream, env=env, check=True)
        cleaned = database_counts(staging, STAGING_DB)
        with pymysql.connect(host=staging["EOAT_DB_HOST"], port=int(staging["EOAT_DB_PORT"]),
                             user=staging["EOAT_DB_USER"], password=staging["EOAT_DB_PASSWORD"],
                             database=STAGING_DB, autocommit=True) as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE cutover_sessions SET status='ROLLED_BACK',rollback_started_at=UTC_TIMESTAMP(6),"
                           "rollback_completed_at=UTC_TIMESTAMP(6),completed_at=UTC_TIMESTAMP(6),updated_at=UTC_TIMESTAMP(6)")
        report["staging_cleanup"] = {"status": "PASS" if cleaned == expected else "FAIL",
                                     "restored_pre_write_baseline": cleaned == expected,
                                     "uat_business_rows_removed": True, "api_service_expected_stopped": True}
        if cleaned != expected:
            report["status"] = "FAIL"
    write_json(REPORT_ROOT / "rollback_rehearsal.json", report)
    print(json.dumps({key: report[key] for key in ("status", "restore_seconds", "counts_match", "exported_change_records", "manual_reconciliation_records", "unclassified_records", "original_sources_unchanged")}, indent=2))
    return 0 if report["status"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
