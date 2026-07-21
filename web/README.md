# EOAT Atlas Web Foundation — Phase 1

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

Commands: `npm run format:check`, `npm run lint`, `npm run typecheck`, `npm test`, `npm run test:e2e`, `npm run build`, `npm run api:generate`, and `npm run api:check`.

## Contract and API client

`npm run api:generate` runs `scripts/export_openapi_schema.py`, which imports the real FastAPI `app`, serializes `app.openapi()` with stable key ordering, then runs `openapi-typescript`. Generated output lives in `src/api/generated/` and is never hand edited. `api:check` regenerates it and uses Git diff to detect drift.

All browser requests go through `src/api/client.ts`, use relative same-origin `/api/v1/...` URLs, have a timeout, and normalize authorization, validation, not-found, unavailable, timeout, and malformed-response cases. Page components do not call `fetch` directly. Missing values are rendered as `Unknown / unavailable`, never guessed.

## Routes and Phase 0 boundary

Registered routes are `/`, `/search`, `/library`, `/eoats/:identifier`, `/machines/:number`, `/tools/:identifier`, and `/fit-check`. The canonical QR-ready EOAT route is `https://<approved-eoat-atlas-host>/eoats/<immutable-identifier>`; the hostname is deliberately not compiled into this client.

Phase 1 implements `/eoats/:identifier` as a read-only mobile-ready profile. It requests profile, current location, relationships, browser-safe document metadata, browser-safe photo metadata, and recent history independently. A failed secondary section does not hide a successfully loaded EOAT identity. Machine and tool links retain their Phase 0 destinations until their own vertical slices are built.

The legacy document/photo API endpoints retain desktop-oriented storage-path metadata for backward compatibility. The browser does **not** call them. It calls `/api/v1/eoats/{identifier}/web-documents` and `/web-photos`, which exclude server and UNC paths and explicitly report that byte delivery is not available through the web interface. Safe server-side content delivery, approved storage-root enforcement, thumbnails, and downloads are Phase 2 candidates.

Phase 1 does not implement search results, library workflows, machine/tool profiles, fit checks, QR generation/printing, document or photo byte delivery, edits, PM workflows, uploads, browser authentication, SAML/LDAP, session cookies, CSRF, deployment, or database changes. Playwright tests use intercepted, controlled API responses and do not touch production data.

## Security and production architecture

No `X-EOAT-Device-Token`, MySQL credential, or API secret belongs in browser code, `VITE_*` variables, source maps, tests, or committed config. This client does not send the trusted desktop token and does not enable writes. CORS and API authorization are unchanged.

The planned production boundary is:

```text
Browser → HTTPS → NGINX → static frontend → same-origin /api reverse proxy
        → FastAPI bound to localhost → MySQL bound to localhost
```

NGINX—not browser JavaScript—will eventually add any internal service-to-service credential required for anonymous read-only access. No NGINX configuration or live server is deployed in Phase 1. Phase 1 delivers the QR deep link to `/eoats/:identifier` and the first authoritative EOAT profile vertical slice; later phases can add authenticated writes only after SAML or LDAP is production-ready.

On this Windows UNC worktree, Vite/Vitest worker URL handling can fail before source evaluation. Copy the exact `web/` source to a disposable local runtime mirror (excluding `node_modules`, build output, reports, and test artifacts), run `npm ci`, and execute frontend validation there. That mirror is validation-only and must never be committed or treated as a source of truth. Install Playwright Chromium with `npx playwright install chromium` before `npm run test:e2e`.
