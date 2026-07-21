# EOAT Atlas Web — Phase 0

This directory is the read-only React/Vite foundation for a future EOAT Atlas web client. It consumes the existing FastAPI contract; it is not a second backend, database, data model, or production Node service.

## Requirements and local development

Use Node.js 22.13 through 24 (`.nvmrc` records the supported version) and npm. Install the Python dependencies required to import the FastAPI app, then:

```powershell
python -m pip install -r ..\requirements.txt
npm ci
npm run api:check
npm run dev
```

The development server proxies `/api` to `http://127.0.0.1:8765` by default. Set `EOAT_API_PROXY_TARGET` in a local ignored `.env` file only when the API runs elsewhere. It is a development-server setting, not a `VITE_*` browser variable, and must never contain a credential.

Commands: `npm run format:check`, `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`, `npm run api:generate`, and `npm run api:check`.

## Contract and API client

`npm run api:generate` runs `scripts/export_openapi_schema.py`, which imports the real FastAPI `app`, serializes `app.openapi()` with stable key ordering, then runs `openapi-typescript`. Generated output lives in `src/api/generated/` and is never hand edited. `api:check` regenerates it and uses Git diff to detect drift.

All browser requests go through `src/api/client.ts`, use relative same-origin `/api/v1/...` URLs, have a timeout, and normalize authorization, validation, not-found, unavailable, timeout, and malformed-response cases. Page components do not call `fetch` directly. Missing values are rendered as `Unknown / unavailable`, never guessed.

## Routes and Phase 0 boundary

Registered routes are `/`, `/search`, `/library`, `/eoats/:identifier`, `/machines/:number`, `/tools/:identifier`, and `/fit-check`. The landing route shows actual health information only after a real API response. All other routes are intentionally honest “later phase” views so bookmarks and refreshes work without fake records.

Phase 0 does not implement entity profiles, search results, library workflows, fit checks, QR generation/printing, documents/photos, edits, PM workflows, uploads, browser authentication, SAML/LDAP, session cookies, CSRF, deployment, or database changes. A minimal Playwright smoke test is deferred to Phase 1 to avoid adding an unintegrated browser-server harness.

## Security and production architecture

No `X-EOAT-Device-Token`, MySQL credential, or API secret belongs in browser code, `VITE_*` variables, source maps, tests, or committed config. This client does not send the trusted desktop token and does not enable writes. CORS and API authorization are unchanged.

The planned production boundary is:

```text
Browser → HTTPS → NGINX → static frontend → same-origin /api reverse proxy
        → FastAPI bound to localhost → MySQL bound to localhost
```

NGINX—not browser JavaScript—will eventually add any internal service-to-service credential required for anonymous read-only access. No NGINX configuration or live server is deployed in Phase 0. Phase 1 should deliver a QR deep link to `/eoats/:identifier` plus the first authoritative EOAT profile vertical slice; later phases can add authenticated writes only after SAML or LDAP is production-ready.
