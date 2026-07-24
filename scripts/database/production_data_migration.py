from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymysql

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

REQUIRED_REVISION = "20260721_0008"
TOOL_VERSION = "1.1.0"
SEED_TABLE_KEYS = {
    "asset_statuses": "code",
    "compatibility_sources": "code",
    "compatibility_statuses": "code",
    "document_types": "code",
    "history_event_types": "code",
    "roles": "role_code",
}
SEMANTIC_IGNORES = {"id", "created_at", "updated_at"}
PRODUCTION_NAMES = {"eoat_atlas_prod", "eoat-atlas-prod", "production"}
TEST_NAME_MARKERS = ("test", "fixture", "pytest")
SUPERSEDED_OPERATIONAL_MIGRATION_ID = "eoat-operational-633d0596386fc44b33c2"
APPROVAL_EVIDENCE_FILENAME = "production-owner-approval-evidence.json"
DUPLICATE_RESOLUTION_FILENAME = "eoat-location-duplicate-resolution-report.json"
EMPTY_BASELINE_FILENAME = "required-empty-production-baseline-counts.json"
SUPERSEDES_FILENAME = "SUPERSEDES.md"
DANGEROUS_RUNTIME_PRIVILEGES = (
    "ALTER", "ALL PRIVILEGES", "CREATE", "CREATE USER", "DROP", "EVENT", "FILE", "GRANT OPTION",
    "INDEX", "LOCK TABLES", "PROCESS", "REFERENCES", "RELOAD", "ROLE_ADMIN", "SHUTDOWN", "SUPER",
    "SYSTEM_USER", "TRIGGER",
)


@dataclass(frozen=True)
class TablePolicy:
    group: str
    copy: bool
    exclude: bool
    merge_seeded_rows: bool
    preserve_ids: bool
    reset_auto_increment: bool
    reason: str


@dataclass(frozen=True)
class ApiSmokeMachineCandidate:
    """A deterministic, plant-qualified machine identity for API read smoke checks."""

    plant_code: str
    machine_number: str
    machine_id: int

    @property
    def profile_params(self) -> dict[str, str]:
        return {"plant_code": self.plant_code}


def _p(group: str, *, copy: bool, exclude: bool = False, merge: bool = False,
       preserve: bool = True, reset: bool = False, reason: str) -> TablePolicy:
    return TablePolicy(group, copy, exclude, merge, preserve, reset, reason)


TABLE_POLICIES: dict[str, TablePolicy] = {
    "alembic_version": _p("A", copy=False, exclude=True, preserve=False,
        reason="Schema state is established by Alembic and must remain at the target revision."),
    "asset_statuses": _p("A", copy=True, merge=True, preserve=False,
        reason="Alembic seeds stable codes; validate semantics and add only source-only operational codes."),
    "compatibility_sources": _p("A", copy=True, merge=True, preserve=False,
        reason="Alembic seeds stable codes; validate semantics and add only source-only operational codes."),
    "compatibility_statuses": _p("A", copy=True, merge=True, preserve=False,
        reason="Alembic seeds stable codes; validate semantics and add only source-only operational codes."),
    "document_types": _p("A", copy=True, merge=True, preserve=False,
        reason="Alembic owns the stable document type codes; identical seeds are retained."),
    "history_event_types": _p("A", copy=True, merge=True, preserve=False,
        reason="Alembic owns the event vocabulary; identical seeds are retained."),
    "roles": _p("A", copy=True, merge=True, preserve=False,
        reason="Alembic owns authorization role meanings; identical roles are retained."),
    "cleanroom_classifications": _p("B", copy=True, reset=True,
        reason="Workbook-derived operational reference data used by EOATs, machines, and areas."),
    "connection_types": _p("B", copy=True, reset=True,
        reason="Workbook-derived operational reference data used by EOAT master records."),
    "eoat_types": _p("B", copy=True, reset=True,
        reason="Workbook-derived operational reference data used by EOAT master records."),
    "plants": _p("B", copy=True, reset=True, reason="Operational facility master data."),
    "areas": _p("B", copy=True, reset=True, reason="Operational plant-area master data."),
    "storage_locations": _p("B", copy=True, reset=True, reason="Operational EOAT storage master data."),
    "eoats": _p("B", copy=True, reset=True, reason="Primary operational EOAT master records."),
    "machines": _p("B", copy=True, reset=True, reason="Primary operational machine master records."),
    "robots": _p("B", copy=True, reset=True, reason="Primary operational robot master records."),
    "tools": _p("B", copy=True, reset=True, reason="Primary operational tool/mold master records."),
    "parts": _p("B", copy=True, reset=True, reason="Primary operational part master records."),
    "machine_robot_assignments": _p("B", copy=True, reset=True, reason="Operational machine/robot relationships."),
    "tool_parts": _p("B", copy=True, reset=True, reason="Operational tool/part relationships."),
    "eoat_machine_compatibility": _p("B", copy=True, reset=True, reason="Operational EOAT/machine compatibility knowledge."),
    "eoat_tool_compatibility": _p("B", copy=True, reset=True, reason="Operational EOAT/tool compatibility knowledge."),
    "tool_machine_compatibility": _p("B", copy=True, reset=True, reason="Operational tool/machine compatibility knowledge."),
    "eoat_installations": _p("C", copy=True, reset=True, reason="Operational installation history."),
    "eoat_storage_assignments": _p("C", copy=True, reset=True, reason="Operational storage-location history."),
    "eoat_location_observations": _p("C", copy=True, reset=True,
        reason="Authoritative observed current-state evidence; not fabricated lifecycle history."),
    "eoat_location_assertions": _p("C", copy=True, reset=True,
        reason="Immutable workbook assertions supporting observations and conflict review."),
    "fit_check_records": _p("C", copy=True, reset=True, reason="Operational fit-check transactions."),
    "audit_records": _p("C", copy=True, reset=True, reason="Operational audit history."),
    "maintenance_events": _p("C", copy=True, reset=True, reason="Operational maintenance history."),
    "documents": _p("C", copy=True, reset=True, reason="Operational document metadata; binaries remain external."),
    "photos": _p("C", copy=True, reset=True, reason="Operational photo metadata; binaries remain external."),
    "document_links": _p("C", copy=True, reset=True, reason="Operational document-to-entity relationships."),
    "tags": _p("C", copy=True, reset=True, reason="Operational tagging vocabulary."),
    "entity_tags": _p("C", copy=True, reset=True, reason="Operational entity tag assignments and history."),
    "annotation_targets": _p("C", copy=True, reset=True, reason="Operational annotation target records."),
    "annotations": _p("C", copy=True, reset=True, reason="Operational annotations and their history."),
    "annotation_target_links": _p("C", copy=True, reset=True, reason="Operational annotation relationships."),
    "entity_history_events": _p("C", copy=True, reset=True, reason="Structured operational entity history."),
    "change_audit_log": _p("C", copy=True, reset=True, reason="Durable operational write audit history."),
    "change_feed": _p("C", copy=True, reset=True, reason="Durable operational change cursor history."),
    "authentication_sessions": _p("D", copy=False, exclude=True,
        reason="Development session tokens and authorization snapshots are environment-specific secrets."),
    "authentication_audit_events": _p("D", copy=False, exclude=True,
        reason="Development authentication activity is transient and identity-environment-specific."),
    "cutover_sessions": _p("D", copy=False, exclude=True,
        reason="Active/development cutover coordination state must not cross environments."),
    "data_state": _p("D", copy=False, exclude=True, preserve=False,
        reason="Target freshness metadata is initialized by Alembic and advanced once by the completed operational import."),
    "idempotency_records": _p("D", copy=False, exclude=True,
        reason="Request replay state is transient and environment-specific."),
    "external_group_role_mappings": _p("D", copy=False, exclude=True,
        reason="Enterprise identity-provider group configuration belongs to production administration."),
    "system_metadata": _p("D", copy=False, exclude=True,
        reason="Development metadata is excluded; the import adds one production migration marker."),
    "system_settings": _p("D", copy=False, exclude=True,
        reason="Environment configuration and local-path settings must be configured in production."),
    "users": _p("D", copy=False, exclude=True,
        reason="Source users are development/application identities; production identity is re-established separately."),
    "user_roles": _p("D", copy=False, exclude=True,
        reason="Development role assignments must not grant production authorization."),
    "application_instances": _p("E", copy=False, exclude=True,
        reason="Development host identity, heartbeat, and local runtime provenance are not portable."),
    "application_releases": _p("E", copy=False, exclude=True,
        reason="All source rows are development releases; production release provenance is registered by production."),
    "import_batches": _p("E", copy=True, reset=True,
        reason="Completed sanctioned source-import batches are required provenance for migrated records."),
    "import_rows": _p("E", copy=True, reset=True,
        reason="Sanctioned source-row evidence is retained for traceability and parity proof."),
    "import_issues": _p("E", copy=True, reset=True,
        reason="Reviewed source-import warnings are retained as evidence; unresolved meaning is not hidden."),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_env(path_or_name: str) -> dict[str, str]:
    if path_or_name == "development":
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
        path = local / "EOAT Atlas Development" / "database.env"
    else:
        path = Path(path_or_name)
    values = {key: value for key, value in os.environ.items() if key.startswith("EOAT_")}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key.strip().startswith("EOAT_"):
                    values[key.strip()] = value.strip()
    return values


def connect(values: dict[str, str], *, database: str | None = None, migration: bool = False,
            autocommit: bool = False):
    prefix = "EOAT_DB_MIGRATION_" if migration else "EOAT_DB_"
    return pymysql.connect(
        host=values.get("EOAT_DB_HOST", "127.0.0.1"),
        port=int(values.get("EOAT_DB_PORT", "3306")),
        user=values.get(f"{prefix}USER", values.get("EOAT_DB_USER", "")),
        password=values.get(f"{prefix}PASSWORD", values.get("EOAT_DB_PASSWORD", "")),
        database=database or values.get("EOAT_DB_NAME"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=autocommit,
        connect_timeout=10,
    )


def database_identity(connection) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT VERSION() server_version, DATABASE() database_name, "
                       "(SELECT version_num FROM alembic_version LIMIT 1) alembic_revision")
        result = cursor.fetchone()
        cursor.execute("SELECT @@hostname server_hostname, @@port server_port")
        result.update(cursor.fetchone())
    return result


def assert_safe_source(identity: dict[str, Any], *, validation_mode: bool = False) -> None:
    name = str(identity["database_name"]).casefold()
    if name in PRODUCTION_NAMES or name.endswith("_prod"):
        raise RuntimeError(f"Refusing production database '{identity['database_name']}' as an export source")
    if any(marker in name for marker in TEST_NAME_MARKERS) and not validation_mode:
        raise RuntimeError(f"Refusing test database '{identity['database_name']}' outside validation mode")
    if identity["alembic_revision"] != REQUIRED_REVISION:
        raise RuntimeError(
            f"Source schema mismatch: required {REQUIRED_REVISION}, found {identity['alembic_revision']}"
        )


def table_names(connection) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT table_name FROM information_schema.tables "
                       "WHERE table_schema=DATABASE() AND table_type='BASE TABLE' ORDER BY table_name")
        return [row["TABLE_NAME"] for row in cursor.fetchall()]


