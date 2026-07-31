# EOAT Atlas privileged deployment helper

`eoat_atlas_deploy_helper.py` is the sole root component of Phase 3.  It
accepts one base64-encoded JSON request, runs as root only, and exposes these
fixed operations: `begin`, `stage`, `activate`, `status`, `abort`, `rollback`,
`recover`, `retention-status`, `host-config-status`, `install-web-host-config`,
`validate-web-host-config`, `rollback-web-host-config`, and explicit
`rotate-web-upstream-token`.

It also exposes two policy-pinned operational-data actions:
`import-press-capacity` and `migrate-profile-media`.  The caller supplies only
the operation, an opaque request ID, and `dry-run` or `execute`; it cannot
supply SQL, a database name, command, source root, destination root, policy
path, candidate, or backup.  Each action is defined by a root-owned
non-group/world-writable JSON policy in `/etc/eoat-atlas/data-operations/`.
The policy pins the main helper digest, canonical policy payload digest,
production database identity, candidate/backup receipt hashes, release/schema
identity, and fixed operation inputs.  Execution requires a fresh matching
dry-run receipt, shares the deployment lock, and writes a non-overwriting
receipt with rollback instructions.  A policy is an installed operational
artifact, never a caller-provided authority.

It never accepts a shell command, executable, service name, filesystem root,
environment-file content, or database credentials from its caller.  Its only
service action is `/bin/systemctl restart eoat-atlas.service`; its only health
probe is the local EOAT API health endpoint.  Archive validation rejects path
traversal, symlinks, device/FIFO nodes, and missing runtime files.  The helper
uses an exclusive root-owned lock, durable transaction/receipt JSON, atomic
symlink replacement, and rollback on post-activation health failure.

Web-host operations use that same mutation lock and only resolve an immutable
release by its release ID. They verify manifest-listed NGINX and systemd
templates plus static assets, back up only the EOAT-approved host paths, and
write a CSPRNG server-only upstream token without returning or recording it.
Reinstall preserves a matching existing token; a mismatch fails closed.

`install_helper.sh` is a human-only, interactive one-time bootstrap.  It
installs a root-owned `0750` helper, validates a root-owned `0440` sudoers file
with `visudo`, and creates only dedicated control directories.  It does not
alter the deployed release, runtime environment, service configuration, NGINX,
or MySQL.  `uninstall_helper.sh` removes the helper/sudo rule only when passed
`--confirm-uninstall`; it intentionally preserves recovery evidence.

The checked-in sudo rule grants `kgray` exactly the Python helper invocation
with `--request-b64`.  The wildcard represents only the opaque structured
request; extra arguments are rejected by `argparse`, and unrecognized request
fields are rejected before any action.
