# Packaging EOAT Atlas

EOAT Atlas is distributed as a Windows PyInstaller `onedir` application, a lightweight launcher, and a no-elevation
per-user installer bundle. Packaging is an internal qualification workflow; it does not imply production approval or
code signing.

## Prerequisites

- Windows 10 or newer.
- Python 3.12.
- A clean committed checkout.
- Runtime dependencies installed from `requirements.lock` and build dependencies from `requirements-build.lock`.

```powershell
python -m pip install -r requirements-build.lock
python -m PyInstaller --version
```

PyInstaller is build tooling and is not included in the runtime lock. UPX is disabled for both application and launcher
builds. No signing identity is configured; an approved certificate and IT process are external requirements.

## Build and verify the application

From the repository root:

```powershell
python scripts/build_package.py
python scripts/smoke_test_package.py "dist/EOAT Atlas/EOAT Atlas.exe"
```

`build_package.py` refuses a dirty tree unless the explicit development-only
`EOAT_ATLAS_ALLOW_DIRTY_BUILD=1` override is set. A production-candidate build must not use that override. The generated
package metadata records the exact commit, branch, timestamp, build run, dirty state, build ID, and executable SHA-256.
The package manifest records every packaged file and checksum.

## Build the Debian server release

Commit the intended source first, then build its exact revision:

```powershell
python scripts/release/build_server_release.py --source-commit HEAD --branch-name fix/release-provenance
```

The builder refuses relevant dirty server files, reads the version and defaults from the selected commit, creates a
normalized ZIP under `dist/server`, inserts generated `release_metadata.json`, and writes adjacent SHA-256 and JSON
manifest files. Reusing the same explicit `--build-timestamp` with the same commit produces the same metadata, build ID,
ZIP ordering, timestamps, permissions, and checksum. The manifest—not the tracked tree—binds the source commit to the
finished archive checksum. The archive intentionally contains no `.git` directory and needs none at runtime.

Writable runtime state belongs under `%LOCALAPPDATA%\EOAT_Atlas`; it must not be written into the onedir package.

## Build the launcher

```powershell
python scripts/build_launcher.py
```

The launcher is written to `dist\launcher\EOAT Atlas Launcher.exe`. It resolves the current per-user application,
validates release/update identity, prevents duplicate launch, and records diagnostics under the per-user runtime root.

## Build the per-user installer bundle

Build the application and launcher first, then run:

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File installer/Build_Installer_Exe.ps1 -PythonExe python -Clean
```

`installer\dist` is the distributable folder. It contains only the no-elevation installer entry point, its audited
runtime script/configuration, and the application and launcher payloads. Installation is per-user and refuses elevated
execution. Validate an installed instance with `installer/Validate_EOAT_Atlas_Install.ps1`.

The configured desktop shortcut is intentional and targets the launcher. Application binaries are versioned under the
per-user application root; logs, cache, and user identity follow the retention behavior documented in
`installer/README_INSTALLER.md`.

## Exclusions and security

Packages must not contain `.env` files, credentials, Git metadata, private workbooks, operational evidence, test
fixtures, developer caches, or backup artifacts. Endpoint allowlisting, certificate-backed signing, production TLS,
production infrastructure, and deployment approval remain external IT controls.