def row_counts(connection) -> dict[str, int]:
    result: dict[str, int] = {}
    with connection.cursor() as cursor:
        for table in table_names(connection):
            cursor.execute(f"SELECT COUNT(*) count FROM `{table}`")
            result[table] = int(cursor.fetchone()["count"])
    return result


def schema_metadata(connection) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    with connection.cursor() as cursor:
        for table in table_names(connection):
            cursor.execute(
                "SELECT column_name,data_type,column_type,is_nullable,column_key,extra,ordinal_position "
                "FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s "
                "ORDER BY ordinal_position", (table,),
            )
            columns = cursor.fetchall()
            cursor.execute(
                "SELECT column_name,referenced_table_name,referenced_column_name,constraint_name "
                "FROM information_schema.key_column_usage WHERE table_schema=DATABASE() AND table_name=%s "
                "AND referenced_table_name IS NOT NULL ORDER BY constraint_name,ordinal_position", (table,),
            )
            foreign_keys = cursor.fetchall()
            primary = [row["COLUMN_NAME"] for row in columns if row["COLUMN_KEY"] == "PRI"]
            metadata[table] = {
                "columns": columns,
                "column_names": [
                    row["COLUMN_NAME"] for row in columns if "generated" not in row["EXTRA"].casefold()
                ],
                "primary_key": primary,
                "auto_increment": next((row["COLUMN_NAME"] for row in columns if "auto_increment" in row["EXTRA"]), None),
                "nullable": {row["COLUMN_NAME"]: row["IS_NULLABLE"] == "YES" for row in columns},
                "foreign_keys": foreign_keys,
            }
    return metadata


def fetch_rows(connection, table: str, meta: dict[str, Any]) -> list[dict[str, Any]]:
    order = meta["primary_key"] or meta["column_names"]
    clause = ",".join(f"`{column}`" for column in order)
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM `{table}` ORDER BY {clause}")
        return list(cursor.fetchall())


def semantic_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in SEMANTIC_IGNORES}


def seed_meaning(row: dict[str, Any], stable_key: str) -> dict[str, Any]:
    display_column = "role_name" if "role_name" in row else "display_name"
    return {
        stable_key: row.get(stable_key),
        display_column: row.get(display_column),
        "is_active": row.get("is_active"),
    }


def seed_parity(source, baseline, source_meta, baseline_counts) -> tuple[list[dict[str, Any]], dict[str, dict[Any, Any]], dict[str, list[dict[str, Any]]]]:
    report = []
    mappings: dict[str, dict[Any, Any]] = {}
    additions: dict[str, list[dict[str, Any]]] = {}
    for table, stable_key in SEED_TABLE_KEYS.items():
        source_rows = fetch_rows(source, table, source_meta[table])
        baseline_rows = fetch_rows(baseline, table, source_meta[table])
        source_by_key = {row[stable_key]: row for row in source_rows}
        baseline_by_key = {row[stable_key]: row for row in baseline_rows}
        matching: list[str] = []
        conflicting: list[dict[str, Any]] = []
        metadata_differences: list[dict[str, Any]] = []
        for key in sorted(set(source_by_key) & set(baseline_by_key), key=str):
            if semantic_row(source_by_key[key]) == semantic_row(baseline_by_key[key]):
                matching.append(str(key))
            elif seed_meaning(source_by_key[key], stable_key) == seed_meaning(baseline_by_key[key], stable_key):
                matching.append(str(key))
                metadata_differences.append({
                    "stable_key": key,
                    "source_metadata": semantic_row(source_by_key[key]),
                    "production_baseline_metadata": semantic_row(baseline_by_key[key]),
                    "resolution": "Production Alembic seed metadata remains canonical; no overwrite.",
                })
            else:
                conflicting.append({
                    "stable_key": key,
                    "source_semantics": semantic_row(source_by_key[key]),
                    "baseline_semantics": semantic_row(baseline_by_key[key]),
                })
        if conflicting:
            raise RuntimeError(f"Seed conflict in {table}: {json.dumps(conflicting, default=str)}")
        used_ids = {row["id"] for row in baseline_rows}
        next_id = max(used_ids or {0}) + 1
        table_map: dict[Any, Any] = {}
        table_additions: list[dict[str, Any]] = []
        for key, row in sorted(source_by_key.items(), key=lambda item: str(item[0])):
            if key in baseline_by_key:
                target_id = baseline_by_key[key]["id"]
            else:
                candidate = row["id"]
                if candidate in used_ids:
                    while next_id in used_ids:
                        next_id += 1
                    candidate = next_id
                target_id = candidate
                used_ids.add(target_id)
                copied = dict(row)
                copied["id"] = target_id
                table_additions.append(copied)
            table_map[row["id"]] = target_id
        mappings[table] = table_map
        additions[table] = table_additions
        report.append({
            "table_name": table,
            "stable_key": stable_key,
            "source_count": len(source_rows),
            "production_baseline_count": baseline_counts[table],
            "matching_rows": matching,
            "source_only_rows": sorted(str(x) for x in set(source_by_key) - set(baseline_by_key)),
            "production_only_rows": sorted(str(x) for x in set(baseline_by_key) - set(source_by_key)),
            "conflicting_rows": conflicting,
            "baseline_canonical_metadata_differences": metadata_differences,
            "selected_import_behavior": "validate shared semantics; insert source-only rows; remap dependent FKs by stable key",
            "source_to_target_id_map": {str(key): value for key, value in sorted(table_map.items())},
        })
    return report, mappings, additions


