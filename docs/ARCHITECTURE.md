# Architecture

The active desktop surface is `app.atlas.minimalist.MinimalistAtlasWindow`, launched through `run_atlas.py`. Home,
Library, Fit Check, Packet Builder, and locked Settings are constructed in one PySide6 process.

The desktop talks to `server.eoat_api.app:app`. MySQL is authoritative for assets, compatibility, installations,
documents, history, identity, and release registration. Runtime and migration credentials use separate bounded
SQLAlchemy engines. Engines live for the API process and are disposed during shutdown.

The API cache in `core/data_gateway` is disposable SQLite data for offline reads. Its schema is distinct from the
globalization SQLite schema. Cached document links are entity-scoped. Offline setup packets are blocked when exact,
current compatibility evidence cannot be revalidated.

`legacy` mode is an explicit migration/comparison boundary. There is no automatic fallback from MySQL/API failures.
