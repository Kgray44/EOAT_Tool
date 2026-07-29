# Coordinated release retry compatibility action

`reconcile-legacy-rollback --transaction <governed-id>` is a one-purpose,
root-only recovery action for historical coordinator 1.3.1 transaction
receipts with schema version 2. It accepts no policy, path, target, or force
argument.

It succeeds only when both live pointers already resolve to the receipt's
recorded old targets, the old targets freshly attest as immutable, API health
proves 0.22.12 / schema `20260721_0008` with writes disabled, NGINX and both
services are healthy, `data_state` is a singleton, and no later unresolved
transaction or deployment lock exists. It never rewrites pointers, reloads
NGINX, restarts services, changes MySQL, or edits the original receipt.

The action exclusively creates `post-activation-rollback.json` with fresh
attestations and `legacy_already_rolled_back` evidence. Existing evidence must
match exactly for an idempotent retry; conflicts fail closed. Normal
schema-version-3 `post-activation-rollback` behavior remains separate.
