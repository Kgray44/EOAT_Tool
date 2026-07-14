# Server-First Write Architecture

The authoritative development flow is:

```text
PySide6 workflow -> Application service -> Data Gateway -> /api/v1 -> write service -> SQLAlchemy -> MySQL
                                                            |                |
                                                            |                +-- business row
                                                            |                +-- change_audit_log
                                                            |                +-- entity_history_events when user-visible
                                                            |                +-- change_feed when cache-visible
                                                            +-- normalized response/error
```

The gateway sends identity, application-instance UUID, client version, expected row version, request ID, and idempotency key as applicable. It updates or rebuilds the disposable cache only after a confirmed server commit. A cache failure after commit is reported as `cache_refresh_required`; it never attempts to undo server state. Offline and incompatible clients are read-only and do not queue writes.

Development write mode requires all three conditions: `EOAT_ATLAS_DATA_BACKEND=mysql_api`, `EOAT_ATLAS_ENVIRONMENT=development`, and `EOAT_ATLAS_WRITES_ENABLED=true`. The API separately requires `EOAT_API_ENVIRONMENT=development` and `EOAT_API_WRITES_ENABLED=true`. Production defaults remain `legacy` and write-disabled.

For an explicitly isolated local session, run `scripts/setup/start_eoat_atlas_mysql_dev.ps1`. It starts or restarts the loopback API in write-enabled development mode, sets the desktop's development-only gateway variables for that process, uses a stable local application-instance UUID, and launches `python -m app.atlas.main`. It does not alter production configuration.

EOAT Profile page data/UI code is outside this conversion by explicit request. Shared endpoints exist, but no Profile page redesign or profile-photo-selection workflow is claimed here.
