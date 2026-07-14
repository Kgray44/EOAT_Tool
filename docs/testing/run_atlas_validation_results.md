# Canonical startup validation results

Validation date: 2026-07-14

The exact canonical command `python run_atlas.py` completed its smoke-validation launch successfully from the canonical network path. All captured Python module paths were inside the canonical repository. The latest Phase 10 validation reported application 0.9.1, API 1.3.0, MySQL 8.4.9, `eoat_atlas_dev`, schema `20260714_0005`, `mysql_api`, disabled legacy fallback, and no startup authentication.

The authoritative test execution used fresh process partitions to isolate Qt global state: 866 regular tests and 21 authenticated MySQL integration tests passed, with zero failures and zero skipped tests. Ruff, compilation, Alembic head/current, SQLAlchemy metadata, MySQL schema, offline behavior, History cache rebuild, and PDF export also passed.

See `reports/repository_consolidation/` for the complete evidence and qualification notes.
