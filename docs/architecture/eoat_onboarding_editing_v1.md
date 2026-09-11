# EOAT onboarding and editing V1

## Scope and production boundary

This candidate begins at accepted production source `a9206eee7917ea8a9f6f8ad281b1837c68fbc311` and schema `20260828_0017`. EOAT Atlas 0.27.0 advances the intended production migration path through `20260904_0018` to `20260910_0019`; the release preflight must therefore start at `20260828_0017` and finish at `20260910_0019`. It does not deploy, alter production data, or write to the Press Capacity workbook. The feature is additive: a saved onboarding draft is not an `eoats` row and therefore cannot enter Library, Fit Check, QR, or ordinary compatibility queries before finalization.

## Inspected architecture

- `server/eoat_api/database/models.py` owns normalized EOAT, Machine, Tool, compatibility, installation/storage, document/photo, entity-history, audit-event, and change-feed tables. `EOAT` already preserves nullable versus zero/false values for the production fields, and uses `row_version` for optimistic concurrency.
- `server/eoat_api/write_contracts.py`, `write_routes.py`, and `write_services.py` are the established write boundary. Asset writes, compatibility writes, assignment transitions, document/photo metadata, profile-photo selection, audit events, history, and idempotency are already implemented there.
- Current location is intentionally separate from `EOATMachineCompatibility` and `EOATToolCompatibility`. `move_to_machine`, `move_to_storage`, and `mark_location_unknown` own the transaction and preserve the installed-versus-storage semantics. Fit Check evaluates the three explicit pairs; onboarding must not collapse them.
- Existing media is browser-safe only through UUID lookup plus approved-root validation (`web_content.py`) and existing document/photo metadata/link tables. Draft media must be staged outside ordinary EOAT links and adopted only in a successful finalization transaction.
- Authentication resolves an `ActorContext`; authorization is enforced server-side by `require(...)`. Corporate group-policy grants are constrained by `GROUP_POLICY_PERMISSIONS`, while protected Administrator authority remains restricted in `security.py`. The frontend may use session permissions only as a usability hint.
- The React application routes in `web/src/app/router.tsx`; profile pages already use shared profile cards, media, relationship, installation, and edit controls. Theme styling is token-based under `web/src/styles`, so onboarding pages will reuse those classes/tokens rather than add a palette.

## Implementation shape

The candidate adds an additive draft/reservation/staged-media representation with row-version checks, explicit lifecycle audit events, and dedicated onboarding routes. Finalization validates the current draft and referenced authoritative entities again, then uses the existing asset, compatibility, location, media, profile-photo, history, and audit mechanisms inside one database transaction. The same payload/section model powers creation and the dedicated EOAT edit route; sensitive identifier changes remain outside normal edits unless an elevated, auditable path is explicitly added.

The baseline `EOAT` table did not contain detailed cylinder, sensor model, pneumatic circuit, or electrical connection data. Migration `20260904_0018` adds the authoritative one-to-one `eoat_engineering_profiles` extension for the supported V1 fields, while freeform claims that lack a defensible model remain governed notes rather than invented engineering facts.

## Command Center data parity

The original EOAT Command Center audit registry is the source reference for
onboarding field labels, controlled options, and automatic defaults. The web
workflow now uses its controlled values for EOAT type, status, interface,
environment, cylinder/gripper choices, operating-condition choices, and the
inspection/documentation assessment fields. Its normal asset fields continue
to finalize into `eoats`; Command Center-only engineering and inspection
details finalize into the versioned `eoat_engineering_profiles.command_center_data`
record added by migration `20260910_0019`.

The preserved fields include EOAT movement, part and robot context, split
robot/external pneumatic circuits, quick-disconnect types, routing and
mechanical condition, reliability/maintenance findings, documentation status,
priority/follow-up/pilot data, and assessment context. Defaults are applied
server-side as well as in the browser: Robot Only air architecture, zero robot
interchangeable circuits, N/A external circuits, PTC pneumatic quick
disconnect, and the Command Center's explicit unknown/no defaults. Selecting
part-present sensing fills Reed Switch and SMC only when those values are still
blank; ATI and DoveTail apply Low and Medium changeover defaults only while the
field remains at its unknown default. This keeps intentional values intact.

## Requiredness calibration

Requiredness is calibrated from the audited physical-record subset of the
authoritative Master Tracker (`EOAT_Master_Tracker.xlsx`, SHA-256
`C3A43289930FBFC38E678302DE9952A6F6B7654925891B185534D63FBAB49F4C`): 67
audited rows without a source-audit reference. The finalization gate requires
the consistently captured identity, interface, environment, pickup,
inspection, circuit, part-context, condition, documentation-status, and
follow-up values. Vacuum, gripper, cylinder, and sensor details are required
only when their applicable hardware is selected. Explicit zero, No, N/A, and
controlled unknown values remain valid answers; an empty value does not.

Machine/Tool assignment, robot make/model, revision, freeform notes, external
circuit details, cable/alignment observations, and a staged upload remain
optional because the tracker commonly records them as N/A, unknown, or absent.
Draft saving is never blocked by these requirements; the review response lists
each omission and finalization refuses it until corrected.

## Operational configuration and staging acceptance

`EOAT_ONBOARDING_ENABLED` defaults to `false`; enabling the candidate requires an explicit environment change after migration and staging UAT. `EOAT_ONBOARDING_STAGING_ROOT` must be an existing controlled filesystem directory, and it must also be listed in `EOAT_DOCUMENT_ROOTS` so finalization can adopt the staged file through the normal document validation path. The upload endpoint rejects an absent root, names that escape the staging directory, invalid base64, and files over 25 MB.

Staging acceptance must prove: a Technician can prepare only their own draft; an Engineer can review/finalize it; an identifier cannot be reserved twice; stale saves return a conflict; discard releases a reservation; a Front photo becomes the profile photo; a finalization failure creates neither a normal EOAT nor compatibility/media links; and an accepted EOAT is visible in Library, profile, Fit Check, history, and QR-label flows. Promotion rollback is additive: turn the flag off, retain drafts and controlled staged files for recovery, restore the retained 0.26.x production release as the application rollback target, and use the normal schema rollback only under the existing deployment procedure. Migration `20260910_0019` downgrades by dropping only its `command_center_data` column; it intentionally retains lookup rows that may have pre-existed or be in use.