def dependency_order(meta: dict[str, dict[str, Any]], included: set[str]) -> list[str]:
    parents: dict[str, set[str]] = {table: set() for table in included}
    children: dict[str, set[str]] = {table: set() for table in included}
    for table in included:
        for fk in meta[table]["foreign_keys"]:
            parent = fk["REFERENCED_TABLE_NAME"]
            if parent in included and parent != table:
                parents[table].add(parent)
                children[parent].add(table)
    queue = deque(sorted(table for table, deps in parents.items() if not deps))
    ordered: list[str] = []
    while queue:
        table = queue.popleft()
        ordered.append(table)
        for child in sorted(children[table]):
            parents[child].discard(table)
            if not parents[child] and child not in ordered and child not in queue:
                queue.append(child)
    ordered.extend(sorted(included - set(ordered)))
    return ordered


def transform_rows(table: str, rows: list[dict[str, Any]], meta: dict[str, Any],
                   seed_maps: dict[str, dict[Any, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    transformed: dict[str, int] = defaultdict(int)
    fk_by_column = {fk["COLUMN_NAME"]: fk["REFERENCED_TABLE_NAME"] for fk in meta["foreign_keys"]}
    output = []
    excluded_targets = {name for name, policy in TABLE_POLICIES.items() if policy.exclude}
    for original in rows:
        row = dict(original)
        for column, value in list(row.items()):
            parent = fk_by_column.get(column)
            if parent in seed_maps and value is not None:
                mapped = seed_maps[parent].get(value)
                if mapped is None:
                    raise RuntimeError(f"Missing seed ID mapping for {table}.{column}={value}")
                if mapped != value:
                    transformed[f"{column}:seed_id_remap"] += 1
                row[column] = mapped
            elif parent in excluded_targets and value is not None:
                if not meta["nullable"].get(column, False):
                    raise RuntimeError(f"Cannot exclude required FK {table}.{column} -> {parent}")
                row[column] = None
                transformed[f"{column}:excluded_{parent}"] += 1
            elif column.endswith("_user_id") and value is not None:
                row[column] = None
                transformed[f"{column}:excluded_development_user"] += 1
            elif column == "application_release_id" and value is not None:
                row[column] = None
                transformed[f"{column}:excluded_development_release"] += 1
            elif column == "application_instance_id" and value is not None:
                row[column] = None
                transformed[f"{column}:excluded_development_instance"] += 1
        output.append(row)
    return output, dict(sorted(transformed.items()))


def sql_literal(connection, value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, bytes | bytearray | memoryview):
        return "X'" + bytes(value).hex().upper() + "'"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime | date | time):
        return connection.escape(value)
    return connection.escape(value)


def insert_sql(connection, table: str, rows: list[dict[str, Any]], columns: list[str], *, chunk: int = 200) -> list[str]:
    statements: list[str] = []
    quoted_columns = ",".join(f"`{column}`" for column in columns)
    for start in range(0, len(rows), chunk):
        values = []
        for row in rows[start:start + chunk]:
            values.append("(" + ",".join(sql_literal(connection, row[column]) for column in columns) + ")")
        statements.append(f"INSERT INTO `{table}` ({quoted_columns}) VALUES\n" + ",\n".join(values) + ";")
    return statements


def secret_findings(data: bytes, configured_secrets: list[str] | None = None) -> list[str]:
    text = data.decode("utf-8", errors="ignore")
    patterns = {
        "database password assignment": r"(?i)(EOAT_DB_(?:ROOT_|MIGRATION_)?PASSWORD|password)\s*[=:]\s*[^\s,;]+",
        "session token hash column": r"(?i)token_hash",
        "private key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "bearer token": r"(?i)authorization\s*:\s*bearer\s+",
    }
    findings = [label for label, pattern in patterns.items() if re.search(pattern, text)]
    for secret in configured_secrets or []:
        if secret and len(secret) >= 8 and secret in text:
            findings.append("configured credential value")
    return sorted(set(findings))


def file_reference_report(connection) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT id,storage_path,storage_provider,file_name FROM documents ORDER BY id")
        rows = cursor.fetchall()
    categories: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for category in ("network_share", "server_local", "client_local", "missing"):
        categories[category] = []
    normalized: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        raw = str(row["storage_path"] or "")
        lower = raw.casefold()
        if raw.startswith("\\\\"):
            category = "network_share"
            path = Path(raw)
        elif re.match(r"^[A-Za-z]:[\\/]", raw):
            category = "client_local"
            path = Path(raw)
        elif raw.startswith("/"):
            category = "server_local"
            path = Path(raw)
        else:
            category = "client_local"
            path = Path(raw)
        exists = path.is_file()
        if not exists:
            categories["missing"].append({"document_id": row["id"], "path": raw})
        categories[category].append({"document_id": row["id"], "path": raw, "exists": exists})
        normalized[lower.replace("/", "\\")].append(row["id"])
    duplicates = [{"normalized_path": key, "document_ids": ids} for key, ids in sorted(normalized.items()) if key and len(ids) > 1]
    return {
        "total_document_references": len(rows),
        "counts": {key: len(value) for key, value in sorted(categories.items())},
        "duplicate_reference_groups": len(duplicates),
        "examples": {key: value[:5] for key, value in sorted(categories.items())},
        "duplicate_examples": duplicates[:10],
        "binaries_copied": False,
        "path_rewrites_applied": False,
    }


def location_observation_report(connection) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT o.observation_uuid,e.business_identifier AS eoat_identifier,o.state,m.machine_number,
                   l.location_code AS storage_location,o.observed_at,o.observed_on,o.observation_precision,
                   o.source_workbook,o.source_worksheet,o.source_row_number,o.original_source_wording,
                   o.confidence,o.resolution_status,o.conflict_group_uuid,o.is_authoritative
            FROM eoat_location_observations o JOIN eoats e ON e.id=o.eoat_id
            LEFT JOIN machines m ON m.id=o.machine_id
            LEFT JOIN storage_locations l ON l.id=o.storage_location_id
            ORDER BY e.business_identifier,o.observed_on,o.observed_at,o.id
        """)
        observations = cursor.fetchall()
        cursor.execute("""
            SELECT a.assertion_uuid,o.observation_uuid,e.business_identifier AS eoat_identifier,a.state,
                   m.machine_number,l.location_code AS storage_location,a.observed_at,a.observed_on,
                   a.observation_precision,a.source_workbook,a.source_worksheet,a.source_row_number,
                   a.original_source_wording,a.confidence,a.participates_in_conflict
            FROM eoat_location_assertions a
            JOIN eoat_location_observations o ON o.id=a.observation_id
            JOIN eoats e ON e.id=a.eoat_id
            LEFT JOIN machines m ON m.id=a.machine_id
            LEFT JOIN storage_locations l ON l.id=a.storage_location_id
            ORDER BY e.business_identifier,a.observed_on,a.source_row_number,a.id
        """)
        assertions = cursor.fetchall()
    state_counts = {
        state: sum(row["state"] == state for row in observations)
        for state in ("INSTALLED", "STORED", "UNKNOWN", "INACTIVE", "CONFLICTING")
    }
    return {
        "semantics": "observed current state; not lifecycle history or compatibility",
        "state_counts": state_counts,
        "observation_count": len(observations),
        "assertion_count": len(assertions),
        "observations": observations,
        "assertions": assertions,
        "conflicts": [row for row in observations if row["state"] == "CONFLICTING"],
    }


def normalization_policy() -> dict[str, Any]:
    path = REPOSITORY_ROOT / "config" / "eoat_location_normalization.json"
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("supersedes_operational_migration_id") != SUPERSEDED_OPERATIONAL_MIGRATION_ID:
        raise RuntimeError("Owner-approved location policy does not name the superseded migration")
    if not policy.get("owner_decisions") or not policy.get("approved_by"):
        raise RuntimeError("Owner-approved location policy is incomplete")
    return policy


def duplicate_resolution_report(connection, policy: dict[str, Any]) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT e.business_identifier,a.source_row_number,m.machine_number
            FROM audit_records a JOIN eoats e ON e.id=a.eoat_id
            LEFT JOIN machines m ON m.id=a.machine_id
            WHERE a.source_sheet='EOAT Inventory' AND a.source_row_number IN (81,82,83,85,86,88,89,92,93)
            ORDER BY a.source_row_number
        """)
        split_audits = cursor.fetchall()
        cursor.execute("""
            SELECT e.business_identifier,a.source_row_number,a.state,a.machine_id,a.storage_location_id
            FROM eoat_location_assertions a JOIN eoats e ON e.id=a.eoat_id
            WHERE a.original_source_wording LIKE '%Press/Machine #=N/A%'
            ORDER BY a.source_row_number
        """)
        na_rows = cursor.fetchall()
        cursor.execute("""
            SELECT i.source_row_number,JSON_UNQUOTE(JSON_EXTRACT(i.raw_values_json,'$."Press/Machine #"')) original_machine,
                   JSON_UNQUOTE(JSON_EXTRACT(i.normalized_values_json,'$.machine')) normalized_machine,m.machine_number AS audit_machine
            FROM import_rows i LEFT JOIN audit_records a ON a.source_sheet=i.source_sheet AND a.source_row_number=i.source_row_number
            LEFT JOIN machines m ON m.id=a.machine_id
            WHERE i.source_sheet='EOAT Inventory'
              AND JSON_UNQUOTE(JSON_EXTRACT(i.raw_values_json,'$."Press/Machine #"'))='26 - Xqual in 25'
            ORDER BY i.source_row_number
        """)
        xqual_rows = cursor.fetchall()
        cursor.execute("""
            SELECT e.business_identifier,o.state,o.machine_id,o.storage_location_id,o.original_source_wording
            FROM eoat_location_observations o JOIN eoats e ON e.id=o.eoat_id
            WHERE o.state IN ('UNKNOWN','CONFLICTING') ORDER BY e.business_identifier
        """)
        unresolved = cursor.fetchall()
    if any(row["state"] != "STORED" or row["machine_id"] is not None or row["storage_location_id"] is not None for row in na_rows):
        raise RuntimeError("N/A source rows are not all normalized to cabinet-unspecified STORED assertions")
    if any(row["normalized_machine"] != "26" or row["audit_machine"] != "26" for row in xqual_rows):
        raise RuntimeError("Xqual source wording was not normalized to Machine 26")
    if unresolved:
        raise RuntimeError("Owner-approved location normalization still has unresolved observations")
    return {
        "status": "RESOLVED",
        "supersedes_operational_migration_id": SUPERSEDED_OPERATIONAL_MIGRATION_ID,
        "approved_by": policy["approved_by"],
        "owner_decisions": policy["owner_decisions"],
        "physical_unit_splits": policy["physical_unit_splits"],
        "actual_split_audit_assignments": split_audits,
        "na_storage_normalizations": na_rows,
        "machine_26_normalizations": xqual_rows,
        "plant4_movement_resolutions": policy.get("plant4_movement_resolutions", []),
        "remaining_unresolved_records": unresolved,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str, sort_keys=True) + "\n", encoding="utf-8")


