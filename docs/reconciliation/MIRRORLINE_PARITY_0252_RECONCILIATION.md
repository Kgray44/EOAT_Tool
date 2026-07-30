# Mirrorline parity 0.25.2 reconciliation

## Baseline

- Source baseline: `main` and `origin/main` both resolve to
  `08508a7f90f6c2a4ce21da5ded087a51d89f0bbc`.
- Canonical source version: `0.25.1`; target source version: `0.25.2`.
- API contract: `1.4.0`.
- Target schema: `20260729_0009`.
- Integration branch: `integration/mirrorline-parity-completion-0.25.2`,
  created from the verified baseline and pushed before implementation.
- The archived UNC worktree on `archived/mysql-source-retained` is dirty and
  is deliberately excluded from all changes.

## Branch and worktree decisions

| Source | Decision | Reason |
| --- | --- | --- |
| `main` / `origin/main` at `08508a7f` | Use as baseline | Exact local/remote parity; contains the integrated 0.25.1 parity release. |
| `integration/mirrorline-functional-parity-0.24.2` | Superseded | Its follow-up, 0.25.1, is the verified main tip. |
| Project Mirrorline and composition branches | Retained as history | Their commits are reachable from main. |
| `codex/candidate-preparation-transaction` at `7e540b29` | Do not merge | It is a partial recovery branch based on `6a5085c`; comparison to main removes current source and test coverage. |
| `integration/production-sealing-idempotency-0241` and legacy 0.24.1 release branches | Do not merge | They are historic release tooling, not an ancestor-safe 0.25.2 source update. |
| `codex/fix-eoat-physical-identity-66` and runbook-only remote branches | Retain for evidence only | Physical identity is already represented by main's 0009 migration; no blind duplicate integration. |
| Historical freshness, portable-client, GUI, and migration branches | Retain for evidence only | They are not current-main release candidates. |

The full local and remote reference inventory was inspected using Git's
`--merged` and `--no-merged` relations against `main`/`origin/main`. No
unmerged branch was merged or discarded during reconciliation.

## Source feature inventory

The 0.25.1 baseline already contains the source implementation and focused
tests for the governed areas required for 0.25.2: server-truth Fit Check
ordering, routable profile tabs and library context, relationship presentation
and evidence, physical EOAT identity migration 0009, press-capacity import,
governed media delivery, and settings authentication. The 0.25.2 branch keeps
those implementations intact and removes the remaining web lint warnings by
separating profile-tab helpers from the Fast Refresh component module.

## Read-only production snapshot

At `2026-07-30T14:46Z`, unauthenticated production status endpoints reported:

- API and frontend: `0.24.1`, coordinated at source commit `cfc89176`.
- API contract: `1.4.0`.
- Active schema: `20260721_0008`, compatible with the active API.
- Database and API health: reachable.
- Operational writes: disabled.
- Active candidate/deployment transaction: none reported by release status.

This is a read-only snapshot, not production acceptance for 0.25.2. A
deployment remains conditional on candidate artifacts, backup verification,
approved capacity/media source manifests, LDAP preflight, and the governed
production-helper checks.
