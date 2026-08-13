# EOAT Atlas Admin Phase 4 Failure-Mode Matrix

Scope: live `eoat_atlas_test` acceptance only. No production schema, service,
credential, deployment, or business record is part of this matrix.

| Failure mode                                         | Expected safe result                                                                              | Live evidence                                                                              |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Missing or invalid CSRF                              | Mutation rejected before preview or commit.                                                       | Real API: `403 CSRF_INVALID`.                                                              |
| Invalid fixture namespace                            | No query or mutation of a target.                                                                 | Real API: `422 FIXTURE_NAMESPACE_INVALID`.                                                 |
| Incorrect step-up secret                             | No step-up proof is issued.                                                                       | Real API: `401 DANGER_STEP_UP_REJECTED`.                                                   |
| Missing idempotency key                              | Commit is not attempted.                                                                          | Real API: `422 IDEMPOTENCY_KEY_REQUIRED`.                                                  |
| No scoped step-up                                    | Persisted preview remains denied; no fixture deletion.                                            | Real API: controlled `DENIED` receipt.                                                     |
| Revoked newest scoped step-up                        | Commit is denied; an older proof cannot be reused.                                                | Real API with a real revoked proof: controlled `DENIED` receipt.                           |
| Changed fixture target                               | Fingerprint mismatch denies commit and preserves the changed target.                              | Real API: controlled `DENIED` receipt.                                                     |
| Conflicting running operation                        | Operation-lock precondition fails.                                                                | Real API: controlled `DENIED` receipt.                                                     |
| Missing, wrong, stale, or modified recovery artifact | High-risk precondition fails closed.                                                              | Focused recovery metadata tests cover all four states.                                     |
| Runtime grant missing or malformed                   | Operations diagnostic is failed and all guarded writes return `503 OPERATION_LEDGER_UNAVAILABLE`. | Guard is exact-table based; pre-repair failure is retained in the acceptance history.      |
| Out-of-scope database action                         | The runtime identity cannot extend its scope.                                                     | Direct live SQL checks denied audit update, test-schema DDL, production read, and `GRANT`. |

The matrix does not simulate a real audit outage by stripping the accepted
runtime access. Audit failure remains fail-closed through the production code
path and requires a separately authorized fault-injection environment if it is
ever exercised end-to-end.
