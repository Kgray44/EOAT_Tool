#!/bin/sh
set -eu
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 77; }
test -f /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py
test "$(stat -c %a /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py)" = 750
test "$(stat -c %a /etc/sudoers.d/eoat-atlas-deploy)" = 440
visudo -cf /etc/sudoers.d/eoat-atlas-deploy
# Fixed self-check request; no caller-controlled helper operation is used.
/usr/bin/python3 /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py --request-b64 eyJvcGVyYXRpb24iOiJzZWxmLWNoZWNrIn0=
stat -c '%n %U %G %a' /opt/eoat-atlas/shared/backups /opt/eoat-atlas/shared/deployment-receipts
