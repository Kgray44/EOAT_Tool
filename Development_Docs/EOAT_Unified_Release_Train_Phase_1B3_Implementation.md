# EOAT Atlas Unified Release Train — Phase 1B-3 implementation record

## Scope and safety boundary

Phase 1B-3 implements final schema-version-2 candidate revalidation and
non-production release-set sealing on `codex/unified-release-train`. It keeps
the governed product version at **0.24.0** and does not add a release-history
operation. It does not publish assets, create a tag or GitHub Release, promote
a manifest, activate a deployment, or contact production infrastructure.

## Final sealing contract

`ReleaseDeploymentService.verify_candidate_for_sealing()` reopens all retained
candidate-relative artifacts. `seal_release_set()` requires the exact typed
confirmation `SEAL <candidate-id>`, signs only after that revalidation passes,
and persists the receipt only after both outer files reopen and signature
verification succeeds. Retrying an already sealed candidate verifies the
existing immutable envelope; it never overwrites it. Conflicting bytes block.

The canonical payload is deterministic sorted-key compact UTF-8 JSON. It
contains the full typed release-set inventory but excludes the outer manifest
and detached-signature file hashes and locators to avoid self-referential
hashing. The receipt records those outer-file facts afterwards. Detached
signatures use Ed25519, configured public keys reject unknown/revoked key IDs,
and verification needs no private key. CI signing material is ephemeral,
non-production, stored only in a runner temporary file, removed before upload,
and never placed in diagnostics or artifacts.

Bootstrap and bootstrap-update-manifest remain `NOT_APPLICABLE` with the
explicit Phase 2 rationale. A successful seal sets
`RELEASE_SET_VALIDATED`, derives no missing components, sets publication
eligibility, and directs the operator only to Phase 1C publication
verification.

## CI evidence

The first complete Phase 1B-3 sealing exercise ran in workflow **Unified
Release Train Phase 1B-2**, run `30308057471`, at commit
`e60a91f9b8bc38a9463e7b8f5ee625724461c995`. All jobs succeeded:

| Job | Conclusion |
| --- | --- |
| `documentation-command-validation` | success |
| `model-receipt-regression` | success |
| `core-artifacts` | success |
| `windows-packaged-artifacts` | success |
| `attachment-verification` | success |
| `sealing-transaction` | success |

The exercise sealed candidate `candidate-0.24.0-e60a91f9b8bc`, source commit
`e60a91f9b8bc38a9463e7b8f5ee625724461c995`, source tree
`8541b48ce887f4bfc533097c07bde80e46725c79`, with canonical release-set digest
`0838c0e27213dcd522b12ad555690e0e710d4b2979d9684ea1893e23063fee71` using
key ID `ci-phase-1b3-test` and Ed25519. The real outer files were
`sealing/release-set-manifest.json`
(`2fbf487bd28537e8c0a593bf435eb321b249058b6339059fa100916c06d4b38f`) and
`sealing/release-set-signature.json`
(`aa7c248cf9f5861cb44412b3317b1ba2a4a57e8da6faf39a383e9ac785f7d0cc`).

The Windows attachment contained non-placeholder desktop and launcher packages
whose hashes were respectively
`7d7c7beb7a5853a372ad871e32b081f2c78461b6976c5aa1660f10284c0ace9b` and
`4b738a7252ffaf7bae18601b501bc8a87e73d1443c8102efc7dd72e71806f8da`. Their
machine-readable smoke receipts both reported `PASS` and hashed to
`33105a57df02be1891098ea83b5371f4cfd902214a8a1a3fb7ec19cf70819bc8` and
`ec1404ba6e09f483ba13ba1d32d5ec22ffc7c5085c196a71e24f0ed5eb63231f`.
Attachment verification exercised atomic attachment, identical retry, and
conflicting-attachment rejection before sealing. Evidence scan found no private
key material in the uploaded sealing artifact.

Focused sealing and release-set tests, convergence regression, CLI/console
coverage, Ruff, repository safety, version governance, and documented-command
validation are required on the final branch tip. The disposable-MySQL test is
outside this artifact/sealing scope and remains intentionally skipped; it is not
counted as a pass.

## Remaining Phase 1C scope

Phase 1C may consume only a trusted, complete sealed release set for immutable
publication verification, release inventory, and deployment-plan integration.
It must retain the separate production authorization boundary; this record does
not authorize publication, activation, stable promotion, or bootstrap work.
