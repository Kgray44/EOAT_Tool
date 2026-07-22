#!/bin/sh
# Human-admin bootstrap only.  It never deploys EOAT Atlas or changes MySQL.
set -eu

if [ "${1:-}" != "--source-dir" ] || [ "$#" -ne 2 ] || [ "$(id -u)" -ne 0 ]; then
    echo "usage: sudo ./install_migration_helper.sh --source-dir /absolute/staged/privileged" >&2
    exit 64
fi
source_dir=$2
case "$source_dir" in /*) ;; *) echo "source directory must be absolute" >&2; exit 64;; esac
helper="$source_dir/eoat_atlas_deploy_helper.py"
sudoers="$source_dir/eoat-atlas-deploy.sudoers"
manifest="$source_dir/helper.manifest.json"
checksum="$source_dir/helper.sha256"
for file in "$helper" "$sudoers" "$manifest" "$checksum"; do [ -f "$file" ] || { echo "missing package file" >&2; exit 66; }; done
(cd "$source_dir" && sha256sum -c helper.sha256)
grep -Fqx 'kgray ALL=(root) NOPASSWD: EOAT_ATLAS_DEPLOY' "$sudoers"
grep -Fqx 'Cmnd_Alias EOAT_ATLAS_DEPLOY = /usr/bin/python3 /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py --request-b64 *' "$sudoers"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_root=/opt/eoat-atlas/shared/helper-backups/$stamp
install -d -o root -g root -m 0700 "$backup_root"
for pair in \
  "/usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py helper.py" \
  "/etc/sudoers.d/eoat-atlas-deploy sudoers" \
  "/etc/eoat-atlas/deployment-helper.manifest.json manifest.json"; do
    set -- $pair
    [ ! -e "$1" ] || cp -p "$1" "$backup_root/$2"
done
restore() {
    if [ -f "$backup_root/helper.py" ]; then install -o root -g root -m 0750 "$backup_root/helper.py" /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py; else rm -f /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py; fi
    if [ -f "$backup_root/sudoers" ]; then install -o root -g root -m 0440 "$backup_root/sudoers" /etc/sudoers.d/eoat-atlas-deploy; else rm -f /etc/sudoers.d/eoat-atlas-deploy; fi
    if [ -f "$backup_root/manifest.json" ]; then install -o root -g root -m 0640 "$backup_root/manifest.json" /etc/eoat-atlas/deployment-helper.manifest.json; else rm -f /etc/eoat-atlas/deployment-helper.manifest.json; fi
}
trap 'restore; exit 1' HUP INT TERM

install -d -o root -g root -m 0755 /usr/local/libexec/eoat-atlas /etc/eoat-atlas
install -d -o root -g eoat-atlas -m 2770 /opt/eoat-atlas/shared/backups /opt/eoat-atlas/shared/deployment-transactions /opt/eoat-atlas/shared/deployment-receipts
install -o root -g root -m 0750 "$helper" /usr/local/libexec/eoat-atlas/.eoat-helper.new
install -o root -g root -m 0440 "$sudoers" /etc/sudoers.d/.eoat-atlas-deploy.new
visudo -cf /etc/sudoers.d/.eoat-atlas-deploy.new
install -o root -g root -m 0640 "$manifest" /etc/eoat-atlas/.deployment-helper.manifest.new
mv -f /usr/local/libexec/eoat-atlas/.eoat-helper.new /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py
mv -f /etc/sudoers.d/.eoat-atlas-deploy.new /etc/sudoers.d/eoat-atlas-deploy
mv -f /etc/eoat-atlas/.deployment-helper.manifest.new /etc/eoat-atlas/deployment-helper.manifest.json
/usr/bin/python3 /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py --request-b64 eyJvcGVyYXRpb24iOiJzZWxmLWNoZWNrIn0=
trap - HUP INT TERM
echo "installed without restarting EOAT Atlas; backup=$backup_root"
