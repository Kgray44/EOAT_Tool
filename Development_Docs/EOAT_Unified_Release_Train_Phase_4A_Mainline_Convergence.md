# EOAT Atlas Unified Release Train — Phase 4A Mainline Convergence

## Scope and safety boundary

Phase 4A merges the accepted Unified Release Train implementation into the
then-current `main` history, validates the exact converged source, and proves
that a new EOAT Atlas `0.24.0` candidate can be built, sealed, published, and
promoted only in disposable infrastructure.  It is not production signing,
publication, activation, or workstation rollout.

The integration branch is created from `origin/main` and receives a real merge
of `codex/unified-release-train`; conflicts are resolved by preserving both
mainline behavior and the release-train safety contracts.  The fast-forward to
`main` is permitted only after the final workflow for the exact integration
commit passes and `origin/main` has not advanced.

## Final current-component candidate profile

Fresh final candidates set `release_set_profile` to
`FINAL_CURRENT_COMPONENTS`.  This profile deliberately differs from
historical Phase 1 receipts: Bootstrap and `bootstrap_update_manifest` are
real, required, built-and-validated components.  Legacy Phase 1 candidates
retain their truthful Phase 2 `NOT_APPLICABLE` treatment, but they cannot be
used as final current-component input.

The final profile requires one coherent identity across server, web, desktop,
desktop update manifest, Launcher, Launcher update manifest, Bootstrap,
Bootstrap update policy, installer support, source-recovery bundle, governed
release notes, outer release-set manifest, detached signature, and channel
policy metadata.  Every file uses a candidate-relative locator and binds the
same product version, release ID, build ID, candidate ID, source commit, and
source tree.  No Phase 1B artifact may be reused for the final candidate.

## Disposable validation pipeline

The `Unified Release Train Final Integration` workflow performs the complete
non-production proof from the exact integration commit:

1. regression, receipt compatibility, version, repository-safety, and
   documentation validation;
2. server, web, source-bundle, MySQL 8.4, API/web activation, browser parity,
   desktop parity, and signed-channel regression;
3. a fresh unsigned final candidate with real server, web, source, and
   release-note bytes;
4. real Windows desktop, Launcher, and Bootstrap packaging, packaged smoke
   receipts, manifests, and an identity-bound attachment bundle;
5. final attachment, ephemeral Ed25519 sealing, signature revalidation,
   disposable immutable publication, inventory classification, deployment
   planning, and disposable channel-promotion validation.

The workflow uses a job-local ephemeral key and a temporary bare Git remote.
It does not print, upload, commit, or reuse that private key, and it does not
contact the repository's production remote or any production service.

## Final acceptance evidence

The accepted final workflow run ID, component hashes, candidate identity,
signature key ID, publication result, promotion result, and test totals are
recorded in the generated final-candidate evidence artifact.  Before the
integration branch advances `main`, Phase 4A records those values in this
document and reruns the exact final workflow for the resulting documentation
commit when that commit changes source identity.

The first complete pre-handoff proof was workflow `30376935315` for source
commit `40880f79d40dc155c37fa80ef14da5e531532521` and tree
`997b123fad850499f8caaea4dfab1c008c9b4f7d`.  It passed regression, server
and web construction, real Windows desktop/Launcher/Bootstrap packaging and
smoke receipts, MySQL 8.4, browser parity, signed channels, fresh candidate
construction, Windows attachment, ephemeral sealing, disposable publication,
and final acceptance.  Its candidate was
`candidate-0.24.0-40880f79d40d`, with canonical digest
`ecb9da0cfa375fd42b7d1aa590ef9aa3c1866ccc107bb7cf6325abd17dda0a7c` and
ephemeral key ID `final-validation-ephemeral`.

The material component SHA-256 values were server
`06f8f2ed52fa0d8c7838d0e2087ab8a87ee7ec4d41e3368c4d5d53fcbee12219`, web
`00c24cd9eaa3b19d6a9473b36667ee35d1588e88f075756547526edc0ed64a6f`, desktop
`ab5f2eb26f32de52ae8fade05003df3a51e47aef00d2f9490af411b8aa10347b`, Launcher
`5b1b6cd7042f57284c473e8db9f28e47fe5857fd8b2408906c608447e1f9c131`, Bootstrap
`8469df4fc9bc39192c257f4bdcffcaf0de1778496afe275f23b489806fb0895b`, and source
bundle `6b322dc350e7f242a01783d56fd38135c793456a9db5f741fb9c58d3af7518d4`.
The outer manifest and detached-signature SHA-256 values were respectively
`b991bb9956ccfb311febc532b21a2efc6589b8f3cf4ad5028f18c4c0f1662531` and
`10e2560c009e46fa16663940b0ad1bd8f135092ff3c99cb2075faf6d6e9d2563`.

## Production handoff

Successful Phase 4A classifies the exact mainline source as:

```
MAINLINE_CONVERGED
FINAL_RELEASE_INPUT_READY
PRODUCTION_SIGNING_REQUIRED
PRODUCTION_PREFLIGHT_REQUIRED
```

It does not create a production-signed release set, tag, GitHub Release,
channel manifest, deployment, database migration, or client rollout.  Those
actions remain separately authorized Phase 4B/live-production work and must
build and sign an exact candidate with authorized production signing material.
