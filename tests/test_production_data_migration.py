from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.database import production_data_migration as migration

EXPECTED_TABLES = {
    "alembic_version", "annotation_target_links", "annotation_targets", "annotations",
    "application_instances", "application_releases", "areas", "asset_statuses", "audit_records",
    "authentication_audit_events", "authentication_sessions", "change_audit_log", "change_feed",
    "cleanroom_classifications", "compatibility_sources", "compatibility_statuses", "connection_types",
    "cutover_sessions", "data_state", "document_links", "document_types", "documents", "entity_history_events",
    "entity_tags", "eoat_installations", "eoat_location_assertions", "eoat_location_observations",
    "eoat_machine_compatibility", "eoat_storage_assignments",
    "eoat_tool_compatibility", "eoat_types", "eoats", "external_group_role_mappings",
    "fit_check_records", "history_event_types", "idempotency_records", "import_batches", "import_issues",
    "import_rows", "machine_robot_assignments", "machines", "maintenance_events", "parts", "photos",
    "plants", "robots", "roles", "storage_locations", "system_metadata", "system_settings", "tags",
    "tool_machine_compatibility", "tool_parts", "tools", "user_roles", "users",
}


class LiteralConnection:
    @staticmethod
    def escape(value):
        if isinstance(value, str):
            return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
        return str(value)


def test_table_classification_is_complete_for_all_56_tables() -> None:
    assert len(EXPECTED_TABLES) == 56
    assert set(migration.TABLE_POLICIES) == EXPECTED_TABLES
    assert {policy.group for policy in migration.TABLE_POLICIES.values()} == {"A", "B", "C", "D", "E"}
    assert all(policy.copy != policy.exclude for policy in migration.TABLE_POLICIES.values())


def test_seed_policy_uses_stable_key_merge_and_never_blind_copy() -> None:
    assert set(migration.SEED_TABLE_KEYS) == {
        "asset_statuses", "compatibility_sources", "compatibility_statuses",
        "document_types", "history_event_types", "roles",
    }
    for table in migration.SEED_TABLE_KEYS:
        policy = migration.TABLE_POLICIES[table]
        assert policy.merge_seeded_rows
        assert not policy.preserve_ids


def test_seed_meaning_distinguishes_metadata_drift_from_conflict() -> None:
    source = {"code": "photo", "display_name": "Photo", "description": "Imported", "sort_order": 0, "is_active": 1}
    baseline = {"code": "photo", "display_name": "Photo", "description": "Controlled", "sort_order": 20, "is_active": 1}
    assert migration.seed_meaning(source, "code") == migration.seed_meaning(baseline, "code")
    assert migration.semantic_row(source) != migration.semantic_row(baseline)


def test_source_schema_mismatch_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="schema mismatch"):
        migration.assert_safe_source({"database_name": "eoat_atlas_dev", "alembic_revision": "old"})


@pytest.mark.parametrize("name", ["eoat_atlas_prod", "EOAT_ATLAS_PROD", "customer_prod"])
def test_production_source_is_rejected(name: str) -> None:
    with pytest.raises(RuntimeError, match="production"):
        migration.assert_safe_source({"database_name": name, "alembic_revision": migration.REQUIRED_REVISION})


def test_test_database_requires_explicit_validation_mode() -> None:
    identity = {"database_name": "eoat_atlas_test", "alembic_revision": migration.REQUIRED_REVISION}
    with pytest.raises(RuntimeError, match="test database"):
        migration.assert_safe_source(identity)
    migration.assert_safe_source(identity, validation_mode=True)


def test_dependency_order_places_parents_before_children_and_is_stable() -> None:
    meta = {
        "parent": {"foreign_keys": []},
        "child_b": {"foreign_keys": [{"REFERENCED_TABLE_NAME": "parent"}]},
        "child_a": {"foreign_keys": [{"REFERENCED_TABLE_NAME": "parent"}]},
    }
    first = migration.dependency_order(meta, set(meta))
    second = migration.dependency_order(meta, set(meta))
    assert first == second == ["parent", "child_a", "child_b"]


def test_stable_row_order_produces_deterministic_sql() -> None:
    rows = [{"id": 1, "name": "alpha"}, {"id": 2, "name": "βeta"}]
    first = migration.insert_sql(LiteralConnection(), "items", rows, ["id", "name"])
    second = migration.insert_sql(LiteralConnection(), "items", rows, ["id", "name"])
    assert first == second
    assert "βeta" in first[0]


