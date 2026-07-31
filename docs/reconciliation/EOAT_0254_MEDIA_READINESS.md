# EOAT Atlas 0.25.4 media readiness

## Classification

`NOT_LOCATED`

No approved and accessible production media root is available in the checked-in
EOAT Atlas configuration or the controlled engineering references reviewed on
2026-07-30. No media was copied, repointed, indexed, or exposed.

## Controlled sources reviewed

- `server/eoat_api/web_content.py` and production runtime contracts: browser
  delivery accepts only server-side approved roots and path mappings.
- `docs/WEB_PHASE_3_PRODUCTION_HOSTING.md`: an approved media mount is an
  explicit deployment gate; without it the mapping must remain empty.
- `docs/reconciliation/EOAT_0252_VALIDATION_RECOVERY.md`: the sanitized
  default root was absent during the prior controlled review.
- `tools/migration/media_migration.py`: a dry-run-first UUID-addressed
  migration exists, but requires source roots and a verified database-backup
  receipt for execution.
- `EOAT_MEDIA_SOURCE_MANIFEST_TEMPLATE.md`: the approval packet contract.

The legacy Photo Index describes metadata and naming evidence, not an approved
browser-serving source root. It therefore cannot authorize discovery or copy
of company storage.

## Result and next external action

Browser metadata and unavailable-media fallbacks remain fail-closed and
truthful. The `migrate-profile-media` policy template intentionally contains
placeholders and is not installable until an owner supplies an approved logical
source, sanitized server-side root, recursion/file-type scope, identity
crosswalk, and read-only mount confirmation using the manifest template.

At that point, run the governed inventory/dry run, hash and validate every
file, reject ambiguity and path escapes, verify thumbnails in disposable
staging, then bind the approved manifest and verified backup to the root-owned
policy. No production media operation is authorized by this readiness record.
