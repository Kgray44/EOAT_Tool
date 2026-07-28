# EOAT Atlas Unified Release Train — Phase 2 implementation

## Scope and safety boundary

Phase 2 adds the per-user, recoverable Windows startup chain:

`EOAT Atlas shortcut -> EOAT Atlas Bootstrap -> active immutable launcher -> desktop application`.

It is deliberately limited to bootstrap-to-launcher update. It does not
publish, deploy, activate API/web, promote a client channel, contact production,
or alter EOAT Atlas product version `0.24.0`.

## Components and layout

Bootstrap component version `0.1.0` is governed independently in
`bootstrap/bootstrap_version.json`. The launcher remains independently versioned
in `launcher/launcher_version.json`. A normal per-user installation uses:

```text
%LOCALAPPDATA%\EOAT_Atlas\
  bootstrap\EOAT Atlas Bootstrap.exe
  launcher_versions\<component-version>\
  active_launcher.json
  last_known_good_launcher.json
  launcher_update_receipts\
  launcher_logs\
```

Version directories are immutable. Pointers are atomically replaced, while the
previous confirmed launcher remains available until a later policy-governed
retention action.

## Signed launcher update and recovery

`bootstrap.core.LauncherUpdateManifest` is canonical compact JSON signed with
Ed25519. The bootstrap verifies key trust/revocation and the signature before
using the locator, version, hash, minimum-version, or mandatory policy. It then
checks ZIP safety, metadata and package-manifest hashes, component/product/
release/build/source identity, and packaged smoke evidence before activation.

The durable receipt records state transitions from checking through package
verification, candidate smoke, activation, startup health, confirmation or
rollback. Startup health is a machine-readable launcher receipt, not process
existence. A failed health result restores the previous atomic pointer; when no
previous launcher exists, the result is blocked with repair guidance.

When transport is offline, only a confirmed-good active/last-known-good
launcher that remains supported by cached signed policy may start. Revoked or
below-minimum versions block.

## Packaging, installer, and migration

`scripts/build_bootstrap.py` and `EOAT_Atlas_Bootstrap.spec` produce the
windowed bootstrap executable with non-interactive smoke mode. Launcher package
creation is handled by `scripts/package_launcher_update.py`, which requires the
real launcher executable, metadata, package manifest, and smoke receipt.

The installer provisions bootstrap and targets the current-user shortcut at
bootstrap. Uninstall removes bootstrap, launcher version/pointer/receipt files
but keeps user data, cache, logs, and exports. `bootstrap.migration` provides a
portable transactional migration record for diagnostics/CI; Windows Shell-link
migration remains installer-governed.

## CLI and console

`tools/eoat_release.py bootstrap --install-root <path> --trusted-keys <public-keys.json>` exposes
`status`, `offline-policy`, and signed `update`. It accepts public keys only.
The existing console has a **Workstation Startup** view that runs the same
bootstrap service on a worker and shows active/LKG inventory and offline-policy
state.

## CI and remaining work

`unified-release-train-phase-2.yml` covers policy, package validation,
bootstrap/launcher packaged builds and smoke, rollback, shortcut/installer
syntax, offline policy, CLI/console, black-box startup-chain regression,
safety, governance, and documented commands using only disposable keys and
local artifacts.

Bootstrap replacement itself remains installer-governed. Production publication,
deployment, API/web activation, and candidate/canary/stable channel promotion
remain separately authorized later work.
