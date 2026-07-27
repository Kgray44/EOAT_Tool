# Release process

Tracked release identity includes application version, release ID, API contract, database revision, launcher/installer
versions, and channel. Generated build identity includes the exact source commit, branch/tag, UTC time, CI/local run ID,
and artifact checksum. The app, API, PDFs, installer, manifest, and database release registration must agree.

After implementation and validation, run one semantic increment with a stable receipt, for example
`python scripts/bump_version.py minor --operation-id task-id`. Then run
`python scripts/check_version_bump.py --base HEAD` and `python scripts/check_version_bump.py --skip-change-check`.

Build with `python scripts/build_package.py`. Smoke the result with
`python scripts/smoke_test_package.py "dist/EOAT Atlas/EOAT Atlas.exe"`. Publishing must stop on metadata, checksum,
safety, smoke, or signing-policy mismatch. A local unsigned build is not an approved production release.

## Schema-2 candidate sealing (Phase 1B-3)

After core and identity-bound Windows artifacts are attached, first reopen the
candidate and then seal only with the exact typed candidate ID:

```text
python tools/eoat_release.py candidate verify-for-sealing candidate-0.24.0-<commit>
python tools/eoat_release.py candidate seal-release-set candidate-0.24.0-<commit> --confirm "SEAL candidate-0.24.0-<commit>"
python tools/eoat_release.py candidate verify-sealed-release-set candidate-0.24.0-<commit>
```

The canonical release-set payload is deterministic and excludes the outer
manifest/signature-file hashes to avoid circular self-hashing. The candidate
receipt stores the real outer-file hashes after signing and verification. A
private signing key is supplied outside Git; signature verification uses only
the configured trusted public-key set and rejects unknown or revoked keys.
Sealing establishes eligibility for Phase 1C verification only. It does not
publish, tag, activate, or promote a production release.

## Phase 1C disposable publication

Production-backed publication is deliberately disabled. For an isolated test
remote and release registry only, use the shared CLI:

```text
python tools/eoat_release.py publish readiness candidate-0.24.0-<commit>
python tools/eoat_release.py publish start-disposable candidate-0.24.0-<commit> --remote path/to/remote.git --registry path/to/registry --confirm "PUBLISH candidate-0.24.0-<commit>"
python tools/eoat_release.py releases list-disposable --registry path/to/registry
```

The backend creates immutable Git refs and filesystem assets, accepts only
exactly matching retries, and blocks conflicts. It is a verification backend,
not authority to create a real tag, GitHub Release, production manifest, or
deployment.
