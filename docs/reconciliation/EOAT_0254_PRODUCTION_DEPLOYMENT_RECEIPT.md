# EOAT Atlas 0.25.4 production deployment receipt

## Status

`NOT_EXECUTED — EXTERNAL SAFETY GATES UNSATISFIED`

The hash-verified 0.25.4 candidate exists, but production deployment and all
production data mutation remain prohibited. Apart from the documented
unauthenticated read-only health, version, and schema requests below, no
production host, database, LDAP service, media source, policy file, or
credential was probed or changed while preparing this receipt.

## Read-only baseline verification

At `2026-07-31T01:25:25Z`, unauthenticated GET requests to the documented
production health, version, and schema endpoints returned HTTP 200. They
confirmed application `0.24.1`, release `eoat-atlas-0.24.1-cfc8917`, API
contract `1.4.0`, schema `20260721_0008`, database reachability, compatibility,
and `writes_enabled: false`. This read-only check did not acquire a lock or
authorize deployment.

## Required gates before activation

1. Verify the current production baseline and take a governed, restorable
   backup; do not infer it from historical receipts.
2. Obtain a fresh GET-only production catalog and rebuild the 52-mapping
   press-capacity candidate for exact commit `b67d9d`.
3. Install and validate root-owned populated policies for the governed data
   operations; perform the matching fresh dry run under the shared lock.
4. Obtain the media owner’s approved read-only source/mount and complete the
   inventory/dry-run/identity crosswalk, or retain `NOT_LOCATED` without
   creating a false media-completion claim.
5. Complete the controlled desktop/browser same-record parity session and
   record differences.
6. Use the governed activation path to verify artifact, migration revision,
   release identity, health endpoints, write lock, and rollback readiness.

LDAPS is intentionally outside this release. No LDAP network probe,
credential action, certificate change, group mapping, or activation is
authorized by this candidate or receipt.
