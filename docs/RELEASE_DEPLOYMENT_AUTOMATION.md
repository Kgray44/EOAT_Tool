# EOAT Atlas release packaging and deployment preflight

> **Superseded operator model.** This document records the historical phased
> implementation. Use [Release and Deployment Console](RELEASE_DEPLOYMENT_CONSOLE.md)
> for the current capability-based workflow. Historical phase language below
> does not describe the current console or unified CLI.

This is the Phase 1/2 release foundation plus the Phase 3 controlled deployment
client.  It deliberately separates a GitHub-published, immutable release
package from an explicit, separately authorized server activation.

## Existing sources of truth

- `app/atlas/version.json` is the tracked application-version authority.
- `release_defaults.json` holds static API, schema, and component compatibility
  defaults. It contains no build identity.
- `release_history.json` is the version ledger used by the existing safe bump
  mechanism.
- `scripts/release/build_server_release.py` remains the existing deterministic
  ZIP builder. The Phase 1 manager reuses its exact-commit generated metadata
  model while producing the Debian-oriented `.tar.gz` deployment artifact.
- Alembic migrations are in `server/migrations`, with configuration in
  `server/alembic.ini`. The current release defaults name the target revision.
- The API source exposes `/api/v1/health` and `/api/v1/version`; those are the
  manifest health probes. No production systemd unit names are hard-coded in
  source, so an approved non-secret server config must provide verified units.

## Phase 1: release manager

Run from a clean, isolated checkout:

```powershell
python tools/release_manager.py status
python tools/release_manager.py validate
python tools/release_manager.py package --bump patch --dry-run
```

`status` is read-only and reports Git state, version, tag, migration head,
detected release tooling, and (when the GitHub CLI can query it) the latest
published release. `validate` records actual command results for compilation,
Ruff when installed, Alembic head discovery, and release-focused tests.

`package --dry-run` clones the selected committed tree into a disposable local
repository, makes a *simulated* release commit there, builds and validates a
real artifact, and prints a machine-readable receipt. It does not alter the
source checkout, commit, tag, push, or publish. A dirty source tree is rejected
unless both `--allow-dirty` and a non-secret `--approved-exception` are given.
The exception is included in the returned receipt.

An active package operation supports `--version X.Y.Z` or `--bump patch|minor|major`.
It uses the repository's established atomic `bump_repository_version` flow,
stages only `app/atlas/version.json` and `release_history.json`, commits
`release: EOAT Atlas X.Y.Z`, builds from that exact resulting commit, creates
an annotated `vX.Y.Z` tag, then pushes and publishes unless `--no-push` or
`--no-publish` is supplied. It never force-pushes, overwrites a tag, or calls
`git add .`. A successful published release attaches the archive, checksum,
external manifest, and the timestamped release receipt. Receipt attachment is
an explicit final step: if it fails after the first three assets publish, the
local receipt records `FAILED_PARTIAL_PUBLICATION` and the exact recovery is to
upload that saved receipt to the existing immutable tag without creating a new
version or moving the tag.

If a branch or tag push succeeds but GitHub publication fails, the receipt
records that partial state. Recover by first running `status`, verifying the
tag target and artifact SHA-256, then publishing that same tag and the saved
artifact assets with `gh release create`; never create another version or move
the existing tag to recover.

## Artifact and manifest model

The artifact name is
`eoat-atlas-server-VERSION-COMMIT7.tar.gz`, with an adjacent portable checksum
line (`SHA256  filename`) and `release_manifest.json`. The package is built
from `git archive` of exactly the release commit, has sorted member names,
normalized uid/gid/timestamps, and contains only runtime/deployment inputs:
API source, migrations, versioning dependencies, lock files, and generated
metadata. It excludes Git data, tests, local databases, caches, build outputs,
logs, screenshots, `.env` files, keys, and likely secret material.

The schema is [release_manifest.schema.json](../deployment/release_manifest.schema.json).
The archive embeds a manifest *core* with release identity and a digest of the
deployable payload. The external manifest wraps that same core and adds the
outer tarball hash and size. This is intentional: embedding an outer tarball
hash inside that tarball would be self-referential. Verification proves that
the core is byte-equivalent, the embedded payload digest matches, and the
external container hash/checksum matches.

