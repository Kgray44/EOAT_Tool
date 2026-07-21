# EOAT Atlas Web Phase 2: Read-Only Discovery

## Scope

Phase 2 completes the read-only browser routes for EOATs, machines, tools, Library discovery, Fit Check, and QR labels. The React client continues to consume the existing FastAPI/MySQL service through same-origin `/api/v1` paths. It introduces no browser-held credential, database access, persistent browser write, or parallel compatibility model.

## Routes and data flow

`/eoats/:identifier`, `/machines/:number`, and `/tools/:identifier` load a typed profile first, then independently load relationships, media metadata, and history. `/library` keeps search, category filter, and page in the URL. `/search` redirects to Library so discovery has one implementation. `/fit-check` invokes only `POST /api/v1/web-fit-checks/evaluate`.

The browser-safe Fit Check request has no `persist` field. The FastAPI route constructs `FitCheckRequest(..., persist=False)` against a runtime session and has no call path to `persist_fit_check`; no audit, history, recent Fit Check, or assignment row can be written by this browser route.

## Content-delivery trust boundary

Browser metadata remains separate from desktop metadata. Browser content routes look up a document by UUID, resolve the stored database path only server-side, and require `EOAT_WEB_CONTENT_ROOTS` to contain a valid approved root. Missing or invalid configuration fails closed. Resolved files must remain under an approved root after normalization and symlink resolution. Relative, encoded traversal, mixed traversal, missing, and escaped paths are rejected without returning a root or filesystem path.

`/api/v1/web-documents/{uuid}/content` and `/api/v1/web-photos/{uuid}/content` use streaming `FileResponse`, `nosniff`, a safe filename, and inline content only for JPEG, PNG, GIF, WebP, and PDF. Other content—including HTML and SVG—is forced to download as `application/octet-stream`. `/api/v1/web-photos/{uuid}/thumbnail` generates a bounded JPEG thumbnail only for accepted raster images. No upload, replacement, deletion, or metadata edit exists.

## QR and responsive behavior

QR labels encode only `window.location.origin` plus a percent-encoded immutable entity path. They include the payload as accessible text and disable printing for localhost, loopback, and `.local` origins. Print CSS suppresses application navigation and profile controls. The layouts use responsive card grids and are covered at 360, 390, 768, and 1280 pixels.

## Local-only browser preferences

Recently viewed items are stored locally with only entity category, identifier, label, and timestamp. They are capped, deduplicated, removable, never synchronized, and hidden while a search query has results.

## Validation and deferred work

The Phase 2 focused suite covers content policy, no-path metadata, machine/tool routes, Library behavior, QR payloads, browser-safe Fit Check, and browser smoke paths. Validation from a UNC checkout uses the existing disposable local runtime mirror; it is not a source of truth.

The production dependency audit reports no vulnerabilities. The full audit reports one high-severity development-only `js-yaml@4.2.0` advisory, affecting `js-yaml` and its `@redocly/openapi-core` parent in the OpenAPI type-generator chain (two npm-audit package entries). It is not shipped in the production Vite bundle. Phase 2 leaves that generator-chain update to a controlled dependency-maintenance change rather than applying a blanket audit fix.

Phase 3 candidates: authenticated writes after enterprise authentication is production-ready, controlled document/photo management, richer compatibility alternatives, QR printing integration, deployment behind NGINX, and production service operations. SAML, LDAP, browser sessions, CSRF, uploads, edits, PWA/offline behavior, deployment, DNS/TLS, and data mutation remain out of scope.
