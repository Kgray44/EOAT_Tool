# EOAT physical-location semantics

Schema revision `20260717_0007` separates an observed present state from a lifecycle event.

- `eoat_installations` means a real installation event with a known `installed_at`.
- `eoat_storage_assignments` means a real storage movement with a known `stored_at` and real location.
- `eoat_location_observations` records an authoritative view of current state without inventing either event.
- `eoat_location_assertions` preserves each workbook row supporting an observation or conflict set.
- Compatibility tables describe where an EOAT may run. They are never current-location evidence.

The five normalized states are `INSTALLED`, `STORED`, `UNKNOWN`, `INACTIVE`, and `CONFLICTING`. A stored observation may have no `storage_location_id`; this means storage is proven but the cabinet/location is unspecified. It must not be replaced by a made-up generic cabinet.

## Owner-approved workbook normalization

The reviewed policy in `config/eoat_location_normalization.json` is authoritative for the operational migration:

- An audited `Press/Machine #` value of `N/A` means `STORED`, with both `machine_id` and `storage_location_id` null.
- `26 - Xqual in 25` is retained in raw workbook/import evidence but normalizes to Machine `26` everywhere a machine relationship is represented.
- Same-day Cleanroom evidence that proves simultaneous identical units is split into physical EOAT masters. The preserved original and the deterministic added IDs retain the shared compatibility relationships; only the evidence row assigned to a unit moves with that unit. Documents, photos, lifecycle history, and unrelated audits are not copied.
- Plant 4 multi-machine audit sequences without duplicate-pair proof are treated as movement evidence, not physical duplicates. When no present machine is reliable, the observed state is `STORED` with cabinet unspecified.

These are observed-current-state decisions, not installation/removal/storage lifecycle events. They never invent event timestamps, cabinet identifiers, actors, or lifecycle history.

## Time precision and precedence

Workbook audits currently provide a date, not a time. Such evidence has `observed_on`, a null `observed_at`, and `observation_precision=DATE`. Exact event timestamps remain in lifecycle tables. The resolver applies these rules:

1. Consider only active lifecycle rows and authoritative, non-superseded observations.
2. A lifecycle event wins only when its exact event time is provably later than the observation.
3. An observation wins when it is later than the event.
4. A date-only observation and event on the same date produce `CONFLICTING`; insertion order never decides chronology.
5. Simultaneous active installation and storage rows produce `CONFLICTING`.
6. With no evidence, return `UNKNOWN`.

The importer is deterministic and restart-safe:

```powershell
python scripts/database/import_eoat_location_observations.py `
  --workbook <EOAT_Master_Tracker.xlsx> `
  --env development `
  --output <plan.json>

python scripts/database/import_eoat_location_observations.py `
  --workbook <EOAT_Master_Tracker.xlsx> `
  --env development `
  --output <applied.json> `
  --apply
```

It requires the current application schema `20260721_0008`, refuses a production-named source, requires the reviewed 57-state distribution, uses UUIDv5 identifiers, and rejects mixed/partial row counts. The later revision retains the observation model and adds independent freshness metadata.

## API and client

EOAT list/detail payloads include `current_location` and structured `current_location_detail`. `GET /api/v1/eoats/{id}/current-location` exposes the resolved result. `GET /api/v1/eoats/{id}/location-observations` returns explicitly labeled observed-current-state evidence. Machine current setup is derived from the same resolver. Fit Check and compatibility endpoints remain independent.
