# EOAT Atlas 0.24.1 release notes

EOAT Atlas 0.24.1 corrects two zero-migration deployment acceptance defects
identified during the preserved 0.23.6 production attempt.

- Machine relationship-flow columns retain authoritative non-routable
  assignment semantics. An unverified current tool or mold now states
  `Current tool / mold not verified`; `NONE_OBSERVED` states that no current
  assignment was observed. Neither value creates an entity, route, QR target,
  Fit Check input, or recent item.
- The legacy root-owned coordinated release helper now validates the governed
  `eoat-atlas:eoat-atlas` API release model through receipt-bound immutable
  attestations. Root ownership remains mandatory for coordinator control data,
  policies, transactions, sealed artifacts, and frontend releases.
- Transaction receipt schema 3 records prior API and frontend attestations
  before activation. Schema 2 receipts remain preserved evidence and produce a
  clear compatibility diagnostic rather than being reinterpreted.

This source change does not deploy, migrate, enable writes, or alter
production data.
