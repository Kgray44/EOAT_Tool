#!/bin/sh
# Removes only the elevation entry and helper; release and transaction evidence
# remain intact for audit and recovery.
set -eu
if [ "${1:-}" != "--confirm-uninstall" ] || [ "$#" -ne 1 ]; then
    echo "usage: sudo ./uninstall_helper.sh --confirm-uninstall" >&2
    exit 64
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "uninstall_helper.sh must run as root" >&2
    exit 77
fi
rm -f /etc/sudoers.d/eoat-atlas-deploy
rm -f /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py
rmdir /usr/local/libexec/eoat-atlas 2>/dev/null || true
echo "EOAT Atlas deployment helper removed; deployment receipts and releases were preserved."
