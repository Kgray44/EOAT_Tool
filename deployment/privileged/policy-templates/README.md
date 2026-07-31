# EOAT Atlas governed data-operation policy templates

These files are templates for a production administrator to copy to the fixed
root-owned directory `/etc/eoat-atlas/data-operations/`.  They are deliberately
not live policies: all placeholder hashes and source fields must be replaced
after the exact release, verified backup, and fresh dry-run inputs exist.

The installed file must be owned by root, non-symlinked, and non-writable by
group or world.  Its canonical `payload` JSON SHA-256 is stored in
`payload_sha256`; the main root helper digest is stored in `helper_sha256`.
The helper accepts neither the policy path nor any policy value from a caller.

`import-press-capacity.json` permits only the approved Plant 4 capacity import
scope. `migrate-profile-media.json` remains unusable until a media source is
classified `APPROVED_AND_ACCESSIBLE` and its exact roots are approved.
