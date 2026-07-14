# Development bootstrap

`run_atlas.py` resolves the repository from its own file location and verifies `EOAT_ATLAS_CANONICAL_DEVELOPMENT_ROOT` before importing application code. It loads `config/development.json`, verifies the local MySQL 8.4.9 service and Alembic revision `20260714_0004`, verifies or starts API 1.3.0, and then launches the minimalist PySide6 application with `mysql_api` as the backend.

Service process state and the disposable API cache live below `%LOCALAPPDATA%\EOAT Atlas Development`. They are not repository content. The desktop process uses the Data Gateway and HTTP API client; direct MySQL access is confined to the API process.

Startup asserts that the application window, Data Gateway, API client, and version-provider modules resolve below the canonical repository root. Legacy mode is available only when explicitly requested and is not a fallback from `mysql_api`.