def git_info(repo: Path) -> dict[str, str]:
    def run(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()
    return {"branch": run("branch", "--show-current"), "commit": run("rev-parse", "HEAD")}


def latest_database_release(connection) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT application_version,release_id,build_id,commit_sha,release_channel,"
            "database_schema_revision,api_contract_version,first_seen_at,last_seen_at "
            "FROM application_releases ORDER BY last_seen_at DESC,id DESC LIMIT 1"
        )
        return cursor.fetchone()


def _classification_payload(meta: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for table in sorted(TABLE_POLICIES):
        policy = asdict(TABLE_POLICIES[table])
        policy["table_name"] = table
        policy["has_auto_increment"] = bool(meta[table]["auto_increment"])
        policy["auto_increment_treatment"] = (
            "Explicit ID inserts advance MySQL AUTO_INCREMENT; validate next value > imported maximum."
            if meta[table]["auto_increment"] and policy["copy"] else "No reset required."
        )
        rows.append(policy)
    return rows


def build(args: argparse.Namespace) -> int:
    # The same module is copied into an operational package as
    # ``migration_tool.py``.  Keep source-checkout-only release metadata
    # loading inside the build path so package verification has no dependency
    # on the repository's ``core`` package.
    from core.versioning import get_version_info

    output = Path(args.output_directory).resolve()
    if output.exists():
        raise FileExistsError(f"Output directory already exists: {output}")
    source_values = read_env(args.source_environment)
    baseline_values = read_env(args.baseline_environment)
    with connect(source_values) as source, connect(baseline_values) as baseline:
        source_identity = database_identity(source)
        baseline_identity = database_identity(baseline)
        assert_safe_source(source_identity, validation_mode=args.validation_mode)
        if baseline_identity["alembic_revision"] != REQUIRED_REVISION:
            raise RuntimeError(f"Baseline revision mismatch: {baseline_identity['alembic_revision']}")
        source_tables = table_names(source)
        baseline_tables = table_names(baseline)
        if source_tables != baseline_tables:
            raise RuntimeError("Source and disposable baseline table sets differ")
        if set(source_tables) != set(TABLE_POLICIES):
            missing = sorted(set(source_tables) - set(TABLE_POLICIES))
            extra = sorted(set(TABLE_POLICIES) - set(source_tables))
            raise RuntimeError(f"Classification is incomplete; missing policies={missing}, stale policies={extra}")
        source_meta = schema_metadata(source)
        source_counts = row_counts(source)
        baseline_counts = row_counts(baseline)
        parity, seed_maps, seed_additions = seed_parity(source, baseline, source_meta, baseline_counts)
        included = {table for table, policy in TABLE_POLICIES.items() if policy.copy and table not in SEED_TABLE_KEYS}
        order = list(SEED_TABLE_KEYS) + dependency_order(source_meta, included)
        export_rows: dict[str, list[dict[str, Any]]] = {}
        transformation_report: dict[str, dict[str, int]] = {}
        exported_counts: dict[str, int] = {}
        for table in order:
            if table in SEED_TABLE_KEYS:
                rows = seed_additions[table]
                transforms = {}
            else:
                rows, transforms = transform_rows(
                    table, fetch_rows(source, table, source_meta[table]), source_meta[table], seed_maps
                )
            export_rows[table] = rows
            exported_counts[table] = len(rows)
            if transforms:
                transformation_report[table] = transforms
        expected_counts = dict(baseline_counts)
        for table in SEED_TABLE_KEYS:
            expected_counts[table] += len(seed_additions[table])
        for table in included:
            expected_counts[table] = source_counts[table]
        expected_counts["system_metadata"] = baseline_counts["system_metadata"] + 1
        repo = Path(__file__).resolve().parents[2]
        git = git_info(repo)
        if args.source_branch:
            branch_commit = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", args.source_branch], text=True
            ).strip()
            if branch_commit != git["commit"]:
                raise RuntimeError(
                    f"Requested source branch {args.source_branch} resolves to {branch_commit}, not checked-out {git['commit']}"
                )
            git["branch"] = args.source_branch
        database_release = latest_database_release(source)
        snapshot_payload = json.dumps({
            "source": {"database": source_identity["database_name"], "revision": source_identity["alembic_revision"]},
            "git": git,
            "counts": source_counts,
        }, sort_keys=True).encode()
        migration_id = "eoat-operational-" + hashlib.sha256(snapshot_payload).hexdigest()[:20]
        marker_key = f"operational_data_migration:{migration_id}"
        sql_lines = [
            "-- EOAT Atlas deterministic operational-data migration",
            f"-- utility-version: {TOOL_VERSION}",
            f"-- required-revision: {REQUIRED_REVISION}",
            f"-- migration-id: {migration_id}",
            "SET NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci;",
            "SET @EOAT_IMPORT_GUARD_ERROR=NULL;",
            "DELIMITER $$",
            "DROP PROCEDURE IF EXISTS `__eoat_operational_import_guard`$$",
            "CREATE PROCEDURE `__eoat_operational_import_guard`()",
            "BEGIN",
            f"  IF (SELECT version_num FROM alembic_version LIMIT 1) <> '{REQUIRED_REVISION}' THEN",
            "    SET @EOAT_IMPORT_GUARD_ERROR='EOAT import refused: schema revision mismatch';",
            "  END IF;",
            f"  IF @EOAT_IMPORT_GUARD_ERROR IS NULL AND EXISTS (SELECT 1 FROM system_metadata WHERE metadata_key={sql_literal(source, marker_key)}) THEN",
            "    SET @EOAT_IMPORT_GUARD_ERROR='EOAT import refused: migration marker already exists';",
            "  END IF;",
        ]
        for table in sorted(baseline_counts):
            if table == "alembic_version":
                continue
            sql_lines.extend([
                f"  IF @EOAT_IMPORT_GUARD_ERROR IS NULL AND (SELECT COUNT(*) FROM `{table}`) <> {baseline_counts[table]} THEN",
                f"    SET @EOAT_IMPORT_GUARD_ERROR='EOAT import refused: non-baseline table {table}';",
                "  END IF;",
            ])
        sql_lines.extend([
            "END$$",
            "CALL `__eoat_operational_import_guard`()$$",
            "DROP PROCEDURE `__eoat_operational_import_guard`$$",
            "DELIMITER ;",
            "SELECT @EOAT_IMPORT_GUARD_ERROR AS import_guard_error;",
            "INSERT INTO `alembic_version` (`version_num`) SELECT `version_num` FROM `alembic_version` "
            "WHERE @EOAT_IMPORT_GUARD_ERROR IS NOT NULL;",
            "INSERT INTO `system_metadata` (`metadata_key`,`metadata_value`,`created_at`,`updated_at`) VALUES "
            f"({sql_literal(source, marker_key)},'IN_PROGRESS',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6));",
            "SET @EOAT_OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS;",
            "SET FOREIGN_KEY_CHECKS=0;",
            "START TRANSACTION;",
        ])
        for table in order:
            rows = export_rows[table]
            if rows:
                sql_lines.append(f"-- {table}: {len(rows)} row(s)")
                sql_lines.extend(insert_sql(source, table, rows, source_meta[table]["column_names"]))
        sql_lines.extend([
            "UPDATE `data_state` SET current_revision=current_revision+1,data_last_modified_at=UTC_TIMESTAMP(6),"
            f"last_import_at=UTC_TIMESTAMP(6),last_import_source={sql_literal(source, f'operational-package:{migration_id}')},"
            "updated_by='operational-data-import' WHERE id=1;",
            f"UPDATE `system_metadata` SET metadata_value='COMPLETED',updated_at=UTC_TIMESTAMP(6) "
            f"WHERE metadata_key={sql_literal(source, marker_key)};",
            "COMMIT;",
            "SET FOREIGN_KEY_CHECKS=@EOAT_OLD_FOREIGN_KEY_CHECKS;",
            "SELECT CASE WHEN @@FOREIGN_KEY_CHECKS=1 THEN 'FOREIGN_KEY_CHECKS_RESTORED' "
            "ELSE 'WARNING_FOREIGN_KEY_CHECKS_WERE_ORIGINALLY_DISABLED' END AS import_session_state;",
        ])
        output.mkdir(parents=True)
        sql_path = output / "operational-data.sql"
        sql_path.write_text("\n".join(sql_lines) + "\n", encoding="utf-8", newline="\n")
        secrets = [value for key, value in source_values.items() if "PASSWORD" in key or "SECRET" in key or "TOKEN" in key]
        findings = secret_findings(sql_path.read_bytes(), secrets)
        if findings:
            shutil.rmtree(output)
            raise RuntimeError(f"Secret scan rejected artifact categories: {', '.join(findings)}")
        digest = hashlib.sha256(sql_path.read_bytes()).hexdigest()
        (output / "operational-data.sql.sha256").write_text(f"{digest}  operational-data.sql\n", encoding="ascii")
        classification = _classification_payload(source_meta)
        excluded_report = {
            "excluded_tables": [
                {"table_name": table, "source_rows": source_counts[table], "reason": TABLE_POLICIES[table].reason}
                for table in sorted(TABLE_POLICIES) if TABLE_POLICIES[table].exclude
            ],
            "value_transformations": transformation_report,
            "credentials_included": False,
            "development_users_included": False,
            "authentication_sessions_included": False,
        }
        file_report = file_reference_report(source)
        location_report = location_observation_report(source)
        policy = normalization_policy()
        resolution_report = duplicate_resolution_report(source, policy)
        approval_evidence = {
            "approved_by": policy["approved_by"],
            "owner_decisions": policy["owner_decisions"],
            "policy_version": policy["policy_version"],
            "approval_scope": "EOAT Atlas observed-location production data normalization",
            "supersedes_operational_migration_id": SUPERSEDED_OPERATIONAL_MIGRATION_ID,
        }
        write_json(output / "source-row-counts.json", source_counts)
        write_json(output / EMPTY_BASELINE_FILENAME, baseline_counts)
        write_json(output / "expected-production-row-counts.json", expected_counts)
        write_json(output / "table-classification.json", classification)
        write_json(output / "seed-parity-report.json", parity)
        write_json(output / "excluded-data-report.json", excluded_report)
        write_json(output / "file-reference-report.json", file_report)
        write_json(output / "eoat-location-observation-report.json", location_report)
        write_json(output / "eoat-location-conflict-report.json", {
            "conflicts": location_report["conflicts"],
            "competing_assertions": [row for row in location_report["assertions"] if row["participates_in_conflict"]],
        })
        write_json(output / DUPLICATE_RESOLUTION_FILENAME, resolution_report)
        write_json(output / APPROVAL_EVIDENCE_FILENAME, approval_evidence)
        (output / SUPERSEDES_FILENAME).write_text(
            f"# Superseded operational migration\n\n"
            f"`{SUPERSEDED_OPERATIONAL_MIGRATION_ID}` is superseded by this corrected package. "
            "Do not import, overwrite, or amend the superseded package.\n",
            encoding="utf-8",
        )
        manifest = {
            "manifest_version": 1,
            "migration_id": migration_id,
            "source_database": {
                "host": source_values.get("EOAT_DB_HOST", "127.0.0.1"),
                "port": int(source_values.get("EOAT_DB_PORT", "3306")),
                "database": source_identity["database_name"],
                "mysql_version": source_identity["server_version"],
                "alembic_revision": source_identity["alembic_revision"],
                "credentials_included": False,
            },
            "source_git": git,
            # Source checkouts intentionally do not track generated release_metadata.json.
            "source_application": asdict(get_version_info(repo)),
            "source_database_latest_application_release": database_release,
            "export_timestamp_utc": args.export_timestamp or utc_now(),
            "export_utility_version": TOOL_VERSION,
            "artifact_filename": sql_path.name,
            "artifact_sha256": digest,
            "supersedes_operational_migration_id": SUPERSEDED_OPERATIONAL_MIGRATION_ID,
            "required_production_schema_revision": REQUIRED_REVISION,
            "table_classifications": classification,
            "table_order": order,
            "per_table_exported_row_counts": exported_counts,
            "total_exported_rows": sum(exported_counts.values()),
            "explicit_exclusions": excluded_report["excluded_tables"],
            "expected_post_import_counts": expected_counts,
            "foreign_key_checks_temporarily_disabled": True,
            "foreign_key_checks_reason": "Self-references and deterministic cross-table ordering; explicit orphan validation is mandatory.",
            "import_marker": marker_key,
            "required_empty_production_baseline_counts_file": EMPTY_BASELINE_FILENAME,
            "owner_approval_evidence_file": APPROVAL_EVIDENCE_FILENAME,
            "duplicate_resolution_report_file": DUPLICATE_RESOLUTION_FILENAME,
        }
        write_json(output / "migration-manifest.json", manifest)
        shutil.copy2(Path(__file__), output / "migration_tool.py")
        validation_md = f"""# Operational-data migration validation

- Source schema revision: `{source_identity['alembic_revision']}` (PASS)
- Disposable production baseline revision: `{baseline_identity['alembic_revision']}` (PASS)
- Classified tables: {len(classification)} of {len(source_tables)} (PASS)
- Seed conflicts: 0 (PASS)
- Exported rows: {sum(exported_counts.values())}
- Artifact SHA-256: `{digest}`
- Credential/secret scan: PASS
- Development authentication/session data excluded: PASS
- File references inspected: {file_report['total_document_references']}
- Owner-approved location normalization evidence: `{APPROVAL_EVIDENCE_FILENAME}` (PASS)
- Duplicate/location resolution report: `{DUPLICATE_RESOLUTION_FILENAME}` (PASS)
- Superseded migration: `{SUPERSEDED_OPERATIONAL_MIGRATION_ID}`

Disposable import, integrity, parity, and API read-smoke results are written by `migration_tool.py validate-database`.
"""
        (output / "validation-report.md").write_text(validation_md, encoding="utf-8")
        write_instructions(output, manifest)
    print(json.dumps({"status": "PASS", "output_directory": str(output), "sha256": digest}, indent=2))
    return 0


