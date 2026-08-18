# EOAT Atlas Admin Phase 5 Production Release Candidate

Date: 2026-08-18

## Candidate identity

* Branch: `feature/admin-phase5-corporate-auth`
* Reconciled frontend base: `0c7833b07e808537c6f82d73d68e3718fd83aecf`
* Qualified staging source: `c2898bd66566548c6ee4be51f5bb598dc615a09c`
* Qualified staging release: `eoat-atlas-phase5-c2898bd6`

The qualified source contains the reconciled current normal EOAT Atlas
frontend plus the Admin/corporate-auth work. It must not be replaced with the
older Admin-only frontend lineage.

## Evidence summary

Staging health is schema-compatible at `20260814_0011`. Normal EOAT Atlas
routes, Admin server-role denial, governed settings/editing, audit receipts,
append-only behavior, session controls, CSRF/idempotency, fresh-auth, and
Danger safeguards have been qualified using the authorized test database and
synthetic/development authentication. Focused server tests passed 39 tests,
real-MySQL governed Admin tests passed 18 tests, web Vitest passed 54 tests,
and local Playwright passed 23 tests with five intentional non-live/visual
skips. TypeScript, ESLint, API contract generation, and production build pass.

## Production state and release gate

No production deployment is authorized by this record. Production currently
remains `eoat-atlas-0.26.10-725e97f`
(`725e97fa4603f10d32312a9b41f9b52c310dedb5`) with writes disabled.

Before any production deployment, require all of the following:

1. Explicit governed production-release authorization for this exact source
   and a rebuilt immutable production artifact.
2. Trusted managed-browser certificate-chain availability for
   `eoat-atlas.gwplastics.com`, followed by approved human corporate
   Administrator and non-Admin acceptance. No self-signed warning bypass,
   browser exception, or insecure TLS verification is acceptable.
3. Confirmation that production writes remain disabled through deployment and
   that production migration/data operations are separately authorized.
4. Final preflight of production health, release pointer, NGINX syntax, schema
   compatibility, artifact checksums, and the exact retained rollback release.

## Rollback plan

The staging release can immediately roll back from `c2898bd6` to `64ba0405`,
then `0d7ec9f0`; the prior non-Phase-5 release is also retained.
`0d7ec9f0` is descended from the reconciled `0c7833b0` frontend base, while
`0c7833b0` itself is not a separately retained release directory. Each
activation must preserve the staging startup guard, run NGINX syntax validation
where NGINX is changed, restart only the staging service when required, and
prove loopback health after the pointer switch.

For any future authorized production rollout, retain the current production
server and static release pointers before changing either pointer. Roll back
both pointers as a matched pair, restart/reload only the affected service as
appropriate, and verify production health and `writes_enabled: false` before
declaring rollback complete. This record does not authorize that operation.
