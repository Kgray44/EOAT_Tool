# Data Freshness and Revision Truth

EOAT Atlas treats these as different facts:

- **Data last updated** is `data_state.data_last_modified_at`: the timestamp of a committed, tracked MySQL data change.
- **Last checked** is a client-side successful `/api/v1/data-status` request. It can advance without a data change.
- **This page refreshed** is when a page applied a bundle. It is not an authority timestamp.
- **Last imported** records a completed external import and its source. A no-op import records the import but does not advance the data revision.
- **Server revision** is `data_state.current_revision`, advanced once per successful logical write transaction or material import.
- **Page revision** is the server revision represented by a loaded data view.

`data_state` contains exactly one row (`id=1`). Write services call `mark_data_changed()` through the existing audit/change-feed path. A SQLAlchemy `before_commit` hook locks that row and increments it once within the same transaction. Rollbacks cannot publish a revision. Import tools use the same row update in their transaction and must only increment it for material data changes.

The lightweight anonymous-read endpoint `GET /api/v1/data-status` returns revision, authoritative modification/import metadata, server time, source, and environment. It does not query full data sets, rebuild caches, or mutate data. Production device-read policy explicitly permits this non-sensitive endpoint just as it permits health/version checks; it never requires a Settings login.

Successful API write responses are committed before the response is released. Consequently, a status request made after a successful write response observes the committed revision; failed responses roll back the request transaction. This boundary matters for clients that poll immediately after another client writes.

`core.data_freshness.DataFreshnessService` is the desktop state machine. `QtDataFreshnessPoller` owns the single status-only timer/worker in MySQL/API mode. Normal polling defaults to one minute; failures back off from 15 seconds to five minutes. A no-change poll updates only `Last checked`. An increasing revision marks registered views stale; a decreasing revision is logged and requires a safe reload. The relative-label timer changes words only, never metadata.

## Qt lifecycle contract

Freshness polling owns one long-lived `QThread` for the lifetime of its owning poller. The worker performs at most one status request at a time on that thread; completed polls reuse the same thread rather than constructing and deleting a native thread for every interval. Closing the owner stops its timer, tells the thread event loop to exit, and waits before the owner can be destroyed.

Settings uses a receiver-owned, single-shot refresh timer. It stops that timer, unregisters and disconnects dynamic source rows, clears its Python registries, and makes shutdown idempotent before Qt receives the widgets' deferred deletions. The main window and library page call their explicit shutdown methods on close, so pollers, photo workers, timers, and dynamic controls do not outlive their owner.

The initial full data snapshot may establish a page revision before the first lightweight status request. If that first status response has the same revision and the client has no authoritative modification timestamp yet, the client adopts the server timestamp once. Later same-revision polls preserve the stored timestamp and advance only `Last checked`; navigation and rerendering never create a data update.

The focused lifecycle regression coverage is in `tests/test_data_freshness_qt.py` and `tests/test_minimalist_settings_page.py`. It covers explicit poller shutdown, disabled manual checks, twelve serial status checks on one worker thread, deferred settings refresh cancellation, 80 dynamic settings-row rebuild/delete cycles, and live-row registry assertions. A release still requires the complete non-integration suite and the separate native UI procedure below; focused tests are not a substitute for either gate.

When implementing a future user-visible data write, route it through the server write service/audit path or call `mark_data_changed(session, actor)` inside the same transaction. For a workbook or operational-package import, call `record_import_completion(..., changed_data=True)` (or perform its equivalent SQL update) in the import transaction. Do not update `data_state` for rendering, reads, health checks, cache rebuilds, no-change polls, or schema-only migrations.

The Settings **Server, Synchronization, and Cache** section controls enablement, the supported 15 sec/30 sec/1 min/5 min/15 min/30 min intervals, safe automatic-versus-notify behavior, edit deferral, minimized polling, and relative/exact display. Diagnostics exposes state, last attempt/success, retry, revisions, import metadata, clock offset, cache state, and active task count. The **Check data connection** action is a status-only manual request.

## Import and deployment ordering

Operational packages classify `data_state` as target-local metadata: it is not copied from the source database. A successful package updates it once in the import transaction; a duplicate package is rejected by its marker before it can create another freshness event. The location-observation importer records `last_import_*` for a deduplicated no-op, but leaves `current_revision` and `data_last_modified_at` unchanged. A failed import must roll back its operational rows and must not update `data_state`.

Deploy the database migration `20260721_0008` before enabling an API or desktop client that expects `/api/v1/data-status`. Existing and future visible writes must continue through the server write/audit path, or explicitly call `mark_data_changed(session, actor)` in the same committed transaction. Do not add a post-commit timer or client-side timestamp as a substitute for this transaction boundary.

## Disposable MySQL acceptance procedure

Use only the approved `eoat_atlas_test` database or a separately named local disposable database. Load the current user's local `database.env` into the test process, override `EOAT_DB_NAME=eoat_atlas_test`, and construct `EOAT_MYSQL_TEST_URL` only in that process from the local runtime account values. Do not put connection URLs, passwords, or database dumps in source control, test output, or documentation.

Run the real-MySQL checks with the test variables present:

```powershell
python scripts\database\reset_mysql_test_database.py --database eoat_atlas_test
python -m pytest tests\integration\test_mysql_foundation.py tests\integration\test_data_freshness_mysql.py tests\integration\test_data_freshness_imports_mysql.py -q -rA
python -m alembic -c server\alembic.ini heads
python scripts\check_version_bump.py --base HEAD
```

The acceptance coverage includes empty bootstrap, downgrade/re-upgrade from `20260717_0007`, singleton idempotence, live HTTP status/write visibility, canonical-write rollback, concurrent writes, changed/no-op/failed location imports, and changed/duplicate operational-package imports. Native desktop visual walkthroughs and a real host sleep/resume cycle remain separate manual acceptance evidence; deterministic timer/state tests do not prove those visual interactions.
