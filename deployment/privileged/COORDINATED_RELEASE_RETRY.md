# Coordinated release coordinator

## Canonical production lineage

EOAT Atlas production releases use the protected `production` branch as their
source-lineage authority. The branch was established at the deployed
`0.26.11` source `ae4fc14b44217a8369dbfe07becadb6ff35d3058` on 2026-08-21.
Before sealing a production candidate, the release owner must fetch
`origin/production` and prove that the candidate descends from that branch and
that the branch identity agrees with the live release metadata. The coordinator
still independently re-attests the live API/static pointers and schema at
preflight.

The repository default branch `main` is a separate legacy history and is not a
production-release authority. It must not be merged into, force-updated from,
or used to replace `production` during normal production release work. Its
lineage reconciliation is a separately authorized project. See
`docs/governance/production-lineage.md` for the branch and evidence policy.

Coordinator 1.4.0 retains the sealed-artifact, paired API/frontend activation,
exact-pointer attestation, and rollback-receipt controls from 1.3.4. Its only
new release path is a policy-pinned migration plan: the policy declares the
exact current schema, target schema, ordered migration revisions, and the
SHA-256 of every revision source. The sealed API archive must contain those
exact files and prove that the sequence is a complete deterministic Alembic
DAG traversal from the active head. An absent plan remains the historical
zero-migration transaction.

For a migration-bearing transaction the coordinator holds the fixed deployment
lock, re-attests both live pointers and the current schema, validates the
sealed plan, creates and independently validates a root-only compressed MySQL
backup, stages both releases, upgrades from the staged immutable API payload,
and verifies the target head before it changes either live pointer. The API and
frontend are then activated as one governed transaction. If migration fails,
the verified backup is restored before the transaction fails. If activation
fails after migration, the coordinator restores both prior pointers, restores
the verified backup, restarts only the API service, and records the failure;
writes remain disabled throughout.

`reconcile-legacy-rollback --transaction <governed-id>` remains a one-purpose,
root-only recovery action for historical coordinator 1.3.1 transaction receipts
with schema version 2. It accepts no policy, path, target, or force argument.

It succeeds only when both live pointers already resolve to the receipt's
recorded old targets, the old targets freshly attest as immutable, API health
proves 0.22.12 / schema `20260721_0008` with writes disabled, NGINX and both
services are healthy, `data_state` is a singleton, and no later unresolved
transaction or deployment lock exists. It never rewrites pointers, reloads
NGINX, restarts services, changes MySQL, or edits the original receipt.

The action exclusively creates `post-activation-rollback.json` with fresh
attestations and `legacy_already_rolled_back` evidence. It scans only direct
`coordinated-*` records for newer unresolved coordinator state; retained
non-coordinator historical evidence is not interpreted as a transaction.
Existing evidence must match exactly for an idempotent retry; conflicts fail closed. Normal
schema-version-3 `post-activation-rollback` behavior remains separate.
