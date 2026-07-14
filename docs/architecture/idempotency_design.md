# Idempotency Design

Critical requests carry `Idempotency-Key`. `idempotency_records` scopes keys by authenticated actor and operation and stores a canonical request SHA-256, request ID, response JSON, status, and result reference. A repeated key and identical body returns the original result with `idempotent_replay=true`; a changed body returns HTTP 409 `IDEMPOTENCY_KEY_REUSED`.

The idempotency row is committed in the same transaction as the business result. This covers asset creation, moves, installation close, audit/maintenance creation and completion, document/photo creation, and similar gateway calls. Non-idempotent writes are not recursively retried.
