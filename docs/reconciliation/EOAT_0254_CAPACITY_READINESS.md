# EOAT Atlas 0.25.4 capacity readiness

## Preserved source evidence

- Workbook SHA-256:
  `2254269d4eabfd3478a6404005e4efdc850e3223e3ed6882b4bdbd0d71a785e3`
- Parsed sections: 54.
- Approved exact canonical mappings: 52.
- Exclusions: Presses 24 and 64; Machines 6, 8, 70, and 72.
- Machine 27: Plant 4, workbook row 99, candidate value 165 US tons.

The prior read-only catalog receipt records 56 unique active Plant 4 records,
null capacity at retrieval, and no created machines, aliases, relationships,
or compatibility rows. The existing import implementation updates only an
existing machine's `press_capacity_tons` within its transaction.

## Current result

The externally retained immutable candidate is documented with SHA-256
`997a21b5672b27d61310d8c38554ead973522c6c3b6c8b0b15a64c9e2de7d5fc`, but
its documented source commit is `4392c999ccf74787279870c712035a995b74e05e`
and it is not present in this worktree. It cannot be claimed valid for the
uncommitted 0.25.4 source or current production state.

The root helper now has a restricted `import-press-capacity` operation. Before
any execution it requires a root-owned pinned policy, matching helper/candidate
and backup hashes, a fresh matching dry run, the shared deployment lock, and
an immutable receipt. The policy scope hard-codes Plant 4 and all six
exclusions; callers cannot provide SQL, a database, or an arbitrary workbook.

## Required gate

After the exact 0.25.4 commit exists, obtain a new read-only production catalog
and rebuild the immutable candidate from the approved workbook and exact source
commit. Then validate hash, catalog, schema, release, canonical identity,
row-version, existing-capacity, exclusion, backup, and dry-run conditions in
the installed root-owned policy. Until then Machine 27 remains truthfully null
in the browser fixture and no capacity import may run.
