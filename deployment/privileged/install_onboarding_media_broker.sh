#!/bin/sh
# Human-only bootstrap for the root-owned onboarding media broker.
set -eu

if [ "${1:-}" != "--source-repository" ] || [ "${3:-}" != "--source-commit" ] || [ "$#" -ne 4 ]; then
    echo "usage: sudo ./install_onboarding_media_broker.sh --source-repository /absolute/protected-checkout --source-commit <40-hex-sha>" >&2
    exit 64
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "install_onboarding_media_broker.sh must run as root" >&2
    exit 77
fi

source_repository=$2
source_commit=$4
case "$source_repository" in
    /*) ;;
    *) echo "source repository must be absolute" >&2; exit 64 ;;
esac
case "$source_commit" in
    *[!0123456789abcdef]*)
        echo "source commit must be a lowercase 40-character SHA" >&2
        exit 64
        ;;
esac
[ "${#source_commit}" -eq 40 ] || {
    echo "source commit must be a lowercase 40-character SHA" >&2
    exit 64
}
git -C "$source_repository" rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
    echo "source repository is not a Git checkout" >&2
    exit 66
}
[ "$(git -C "$source_repository" rev-parse HEAD)" = "$source_commit" ] || {
    echo "source repository HEAD does not match the approved protected commit" >&2
    exit 66
}
[ -z "$(git -C "$source_repository" status --porcelain --untracked-files=all)" ] || {
    echo "source repository has local changes" >&2
    exit 66
}

source_dir="$source_repository/deployment/privileged"
broker="$source_dir/eoat_onboarding_media_broker.py"
unit="$source_dir/eoat-onboarding-media-broker.service"
template="$source_dir/onboarding-media.env.template"
for required in "$broker" "$unit" "$template"; do
    [ -f "$required" ] || { echo "missing broker bootstrap file: $required" >&2; exit 66; }
done

install -d -o root -g root -m 0755 /usr/local/libexec/eoat-atlas
install -d -o root -g root -m 0755 /etc/eoat-atlas
install -o root -g root -m 0750 "$broker" /usr/local/libexec/eoat-atlas/eoat_onboarding_media_broker.py
install -o root -g root -m 0644 "$unit" /etc/systemd/system/eoat-onboarding-media-broker.service
if [ ! -e /etc/eoat-atlas/onboarding-media.env ]; then
    install -o root -g root -m 0640 "$template" /etc/eoat-atlas/onboarding-media.env
fi
systemctl daemon-reload
echo "EOAT onboarding media broker installed but not enabled. Validate its root-owned configuration before enabling it."
