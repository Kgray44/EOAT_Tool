# Phase 4B Schema-2 Production Publisher

The production publisher accepts only a sealed schema-version-2 candidate.
It independently reopens the canonical manifest, detached Ed25519 signature,
repository-governed trust policy, candidate commit/tree, and every retained
component byte before any remote mutation is attempted.

## Immutable asset inventory

The GitHub Release is not a three-file server release.  The signed inventory
contains the server archive, external manifest and checksum; web package and
file manifest; desktop, Launcher, and Bootstrap packages; their package and
update manifests; packaged smoke receipts; source bundle and verification
evidence; release notes; release-set manifest and signature; and the governed
Bootstrap installer package, installer configuration, and production public
trust policy.  Installer and trust material are retained as explicit,
candidate-relative Bootstrap supporting evidence and are revalidated during
attachment, sealing, and publication.

The Windows attachment exporter builds the installer only after the desktop,
Launcher, and Bootstrap packages are present.  It declares every supporting
asset with a relative locator, exact size, and SHA-256.  The attachment service
copies those bytes atomically into immutable candidate storage; it never
publishes from a CI download path.

## Transaction and trust boundary

`publish begin-production <candidate> --confirm "PUBLISH EOAT ATLAS <version> TO Kgray44/EOAT_Tool"`
derives its confirmation from the sealed candidate identity.  The production
adapter is restricted to `Kgray44/EOAT_Tool`; it requires accepted `main` for a
detached release worktree and never uses a test signing provider.

The transaction creates the annotated tag locally, verifies/pushes the exact
tag, creates a draft GitHub Release, uploads only missing matching sealed
assets, downloads each remote asset to verify its SHA-256 and size, uploads a
redacted public publication receipt last, then publishes the draft.  Existing
assets are accepted only when their bytes match exactly; no clobber, deletion,
or force operation is available.  The local schema-2 receipt retains state
history and is immutable after `PUBLICATION_COMPLETE`; the uploaded receipt
contains no local receipt path or private signing material.

`publish inspect-assets <publication>` performs the same remote download and
hash verification and reports `COMPLETE_TRUSTED` only when the full sealed
inventory and final publication receipt match.

Production preflight, staging, activation, migration, service changes, and
channel promotion remain outside this publisher and require their separately
authorized Phase 4C workflow.
