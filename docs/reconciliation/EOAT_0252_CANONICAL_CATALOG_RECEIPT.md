# EOAT Atlas Plant 4 canonical catalog retrieval receipt

Date: 2026-07-30
Mode: production API `GET` requests only; no database credential, write route,
maintenance lock, migration, service, or deployment operation was used.

## Production boundary at retrieval

| Property | Observed value |
| --- | --- |
| Application / release | `0.24.1` / `eoat-atlas-0.24.1` |
| Build identity | `eoat-atlas-0.24.1-cfc8917-20260729T130842Z` |
| API contract | `1.4.0` |
| Current / expected schema | `20260721_0008` / `20260721_0008` |
| Schema compatible | Yes |
| Production writes enabled | No |

The catalog was retrieved at `2026-07-30T19:55:28Z` from the existing
read-only API contract: health, version, an `include_inactive=true` machine
listing filtered by explicit `plant=P4`, and one plant-qualified profile GET
per returned machine. `P4` is an API plant field, not a number-range
assumption.

## Sanitized external evidence

The catalog itself is retained outside Git in the governed inspection-evidence
location. It contains only API identity, machine number, plant, area, display
metadata, activity/status, row version, existing capacity, units, and the
API-contract alias-availability statement. It contains no credential,
connection string, token, raw database export, notes, or relationship data.

| Artifact | SHA-256 |
| --- | --- |
| Canonical catalog payload | `7aff11deb44240ec9e4397545094305ec6e3f13020e040ae11c7b7e5fb6c0074` |
| Canonical catalog manifest file | `ab45a39519b1a302d67c84d17f1cdba9c03da516e872dca657d163db19872550` |
| Catalog-to-capacity dry-run manifest | `d4aea35afd50c0737e2780c9f82e72a0ea3a0033a6bef2ba9c427b656623c254` |

The production API contract does not expose governed machine aliases or a
database UUID. Each catalog record therefore uses its plant-qualified API
identity plus API row version as its stable read identity, and records the
absence of alias data rather than inventing aliases.

A preliminary local artifact was rejected before planning because its generated
API identity field was not unique. It was retained outside Git for audit only,
excluded from every calculation, and replaced by the catalog above after a
fresh GET-only retrieval verified 56 unique plant-qualified identities.

## Scope result

The listing returned 56 canonical `P4` records: 56 active, zero inactive, and
zero with an existing `press_capacity_tons` value. It has no duplicate active
machine numbers or alias collisions. These observations are the input to the
[canonical capacity mapping review](EOAT_0252_CANONICAL_CAPACITY_MAPPING.md),
not authorization to execute an import.

A post-goal health/version GET returned the same release, schema, compatible
state, and `writes_enabled: false`; production remained unchanged.
