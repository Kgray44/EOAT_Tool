#!/bin/sh
# Root-only bootstrap for the separately governed coordinated release helper.
set -eu

if [ "${1:-}" != "--source-dir" ] || [ "$#" -ne 2 ]; then
    echo "usage: sudo ./install_coordinated_release_retry.sh --source-dir /absolute/staged/privileged" >&2
    exit 64
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "install_coordinated_release_retry.sh must run as root" >&2
    exit 77
fi
source_dir=$2
case "$source_dir" in /*) ;; *) echo "source directory must be absolute" >&2; exit 64;; esac
helper="$source_dir/coordinated_release_retry.py"
web_helper="$source_dir/install_http_web_host.py"
sudoers="$source_dir/eoat-atlas-coordinated.sudoers"
for required in "$helper" "$web_helper" "$sudoers"; do
    [ -f "$required" ] || { echo "missing coordinated bootstrap file: $required" >&2; exit 66; }
done
grep -Fqx 'kgray ALL=(root) NOPASSWD: EOAT_ATLAS_COORDINATED' "$sudoers" || { echo "sudoers principal was modified" >&2; exit 65; }
grep -Fqx 'Cmnd_Alias EOAT_ATLAS_COORDINATED = /usr/bin/python3 /usr/local/libexec/eoat-atlas/coordinated_release_retry.py preflight --policy /etc/eoat-atlas/coordinated-release-policy.json, /usr/bin/python3 /usr/local/libexec/eoat-atlas/coordinated_release_retry.py activate --policy /etc/eoat-atlas/coordinated-release-policy.json, /usr/bin/python3 /usr/local/libexec/eoat-atlas/coordinated_release_retry.py post-activation-rollback --transaction *' "$sudoers" || { echo "sudoers command surface was modified" >&2; exit 65; }
install -d -o root -g root -m 0755 /usr/local/libexec/eoat-atlas
install -o root -g root -m 0750 "$helper" /usr/local/libexec/eoat-atlas/coordinated_release_retry.py
install -o root -g root -m 0750 "$web_helper" /usr/local/libexec/eoat-atlas/install_http_web_host.py
install -d -o root -g root -m 0755 /etc/eoat-atlas
install -o root -g root -m 0440 "$sudoers" /etc/sudoers.d/eoat-atlas-coordinated
visudo -cf /etc/sudoers.d/eoat-atlas-coordinated