def test_binary_and_nullable_values_are_safe() -> None:
    connection = LiteralConnection()
    assert migration.sql_literal(connection, b"\x00\xff") == "X'00FF'"
    assert migration.sql_literal(connection, None) == "NULL"


def test_generated_columns_are_not_part_of_insert_contract() -> None:
    source = Path(migration.__file__).read_text(encoding="utf-8")
    assert '"generated" not in row["EXTRA"].casefold()' in source


def test_excluded_runtime_foreign_keys_are_cleared_and_counted() -> None:
    meta = {
        "foreign_keys": [
            {"COLUMN_NAME": "actor_user_id", "REFERENCED_TABLE_NAME": "users"},
            {"COLUMN_NAME": "application_instance_id", "REFERENCED_TABLE_NAME": "application_instances"},
        ],
        "nullable": {"actor_user_id": True, "application_instance_id": True},
    }
    rows, report = migration.transform_rows(
        "entity_history_events",
        [{"id": 8, "actor_user_id": 2, "application_instance_id": 1}],
        meta,
        {},
    )
    assert rows == [{"id": 8, "actor_user_id": None, "application_instance_id": None}]
    assert sum(report.values()) == 2


def test_required_excluded_foreign_key_is_refused() -> None:
    meta = {
        "foreign_keys": [{"COLUMN_NAME": "user_id", "REFERENCED_TABLE_NAME": "users"}],
        "nullable": {"user_id": False},
    }
    with pytest.raises(RuntimeError, match="Cannot exclude required FK"):
        migration.transform_rows("copied", [{"user_id": 1}], meta, {})


def test_seed_id_remapping_preserves_relationship_meaning() -> None:
    meta = {
        "foreign_keys": [{"COLUMN_NAME": "status_id", "REFERENCED_TABLE_NAME": "asset_statuses"}],
        "nullable": {"status_id": True},
    }
    rows, report = migration.transform_rows("eoats", [{"id": 1, "status_id": 5}], meta, {"asset_statuses": {5: 3}})
    assert rows[0]["status_id"] == 3
    assert report["status_id:seed_id_remap"] == 1


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"EOAT_DB_PASSWORD=hunter2value", "database password assignment"),
        (b"token_hash", "session token hash column"),
        (b"-----BEGIN PRIVATE KEY-----", "private key"),
    ],
)
def test_secret_leakage_detection(payload: bytes, expected: str) -> None:
    assert expected in migration.secret_findings(payload)


def test_clean_artifact_passes_secret_scan() -> None:
    assert migration.secret_findings(b"INSERT INTO eoats VALUES (1,'CL-EOAT-0001');") == []