SHA-256 proves artifact integrity after a trusted hash is obtained; it does not
by itself authenticate the publisher. The verifier is structured so a future
signature verifier can be added without weakening hash validation.

## Phase 2: read-only updater/preflight

```powershell
python tools/server_updater.py status
python tools/server_updater.py --server-config C:\safe\eoat-atlas-production-readonly.json inspect-server
python tools/server_updater.py list-releases
python tools/server_updater.py inspect-release --version 0.17.2
python tools/server_updater.py deploy-latest --dry-run
python tools/server_updater.py deploy-version 0.17.2 --dry-run
```

For offline or rehearsal verification, provide a directory containing
`release_manifest.json`, the named `.tar.gz`, and its `.sha256` file:

```powershell
python tools/server_updater.py --release-dir C:\safe\release deploy-latest --dry-run
```

For an SSH inspection, copy the non-secret
`config/deployment_server.example.json` outside the repository, verify its
hostname/service unit values with infrastructure owners, and supply it with
`--server-config`. Private keys, passwords, tokens, and environment files are
never configured in this file. OpenSSH agent/configuration and normal
`known_hosts` handling are used instead.

The inspect-server command is the release-independent production inspection
command. It uses only the same fixed read-only allowlist as preflight and
saves a local receipt under .local/deployment-preflight-receipts. It discovers
relevant EOAT/Nginx units, captures safe filesystem metadata, and accepts the
legacy release_metadata.json layout used by releases published before this
Phase 1 manifest format. It does not read environment-file contents.
The checked-in example reflects the verified EOAT topology: the eoat-atlas
application unit, its host-routed NGINX endpoint, and the current inspection
account. The approved public probe is
`http://eoat-atlas.gwplastics.com:80`; its three health paths are recorded in
both release manifests and the non-secret server configuration. HTTP is
intentional for the current approved internal endpoint: the updater does not
infer HTTPS or treat absent port 443 as an API failure, but records TLS absence
as a non-blocking infrastructure warning for any broader rollout. A MySQL login path remains an operator-provided read-only capability;
the updater reports its absence instead of falling back to credentials or
environment-file contents.

Phase 2 enforces `BatchMode=yes` and `StrictHostKeyChecking=yes`. It never
accepts arbitrary remote shell text. The only remote actions are a fixed
read-only allowlist: host/OS/runtime facts, `df`/`free`, safe `/opt/eoat-atlas`
metadata, current manifest/symlink inspection, approved `systemctl show`,
local GET health probes, a bounded read-only Alembic revision query through the
configured MySQL login path, and safe lock metadata inspection. There is no
SFTP/upload method and no code path for service control, filesystem writes,
migrations, package installation, symlink changes, or database writes.
If the configured host is absent from `known_hosts` (or has changed), the
updater stops before SSH. It may display an *untrusted candidate* fingerprint
obtained from `ssh-keyscan` for an operator to verify out-of-band; if a
legacy scanner cannot negotiate a modern server, it uses an equally
non-authenticating, strict SSH debug handshake only to display that candidate.
It never adds the key or proceeds automatically.

The updater selects the highest semantic-version non-draft, non-prerelease
GitHub Release with exactly one `.tar.gz`, its checksum, and
`release_manifest.json`. Downloads are atomic into `.local/deployment-cache`,
are revalidated before reuse, and corrupt entries are quarantined locally.
It rejects mismatched tag/manifest identity, unsafe archive paths, hash or size
mismatches, and missing required runtime content before opening SSH.

The JSON dry-run receipt includes artifact verification, server facts, current
manifest/symlink, services, health probes, database/migration observations,
disk information, deployment-lock metadata, compatibility warnings, and the
future active-deployment plan. It explicitly records that no production state
was modified. If SSH credentials, a known host, or an approved read-only MySQL
login path are unavailable, the receipt says `UNKNOWN`; it does not weaken
security or guess production truth.

## Phase 3 boundary

Phase 3 is available only after the one-time human sudo bootstrap described in
[Phase 3 deployment controls](PHASE_3_DEPLOYMENT_READINESS.md).  The updater's
`--stage-only` mode never activates a release; `activate DEPLOYMENT_ID` is a
separate conscious operation.  Migration-bearing releases are refused pending
an independently approved backup/restore and migration runbook.  The helper
does not manage NGINX and does not infer HTTPS for the approved HTTP endpoint.
