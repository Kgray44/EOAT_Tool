# Development setup

Use an authorized clone, Python 3.12, MySQL 8.4, and environment-provided credentials. Set
`EOAT_ATLAS_CANONICAL_DEVELOPMENT_ROOT` to the clone root when path pinning is desired. The repository must contain the
canonical marker, release metadata, `app/atlas/main.py`, and `server/`.

Install with `python -m pip install -r requirements.txt -r requirements-dev.txt`. Start with `python run_atlas.py`.
The normal backend is `mysql_api`; use `--backend legacy` only for intentional migration comparison. Never commit
`.env`, personal paths, workbooks, production exports, credentials, or local caches.

Run `python scripts/validate_documented_commands.py`, `python scripts/repo_safety_audit.py --root .`, and focused tests
before broader validation.
