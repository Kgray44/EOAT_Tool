# User Acceptance Test Plan

Required cases: health/version compatibility; Home summary; EOAT/machine/tool browsing and search; asset creation/update/archive; compatibility; transactional movement; audits; maintenance; documents; photo metadata and profile-photo selection; tags and annotations; fit checks; authorization; optimistic concurrency; idempotency; three independent client caches; API outage with cache reads and blocked writes; cache rebuild; source immutability; performance; and post-cutover export.

Each case records environment, release/schema version, actor role, HTTP result, duration, created identifiers, and cleanup or rollback disposition. Pass requires the expected business result and matching audit/change-feed evidence. A visual-only desktop observation cannot substitute for API/data evidence, and automated evidence cannot claim that a human approved usability.

For EOAT Atlas 0.27.0, record the exact published candidate SHA, source schema
`20260828_0017`, and final schema `20260910_0019`. Authenticated onboarding
UAT additionally covers technician-owned draft creation, engineer review and
finalization, duplicate identifier denial, stale-save conflict, discard and
reservation release, front-photo adoption, atomic finalization failure, and
the created EOAT's Library, profile, Fit Check, history, and QR-label paths.

Automated results are in `reports/cutover_rehearsal/uat_results.json`. Human business-owner sign-off remains a production go-live gate even when the local rehearsal passes.
