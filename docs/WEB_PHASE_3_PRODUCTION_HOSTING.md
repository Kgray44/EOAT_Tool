# EOAT Atlas Web Phase 3: Production Read-Only Hosting

## Reconciled basis and scope

Phase 3 reconciles the accepted transactional deployment implementation from
`development/mysql-api-consolidated` through `a4b6a32cd` with the Phase 2 web
branch.  The deployment archive now has a `web-static/` subtree built from the
exact release commit.  It contains only the Vite output, a SHA-256 subtree
manifest, and no Node runtime, `node_modules`, source maps, browser secrets,
or development files.

The browser remains read-only. NGINX permits GET/HEAD for `/api/` and permits
POST only for the exact `/api/v1/web-fit-checks/evaluate` route. FastAPI still
forces that request to `persist=False`; every other browser mutation is
rejected before the private upstream is reached.

## Release and installation model

`deployment.release_manager` first runs pinned `npm ci`, OpenAPI generation
drift detection, formatting, linting, TypeScript, unit tests, Playwright, and
a Vite production build in a temporary extraction of the selected commit. It
then adds `web-static/` and `web-static.manifest.json` to the deterministic
tarball. Archive validation rejects traversal, duplicate entries, forbidden
secret files, and hash/identity mismatches.

The established privileged helper stages the verified archive below
`/opt/eoat-atlas/releases`, retains `current` and `previous` symlinks, and
uses its transaction receipt/rollback model. The included runtime templates
are installed only through the existing privileged deployment process after a
human administrator has provisioned the protected server files.

## Host boundary

NGINX serves `/opt/eoat-atlas/current/web-static`, falls back to `index.html`
only for non-API routes, and proxies `/api/` to `127.0.0.1:8765`. The template
removes client token input by replacing `X-EOAT-Device-Token` on the upstream
request with `$eoat_atlas_upstream_token`; that variable comes solely from
`/etc/eoat-atlas/nginx-upstream-token.conf`, a root-owned file outside Git.
It is never sent in a browser response.

`deployment/runtime/systemd/eoat-atlas.service` runs FastAPI as `eoat-atlas`,
binds it to loopback, reads `/etc/eoat-atlas/runtime.env`, uses a restrictive
umask and systemd hardening, and keeps write access limited to designated
runtime/log directories. The runtime environment must set
`EOAT_API_WRITES_ENABLED=false`.

## Media mapping

`EOAT_WEB_CONTENT_ROOTS` names approved Debian mount roots. If database paths
are Windows/UNC paths, `EOAT_WEB_CONTENT_PATH_MAPPINGS` is a server-only JSON
list of exact `source_prefix` to `target_root` mappings. Prefixes are
normalized with Windows case semantics; partial-prefix tricks, traversal,
unmapped shares, missing roots, and symlink escapes fail closed. Browser
responses never reveal source prefixes, mounted roots, or resolved paths.

An SMB mount remains an IT operation: use a protected credentials file and a
read-only `ro,nosuid,nodev,noexec` mount where compatible. Without approved
mount details, leave the mapping empty; metadata remains visible and media is
truthfully unavailable.

## DNS, TLS, and deployment gate

No approved production DNS hostname, certificate/key path, plant/Wi-Fi source
ranges, firewall authorization, or server configuration was supplied with
this repository task. Therefore production activation is **NO-GO**. Required
IT inputs are an internal DNS name, trusted TLS chain, port-443 firewall scope,
phone/tablet reachability, protected NGINX token file, protected runtime
environment, approved media mount, known SSH host key, current-release and
rollback evidence.

After those inputs exist, validate `nginx -t`, `systemd-analyze verify`, the
private health/version/schema endpoints, direct SPA refreshes, media behavior,
security headers, API method restrictions, and non-persisting Fit Check before
activation. HSTS is deliberately not enabled until valid HTTPS is confirmed.

## Deferred Phase 4

Enterprise SAML/LDAP, browser sessions, CSRF, role mapping, controlled writes,
uploads, PM completion, issue reporting, notes, and audit submissions remain
Phase 4 work.
