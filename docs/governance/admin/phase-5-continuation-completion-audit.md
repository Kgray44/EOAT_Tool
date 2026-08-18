# EOAT Atlas Admin Phase 5 Continuation Completion Audit

Date: 2026-08-18

## Scope and identity

This audit covers the continuation directed after IT confirmed that a
browser-trusted PKI/certificate is not currently available. It does not treat
the TLS limitation as a reason to stop nonproduction functional acceptance,
and it does not claim that synthetic/development authentication proves real
corporate authentication.

* Authoritative reconciled frontend base:
  `0c7833b07e808537c6f82d73d68e3718fd83aecf`
* Deployed staging source:
  `c2898bd66566548c6ee4be51f5bb598dc615a09c`
* Deployed staging server/static release: `eoat-atlas-phase5-c2898bd6`

## Requirement-by-requirement evidence

| Objective item | Evidence | Status |
| --- | --- | --- |
| Deploy reconciled candidate | Staging server and static pointers resolve to `eoat-atlas-phase5-c2898bd6`; its static provenance records source `c2898bd…` and describes the reconciled Phase 5 UI. `0c7833b…` is an ancestor of the current source. | Complete |
| Health and rollback | Staging service is active and healthy at schema `20260814_0011`. Retained rollback releases are `c2898bd6 -> 64ba0405 -> 0d7ec9f0`, plus the pre-Phase-5 release. | Complete |
| Normal EOAT Atlas surface | Current staging loopback checks returned `200` for Home, EOAT, Machine, Tool, lookups, Fit Check options, search, and representative EOAT/Machine/Tool history, documents, and photos routes. | Complete for service/API regression |
| Complete Admin surface and role gate | Anonymous staging overview, settings, and audit routes each return `401`. Local browser and server suites cover Admin overview, ledger, settings, audit detail, diagnostics, governed editing, and Danger controls with synthetic test identities. | Complete for synthetic/development acceptance; real corporate identity acceptance is external |
| Browser parity | Playwright: **23 passed, 5 intentional live/visual skips**. It covers normal routes, direct links, responsive layouts, Admin deep links, denial, and Danger rehearsal on the reconciled frontend. | Complete for local browser regression |
| Settings and governed editing | Controlled real-MySQL Phase 2--4 execution against the authorized test database completed **18 passed** on the deployed candidate. It covers Settings and governed mutation architectures. | Complete; a later local rerun correctly skipped because test-DB credentials were intentionally not loaded into this workstation environment |
| Audit evidence | The controlled MySQL suite verifies actor/correlation values, receipts, before/after state, and audit-failure rollback/append-only behavior. Focused server/admin coverage also passes. | Complete for authorized test database |
| Session and Danger protections | Focused corporate-session tests and real-MySQL evidence cover expiry, revocation, logout, CSRF, idempotency, mapping refresh, fresh-auth, and test-only Danger safeguards. No real corporate credential was entered. | Complete for synthetic/development acceptance; real corporate session evidence is external |
| Server and client validation | Current runs: OpenAPI drift check, TypeScript, ESLint, build, 54 Vitest tests, 23 Playwright tests, 30 server tests, focused 39 server/Admin/auth/media tests, targeted Ruff, and Python compilation all pass. | Complete with the stated inherited baseline qualifications below |
| Production candidate and rollback | `phase-5-production-release-candidate.md` identifies the qualified staging source, release gates, and matched-pointer rollback procedure. Production was not deployed. | Complete |

## Qualification findings

* `pnpm run format:check` reports 84 existing web files. No broad formatting
  rewrite was performed because those unrelated changes are not Phase 5 work.
* Broad `ruff check server tests` reports 12 pre-existing non-Phase-5 issues in
  desktop/test files. Targeted `server/eoat_api`, `tests/server`, and web
  content lint passes.
* The production build succeeds with the existing Vite chunk-size advisory.
* A current bare local invocation of the real-MySQL suites is expected to skip
  without the isolated test-database environment variables. It is not counted
  as a passing run; the controlled 18-pass execution remains the authoritative
  test-database evidence.

## External corporate-login boundary

Both HTTPS ports continue to serve the same hostname-valid self-issued
certificate (subject/issuer `CN=eoat-atlas.gwplastics.com`; SHA-256 fingerprint
`35:95:AB:1E:4B:85:7E:E9:9C:FC:48:11:51:94:D4:1A:22:BA:29:3A:22:35:A4:06:54:0B:A5:14:1D:F9:82:8F`).
Normal OpenSSL verification returns self-signed certificate error 18 and normal
curl verification returns certificate error 60. No insecure mode, trust-root
installation, warning bypass, or real corporate credential was used.

The only acceptance still externally blocked is managed-browser corporate TLS
trust and the resulting approved human corporate Administrator/non-Admin and
provider-outage exercises. It does not invalidate the completed synthetic and
test-database qualification above.

## Production disposition

Production remains `eoat-atlas-0.26.10-725e97f`
(`725e97fa4603f10d32312a9b41f9b52c310dedb5`), healthy, schema-compatible, and
`writes_enabled: false`. No production service, release pointer, database,
write setting, NGINX configuration, certificate configuration, or data was
changed by this continuation.
