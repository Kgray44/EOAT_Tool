# EOAT onboarding and editing V1

## Scope and production boundary

This candidate begins at accepted production source `a9206eee7917ea8a9f6f8ad281b1837c68fbc311` and schema `20260828_0017`. It does not deploy, alter production data, or write to the Press Capacity workbook. The feature is additive: a saved onboarding draft is not an `eoats` row and therefore cannot enter Library, Fit Check, QR, or ordinary compatibility queries before finalization.

## Inspected architecture

- `server/eoat_api/database/models.py` owns normalized EOAT, Machine, Tool, compatibility, installation/storage, document/photo, entity-history, audit-event, and change-feed tables. `EOAT` already preserves nullable versus zero/false values for the production fields, and uses `row_version` for optimistic concurrency.
- `server/eoat_api/write_contracts.py`, `write_routes.py`, and `write_services.py` are the established write boundary. Asset writes, compatibility writes, assignment transitions, document/photo metadata, profile-photo selection, audit events, history, and idempotency are already implemented there.
- Current location is intentionally separate from `EOATMachineCompatibility` and `EOATToolCompatibility`. `move_to_machine`, `move_to_storage`, and `mark_location_unknown` own the transaction and preserve the installed-versus-storage semantics. Fit Check evaluates the three explicit pairs; onboarding must not collapse them.
- Existing media is browser-safe only through UUID lookup plus approved-root validation (`web_content.py`) and existing document/photo metadata/link tables. Draft media must be staged outside ordinary EOAT links and adopted only in a successful finalization transaction.
- Authentication resolves an `ActorContext`; authorization is enforced server-side by `require(...)`. Corporate group-policy grants are constrained by `GROUP_POLICY_PERMISSIONS`, while protected Administrator authority remains restricted in `security.py`. The frontend may use session permissions only as a usability hint.
- The React application routes in `web/src/app/router.tsx`; profile pages already use shared profile cards, media, relationship, installation, and edit controls. Theme styling is token-based under `web/src/styles`, so onboarding pages will reuse those classes/tokens rather than add a palette.

## Implementation shape

The candidate adds an additive draft/reservation/staged-media representation with row-version checks, explicit lifecycle audit events, and dedicated onboarding routes. Finalization validates the current draft and referenced authoritative entities again, then uses the existing asset, compatibility, location, media, profile-photo, history, and audit mechanisms inside one database transaction. The same payload/section model powers creation and the dedicated EOAT edit route; sensitive identifier changes remain outside normal edits unless an elevated, auditable path is explicitly added.

The existing normalized `EOAT` model does not contain all engineering fields named in the product brief (for example detailed cylinder, sensor model, pneumatic circuit, and electrical pinout fields). V1 stores only its currently authoritative fields in normalized EOAT columns and retains draft-only/freeform information in governed notes until a separately justified authoritative-schema expansion is approved; it does not invent unsupported engineering facts.
