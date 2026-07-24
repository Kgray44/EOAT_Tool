# Desktop Data Gateway Design

`core/data_gateway` is the desktop boundary for `mysql_api` mode. UI workers receive an `AtlasDataBundle` built from the API/cache and do not construct URLs, parse raw API errors, query SQLite directly, open Excel, or know MySQL credentials.

The gateway supplies the existing reads plus server-first asset, compatibility, location, audit, maintenance, document/photo metadata, tag, and annotation writes.

Connectivity states are `ONLINE`, `OFFLINE_READ_ONLY`, `INCOMPATIBLE_SERVER`, `INITIALIZING`, `REFRESHING`, and `ERROR`. Offline/incompatible modes block permanent writes without queuing or legacy fallback. Authoritative responses precede cache refresh. Conflicts, validation, permission, unavailable-server, and write-block errors have distinct gateway exceptions.

Both classic and minimalist background loaders select the gateway only when `EOAT_ATLAS_DATA_BACKEND=mysql_api`. Existing QThread loading keeps network/cache work off the PySide6 event loop. The Library index's independent rebuild path also uses the gateway in this mode, closing the hidden Excel-read path.

For server freshness semantics, see [Data Freshness and Revision Truth](data_freshness.md). The status-only polling worker is separate from cache synchronization: an unchanged revision never triggers `SyncCoordinator.standard_refresh()` or rebuilds a page bundle.

`core.annotations.AnnotationService` returns an API-backed compatibility facade in `mysql_api` mode, so the permanent SQLite annotation database cannot receive writes. Audit save similarly calls the gateway and skips Excel, Robot Info, and legacy queue writes. EOAT Profile page conversion remains explicitly deferred.
