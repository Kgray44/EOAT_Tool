# EOAT Atlas Web Phase 1: QR profile vertical slice

## Data flow

`/eoats/:identifier` is the canonical future QR destination. React Router safely decodes a single path segment, the typed client percent-encodes it again for every relative FastAPI call, and TanStack Query independently loads:

- `/api/v1/eoats/{identifier}`
- `/api/v1/eoats/{identifier}/current-location`
- `/api/v1/eoats/{identifier}/relationships`
- `/api/v1/eoats/{identifier}/history?page_size=12`
- `/api/v1/eoats/{identifier}/web-documents`
- `/api/v1/eoats/{identifier}/web-photos`

The existing FastAPI service and MySQL database remain authoritative. The browser never accesses MySQL and makes no write request.

## Truth and security

Identity and current location remain visible at the top of the mobile layout. Unknown, unavailable, and conflicting locations have explicit text labels. A secondary endpoint failure stays confined to that section and offers a safe GET retry.

The new `web-documents` and `web-photos` metadata endpoints are read-only adapters over existing metadata. They intentionally omit `storage_path`, UNC paths, and any content URL. Browser content delivery is deferred until a server-side approved-root resolver and safe MIME/disposition policy are separately accepted.

No browser code, fixture, environment example, or request contains `X-EOAT-Device-Token`, database credentials, or a service secret. The production same-origin NGINX/FastAPI boundary remains unchanged.

## Validation and deferred work

Vitest covers encoded URLs, successful profile load, conflict truth, secondary failures, retry, not-found, empty metadata, relationship links, and read-only requests. Playwright uses a controlled intercepted API for direct navigation, refresh, back navigation, not-found, token absence, GET-only behavior, and mobile overflow.

Phase 2 candidates: browser-safe photo thumbnails/document downloads with approved storage roots; machine and tool profile slices; search and library; QR generation; and authenticated browser writes after SAML or LDAP readiness.