def write_instructions(output: Path, manifest: dict[str, Any]) -> None:
    migration_id = manifest["migration_id"]
    digest = manifest["artifact_sha256"]
    release_evidence_dir = str(manifest.get("source_git", {}).get("commit") or "uncommitted")[:7]
    import_text = f"""# EOAT Atlas controlled operational-data import

These commands are documentation only. Run them interactively on EOAT-ATLAS as an authorized operator. The database login paths must be created beforehand with `mysql_config_editor`; never place passwords on a command line.

```bash
set -euo pipefail
PACKAGE=/opt/eoat-atlas/incoming/{migration_id}
cd "$PACKAGE"
sha256sum -c operational-data.sql.sha256
/opt/eoat-atlas/current/venv/bin/python migration_tool.py verify-package --package-directory "$PACKAGE"
test "$(mysql --login-path=eoat-atlas-prod-runtime --batch --skip-column-names eoat_atlas_prod -e 'SELECT version_num FROM alembic_version')" = "{REQUIRED_REVISION}"
EOAT_DB_NAME=eoat_atlas_prod /opt/eoat-atlas/current/venv/bin/python migration_tool.py verify-empty-baseline --package-directory "$PACKAGE"

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/opt/eoat-atlas/shared/backups/eoat_atlas_prod-pre-operational-import-$STAMP.sql
mysqldump --login-path=eoat-atlas-prod-admin --single-transaction --no-tablespaces --routines --triggers --events --hex-blob --set-gtid-purged=OFF eoat_atlas_prod > "$BACKUP"
sha256sum "$BACKUP" | tee "$BACKUP.sha256"
test -s "$BACKUP"

VALIDATION_DB=eoat_atlas_validation_{migration_id[-8:]}
mysql --login-path=eoat-atlas-prod-admin -e "CREATE DATABASE \\`$VALIDATION_DB\\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
EOAT_DB_NAME="$VALIDATION_DB" /opt/eoat-atlas/current/venv/bin/python -m alembic -c /opt/eoat-atlas/current/server/alembic.ini upgrade {REQUIRED_REVISION}
mysql --login-path=eoat-atlas-prod-admin "$VALIDATION_DB" < operational-data.sql
EOAT_DB_NAME="$VALIDATION_DB" /opt/eoat-atlas/current/venv/bin/python migration_tool.py validate-database --package-directory "$PACKAGE"
PYTHONPATH=/opt/eoat-atlas/current EOAT_DB_NAME="$VALIDATION_DB" /opt/eoat-atlas/current/venv/bin/python migration_tool.py api-smoke --package-directory "$PACKAGE"
mysqlcheck --login-path=eoat-atlas-prod-admin --check --extended "$VALIDATION_DB"
if mysql --login-path=eoat-atlas-prod-admin "$VALIDATION_DB" < operational-data.sql; then
  echo 'ERROR: duplicate import unexpectedly succeeded' >&2
  exit 1
fi
echo 'PASS: duplicate import correctly refused'
EOAT_DB_NAME="$VALIDATION_DB" /opt/eoat-atlas/current/venv/bin/python migration_tool.py validate-database --package-directory "$PACKAGE"
mysql --login-path=eoat-atlas-prod-admin -e "DROP DATABASE \\`$VALIDATION_DB\\`"

# Owner-approved normalization evidence is verified by verify-package above.
test -s "$PACKAGE/{APPROVAL_EVIDENCE_FILENAME}"
test -s "$PACKAGE/{DUPLICATE_RESOLUTION_FILENAME}"
EOAT_DB_NAME=eoat_atlas_prod /opt/eoat-atlas/current/venv/bin/python migration_tool.py verify-empty-baseline --package-directory "$PACKAGE"

EXPECTED='IMPORT {migration_id} INTO eoat_atlas_prod'
read -r -p "Type exactly: $EXPECTED: " CONFIRM
test "$CONFIRM" = "$EXPECTED"
test "$(sha256sum operational-data.sql | awk '{{print $1}}')" = "{digest}"
mysql --login-path=eoat-atlas-prod-admin eoat_atlas_prod < operational-data.sql
EOAT_DB_NAME=eoat_atlas_prod /opt/eoat-atlas/current/venv/bin/python migration_tool.py validate-database --package-directory "$PACKAGE"
PYTHONPATH=/opt/eoat-atlas/current EOAT_DB_NAME=eoat_atlas_prod /opt/eoat-atlas/current/venv/bin/python migration_tool.py api-smoke --package-directory "$PACKAGE"
mysqlcheck --login-path=eoat-atlas-prod-admin --check --extended eoat_atlas_prod
if mysql --login-path=eoat-atlas-prod-admin eoat_atlas_prod < operational-data.sql; then
  echo 'ERROR: duplicate production import unexpectedly succeeded' >&2
  exit 1
fi
echo 'PASS: duplicate production import correctly refused'
EOAT_DB_NAME=eoat_atlas_prod /opt/eoat-atlas/current/venv/bin/python migration_tool.py validate-database --package-directory "$PACKAGE"

POST=/opt/eoat-atlas/shared/backups/eoat_atlas_prod-post-operational-import-$STAMP.sql
mysqldump --login-path=eoat-atlas-prod-admin --single-transaction --no-tablespaces --routines --triggers --events --hex-blob --set-gtid-purged=OFF eoat_atlas_prod > "$POST"
sha256sum "$POST" | tee "$POST.sha256"
install -m 0640 disposable-validation-report.json /opt/eoat-atlas/shared/releases/{release_evidence_dir}/production-data-import-$STAMP.json
```

Do not start the API and do not change systemd, Nginx, or runtime configuration in this procedure. The persistent marker `{manifest['import_marker']}` and exact baseline-count guard refuse duplicate or non-baseline imports. An `IN_PROGRESS` marker indicates an interrupted attempt and requires evidence preservation plus rollback, not a blind retry.
"""
    rollback_text = f"""# EOAT Atlas controlled rollback

Use the exact pre-import backup created by the import procedure. Never delete or overwrite it.

```bash
set -euo pipefail
BACKUP=/opt/eoat-atlas/shared/backups/eoat_atlas_prod-pre-operational-import-REPLACE_WITH_STAMP.sql
test -s "$BACKUP"
test -s "$BACKUP.sha256"
cd "$(dirname "$BACKUP")"
sha256sum -c "$(basename "$BACKUP").sha256"

RESTORE_CHECK=eoat_atlas_restore_check_{migration_id[-8:]}
mysql --login-path=eoat-atlas-prod-admin -e "CREATE DATABASE \\`$RESTORE_CHECK\\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
mysql --login-path=eoat-atlas-prod-admin "$RESTORE_CHECK" < "$BACKUP"
test "$(mysql --login-path=eoat-atlas-prod-admin --batch --skip-column-names "$RESTORE_CHECK" -e 'SELECT version_num FROM alembic_version')" = "{REQUIRED_REVISION}"
mysqlcheck --login-path=eoat-atlas-prod-admin --check --extended "$RESTORE_CHECK"
mysql --login-path=eoat-atlas-prod-admin -e "DROP DATABASE \\`$RESTORE_CHECK\\`"

EXPECTED='RESTORE eoat_atlas_prod FROM VERIFIED PRE-IMPORT BACKUP'
read -r -p "Type exactly: $EXPECTED: " CONFIRM
test "$CONFIRM" = "$EXPECTED"
FAILED=/opt/eoat-atlas/shared/backups/eoat_atlas_prod-failed-import-$(date -u +%Y%m%dT%H%M%SZ).sql
mysqldump --login-path=eoat-atlas-prod-admin --single-transaction --no-tablespaces --routines --triggers --events --hex-blob --set-gtid-purged=OFF eoat_atlas_prod > "$FAILED"
sha256sum "$FAILED" > "$FAILED.sha256"
mysql --login-path=eoat-atlas-prod-admin -e 'DROP DATABASE eoat_atlas_prod; CREATE DATABASE eoat_atlas_prod CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci'
mysql --login-path=eoat-atlas-prod-admin eoat_atlas_prod < "$BACKUP"
test "$(mysql --login-path=eoat-atlas-prod-admin --batch --skip-column-names eoat_atlas_prod -e 'SELECT version_num FROM alembic_version')" = "{REQUIRED_REVISION}"
mysqlcheck --login-path=eoat-atlas-prod-admin --check --extended eoat_atlas_prod
```

Stop immediately if the backup or checksum is absent or invalid. Preserve the failed-state dump, package, validation reports, and logs.
"""
    (output / "IMPORT_INSTRUCTIONS.md").write_text(import_text, encoding="utf-8")
    (output / "ROLLBACK_INSTRUCTIONS.md").write_text(rollback_text, encoding="utf-8")


