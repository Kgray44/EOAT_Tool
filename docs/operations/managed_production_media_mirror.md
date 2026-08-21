# Managed production media mirror

EOAT Atlas production keeps the authoritative document `storage_path` in the
database.  Photo paths remain corporate UNC paths.  This procedure creates a
separate, hash-verified Debian mirror and a JPEG-only web tree; it never mounts
SMB, changes source photos, or rewrites document records.

## Layout and boundary

The approved production layout is `/var/lib/eoat-atlas/media`:

```text
originals/<document-uuid>/<original filename>  # immutable source copy
web/<document-uuid>.jpg                        # browser-facing derivative
manifest/media-manifest.json                    # private UUID/source/hash map
incoming/                                      # group-writable SSH transfer area
```

`originals`, `web`, and `manifest` are owned by `root:eoat-atlas` and mode
`2750`; normal API serving needs read access only. `incoming` is
`kgray:eoat-atlas`, mode `2770`, so the approved Windows SSH identity can
transfer a package without granting it write access to published media.

When `EOAT_WEB_MEDIA_MANIFEST` is configured, a photo request can resolve only
when all of these match: the database document UUID, its authoritative stored
source path, exactly one manifest entry, and a relative `.jpg` file underneath
`EOAT_WEB_CONTENT_ROOTS`. The API returns JPEG from the controlled `web` tree,
not the UNC source or archival original. The manifest is never an API response.

## One-time provisioning

Run on the established Debian host as an approved sudo operator:

```bash
sudo install -d -o root -g eoat-atlas -m 2750 \
  /var/lib/eoat-atlas/media \
  /var/lib/eoat-atlas/media/originals \
  /var/lib/eoat-atlas/media/web \
  /var/lib/eoat-atlas/media/manifest
sudo install -d -o kgray -g eoat-atlas -m 2770 /var/lib/eoat-atlas/media/incoming
sudo install -d -o root -g eoat-atlas -m 2750 /opt/eoat-atlas/shared/media-tools
```

Install the two versioned scripts from the exact release candidate under test
into `/opt/eoat-atlas/shared/media-tools`, owned `root:eoat-atlas`, mode `0750`.
Do not run unversioned scripts from a user home directory.

## Sync procedure

1. On Debian, export an inventory using the existing protected runtime
   environment. The command reads only the `documents`, `photos`,
   `document_links`, and `eoats` tables. It writes the private inventory under
   `incoming/manifest`; it does not print source paths or credentials.

   ```bash
   sudo -u eoat-atlas bash -c '
     set -a; . /etc/eoat-atlas/runtime.env; set +a
     /opt/eoat-atlas/current/venv/bin/python \
       /opt/eoat-atlas/shared/media-tools/export_linked_photo_inventory.py \
       --output /var/lib/eoat-atlas/media/incoming/manifest/inventory.json
   '
   ```

2. Copy that private inventory to the authorized Windows workstation over the
   already-approved SSH connection. Run `stage` on Windows with the exact UNC
   prefix. It computes SHA-256 itself, refuses missing paths, prefix escapes,
   stale inventory hashes, and a changed source that conflicts with an earlier
   staged copy. It does not modify the UNC source.

   ```powershell
   python scripts/media/sync_eoat_media.py stage `
     --inventory .\inventory.json `
     --source-prefix '\\gwplastics.com\VT' `
     --staging-root "$env:LOCALAPPDATA\EOAT Atlas\media-transfer"
   ```

3. Transfer the generated `originals/` and `manifest/staged-inventory.json`
   with the established SSH/SFTP identity into
   `/var/lib/eoat-atlas/media/incoming`. Do not use a CIFS mount or create an
   SMB service account.

4. On Debian, run `sync` as an approved sudo operator. It verifies every
   transferred hash before copying an original, creates or repairs only missing
   JPEG derivatives, then atomically replaces the manifest. It never deletes
   originals. A changed source is a hard `SOURCE_CHANGED` result and requires a
   separate governed decision rather than replacement in place.

   ```bash
   sudo /opt/eoat-atlas/current/venv/bin/python \
     /opt/eoat-atlas/shared/media-tools/sync_eoat_media.py sync \
     --staged-inventory /var/lib/eoat-atlas/media/incoming/manifest/staged-inventory.json \
     --staging-root /var/lib/eoat-atlas/media/incoming \
     --media-root /var/lib/eoat-atlas/media
   ```

The manifest records document UUID, EOAT links, source UNC path, source hash,
mirrored-original path, web derivative path/hash/dimensions, source format,
conversion parameters, and synchronization time. Unreferenced originals are
reported as orphans and are never deleted by sync.

## Conversion settings

HEIC/HEIF decoding uses the pinned `Pillow` and `pillow-heif` dependencies.
Every browser derivative is an orientation-corrected RGB JPEG, progressive,
quality `94`, 4:4:4 subsampling (`0`). Only capture-time EXIF fields are kept;
device and location metadata are omitted. JPEG originals remain archived
byte-for-byte and receive a separate controlled JPEG derivative, so they are
not recompressed in place or at request time.

## Runtime configuration and release handoff

The combined Photo + Fit Check release must set these existing protected
environment-file values as part of its authorized activation, then restart only
that hash-bound release:

```text
EOAT_WEB_CONTENT_ROOTS=/var/lib/eoat-atlas/media
EOAT_WEB_MEDIA_MANIFEST=/var/lib/eoat-atlas/media/manifest/media-manifest.json
```

Do not set a UNC-to-filesystem mapping for these photos. The manifest resolver
is the mapping. The current `0.26.11-d032a8f` service does not consume the new
manifest variable, so no restart or application deployment is part of mirror
provisioning alone.

Before release activation, validate at least five EOATs using the candidate API:

* all inventory originals hash-match the staged source hashes;
* the second `sync` reports zero copied originals and zero generated
  derivatives;
* the two original JPEG records and representative HEIC records return
  `image/jpeg` from both thumbnail and full-content endpoints;
* Library availability, profile hero selection, and Docs & Photos gallery use
  the same selected document UUID;
* the service account can read `web/` but cannot write `originals/` during
  normal serving; and
* invalid UUIDs, a manifest/source-path mismatch, traversal, and paths outside
  `/var/lib/eoat-atlas/media` remain unavailable or forbidden without exposing
  filesystem or UNC paths.
