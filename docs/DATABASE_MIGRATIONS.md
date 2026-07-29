# Database migrations

Alembic configuration is `server/alembic.ini`; migrations are under `server/migrations`. Set migration credentials with
`EOAT_DB_MIGRATION_USER` and `EOAT_DB_MIGRATION_PASSWORD`, then select the database with `EOAT_DB_NAME`.

Check using `python -m alembic -c server/alembic.ini heads` and
`python -m alembic -c server/alembic.ini current`. Upgrade with
`python -m alembic -c server/alembic.ini upgrade head`.

The current application-required head is `20260729_0009`. This revision adds a stable physical EOAT UUID, a design/family identifier, and a source-alias provenance table so a legacy identifier, machine, tool, or audit observation cannot act as the physical identity key. It follows `20260721_0008`, which adds the singleton `data_state` table used for authoritative server data revision and freshness metadata. Do not use an audit date as an installation or storage-movement timestamp.

Downgrade/re-upgrade exercises are allowed only against `eoat_atlas_test` or a disposable database. Never downgrade the
development or production database as a test. Record unavailable credentials, unreachable services, and skipped tests
as blocked—not passed.