def verify_package(package: Path) -> dict[str, Any]:
    manifest = json.loads((package / "migration-manifest.json").read_text(encoding="utf-8"))
    artifact = package / manifest["artifact_filename"]
    actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if actual != manifest["artifact_sha256"]:
        raise RuntimeError(f"Artifact checksum mismatch: expected {manifest['artifact_sha256']}, actual {actual}")
    if manifest["required_production_schema_revision"] != REQUIRED_REVISION:
        raise RuntimeError("Manifest target revision is not approved")
    if secret_findings(artifact.read_bytes()):
        raise RuntimeError("Artifact secret scan failed")
    if manifest.get("supersedes_operational_migration_id") != SUPERSEDED_OPERATIONAL_MIGRATION_ID:
        raise RuntimeError("Package does not explicitly supersede the rejected migration")
    for key, filename in (
        ("required_empty_production_baseline_counts_file", EMPTY_BASELINE_FILENAME),
        ("owner_approval_evidence_file", APPROVAL_EVIDENCE_FILENAME),
        ("duplicate_resolution_report_file", DUPLICATE_RESOLUTION_FILENAME),
    ):
        if manifest.get(key) != filename or not (package / filename).is_file():
            raise RuntimeError(f"Package is missing required evidence: {filename}")
    approval = json.loads((package / APPROVAL_EVIDENCE_FILENAME).read_text(encoding="utf-8"))
    if approval.get("approved_by") != {"name": "Kato Gray", "role": "EOAT Atlas project/data owner"}:
        raise RuntimeError("Package owner approval record is not the authorized EOAT data owner")
    decisions = " ".join(approval.get("owner_decisions", []))
    for phrase in ("N/A means stored", "26 - Xqual in 25 means Machine 26", "separate deterministic EOAT IDs", "movement", "STORED", "No unsupported lifecycle history"):
        if phrase not in decisions:
            raise RuntimeError("Package owner approval record is incomplete")
    resolution = json.loads((package / DUPLICATE_RESOLUTION_FILENAME).read_text(encoding="utf-8"))
    if resolution.get("status") != "RESOLVED" or resolution.get("remaining_unresolved_records"):
        raise RuntimeError("Package duplicate-resolution evidence is incomplete")
    return {"status": "PASS", "artifact_sha256": actual, "migration_id": manifest["migration_id"]}


