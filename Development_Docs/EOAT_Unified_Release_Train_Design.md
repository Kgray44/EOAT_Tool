# EOAT Atlas Unified Release Train design record

## Scope and immutable base

- Repository: `Kgray44/EOAT_Tool`
- Unified-release branch: `codex/unified-release-train`
- Convergence base: `170d9fb3d8f2ab2dabe6eb86ee7898ccbbd3a6ab`
- Governed product-version transition: one final minor increment from `0.23.0`

This branch extends the convergence service.  It does not replace its
candidate, receipt, publication, deployment, migration, helper, CLI, or
operator-console safety boundaries.  No production endpoint, MySQL instance,
host configuration, tag, or GitHub Release is a test target for this work.

## Inventory findings before implementation

`app/atlas/version.json` is the sole tracked product-version authority.
`release_defaults.json` carries component and compatibility defaults only;
`release_history.json` is the governed release ledger.  Existing API contract,
database schema, launcher, and installer versions are separate component
revisions and must not be presented as product releases.

The existing convergence candidate is a deterministic server archive plus an
optional web static bundle.  Its schema-1 receipts use one artifact path and
hash, so readers must retain a legacy single-artifact path while schema-2
receipts add an explicit release-set artifact map.

There are currently two launcher implementations. `launcher/` provides the
windowed diagnostics, repair, discovery, process protection, and update check;
`release_tools/launcher.py` performs the actual local package transaction.
The packaged launcher currently enters the latter directly, which means the
diagnostic launcher only warns a user to obtain an update.  The release train
will converge them behind one shared update service and preserve both sets of
capabilities.

The API already has health, version, and server-status responses based on
canonical release metadata.  The train will make `release-status` the
authoritative safe contract, add client compatibility enforcement, and make
web metadata use the same product identity.  Existing server/web deployment
and privileged-helper boundaries remain narrow and read-only unless a caller
is already explicitly activating an approved plan.

## Product identity and signed release sets

Every artifact in one product release has one `ProductReleaseIdentity`:

- product version, release ID, build ID, candidate ID, release channel
- exact source commit and tree, source branch, and build timestamp
- deterministic release-set manifest digest after artifact collection

Schema-2 release sets explicitly classify the server, web, desktop,
desktop-update-manifest, launcher, and bootstrap components as built, reused
from an exact immutable release/build, or not applicable.  No component can be
silently omitted.  Independent schema, API-contract, launcher, bootstrap,
installer, and receipt revisions remain component metadata.

Release-set bytes use sorted-key, compact UTF-8 JSON.  They are signed using
Ed25519 through the maintained `cryptography` library.  The signature envelope
contains an algorithm and key ID; launchers trust configured public keys and
fail closed for malformed, unknown, or revoked keys.  Private material is
external to Git; production-channel publication must require externally
configured signing material.

## Intended transaction order

Candidate preparation builds all applicable artifacts from one isolated,
committed candidate tree and retains a Git recovery bundle.  Immutable artifact
publication precedes API/web staging and coordinated activation.  Signed stable
desktop promotion is a separate, explicit action after API/web live acceptance
proves the same identity.  A failed activation never promotes the client
channel.

The bootstrap owns only launcher self-update and pointer fallback.  The active
launcher owns desktop update download, archive/path safety, embedded identity
and file-manifest verification, machine-readable candidate smoke receipt,
atomic activation, startup health confirmation, last-known-good retention, and
offline policy.  Offline operation is explicitly local-only and is blocked for
cached revoked or below-minimum clients.

## Rollback and compatibility semantics

Application pointer rollback restores a retained confirmed-good application;
it never claims database rollback.  Server/web activation will switch both
identities as one transaction or restore both prior pointers.  Mixed product
identities, unknown drift, unsafe archives, invalid signatures, and incomplete
release sets block the relevant transition.  Browser HTML/release metadata will
not be cache-immutable; content-hashed assets can be immutable.  A web/API
mismatch allows one controlled reload and otherwise blocks ordinary operation.

## Continuation gap inventory (2026-07-27)

The initial foundation is deliberately not a completed release train.  The
convergence service still persists a schema-1, single-server-artifact candidate
record; publication, release inventory, deployment planning, and the console
therefore cannot yet require the signed release-set digest.  Candidate
preparation also does not yet construct desktop, launcher, or bootstrap
artifacts from one candidate commit.

There is no bootstrap executable, immutable launcher-version store, launcher
self-update policy, shortcut migration, or launcher smoke receipt.  The
launcher has a signed desktop transaction when configured, but offline policy,
post-launch health rollback, retention, and installer-provisioned policy remain
unfinished.

`/api/v1/release-status` now exposes safe identity facts, but server/web
activation does not yet verify a shared release set or switch both targets as
one rollbackable transaction.  The frontend does not yet embed full identity or
block stale browser assets after one controlled reload.  The desktop does not
yet enforce the release-status contract before enabling connected operation.

Candidate/canary/stable signed promotion, a drift scanner, console actions,
disposable MySQL coverage, built bootstrap/launcher tests, a black-box release
train, the required CI jobs, and the final completion report remain open.  No
open item may be reported as production-ready without its corresponding real
test evidence.

## Phase 1B-2 artifact collection boundary

An unsigned schema-2 candidate now owns an immutable candidate-relative
directory: `source/`, `core/server/`, `core/web/`, `core/release-notes/`,
`platform/windows/`, `receipts/`, and a reserved `sealing/` boundary. Core
construction retains the actual server archive, checksum and external manifest;
an immutable deployable web ZIP rather than only its static manifest; a
version-specific governed release-note artifact; and a Git bundle verified by
`git bundle verify`, isolated fetch, exact commit/tree resolution, and base
ancestry. All locators in the working release set are candidate-relative.

Windows builders receive the exact candidate identity through controlled
environment variables, build the governed PyInstaller specifications, produce
package manifests, run the packaged executable entry points, and write bounded
machine-readable smoke receipts. A self-contained attachment declares the four
Windows component kinds, package bytes, supporting metadata, package manifests,
smoke receipts, update manifests, and GitHub workflow provenance. The service
does not trust provenance alone: attachment verifies exact candidate/product/
release/build/commit/tree identity, hashes and sizes, safe paths, packaged
metadata, smoke evidence, and update-manifest package binding before staging
and atomically promoting the bytes.

Attachment is idempotent only when the immutable component hash already agrees;
different bytes at an occupied component locator block. After attachment the
only required pending items are `release_set_manifest` and
`release_set_signature`; bootstrap and its update manifest remain
`NOT_APPLICABLE` because Unified Release Train Phase 2 owns bootstrap. Phase
1B-3 alone serializes, signs, and seals the final release-set envelope.
