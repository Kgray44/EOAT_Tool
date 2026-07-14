# Enterprise Settings authentication test results

Date: 2026-07-14

- Provider/unit/bootstrap/database tests: 18 passed.
- Fresh-process Settings UI tests: 24 passed.
- Settings authentication API integration: 4 passed.
- MySQL foundation with schema 0005: 5 passed.
- Focused total: 51 passed, 0 failed, 0 counted skipped.
- Alembic development upgrade: passed.
- Alembic test upgrade/downgrade/upgrade: passed after correcting MySQL FK/index drop order.
- Exact unsigned-in canonical startup: passed, exit 0, schema 0005.
- Direct API boundary: ordinary unsigned-in 200; Settings 401/403/200; revoked session 401.

A combined long-lived Qt process encountered the repository's known native PySide accumulation crash and was not counted. The same relevant tests passed in fresh processes.

Blocked: real SAML/LDAP staging tests, IT review and human business UAT.
