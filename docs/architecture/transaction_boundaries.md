# Transaction Boundaries

- Every API write dependency owns one SQLAlchemy session and one transaction. Business rows, audit rows, history, change feed, and idempotency result commit or roll back together.
- EOAT move-to-machine locks the EOAT and target machine, validates active state and compatibility, closes active storage/installation rows, creates one installation, increments the EOAT version, and emits evidence in one transaction.
- Move-to-storage similarly closes both possible active locations before creating one storage assignment. Generated unique markers additionally prevent two active machine installations or two active storage rows for one EOAT.
- Mark-location-unknown requires explicit confirmation and a reason, closes active records without deleting history, then emits audit/history/feed records.
- Audit and maintenance completion update the structured record and evidence together. Completed maintenance cannot be casually edited.
- Document/photo metadata is inserted only after the referenced file exists and passes controlled-root validation when roots are configured.
- Optional Fit Check history uses a savepoint so a history failure cannot falsify a valid evaluation result.
- Import batches are all-or-nothing and are rejected on a completed same-source checksum.
