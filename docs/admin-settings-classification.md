# Administrator Settings classification

The browser Settings page retains personal appearance and accessibility preferences. They are stored per browser and are not Administrator controls: theme, accent appearance, reduced motion, and high-contrast/accessibility choices.

The legacy desktop-only settings (`AtlasSettings`) remain desktop-client preferences or workflow defaults. They are not silently promoted to web-wide policy because their persistence is client-local and their behavior is not implemented by the web server.

The API and deployment configuration remains environment-controlled: database connection details, corporate-authentication endpoints and credentials, media roots/mirror paths, cookie/TLS configuration, write gates, and release/deployment metadata. None is exposed as a browser-editable setting.

The governed, system-wide browser setting introduced in this release is `app.default_catalog_page_size`. It controls the default number of Library results returned for Machine, Tool, and EOAT catalog requests only when a browser has not explicitly selected a page size. It is server-persisted, validated to the API range (1–250), requires an Administrator reason, uses row-version concurrency, and writes a `SETTINGS_CHANGE` audit event.
