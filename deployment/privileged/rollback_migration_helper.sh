#!/bin/sh
set -eu
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 77; }
[ "${1:-}" = "--backup-dir" ] && [ "$#" -eq 2 ] || { echo "usage: --backup-dir /opt/eoat-atlas/shared/helper-backups/TIMESTAMP" >&2; exit 64; }
case "$2" in /opt/eoat-atlas/shared/helper-backups/*) ;; *) echo "unsafe backup path" >&2; exit 64;; esac
test -f "$2/helper.py" && test -f "$2/sudoers" && test -f "$2/manifest.json"
install -o root -g root -m 0750 "$2/helper.py" /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py
install -o root -g root -m 0440 "$2/sudoers" /etc/sudoers.d/eoat-atlas-deploy
visudo -cf /etc/sudoers.d/eoat-atlas-deploy
install -o root -g root -m 0640 "$2/manifest.json" /etc/eoat-atlas/deployment-helper.manifest.json
echo "helper package rolled back; no service restart or database action was performed"
