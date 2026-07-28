# EOAT Atlas Unified Release Train — Phase 3A Implementation

## Scope and safety boundary

Phase 3A implements coordinated **disposable** API and static-web activation
for a signed, published release set. It does not contact a production host or
database and does not operate NGINX, systemd, sudo policy, release channels,
tags, or GitHub Releases. EOAT Atlas remains product version `0.24.0`.

## Trusted input and durable transactions

`VerifiedDeploymentInput.from_complete_trusted_inventory` accepts only a
`COMPLETE_TRUSTED` signed inventory item with complete server/web asset
identities. It rejects legacy, incomplete, unsigned, revoked, or conflicting
same-version input. `DisposableCoordinatedDeployment` persists schema-2
`transaction` receipts through `ReceiptStore`; malformed receipts are
quarantined, future schemas are rejected, and completed receipts are immutable.

The typed sequence is `PREFLIGHT_COMPLETE`, `INPUT_VERIFIED`, immutable server
and web staging, `STAGED_COMPLETE`, activation/health gates, and either
`ACTIVE_CONFIRMED` or truthful rollback. State history, old/new pointers,
artifact hashes, API/web identity, HTTP evidence, desktop evidence, recovery
state, and bounded diagnostics are retained. Database rollback is never
claimed by an application-pointer rollback.

## Artifact and runtime acceptance

Staging verifies ZIP path safety, hashes, embedded identity, server contract
and target-schema metadata, web file manifests, `index.html`, and the absence
of mutable state, secrets, `.env`, caches, `node_modules`, and source maps.
The disposable runtime serves staged web bytes through a loopback HTTP server
and verifies `release_identity.json`, `index.html` cache headers, and API/web
identity equality before activation can be confirmed.

The production build path now emits `release_identity.json` from the exact
generated candidate metadata. Browser startup compares it to
`/api/v1/release-status`, performs at most one session-guarded cache-busting
reload, and otherwise blocks normal UI behind an update-required screen.
Hashed assets remain immutable; index is revalidated and release identity is
`no-store`.

## Runtime compatibility and recovery

All release-aware API routes use `runtime_release_identity()`. It safely
exposes product/release/build/candidate/source/release-set identity plus API
contract, schema, minimum supported clients, and transaction ID. Once release
parity is enabled, all ordinary `/api/v1` reads and writes require full client
identity; health, release status, version, and data-status remain available for
repair. Mismatch returns `CLIENT_RELEASE_MISMATCH` with a restart-through-
Bootstrap action.

`drift()` reports `MATCH`, `MISMATCH`, `NOT_AVAILABLE`, `UNKNOWN`, or
`RECOVERY_REQUIRED`; unknown is never a match. The MySQL 8.4 rehearsal uses a
caller-owned disposable connection, captures a bounded logical backup before a
required migration, verifies the target Alembic revision and `data_state`
singleton, and leaves failed migration recovery explicit.

## Operator surfaces and CI

The shared CLI exposes `coordinated-deploy verify-input`, `stage`, `activate`,
and `drift-scan`; stage and activation require exact typed confirmation and an
explicit non-production root. The existing PySide6 console has a Coordinated
Activation tab using the same service via its worker queue.

The Phase 3A workflow has independent input, state, staging, activation,
rollback, API parity, Playwright, Windows desktop/Bootstrap, drift, MySQL 8.4,
migration, CLI/console, end-to-end, compatibility, safety, version, and
documentation gates. Diagnostic artifacts are retained for browser failures.

## Remaining Phase 3B work

Phase 3B is limited to separately authorized non-disposable promotion,
operational change control, and production activation. It must reverify the
same sealed release-set and never bypass the Phase 3A receipts or recovery
gates.

## CI acceptance evidence

The Phase 3A implementation commit `1fa446f61516bfbb21c3c9ff5126a77773f43133`
was accepted by GitHub Actions workflow **Unified Release Train Phase 3A**, run
[`30361496422`](https://github.com/Kgray44/EOAT_Tool/actions/runs/30361496422).
All required jobs concluded `success`: deployment-input-verification,
transaction-state-machine, api-staging, web-staging, coordinated-activation,
rollback-and-recovery, runtime-release-status,
api-compatibility-enforcement, web-parity-playwright,
desktop-parity-windows, drift-scanner, disposable-mysql-8-4,
migration-and-recovery, cli-console-smoke, end-to-end-disposable-deployment,
receipt-compatibility, repository-safety, version-governance, and
documentation-command-validation.

The run exercised the real MySQL 8.4 service and a Chromium Playwright
installation, and the Windows job ran the Bootstrap startup-chain and API
parity contract tests. The only intentional non-run in local development is
the disposable MySQL integration test, which requires CI's ephemeral MySQL
8.4 service; it was not skipped in the accepted workflow. No production
credential, production signing material, production target, tag, release, or
manifest channel was used.
