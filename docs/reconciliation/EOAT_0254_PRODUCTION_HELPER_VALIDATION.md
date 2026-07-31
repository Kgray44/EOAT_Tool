# EOAT Atlas 0.25.4 restricted production-helper validation

## Implemented boundary

The existing root deployment entry point now dispatches only two additional
structured operations: `import-press-capacity` and `migrate-profile-media`.
`governed_data_operations.py` accepts exactly an operation, opaque request ID,
and `dry-run` or `execute` mode.

It rejects caller-provided commands, SQL, database names, source paths,
destination paths, policy paths, candidate paths, and backup paths. The fixed
policy location is `/etc/eoat-atlas/data-operations/<operation>.json`.

Before a policy can run, the helper requires:

- a regular non-symlink policy file with root-owned/non-group-world-writable
  Linux ownership and permissions;
- exact main-helper SHA-256 plus canonical policy-payload SHA-256 binding;
- the only allowed production database identity, `eoat_atlas_prod`;
- a governed-root candidate and verified backup receipt with pinned hashes;
- a fixed release script and inputs selected only by policy;
- a fresh matching dry run, shared deployment lock, and non-overwriting
  receipt for execution; and
- the Plant 4 capacity scope and six exact exclusions for capacity imports.

The media template remains intentionally unusable until an approved source root
exists. Both templates are checked-in examples only; a root administrator must
install populated policies after candidate and backup evidence exist.

## Focused evidence

`tests/test_governed_data_operations.py` and
`tests/test_phase3_privileged_helper.py` passed **37 tests** together on
2026-07-30. The harness covers valid dry-run/execute/idempotent behavior and
rejection of arbitrary caller control, malformed IDs, policy payload drift,
path traversal, non-production database identity, missing policy, stale/missing
dry runs, and existing-helper deployment boundaries.

This is source and disposable-harness validation. No policy is installed on a
production host and no privileged production mutation has been attempted.