def orphan_checks(connection) -> list[dict[str, Any]]:
    meta = schema_metadata(connection)
    results = []
    with connection.cursor() as cursor:
        for table in sorted(meta):
            for fk in meta[table]["foreign_keys"]:
                column = fk["COLUMN_NAME"]
                parent = fk["REFERENCED_TABLE_NAME"]
                parent_column = fk["REFERENCED_COLUMN_NAME"]
                cursor.execute(
                    f"SELECT COUNT(*) count FROM `{table}` child LEFT JOIN `{parent}` parent "
                    f"ON child.`{column}`=parent.`{parent_column}` WHERE child.`{column}` IS NOT NULL "
                    f"AND parent.`{parent_column}` IS NULL"
                )
                results.append({
                    "table": table, "column": column, "parent_table": parent,
                    "constraint": fk["CONSTRAINT_NAME"], "orphan_count": int(cursor.fetchone()["count"]),
                })
    return results


def duplicate_checks(connection) -> list[dict[str, Any]]:
    results = []
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name,index_name,GROUP_CONCAT(column_name ORDER BY seq_in_index) columns_csv "
            "FROM information_schema.statistics WHERE table_schema=DATABASE() AND non_unique=0 "
            "AND index_name <> 'PRIMARY' GROUP BY table_name,index_name ORDER BY table_name,index_name"
        )
        indexes = cursor.fetchall()
        for item in indexes:
            columns = item["columns_csv"].split(",")
            group = ",".join(f"`{column}`" for column in columns)
            nonnull = " AND ".join(f"`{column}` IS NOT NULL" for column in columns)
            cursor.execute(
                f"SELECT COUNT(*) count FROM (SELECT 1 FROM `{item['TABLE_NAME']}` WHERE {nonnull} "
                f"GROUP BY {group} HAVING COUNT(*)>1) duplicates"
            )
            results.append({**item, "duplicate_groups": int(cursor.fetchone()["count"])})
    return results


def auto_increment_checks(connection) -> list[dict[str, Any]]:
    meta = schema_metadata(connection)
    results = []
    with connection.cursor() as cursor:
        for table in sorted(meta):
            column = meta[table]["auto_increment"]
            if not column:
                continue
            cursor.execute(f"SELECT COALESCE(MAX(`{column}`),0) maximum_id FROM `{table}`")
            maximum = int(cursor.fetchone()["maximum_id"])
            cursor.execute("SELECT COALESCE(auto_increment,1) next_id FROM information_schema.tables "
                           "WHERE table_schema=DATABASE() AND table_name=%s", (table,))
            next_id = int(cursor.fetchone()["next_id"])
            results.append({"table": table, "column": column, "maximum_id": maximum,
                            "next_auto_increment": next_id, "valid": next_id > maximum})
    return results


def assess_runtime_grants(grants: list[str]) -> dict[str, Any]:
    combined = " ".join(grants).upper()
    all_privileges = "ALL PRIVILEGES" in combined
    required = [
        permission for permission in ("SELECT", "INSERT", "UPDATE", "DELETE")
        if permission not in combined and not all_privileges
    ]
    forbidden = [
        permission for permission in DANGEROUS_RUNTIME_PRIVILEGES
        if permission in combined
    ]
    return {
        "valid": not required and not forbidden,
        "required_permissions": ["SELECT", "INSERT", "UPDATE", "DELETE"],
        "missing_required_permissions": required,
        "forbidden_permissions_present": forbidden,
        "grants_redacted": True,
    }


def runtime_grant_check(connection) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute("SHOW GRANTS FOR CURRENT_USER")
        grants = [str(next(iter(row.values()))) for row in cursor.fetchall()]
    return assess_runtime_grants(grants)


def verify_empty_baseline(args: argparse.Namespace) -> int:
    package = Path(args.package_directory).resolve()
    verify_package(package)
    manifest = json.loads((package / "migration-manifest.json").read_text(encoding="utf-8"))
    baseline = json.loads((package / EMPTY_BASELINE_FILENAME).read_text(encoding="utf-8"))
    values = read_env(args.database_environment)
    with connect(values) as connection:
        identity = database_identity(connection)
        if identity["alembic_revision"] != REQUIRED_REVISION:
            raise RuntimeError(f"Baseline revision mismatch: {identity['alembic_revision']}")
        actual = row_counts(connection)
        mismatches = {table: {"expected": count, "actual": actual.get(table)}
                      for table, count in baseline.items() if actual.get(table) != count}
        with connection.cursor() as cursor:
            cursor.execute("SELECT metadata_value FROM system_metadata WHERE metadata_key=%s", (manifest["import_marker"],))
            marker = cursor.fetchone()
    report = {
        "status": "PASS" if not mismatches and marker is None else "FAIL",
        "database": identity["database_name"],
        "required_schema_revision": REQUIRED_REVISION,
        "row_count_mismatches": mismatches,
        "operational_migration_marker_absent": marker is None,
        "location_observations": actual.get("eoat_location_observations"),
        "location_assertions": actual.get("eoat_location_assertions"),
    }
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


def transient_name_checks(connection) -> list[dict[str, Any]]:
    meta = schema_metadata(connection)
    findings = []
    with connection.cursor() as cursor:
        for table in sorted(meta):
            text_columns = [row["COLUMN_NAME"] for row in meta[table]["columns"]
                            if row["DATA_TYPE"] in {"char", "varchar", "text", "mediumtext", "longtext", "json"}]
            for column in text_columns:
                cursor.execute(
                    f"SELECT COUNT(*) count FROM `{table}` WHERE LOWER(CAST(`{column}` AS CHAR)) "
                    "REGEXP 'eoat_atlas_(test|validation|staging_restore)'"
                )
                count = int(cursor.fetchone()["count"])
                if count:
                    findings.append({"table": table, "column": column, "count": count})
    return findings


