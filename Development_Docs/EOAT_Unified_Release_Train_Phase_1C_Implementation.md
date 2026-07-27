# EOAT Atlas Unified Release Train — Phase 1C implementation record

## Scope

Phase 1C adds non-production immutable publication, signed-release inventory,
and read-only deployment-plan integration on `codex/unified-release-train`.
The governed EOAT Atlas product version remains **0.24.0**. No version bump or
release-history operation is part of this phase.

## Publication contract

`publication_readiness` independently reopens the schema-2 candidate receipt,
outer manifest and detached signature, trusted-key policy, canonical digest,
component inventory, and retained candidate-relative bytes. It rejects
unsealed/legacy candidates, unknown or revoked keys, pending or invalid
components, missing outer evidence, recovery-required records, and mixed
identity.

`DisposablePublicationBackend` uses a real disposable Git repository and bare
remote for candidate promotion and immutable annotated tags. Its filesystem
registry models a release record plus immutable asset directory and hash index.
The transaction is durable and resumable through preflight, sealed-candidate
verification, commit/tag/remote promotion, release creation, complete asset
upload, independent verification, receipt attachment last, and completion.
Matching retries are accepted; conflicting refs, records, or assets block with
no force, clobber, replacement, or deletion.

The complete published inventory includes server archive plus manifest/checksum,
web archive plus file manifest, desktop and launcher packages/update manifests/
smoke receipts and package metadata where present, source recovery bundle,
release notes, release-set manifest, detached signature, and publication
receipt. Absolute local paths and signing material are never published.

## Inventory and planning

The disposable inventory verifies the detached Ed25519 signature and every
indexed immutable asset before calling a release `COMPLETE_TRUSTED`. Incomplete,
untrusted, revoked, conflicting, legacy, unknown, and recovery-required states
are not deployable. The Phase 1C plan consumes only a complete trusted
publication and binds product/release/build/source/tree/digest/key identity,
server/web shared release-set identity, signed target schema, and read-only
target helper facts. Migration state remains explicit; planning has no staging
or activation side effect.

## Operator interfaces and CI

The unified CLI adds sealed publication readiness, explicit
`PUBLISH <candidate-id>` disposable start/resume, disposable inventory, and
trusted-publication plan commands. The existing console exposes the same shared
service operations and leaves production publication unavailable.

`.github/workflows/unified-release-train-phase-1c.yml` runs publication
eligibility, real disposable Git/filesystem publication, asset verification,
inventory, deployment-plan, CLI/console, receipt compatibility, end-to-end,
safety, version-governance, and documentation-command gates without GitHub
publication credentials.

## Remaining work

Phase 2 owns bootstrap implementation. Later authorized phases own real
GitHub publication, candidate/canary/stable promotion, production deployment,
atomic API/web activation, and any database migration or recovery execution.