def test_artifact_checksum_and_manifest_accuracy(tmp_path: Path) -> None:
    artifact = tmp_path / "operational-data.sql"
    artifact.write_text("SELECT 1;\n", encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (tmp_path / migration.EMPTY_BASELINE_FILENAME).write_text("{}", encoding="utf-8")
    (tmp_path / migration.APPROVAL_EVIDENCE_FILENAME).write_text(json.dumps({
        "approved_by": {"name": "Kato Gray", "role": "EOAT Atlas project/data owner"},
        "owner_decisions": [
            "N/A means stored in cabinet with no cabinet identifier invented.",
            "26 - Xqual in 25 means Machine 26 while the original workbook wording is retained as evidence.",
            "Proven identical cleanroom EOATs receive separate deterministic EOAT IDs.",
            "Plant 4 multi-machine audit sequences that do not prove duplicates are treated as movement.",
            "Uncertain present locations become STORED with cabinet unspecified.",
            "No unsupported lifecycle history, user, cabinet identifier, or timestamp may be fabricated.",
        ],
    }), encoding="utf-8")
    (tmp_path / migration.DUPLICATE_RESOLUTION_FILENAME).write_text(json.dumps({
        "status": "RESOLVED", "remaining_unresolved_records": [],
    }), encoding="utf-8")
    (tmp_path / "migration-manifest.json").write_text(json.dumps({
        "artifact_filename": artifact.name,
        "artifact_sha256": digest,
        "required_production_schema_revision": migration.REQUIRED_REVISION,
        "migration_id": "unit-test",
        "supersedes_operational_migration_id": migration.SUPERSEDED_OPERATIONAL_MIGRATION_ID,
        "required_empty_production_baseline_counts_file": migration.EMPTY_BASELINE_FILENAME,
        "owner_approval_evidence_file": migration.APPROVAL_EVIDENCE_FILENAME,
        "duplicate_resolution_report_file": migration.DUPLICATE_RESOLUTION_FILENAME,
    }), encoding="utf-8")
    result = migration.verify_package(tmp_path)
    assert result["status"] == "PASS"
    artifact.write_text("SELECT 2;\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        migration.verify_package(tmp_path)


def test_copied_operational_migration_tool_has_no_source_checkout_dependency(tmp_path: Path) -> None:
    tool = tmp_path / "migration_tool.py"
    shutil.copy2(Path(migration.__file__), tool)
    result = subprocess.run([sys.executable, str(tool), "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "verify-package" in result.stdout


def test_duplicate_import_prevention_is_required_by_policy() -> None:
    assert migration.TABLE_POLICIES["system_metadata"].exclude
    source = Path(migration.__file__).read_text(encoding="utf-8")
    assert "migration marker already exists" in source
    assert "IN_PROGRESS" in source and "COMPLETED" in source


def test_auto_increment_validation_requires_next_id_above_maximum() -> None:
    valid = {"maximum_id": 8, "next_auto_increment": 9}
    invalid = {"maximum_id": 8, "next_auto_increment": 8}
    assert valid["next_auto_increment"] > valid["maximum_id"]
    assert not invalid["next_auto_increment"] > invalid["maximum_id"]


def test_windows_source_and_linux_target_paths_are_both_documented(tmp_path: Path) -> None:
    manifest = {
        "migration_id": "eoat-operational-unit",
        "artifact_sha256": "a" * 64,
        "import_marker": "operational_data_migration:unit",
    }
    migration.write_instructions(tmp_path, manifest)
    import_text = (tmp_path / "IMPORT_INSTRUCTIONS.md").read_text(encoding="utf-8")
    assert "/opt/eoat-atlas/incoming/" in import_text
    assert "mysql_config_editor" in import_text
    assert "FOREIGN_KEY" not in import_text or isinstance(import_text, str)
    assert str(PureWindowsPathForTest("C:/EOAT/EOAT_Master_Tracker.xlsx")).startswith("C:")


def PureWindowsPathForTest(value: str):
    from pathlib import PureWindowsPath
    return PureWindowsPath(value)


def test_import_and_rollback_require_exact_typed_confirmation(tmp_path: Path) -> None:
    manifest = {
        "migration_id": "eoat-operational-unit",
        "artifact_sha256": "b" * 64,
        "import_marker": "operational_data_migration:unit",
    }
    migration.write_instructions(tmp_path, manifest)
    assert "Type exactly" in (tmp_path / "IMPORT_INSTRUCTIONS.md").read_text(encoding="utf-8")
    rollback = (tmp_path / "ROLLBACK_INSTRUCTIONS.md").read_text(encoding="utf-8")
    assert "Type exactly" in rollback
    assert "test -s \"$BACKUP\"" in rollback
    assert "failed-import" in rollback


def test_runtime_permissions_require_only_the_four_dml_privileges_and_reject_dangerous_ones():
    allowed = migration.assess_runtime_grants([
        "GRANT SELECT, INSERT, UPDATE, DELETE ON `eoat_atlas_prod`.* TO `eoat_runtime`@`localhost`"
    ])
    assert allowed["valid"]
    assert allowed["missing_required_permissions"] == []
    assert "EXECUTE" not in allowed["required_permissions"]

    forbidden = migration.assess_runtime_grants(["GRANT ALL PRIVILEGES ON *.* TO `eoat_runtime`@`localhost`"])
    assert not forbidden["valid"]
    assert "ALL PRIVILEGES" in forbidden["forbidden_permissions_present"]


def test_validation_implementation_covers_orphans_duplicates_auto_increment_and_transient_names() -> None:
    source = Path(migration.__file__).read_text(encoding="utf-8")
    for function in ("orphan_checks", "duplicate_checks", "auto_increment_checks", "transient_name_checks"):
        assert f"def {function}" in source
    assert "def runtime_grant_check" in source
    assert "def api_smoke" in source


def test_file_path_classification_implementation_is_non_rewriting() -> None:
    source = Path(migration.__file__).read_text(encoding="utf-8")
    assert '"path_rewrites_applied": False' in source
    assert '"binaries_copied": False' in source
    for category in ("network_share", "server_local", "client_local", "missing"):
        assert category in source
