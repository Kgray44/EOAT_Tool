#!/bin/sh
# Must be executed interactively by a human administrator.  This script is not
# granted through sudoers and is intentionally separate from deployments.
set -eu

if [ "${1:-}" != "--source-dir" ] || [ "$#" -ne 2 ]; then
    echo "usage: sudo ./install_helper.sh --source-dir /absolute/staged/privileged" >&2
    exit 64
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "install_helper.sh must run as root" >&2
    exit 77
fi

source_dir=$2
case "$source_dir" in
    /*) ;;
    *) echo "source directory must be absolute" >&2; exit 64 ;;
esac
helper="$source_dir/eoat_atlas_deploy_helper.py"
sudoers="$source_dir/eoat-atlas-deploy.sudoers"
for required in "$helper" "$sudoers"; do
    [ -f "$required" ] || { echo "missing bootstrap file: $required" >&2; exit 66; }
done
grep -Fqx 'kgray ALL=(root) NOPASSWD: EOAT_ATLAS_DEPLOY' "$sudoers" || {
    echo "sudoers principal or command alias was modified" >&2; exit 65;
}
grep -Fqx 'Cmnd_Alias EOAT_ATLAS_DEPLOY = /usr/bin/python3 /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py --request-b64 *' "$sudoers" || {
    echo "sudoers helper command was modified" >&2; exit 65;
}

install -d -o root -g root -m 0755 /usr/local/libexec
install -d -o root -g root -m 0755 /usr/local/libexec/eoat-atlas
install -o root -g root -m 0750 "$helper" /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py
install -o root -g root -m 0440 "$sudoers" /etc/sudoers.d/eoat-atlas-deploy
visudo -cf /etc/sudoers.d/eoat-atlas-deploy

# Only dedicated control directories are provisioned.  Existing releases,
# current/previous symlinks, runtime.env, services, and database are untouched.
install -d -o root -g eoat-atlas -m 2770 /opt/eoat-atlas/incoming
install -d -o root -g eoat-atlas -m 2770 /opt/eoat-atlas/shared/deployment-transactions
install -d -o root -g eoat-atlas -m 2770 /opt/eoat-atlas/shared/deployment-receipts
install -d -o root -g eoat-atlas -m 2770 /opt/eoat-atlas/shared/backups
install -d -o root -g root -m 0700 /opt/eoat-atlas/shared/host-config-transactions
install -d -o root -g root -m 0700 /opt/eoat-atlas/shared/host-config-receipts
install -d -o root -g root -m 0700 /opt/eoat-atlas/shared/host-config-backups
echo "EOAT Atlas privileged deployment helper installed. Verify with: sudo -l -U kgray"
