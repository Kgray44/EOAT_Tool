# EOAT Atlas production lineage

## Authority

The protected `production` branch is the canonical source lineage for EOAT
Atlas production releases. It was created on 2026-08-21 from the live
production source commit:

```text
ae4fc14b44217a8369dbfe07becadb6ff35d3058
```

At establishment, that commit was the source recorded by production API
release `eoat-atlas-0.26.11`; the paired API/static release directories were
the retained rollback state for the next transaction.

GitHub's default `main` branch is an unrelated legacy history. It is neither a
source nor merge base for ordinary EOAT Atlas production releases. Do not
merge it into `production`, force-update either history, or remove either
branch while releasing a production change. A later, separately authorized
lineage-reconciliation project owns that work.

## Branch controls

`production` is protected with force-pushes and deletion disabled. These
controls preserve the released history while allowing the normal review and
merge workflow selected by the release owner. Any stronger required-review or
status-check policy must be added without weakening those protections.

## Release procedure

For every production candidate:

1. Fetch `origin/production` and record its exact SHA.
2. Prove the candidate is descended from that SHA; reject unrelated history.
3. Merge through the ordinary protected-branch path, then re-read the remote
   `production` SHA and prove it is the source used for build inputs.
4. Rebuild sealed API and static artifacts from that exact SHA.
5. Record the current API/static production releases as rollback targets.
6. Run the coordinator preflight and activate only its policy-pinned artifacts.
7. Re-read the production pointers and perform the defined browser/API
   acceptance checks. Preserve the pre-activation pair for rollback.

The production coordinator does not infer branch authority from the repository
default branch. Its runtime pointer and schema checks remain mandatory even
after source-lineage parity is established.
