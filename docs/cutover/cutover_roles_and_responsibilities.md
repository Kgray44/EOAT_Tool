# Cutover Roles and Responsibilities

| Role | Responsibilities |
|---|---|
| Incident commander | owns timeline, go/no-go, rollback trigger, communications |
| Database operator | account setup, migrations, backup, restore, schema/count verification |
| Application lead | release artifact, API, launcher/client configuration, monitoring |
| Data steward | freeze hashes, issue dispositions, parity and rollback reconciliation |
| UAT/business owner | executes business scenarios and signs acceptance |
| Service desk/communications | outage notice, user instructions, issue intake |
| Security approver | production identity, secret, network, logging review |

No single operator should both execute and approve a production restore. The local rehearsal may combine roles for convenience but records that as a production-only separation-of-duties gate.
