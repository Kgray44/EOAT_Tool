# EOAT Atlas release and update

To publish a tested patch update, double-click:
`Publish Patch Update.cmd`

The publisher reads the already-bumped canonical version, requires it to be newer than the current network manifest, asks once for `PUBLISH`, then tests, builds, smoke-tests, packages, verifies, and promotes that exact release. `release_metadata.json` is the sole app-version source. Perform the task's one version bump before publishing; publishing never adds a second bump. The initial release is deliberately different because no valid network history exists: run `python scripts/publish_release.py --initialize --release-notes "Initial managed release"`; inspect a dry run first by adding `--dry-run --yes`.

## Commands

- Safe full validation: `python scripts/publish_release.py --dry-run --initialize --yes --release-notes "..."`
- Temporary deployment integration: `python scripts/publish_release.py --initialize --yes --deployment-root "C:\temp\EOAT Atlas" --release-notes "..."`
- Normal publish after the task bump: `python scripts/publish_release.py --yes --release-notes "..."`
- Explicit compatibility floor only when intended: add `--minimum-supported-version X.Y.Z`.

`latest.json` requires `latest_version`, matching `release_id`, unique `build_id`, immutable `release_path`, `minimum_supported_version`, `sha256`, `package_size`, and `published_at`; it also records `release_notes` and tolerates unknown optional fields. The manifest is atomically replaced only after the final package has been read back and verified against the same embedded version/release/build identity.

The launcher compares parsed numeric semantic versions. Missing or older local apps install/update; equal starts immediately; newer local versions are never downgraded. Network or package failures use the last-known-good local app only when it meets the cached compatibility floor. A required but unreachable update shows an actionable error. Packages stage under `%LOCALAPPDATA%\EOAT_Atlas\app_staging`, activate into `app_versions\VERSION`, and switch `current.json` atomically. Settings, SQLite data, caches, logs, exports, identity, and last-known-good metadata are outside version directories and are never removed.

The per-user installer seeds the stable launcher and an initial app without admin rights. Its Desktop shortcut always targets `EOAT Atlas Launcher.exe`; every subsequent launch retrieves the latest app through `latest.json`, so app-only patches do not rebuild the launcher or installer. A future launcher change increments `launcher/launcher_version.json`, builds with `python scripts/build_launcher.py`, is separately approved and deployed, and then refreshes the bootstrap installer.

Rollback is deliberate: validate the desired archived immutable package, create a new manifest that names it with its real version/checksum/size, and atomically replace `latest.json`. Never edit binaries in place. Release locks record user, host, PID, and time. If a lock appears stale, verify that publisher process is gone before deliberately deleting only `Manifests\publish.lock`; the tool never deletes a lock automatically.

Deployment results are written to `Logs\Deployment Tests`; dry-run logs stay under `build\release_logs`. If SentinelOne blocks an artifact, stop and send its checksum and deployment log to IT for allowlisting. Do not disable or bypass endpoint security. Recovery never requires deleting `%LOCALAPPDATA%\EOAT_Atlas`; repair the network artifact or launcher and retain user runtime data.
