# EOAT Atlas Unified Release Train — Phase 3B

Phase 3B adds the disposable-only signed client-channel model. Channel payloads
are canonical compact JSON, signed with Ed25519, carry release-set and desktop/
launcher identity, and are persisted in append-only per-channel history.
`current.json` is an atomic pointer; retries are idempotent only for identical
bytes, sequence regressions and broken predecessor chains fail closed, and a
rollback is a new higher signed sequence.

Candidate, canary, and stable promotion are designed around the same trusted
release identity. Canary requires confirmed API/web acceptance; stable requires
explicit authorization after an observation gate. Cohorts use only an opaque
installation ID and public policy salt. Rollout status deliberately excludes
usernames, machine names, filesystem paths, documents, content, and tokens.

Production adapters are planning/readiness-only in this phase. A production
change package is deterministic from verified input and contains no secrets.
The readiness result remains `IMPLEMENTATION_READY_LIVE_AUTHORIZATION_REQUIRED`
without an unexpired external authorization, known baseline, and verified
helper capability. No production channel, tag, GitHub Release, server, MySQL,
NGINX, systemd, sudo policy, or workstation is touched.

## Accepted disposable CI evidence

Implementation commit `781fc45d51` was accepted by **Unified Release Train
Phase 3B** workflow run
[`30364313689`](https://github.com/Kgray44/EOAT_Tool/actions/runs/30364313689).
All required jobs succeeded: channel-model, signed-channel-manifests,
immutable-channel-history, candidate-promotion, canary-promotion,
stable-promotion, channel-rollback, cohort-policy, Bootstrap-channel-
consumption, Launcher-desktop-channel-consumption, observation-gates,
rollout-status-privacy, production-publisher-adapter,
production-deployment-adapter, change-package, go-no-go-evaluator,
drift-scanner, CLI-console-smoke, black-box-disposable-promotion,
receipt-compatibility, repository-safety, version-governance, and
documentation-command-validation. The run used disposable signing material
only; no test was intentionally skipped.
