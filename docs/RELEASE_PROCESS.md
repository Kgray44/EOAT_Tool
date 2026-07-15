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
