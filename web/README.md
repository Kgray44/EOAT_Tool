# EOAT Atlas Web Foundation — Phase 2

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

## Routes and read-only scope

Registered routes are `/`, `/search`, `/library`, `/eoats/:identifier`, `/machines/:number`, `/tools/:identifier`, and `/fit-check`. The canonical QR-ready EOAT route is `https://<approved-eoat-atlas-host>/eoats/<immutable-identifier>`; the hostname is deliberately not compiled into this client.

Phase 2 implements read-only EOAT, machine, and tool profiles; unified Library discovery; local-only recent items; browser-safe Fit Check; and QR label previews. Every profile requests its identity before independent relationships, media, and history sections, so secondary failures do not hide the confirmed record.

The legacy document/photo API endpoints retain desktop-oriented storage-path metadata for backward compatibility. The browser does **not** call them. It calls entity-specific `web-documents` and `web-photos` metadata routes, then UUID-only browser content routes. `EOAT_WEB_CONTENT_ROOTS` is a server-only, approved-root allowlist; a missing or invalid configuration fails closed. The browser never receives a root, UNC path, or filesystem path.

Phase 2 remains read-only: it does not implement edits, PM workflows, uploads, browser authentication, SAML/LDAP, session cookies, CSRF, deployment, database changes, PWA/offline behavior, or service workers. Its dedicated web Fit Check route enforces non-persistence server-side. Playwright tests use intercepted, controlled API responses and do not touch production data.

## Security and production architecture

No `X-EOAT-Device-Token`, MySQL credential, or API secret belongs in browser code, `VITE_*` variables, source maps, tests, or committed config. This client does not send the trusted desktop token and does not enable writes. CORS and API authorization are unchanged.

The planned production boundary is:

```text
Browser → HTTPS → NGINX → static frontend → same-origin /api reverse proxy
        → FastAPI bound to localhost → MySQL bound to localhost
```

NGINX, not browser JavaScript, will eventually add any internal service-to-service credential required for anonymous read-only access. No NGINX configuration or live server is deployed in Phase 2. The QR-ready profile routes, discovery, and non-persisting Fit Check remain read-only; authenticated writes require a separately designed SAML or LDAP session boundary.

On this Windows UNC worktree, Vite/Vitest worker URL handling can fail before source evaluation. Copy the exact `web/` source to a disposable local runtime mirror (excluding `node_modules`, build output, reports, and test artifacts), run `npm ci`, and execute frontend validation there. That mirror is validation-only and must never be committed or treated as a source of truth. Install Playwright Chromium with `npx playwright install chromium` before `npm run test:e2e`.
