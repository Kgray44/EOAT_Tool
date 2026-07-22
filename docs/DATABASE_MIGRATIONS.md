# Database migrations

Alembic configuration is `server/alembic.ini`; migrations are under `server/migrations`. Set migration credentials with
`EOAT_DB_MIGRATION_USER` and `EOAT_DB_MIGRATION_PASSWORD`, then select the database with `EOAT_DB_NAME`.

Check using `python -m alembic -c server/alembic.ini heads` and
`python -m alembic -c server/alembic.ini current`. Upgrade with
`python -m alembic -c server/alembic.ini upgrade head`.

The current application-required head is `20260721_0008`. This revision adds the singleton `data_state` table used for authoritative server data revision and freshness metadata. It initializes from the existing change-feed maximum when present; otherwise the initialization time is the first known timestamp. It follows `20260717_0007`, which added EOAT location observations/assertions; see [EOAT physical-location semantics](database/eoat_location_observations.md). Do not use an audit date as an installation or storage-movement timestamp.

Downgrade/re-upgrade exercises are allowed only against `eoat_atlas_test` or a disposable database. Never downgrade the
development or production database as a test. Record unavailable credentials, unreachable services, and skipped tests
as blocked—not passed.