def validate_database(args: argparse.Namespace) -> int:
    package = Path(args.package_directory).resolve()
    verify_package(package)
    expected = json.loads((package / "expected-production-row-counts.json").read_text(encoding="utf-8"))
    values = read_env(args.database_environment)
    with connect(values) as connection:
        identity = database_identity(connection)
        if identity["alembic_revision"] != REQUIRED_REVISION:
            raise RuntimeError(f"Validation database revision mismatch: {identity['alembic_revision']}")
        actual = row_counts(connection)
        mismatches = {table: {"expected": count, "actual": actual.get(table)}
                      for table, count in expected.items() if actual.get(table) != count}
        orphans = orphan_checks(connection)
        duplicates = duplicate_checks(connection)
        auto = auto_increment_checks(connection)
        transient = transient_name_checks(connection)
        grants = runtime_grant_check(connection)
        marker = json.loads((package / "migration-manifest.json").read_text(encoding="utf-8"))["import_marker"]
        with connection.cursor() as cursor:
            cursor.execute("SELECT metadata_value FROM system_metadata WHERE metadata_key=%s", (marker,))
            marker_row = cursor.fetchone()
        status = "PASS" if (
            not mismatches and not any(x["orphan_count"] for x in orphans)
            and not any(x["duplicate_groups"] for x in duplicates)
            and all(x["valid"] for x in auto) and not transient
            and grants["valid"]
            and marker_row and marker_row["metadata_value"] == "COMPLETED"
        ) else "FAIL"
        report = {
            "status": status,
            "database": {"host": values.get("EOAT_DB_HOST", "127.0.0.1"),
                         "port": int(values.get("EOAT_DB_PORT", "3306")),
                         "name": identity["database_name"], "server_version": identity["server_version"],
                         "alembic_revision": identity["alembic_revision"]},
            "row_count_mismatches": mismatches,
            "actual_row_counts": actual,
            "foreign_key_orphan_checks": orphans,
            "unique_key_duplicate_checks": duplicates,
            "auto_increment_checks": auto,
            "transient_database_name_findings": transient,
            "runtime_permission_check": grants,
            "import_marker_complete": bool(marker_row and marker_row["metadata_value"] == "COMPLETED"),
            "validated_at_utc": utc_now(),
        }
    write_json(package / "disposable-validation-report.json", report)
    with (package / "validation-report.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n## Disposable import validation\n\n- Result: **{status}**\n")
        stream.write(f"- Row-count mismatches: {len(mismatches)}\n")
        stream.write(f"- Foreign-key orphans: {sum(x['orphan_count'] for x in orphans)}\n")
        stream.write(f"- Duplicate unique-key groups: {sum(x['duplicate_groups'] for x in duplicates)}\n")
        stream.write(f"- AUTO_INCREMENT failures: {sum(not x['valid'] for x in auto)}\n")
        stream.write(f"- Transient database-name findings: {len(transient)}\n")
    print(json.dumps({"status": status, "report": str(package / "disposable-validation-report.json")}, indent=2))
    return 0 if status == "PASS" else 1


def select_api_smoke_machine(cursor) -> ApiSmokeMachineCandidate:
    """Select a stable machine record without treating machine numbers as globally unique.

    Machine numbers are unique only within a plant.  The smoke request therefore always
    uses the supported ``plant_code`` query parameter instead of relying on an arbitrary
    unqualified lookup.  The primary-key tie breaker makes the selection repeatable.
    """
    cursor.execute(
        "SELECT p.plant_code,m.machine_number,m.id machine_id "
        "FROM machines m JOIN plants p ON p.id=m.plant_id "
        "WHERE p.plant_code IS NOT NULL AND TRIM(p.plant_code) <> '' "
        "AND m.machine_number IS NOT NULL AND TRIM(m.machine_number) <> '' "
        "ORDER BY p.plant_code,m.machine_number,m.id"
    )
    rows = cursor.fetchall()
    candidates = [
        ApiSmokeMachineCandidate(
            plant_code=str(row["plant_code"]).strip(),
            machine_number=str(row["machine_number"]).strip(),
            machine_id=int(row["machine_id"]),
        )
        for row in rows
        if row.get("plant_code") and row.get("machine_number") and row.get("machine_id") is not None
    ]
    candidates = [candidate for candidate in candidates if candidate.machine_id > 0]
    if not candidates:
        raise RuntimeError(
            "API smoke cannot select a machine profile candidate: imported operational data contains no "
            "machine with both a plant code and machine number."
        )
    return min(candidates, key=lambda candidate: (
        candidate.plant_code.casefold(), candidate.machine_number.casefold(), candidate.machine_id
    ))


def api_smoke(args: argparse.Namespace) -> int:
    package = Path(args.package_directory).resolve()
    verify_package(package)
    values = read_env(args.database_environment)
    for key, value in values.items():
        if key.startswith("EOAT_"):
            os.environ[key] = value
    with connect(values) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT business_identifier FROM eoats ORDER BY id LIMIT 1")
        eoat = cursor.fetchone()["business_identifier"]
        machine = select_api_smoke_machine(cursor)
        cursor.execute("SELECT tool_number FROM tools ORDER BY id LIMIT 1")
        tool = cursor.fetchone()["tool_number"]
        cursor.execute(
            "SELECT e.business_identifier,m.machine_number,t.tool_number "
            "FROM eoat_machine_compatibility em JOIN eoats e ON e.id=em.eoat_id "
            "JOIN machines m ON m.id=em.machine_id "
            "JOIN tool_machine_compatibility tm ON tm.machine_id=m.id JOIN tools t ON t.id=tm.tool_id "
            "JOIN eoat_tool_compatibility et ON et.eoat_id=e.id AND et.tool_id=t.id "
            "WHERE m.id=%s ORDER BY e.id,t.id LIMIT 1",
            (machine.machine_id,),
        )
        triple_row = cursor.fetchone()
    triple = (
        (triple_row["business_identifier"], triple_row["machine_number"], triple_row["tool_number"])
        if triple_row else (eoat, machine.machine_number, tool)
    )
    from fastapi.testclient import TestClient

    from server.eoat_api.app import app

    checks: dict[str, int] = {}
    with TestClient(app) as client:
        requests = {
            "health": ("get", "/api/v1/health", None),
            "eoat_list": ("get", "/api/v1/eoats", {"limit": 5}),
            "eoat_detail": ("get", f"/api/v1/eoats/{eoat}", None),
            "eoat_current_location": ("get", f"/api/v1/eoats/{eoat}/current-location", None),
            "eoat_location_observations": ("get", f"/api/v1/eoats/{eoat}/location-observations", None),
            "eoat_compatibility": ("get", f"/api/v1/eoats/{eoat}/relationships", None),
            "eoat_history": ("get", f"/api/v1/eoats/{eoat}/history", None),
            "documents": ("get", f"/api/v1/eoats/{eoat}/documents", None),
            "photos": ("get", f"/api/v1/eoats/{eoat}/photos", None),
            "machine_list": ("get", "/api/v1/machines", {"limit": 5}),
            "machine_detail": ("get", f"/api/v1/machines/{machine.machine_number}", machine.profile_params),
            "tool_list": ("get", "/api/v1/tools", {"limit": 5}),
            "tool_detail": ("get", f"/api/v1/tools/{tool}", None),
            "home_summary": ("get", "/api/v1/home-summary", None),
        }
        for name, (_, path, params) in requests.items():
            response = client.get(path, params=params)
            checks[name] = response.status_code
        e, m, t = triple
        response = client.post("/api/v1/fit-checks/evaluate", json={
            "eoat_identifier": e,
            "machine_number": m,
            "plant_code": machine.plant_code,
            "tool_number": t,
            "persist": False,
        })
        checks["fit_check"] = response.status_code
        response = client.get("/api/v1/compatibility/alternatives", params={
            "eoat_identifier": e,
            "machine_number": m,
            "plant_code": machine.plant_code,
            "tool_number": t,
        })
        checks["compatibility_alternatives"] = response.status_code
    status = "PASS" if checks and all(code == 200 for code in checks.values()) else "FAIL"
    report = {"status": status, "checks": checks, "live_api_started": False, "validated_at_utc": utc_now()}
    write_json(package / "api-read-smoke-report.json", report)
    print(json.dumps(report, indent=2))
    return 0 if status == "PASS" else 1


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Build and validate the EOAT Atlas production operational-data migration")
    commands = root.add_subparsers(dest="command", required=True)
    build_cmd = commands.add_parser("build")
    build_cmd.add_argument("--source-environment", default="development")
    build_cmd.add_argument("--baseline-environment", required=True)
    build_cmd.add_argument("--output-directory", required=True)
    build_cmd.add_argument("--export-timestamp")
    build_cmd.add_argument("--source-branch")
    build_cmd.add_argument("--validation-mode", action="store_true")
    verify_cmd = commands.add_parser("verify-package")
    verify_cmd.add_argument("--package-directory", required=True)
    baseline_cmd = commands.add_parser("verify-empty-baseline")
    baseline_cmd.add_argument("--package-directory", required=True)
    baseline_cmd.add_argument("--database-environment", default="environment")
    validate_cmd = commands.add_parser("validate-database")
    validate_cmd.add_argument("--package-directory", required=True)
    validate_cmd.add_argument("--database-environment", default="environment")
    smoke_cmd = commands.add_parser("api-smoke")
    smoke_cmd.add_argument("--package-directory", required=True)
    smoke_cmd.add_argument("--database-environment", default="environment")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "build":
            return build(args)
        if args.command == "verify-package":
            print(json.dumps(verify_package(Path(args.package_directory)), indent=2))
            return 0
        if args.command == "verify-empty-baseline":
            return verify_empty_baseline(args)
        if args.command == "api-smoke":
            return api_smoke(args)
        return validate_database(args)
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
