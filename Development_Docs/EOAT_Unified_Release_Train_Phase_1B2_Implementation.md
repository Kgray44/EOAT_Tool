# EOAT Atlas Unified Release Train — Phase 1B-2 implementation

## Scope

Phase 1B-2 turns the unsigned schema-2 candidate into an artifact-collection
transaction. It does not seal a release set, publish assets, activate a target,
or use production credentials.

## Artifact contract

Candidate preparation builds core bytes in an isolated source clone. The core
verification operation reopens the immutable server archive and its external
manifest/checksum, validates the actual web ZIP and static file manifest,
copies the governed 0.24.0 candidate note, and independently verifies the
source Git bundle in a disposable shared-object repository. The receipt stores
candidate-relative locators and hashes; absolute workstation paths are not part
of release identity.

The Windows export script builds `EOAT_Atlas.spec` and
`EOAT_Atlas_Launcher.spec`, packages the real outputs into ZIPs, writes file
manifests and update manifests from those exact packages, runs the packaged
entry points with their smoke modes, and emits an attachment directory. The
attachment includes only public identity, hashes, bounded diagnostics, and
workflow provenance; it never contains production credentials or signing keys.

## Attachment trust boundary

`candidate attach-platform-artifacts` accepts only an unsigned
`PLATFORM_ARTIFACTS_PENDING` schema-2 receipt. It validates all four expected
Windows component kinds, product/release/build/candidate identity, source
commit/tree, safe relative paths, hashes, sizes, metadata, package manifests,
smoke receipts, and update-manifest package binding. Bytes are copied through
candidate-local staging and the candidate receipt is updated only after all
files validate. An identical retry is safe; conflicting bytes are blocked.

## Operator and CI use

The command-line and existing PySide6 console expose core validation, attachment
inspection/import, attached-artifact verification, component inventory, dynamic
missing components, blocking reasons, and the next safe action. The dedicated
workflow builds core artifacts, runs real Windows desktop and launcher package
smokes, uploads a self-contained attachment, then exercises the real attachment
service in a dependent job. Repository safety and the existing single governed
version bump check remain required.

## Deferred Phase 1B-3 work

Phase 1B-3 will perform final component revalidation, construct the canonical
payload, write and hash the outer manifest and detached signature, use an
externally supplied non-production signing key, and then make a complete
release set eligible for publication verification. Bootstrap implementation,
stable promotion, publication, deployment, and production activation remain
outside this phase.
