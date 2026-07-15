from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

import server.eoat_api.database.models  # noqa: F401
from server.eoat_api.database.base import Base
from server.eoat_api.database.config import migration_database_url


def verify() -> dict:
    engine = create_engine(migration_database_url(), pool_pre_ping=True)
    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())
    expected_tables = set(Base.metadata.tables)
    table_details = {}
    for table in sorted(expected_tables):
        table_details[table] = {
            "columns": [column["name"] for column in inspector.get_columns(table)],
            "primary_key": inspector.get_pk_constraint(table),
            "foreign_keys": inspector.get_foreign_keys(table),
            "indexes": inspector.get_indexes(table),
            "unique_constraints": inspector.get_unique_constraints(table),
            "check_constraints": inspector.get_check_constraints(table),
        }
    with engine.connect() as connection:
        version = connection.execute(text("SELECT VERSION()" )).scalar_one()
        database = connection.execute(text("SELECT DATABASE()" )).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version" )).scalar_one()
        collation = connection.execute(
            text("SELECT DEFAULT_COLLATION_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = DATABASE()")
        ).scalar_one()
        engine_counts = connection.execute(
            text("SELECT ENGINE, COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() GROUP BY ENGINE")
        ).all()
        invalid_foreign_keys = connection.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS "
                "WHERE CONSTRAINT_SCHEMA = DATABASE() AND REFERENCED_TABLE_NAME IS NULL"
            )
        ).scalar_one()
    engine.dispose()
    totals = {
        "tables": len(actual_tables),
        "model_tables": len(expected_tables),
        "foreign_keys": sum(len(item["foreign_keys"]) for item in table_details.values()),
        "indexes": sum(len(item["indexes"]) for item in table_details.values()),
        "unique_constraints": sum(len(item["unique_constraints"]) for item in table_details.values()),
        "check_constraints": sum(len(item["check_constraints"]) for item in table_details.values()),
    }
    errors = []
    if expected_tables - actual_tables:
        errors.append(f"missing tables: {sorted(expected_tables - actual_tables)}")
    if revision != "20260715_0006":
        errors.append(f"unexpected Alembic revision: {revision}")
    if invalid_foreign_keys:
        errors.append(f"invalid foreign-key metadata rows: {invalid_foreign_keys}")
    if dict(engine_counts).get("InnoDB", 0) < len(expected_tables):
        errors.append(f"not all model tables use InnoDB: {dict(engine_counts)}")
    return {
        "status": "PASS" if not errors else "FAIL",
        "database": database,
        "server_version": version,
        "schema_revision": revision,
        "collation": collation,
        "engines": dict(engine_counts),
        "totals": totals,
        "extra_tables": sorted(actual_tables - expected_tables),
        "errors": errors,
        "tables": table_details,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = verify()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "database", "server_version", "schema_revision", "collation", "totals", "errors")}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
