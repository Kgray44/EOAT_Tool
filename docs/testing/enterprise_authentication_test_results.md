# Enterprise Settings authentication test results

Date: 2026-07-15

- Provider/Settings/UI/configuration tests: 38 passed.
- Settings authentication API integration: 7 passed.
- Development bootstrap, History gateway, and PDF session regressions: 17 passed.
- Focused total: 62 passed, 0 failed, 0 counted skipped.
- Alembic development upgrade: passed.
- Alembic test upgrade/downgrade/upgrade: passed after correcting MySQL FK/index drop order.
- Exact unsigned-in canonical startup: passed, exit 0, schema 0005.
- Direct API boundary: ordinary unsigned-in 200; anonymous non-secret Settings read 200; Settings writes 401/403/200; revoked session 401; live permission loss 403; provider outage 503 while ordinary Home remained 200.
- Ruff, Python compilation, `pip check`, and `pip-audit`: passed; no known vulnerabilities reported.

A combined long-lived Qt process encountered the repository's known native PySide accumulation crash and was not counted. The same relevant tests passed in fresh processes.

Blocked: real SAML/LDAP staging tests, IT review and human business UAT.
