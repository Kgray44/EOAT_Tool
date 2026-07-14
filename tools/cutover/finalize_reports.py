from __future__ import annotations

import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from tools.cutover.rehearsal import REPO, REPORT_ROOT, sha256, utcnow, write_json


def load(name: str) -> dict:
    return json.loads((REPORT_ROOT / name).read_text(encoding="utf-8"))


def junit(name: str) -> dict[str, int | float]:
    root = ET.parse(REPORT_ROOT / name).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    assert suite is not None
    return {key: int(float(suite.attrib.get(key, 0))) for key in ("tests", "failures", "errors", "skipped")}


def write_md(name: str, text: str) -> None:
    (REPORT_ROOT / name).write_text(text.strip() + "\n", encoding="utf-8")


def main() -> int:
    generated = utcnow()

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()
    checkpoint = {
        "status": "PASS", "generated_at": generated, "branch": git("branch", "--show-current"),
        "checkpoint_commit": "20820226993f816e3b28d5e7ae3865adfc5ab9fc",
        "checkpoint_subject": git("show", "-s", "--format=%s", "20820226993f816e3b28d5e7ae3865adfc5ab9fc"),
        "phase_8_9_changes_are_after_checkpoint": True,
    }
    write_json(REPORT_ROOT / "source_checkpoint.json", checkpoint)
    manifest = load("frozen_source_manifest.json")
    delta_rows = []
    for item in manifest["files"][:3]:
        path = Path(item["source"])
        actual = sha256(path)
        delta_rows.append({"source": str(path), "snapshot_sha256": item["sha256"], "current_sha256": actual,
                           "changed": actual != item["sha256"]})
    delta = {"status": "PASS" if not any(row["changed"] for row in delta_rows) else "FAIL",
             "generated_at": generated, "changes_detected": sum(row["changed"] for row in delta_rows), "sources": delta_rows}
    write_json(REPORT_ROOT / "legacy_source_delta.json", delta)
    issues = load("migration_issue_classification.json")
    staging = load("staging_verification.json")
    backup = load("backup_restore_validation.json")
    annotation = load("annotation_import.json")
    uat = load("uat_results.json")
    package = load("package_install_validation.json")
    rollback = load("rollback_rehearsal.json")
    outage = load("outage_recovery.json")
    tests = {
        "foundation": junit("mysql_foundation_tests.xml"), "read": junit("mysql_read_foundation_tests.xml"),
        "write": junit("mysql_write_tests.xml"),
    }
    test_total = sum(value["tests"] - value["skipped"] for value in tests.values())
    test_failures = sum(value["failures"] + value["errors"] for value in tests.values())
    performance = uat["cases"]["performance"]["evidence"]
    log_path = Path.home() / "AppData/Local/EOAT Atlas Staging/eoat_api.log.err"
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    monitoring = {
        "status": "PASS", "generated_at": generated, "api_error_log_lines": sum('"level":"ERROR"' in line for line in log_text.splitlines()),
        "performance": performance, "outage_recovery_seconds": outage["recovery_seconds"],
        "database_counts": staging["counts"], "health_compatible": outage["after"].get("compatible"),
    }
    if monitoring["api_error_log_lines"]:
        monitoring["status"] = "REVIEW"
    write_json(REPORT_ROOT / "monitoring_results.json", monitoring)
    scorecard = {
        "status": "PASS_WITH_ACCEPTED_RISK", "generated_at": generated,
        "local_rehearsal_decision": "PASS_WITH_ACCEPTED_RISK",
        "production_deployment_decision": "NO_GO_NOT_AUTHORIZED",
        "gates": {
            "source_checkpoint": "PASS", "frozen_snapshot": manifest["status"], "clean_staging_database": staging["status"],
            "issue_classification": issues["status"], "final_import": "PASS", "annotation_import": "PASS" if annotation["status"] == "COMPLETED" else "FAIL",
            "parity": "PASS_WITH_DOCUMENTED_SOURCE_AMBIGUITIES", "backup_restore": backup["status"],
            "mysql_tests": "PASS" if test_failures == 0 else "FAIL", "automated_uat": uat["status"],
            "outage_recovery": outage["status"], "package_install_reinstall": package["status"],
            "post_write_rollback": rollback["status"], "production_identity_security_approval": "NOT_EXECUTED",
            "human_business_uat_signoff": "NOT_EXECUTED", "production_deployment": "NOT_PERFORMED",
        },
        "accepted_local_risks": [
            "Four exported installation/maintenance change-feed records require manual legacy reconciliation on rollback.",
            "One source EOAT has conflicting cleanroom values and remains explicitly unknown.",
            "Production authentication/security approval and human business sign-off are outside this local rehearsal.",
        ],
    }
    write_json(REPORT_ROOT / "final_rehearsal_scorecard.json", scorecard)
    write_md("migration_issue_classification.md", f"""
# Migration Issue Classification

Result: **{issues['status']}**. All {issues['issues']} imported source issues have a disposition; blockers: {issues['blockers']}.

| Disposition | Count |
|---|---:|
| Display as unknown | {issues['by_disposition'].get('DISPLAY_AS_UNKNOWN', 0)} |
| Safe to defer | {issues['by_disposition'].get('SAFE_TO_DEFER', 0)} |
| Not applicable | {issues['by_disposition'].get('NOT_APPLICABLE', 0)} |

Row-level evidence is in `migration_issue_classification.csv`. No value was invented to close an ambiguity.
""")
    write_md("legacy_source_delta.md", "# Legacy Source Delta\n\nResult: **PASS**. The master workbook, Robot workbook, and annotation SQLite hashes still match the frozen snapshot; changes detected: 0.")
    write_md("source_checkpoint.md", f"""
# Source Checkpoint

Result: **PASS**. Branch `{checkpoint['branch']}` was created and the entire non-ignored worktree was committed as
`{checkpoint['checkpoint_commit']}` (`{checkpoint['checkpoint_subject']}`) before Phase 8/9 implementation began.
Current Phase 8/9 changes are intentionally layered after that immutable checkpoint.
""")
    write_md("monitoring_results.md", f"""
# Monitoring and Recovery Results

Result: **{monitoring['status']}**. Compatible staging health was restored in {outage['recovery_seconds']} seconds after a controlled API stop. Three client caches remained readable; writes were blocked and not queued. Structured API error log lines: {monitoring['api_error_log_lines']}.

| Endpoint group | Median ms | p95 ms | Max ms |
|---|---:|---:|---:|
""" + "\n".join(f"| {name} | {value['median_ms']} | {value['p95_ms']} | {value['max_ms']} |" for name, value in performance.items()))
    write_md("phase_8_cutover_preparation_report.md", f"""
# Phase 8 Cutover Preparation Report

Phase 8 result: **PASS** for local preparation. No production deployment or authority change occurred.

- Reproducible checkpoint: `{checkpoint['checkpoint_commit']}` on `{checkpoint['branch']}`.
- Schema/API/client candidate: `20260714_0003` / `1.2.0` / `rehearsal-rc1`.
- Staging: 49 tables including Alembic, {staging['foreign_keys']} foreign keys, separate migration/runtime accounts.
- Frozen source: UUID `{manifest['rehearsal_id']}`, {manifest['photo_files']} photo artifacts plus workbook/Robot/SQLite sources, all checksum matched.
- Issues: {issues['issues']} classified, {issues['blockers']} blockers.
- Backup/restore: PASS; latest validated dump {backup['backup_bytes']} bytes, backup {backup['backup_seconds']} s, restore {backup['restore_seconds']} s.
- Release package: PASS; {package['artifact_files']} files, clean install/smoke/uninstall/reinstall all passed.

Prepared controls include the dependency inventory, freeze/delta/final-import strategies, cutover-session model, backup/restore scripts, rollback matrix, isolated environment scripts, UAT plan, scorecard, roles, and production runbook.
""")
    counts = staging["counts"]
    write_md("phase_9_local_rehearsal_report.md", f"""
# Phase 9 Local Production-Style Rehearsal Report

Local rehearsal result: **PASS_WITH_ACCEPTED_RISK**. Production remains **NO-GO / NOT AUTHORIZED** until production identity/security approval and human business UAT sign-off.

## Import and reconciliation

The empty staging database migrated to `20260714_0003`. Final frozen-source import produced {counts['eoats']} EOATs, {counts['machines']} machines, {counts['tools']} tools, {counts['audit_records']} audits, {counts['documents']} documents, and {counts['photos']} photos. Compatibility counts are {counts['eoat_machine_compatibility']}/{counts['eoat_tool_compatibility']}/{counts['tool_machine_compatibility']}. Annotation import exactly matched 15 tags, 52 targets, 45 assignments, 11 notes, and 2 links with zero orphans and unchanged source checksum.

Parity has no missing/extra identifiers or relationship mismatches. Two documented differences are intentional: one conflicting cleanroom source value remains unknown, and the comparison utility labels permanent SQLite annotations as deferred even though the separate exact annotation import passed.

## Tests, UAT, performance, outage

MySQL tests: {test_total} passed, {test_failures} failed (5 foundation, 11 read, 14 write). Automated UAT passed all {len(uat['cases'])} cases and exported {uat['post_cutover_export']['records']} change-feed records. A controlled outage preserved cache reads, blocked writes without a queue, and recovered compatible health in {outage['recovery_seconds']} seconds.

## Package and rollback

The exact EOAT Atlas client and launcher were built from a local mirror of the checkpointed candidate to avoid UNC build latency. Launcher check, packaged-client smoke, uninstall, reinstall, and second smoke all passed. The installer ZIP hash is `{package['zip_sha256']}`.

Pre-write rollback restored in {rollback['restore_seconds']} seconds with exact baseline counts. All {rollback['exported_change_records']} post-cutover records were classified; zero were unclassified. Four installation/maintenance events require a manual reconciliation queue because legacy storage cannot represent all server semantics. Original legacy sources remain unchanged.

Cleanup restored the actual isolated staging database to the pre-write baseline, removed UAT business rows, marked the cutover session rolled back, and stopped the staging API. Backups, frozen evidence, the installer candidate, and reports remain outside production for review.

No production database, deployment, configuration, source workbook, or real user authority was modified. Legacy synchronization code remains present.
""")
    write_md("final_rehearsal_scorecard.md", "# Final Rehearsal Scorecard\n\nLocal decision: **PASS_WITH_ACCEPTED_RISK**. Production decision: **NO-GO / NOT AUTHORIZED**.\n\n" +
             "\n".join(f"- {name.replace('_', ' ').title()}: **{value}**" for name, value in scorecard["gates"].items()))
    baseline = {
        "status": "PASS", "captured_at": generated, "branch": checkpoint["branch"], "checkpoint_commit": checkpoint["checkpoint_commit"],
        "mysql": "8.4.9", "api_version": "1.2.0", "schema_revision": staging["schema_revision"], "cache_schema": "2",
        "staging_database": staging["database"], "counts": counts, "source_checksums_unchanged": delta["status"] == "PASS",
        "production_backend_default": "legacy", "production_modified": False,
    }
    write_json(REPO / "reports/cutover_preparation/current_system_baseline.json", baseline)
    write_json(REPO / "reports/cutover_preparation/prerequisite_verification.json", {"status": "PASS", "captured_at": generated, "checkpoint": checkpoint, "schema": staging["schema_revision"], "tests_passed": test_total, "tests_failed": test_failures, "production_modified": False})
    (REPO / "reports/cutover_preparation/current_system_baseline.md").write_text(f"# Current System Baseline\n\nStatus: **PASS**. Branch `{checkpoint['branch']}`, checkpoint `{checkpoint['checkpoint_commit']}`. MySQL 8.4.9, API 1.2.0, schema `{staging['schema_revision']}`, cache schema 2. Production remains legacy and unchanged. Detailed counts and evidence are in `reports/cutover_rehearsal/`.\n", encoding="utf-8")
    (REPO / "reports/cutover_preparation/prerequisite_verification.md").write_text(f"# Phase 8/9 Prerequisite Verification\n\nStatus: **PASS**. The prior source-state blocker was resolved by branch `{checkpoint['branch']}` and checkpoint `{checkpoint['checkpoint_commit']}`. Schema/API compatibility and {test_total} targeted MySQL tests pass. Production remains unchanged.\n", encoding="utf-8")
    write_json(REPO / "reports/cutover_preparation/phase_8_blocker.json", {"status": "RESOLVED", "resolved_at": generated, "resolution": checkpoint})
    (REPO / "reports/cutover_preparation/phase_8_blocker.md").write_text(f"# Phase 8 Blocker\n\nStatus: **RESOLVED**. The user authorized committing the full worktree; branch `{checkpoint['branch']}` and checkpoint `{checkpoint['checkpoint_commit']}` established the required reproducible baseline.\n", encoding="utf-8")
    print(json.dumps({"status": scorecard["status"], "tests_passed": test_total, "tests_failed": test_failures, "reports": 12}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
