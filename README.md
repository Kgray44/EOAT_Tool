# EOAT Atlas

EOAT Atlas is the Minimalist desktop client and API for finding EOAT, machine, and tool records; evaluating their
compatibility; reviewing evidence; and producing controlled setup references. MySQL through the EOAT Atlas API is the
authoritative operational backend. The local SQLite API cache is disposable, read-only evidence for limited offline
browsing and must never be treated as setup approval.

## Safety and authority

- Compatibility fails closed. Missing, inactive, expired, future, review-required, and unrecognized relationships are
  not compatible.
- Installation writes require a complete compatible Machine + Tool + EOAT evaluation. Authorized overrides are
  separately permissioned and audited.
- Normal application use has no user sign-in prompt. Settings administration is separately authenticated and starts
  locked.
- `legacy` is an explicit migration/comparison mode. It is never a silent fallback from `mysql_api`.
- Production identity, TLS, network controls, secrets, signing, infrastructure, UAT, and approval remain IT/business
  responsibilities. This repository does not prove production readiness.

## Development start

Use Python 3.12 on Windows and configure local secrets outside Git.

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
$env:EOAT_ATLAS_CANONICAL_DEVELOPMENT_ROOT = (Get-Location).Path
python run_atlas.py
```

The bootstrap validates the canonical marker and source layout, selects `mysql_api`, and verifies or starts the local
development MySQL/API stack. To compare legacy inputs deliberately, use `python run_atlas.py --backend legacy`.

### Legacy demo data

Demo mode remains available only for explicit legacy comparison with the synthetic `examples/demo_project` data. It is
never selected as a fallback from MySQL/API operation. In that legacy mode, use **Choose Real Project Folder** to point
the comparison workflow at an authorized private project root; see [USAGE.md](USAGE.md) for the isolated-file rules.

## Database and API

Default development database: `eoat_atlas_dev`. Test migrations and destructive database exercises belong only in
`eoat_atlas_test`. Credentials use `EOAT_DB_*` and `EOAT_DB_MIGRATION_*` environment variables.

```powershell
python -m alembic -c server/alembic.ini current
python -m alembic -c server/alembic.ini upgrade head
python -m uvicorn server.eoat_api.app:app --host 127.0.0.1 --port 8765
```

API documentation is available at `/api/docs` only when enabled. It defaults off outside development/local staging.

## Validation

```powershell
python scripts/repo_safety_audit.py --root .
python -m ruff check .
python -m compileall -q app core server scripts
python scripts/validate_documented_commands.py
python scripts/ci_atlas_smoke_check.py --root .
python -m pytest
```

Real MySQL integration tests must receive explicit test-database configuration. A skipped integration test is not a
pass. CI separates repository safety, lint, version validation, unit/API/migration tests, UI smoke, packaging, package
smoke, and dependency audit so one failure cannot conceal another gate.

## Release and packaging

`app/atlas/version.json` owns the tracked application version; `release_defaults.json` owns non-build component
defaults. Packaging generates `release_metadata.json` and manifests only after selecting the exact source commit.
Build with `python scripts/build_package.py`; validate with
`python scripts/smoke_test_package.py "dist/EOAT Atlas/EOAT Atlas.exe"`. Do not publish mismatched metadata or unsigned
artifacts as approved production releases.

Application changes receive one version increment after validation using `scripts/bump_version.py` with a stable
operation ID. No commit, tag, push, release, or deployment is performed automatically by these instructions.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Development setup](docs/DEVELOPMENT_SETUP.md)
- [Database migrations](docs/DATABASE_MIGRATIONS.md)
- [Release process](docs/RELEASE_PROCESS.md)
- [IT deployment](docs/IT_DEPLOYMENT.md)
- [Security boundary](docs/SECURITY_BOUNDARY.md)
- [Disaster recovery](docs/DISASTER_RECOVERY.md)

Historical migration reports may mention retired products or paths; they are not current operating instructions.
