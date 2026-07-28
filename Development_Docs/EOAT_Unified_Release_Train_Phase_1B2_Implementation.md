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

## CI closure evidence

Phase 1B-2 CI closure completed on commit `84dff6edd926abb69dc39acb201c6777f14b0ea7`
in GitHub Actions run `30300291400` (Unified Release Train Phase 1B-2). The
required jobs concluded successfully: `documentation-command-validation`,
`model-receipt-regression`, `core-artifacts`, `windows-packaged-artifacts`, and
`attachment-verification`.

The Windows attachment artifact was identity-bound to candidate
`candidate-0.24.0-84dff6edd926`, source commit
`84dff6edd926abb69dc39acb201c6777f14b0ea7`, source tree
`cd43a94663856429c24b3f38678ef14eb04e4c71`, release ID
`eoat-atlas-0.24.0`, and build ID
`eoat-atlas-0.24.0-84dff6e-20260727T195721Z`. Its verified component hashes
were:

- desktop ZIP `desktop/EOAT-Atlas-desktop.zip`:
  `d1a3da8c9925217f229b6903113eecbb46126413fd73e432f67c440af976316e`
- desktop update manifest: `c0da2abedfff08e1ec371b49421b5154c9fed2652daba07995a360666dccdf55`
- launcher ZIP `launcher/EOAT-Atlas-launcher.zip`:
  `4637da731832f863cf4739024f7551d8210e3ee1fb61cd27142ff44998c763ce`
- launcher update manifest: `20003cc477aa763392bcede4f51c2e1b92fabdeaaf334699eb1e460a79aab0cb`
- attachment manifest: `e6c9a6418b361131f4c640f760cd942dfa273ea8db3bea040dd178c5d3be2bd7`

The desktop smoke receipt (`b5bdec5e721c6e60c5b1c8b47f28167fe41e1f5a6ece706474863dae369d06a6`)
and launcher smoke receipt (`87a465cd347cf75e6b3cc99e194db212de8635d27548520422408474742dafa5`)
both report `PASS` with the exact candidate identity. The real attachment job
validated metadata, package manifests, receipts, update manifests and hashes,
then attached the component set while leaving only `RELEASE_SET_MANIFEST` and
`RELEASE_SET_SIGNATURE` pending and publication eligibility false. It also
proves a byte-identical retry is idempotent; the focused attachment tests prove
conflicting bytes are rejected and a failed attachment preserves the receipt.

The original Windows packaging stall was isolated to desktop smoke. Bounded
export subprocesses now write per-operation diagnostic receipts, timeout and
terminate their owned Windows process trees, and the desktop smoke path
initializes the frozen Qt entry point and release identity before writing its
receipt and exiting without an interactive GUI event loop. A second correction
uses the candidate build timestamp when producing packaged metadata, preventing
a mismatched build-ID/timestamp tuple from being accepted by the frozen app.
The final version-governance job fetches the declared convergence base before
checking the single governed `0.23.0` to `0.24.0` transition.

Focused local closure before this record: six Phase 1B-2 smoke/attachment tests
passed, Ruff passed for the changed modules, and `check_version_bump.py --base
170d9fb3d8f2ab2dabe6eb86ee7898ccbbd3a6ab` passed. The disposable-MySQL test is
intentionally not counted here: it is outside artifact construction and Phase
1B-2 uses no production or shared MySQL environment.

## Deferred Phase 1B-3 work

Phase 1B-3 will perform final component revalidation, construct the canonical
payload, write and hash the outer manifest and detached signature, use an
externally supplied non-production signing key, and then make a complete
release set eligible for publication verification. Bootstrap implementation,
stable promotion, publication, deployment, and production activation remain
outside this phase.
