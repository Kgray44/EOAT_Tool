# EOAT Atlas privileged deployment helper

`eoat_atlas_deploy_helper.py` is the sole root component of Phase 3.  It
accepts one base64-encoded JSON request, runs as root only, and exposes these
fixed operations: `begin`, `stage`, `activate`, `status`, `abort`, `rollback`,
`recover`, and `retention-status`.

It never accepts a shell command, executable, service name, filesystem root,
environment-file content, or database credentials from its caller.  Its only
service action is `/bin/systemctl restart eoat-atlas.service`; its only health
probe is the local EOAT API health endpoint.  Archive validation rejects path
traversal, symlinks, device/FIFO nodes, and missing runtime files.  The helper
uses an exclusive root-owned lock, durable transaction/receipt JSON, atomic
symlink replacement, and rollback on post-activation health failure.

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
