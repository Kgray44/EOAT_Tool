#!/bin/sh
# One-time HTTP-only deployment of the verified 0.20.1 static client.
# It never switches /opt/eoat-atlas/current or touches the database.
set -eu
umask 027

HOST=eoat-atlas.gwplastics.com
STATIC=/opt/eoat-atlas/releases/eoat-atlas-server-0.20.1-0a75860/web-static
STATIC_MANIFEST_SHA256=58e18aa80dfe0065d5e0a5918b5fd261ea4649c4d456c3945f387054c53bcc14
WEB_BASE=/var/www/eoat-atlas
WEB_RELEASE=/var/www/eoat-atlas/releases/eoat-atlas-web-0.20.1-0a75860
WEB_CURRENT=/var/www/eoat-atlas/current
API_RELEASE=/opt/eoat-atlas/releases/eoat-atlas-server-0.18.0-8f0788e
RUNTIME=/etc/eoat-atlas/runtime.env
TOKEN=/etc/eoat-atlas/nginx-upstream-token.conf
SITE=/etc/nginx/sites-available/eoat-atlas
ENABLED=/etc/nginx/sites-enabled/eoat-atlas
DEFAULT=/etc/nginx/sites-enabled/default
LEGACY_API=/etc/nginx/conf.d/eoat-atlas-api.conf
BACKUP=/opt/eoat-atlas/shared/web-host-backups/web-host-$(date -u +%Y%m%dT%H%M%SZ)

[ "$(id -u)" -eq 0 ] || { echo "must run as root" >&2; exit 77; }
[ "$(readlink -f /opt/eoat-atlas/current)" = "$API_RELEASE" ] || { echo "unexpected active API release" >&2; exit 65; }
[ -f "$STATIC/index.html" ] || { echo "static client is incomplete" >&2; exit 66; }
[ "$(sha256sum "$STATIC/web-static.manifest.json" | awk '{print $1}')" = "$STATIC_MANIFEST_SHA256" ] || { echo "static manifest digest mismatch" >&2; exit 65; }

python3 - "$STATIC" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1]); manifest_path = root / "web-static.manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
actual = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file() and path != manifest_path}
if manifest != actual:
    raise SystemExit("static subtree hash verification failed")
PY

mkdir -p "$BACKUP"
backup() { [ -e "$1" ] || [ -L "$1" ] && { cp -a "$1" "$BACKUP/$2"; : >"$BACKUP/$2.present"; } || true; }
restore() { rm -f "$1"; [ -f "$BACKUP/$2.present" ] && cp -a "$BACKUP/$2" "$1" || true; }
rollback() {
    code=$?
    trap - EXIT INT TERM
    restore "$SITE" site; restore "$ENABLED" enabled; restore "$DEFAULT" default; restore "$LEGACY_API" legacy-api; restore "$WEB_CURRENT" web-current
    if [ -f "$BACKUP/web-release-created" ]; then
        [ "$WEB_RELEASE" = "/var/www/eoat-atlas/releases/eoat-atlas-web-0.20.1-0a75860" ] && rm -rf -- "$WEB_RELEASE"
    fi
    restore "$RUNTIME" runtime; restore "$TOKEN" token
    systemctl restart eoat-atlas.service >/dev/null 2>&1 || true
    nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
    echo "ROLLED_BACK backup=$BACKUP" >&2
    exit "$code"
}
backup "$SITE" site; backup "$ENABLED" enabled; backup "$DEFAULT" default; backup "$LEGACY_API" legacy-api
backup "$RUNTIME" runtime; backup "$TOKEN" token
backup "$WEB_CURRENT" web-current
readlink -f /opt/eoat-atlas/current >"$BACKUP/active-api-release.txt"
trap rollback EXIT INT TERM

install -d -o root -g root -m 0755 "$WEB_BASE/releases"
if [ ! -e "$WEB_RELEASE" ]; then
    install -d -o root -g root -m 0755 "$WEB_RELEASE"
    cp -a "$STATIC/." "$WEB_RELEASE/"
    chown -R root:root "$WEB_RELEASE"
    find "$WEB_RELEASE" -type d -exec chmod 0755 {} +
    find "$WEB_RELEASE" -type f -exec chmod 0644 {} +
    : >"$BACKUP/web-release-created"
fi
python3 - "$WEB_RELEASE" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1]); manifest_path = root / "web-static.manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
actual = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file() and path != manifest_path}
if manifest != actual:
    raise SystemExit("staged web subtree hash verification failed")
PY
ln -sfn releases/eoat-atlas-web-0.20.1-0a75860 "$WEB_CURRENT"

python3 - "$RUNTIME" "$TOKEN" <<'PY'
import os, re, secrets, sys, tempfile
from pathlib import Path
runtime_path, token_path = map(Path, sys.argv[1:])
lines = runtime_path.read_text(encoding="utf-8").splitlines()
runtime_token = next((line.split("=", 1)[1] for line in lines if line.startswith("EOAT_API_DEVICE_TOKEN=")), None)
nginx_token = None
if token_path.exists():
    match = re.fullmatch(r'\s*set \$eoat_atlas_upstream_token "([A-Za-z0-9_-]{32,128})";\s*', token_path.read_text(encoding="ascii"))
    if not match: raise SystemExit("existing upstream-token file is invalid")
    nginx_token = match.group(1)
if runtime_token and not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", runtime_token): raise SystemExit("existing API token is invalid")
if runtime_token and nginx_token and runtime_token != nginx_token: raise SystemExit("existing token representations differ")
token = runtime_token or nginx_token or secrets.token_urlsafe(32)
lines = [line for line in lines if not line.startswith("EOAT_API_DEVICE_TOKEN=")]
lines.append(f"EOAT_API_DEVICE_TOKEN={token}")
runtime_gid = os.stat(runtime_path).st_gid
def atomic(path, text, gid):
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream: stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.chown(temporary, 0, gid); os.chmod(temporary, 0o640); os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
atomic(runtime_path, "\n".join(lines) + "\n", runtime_gid)
atomic(token_path, f'set $eoat_atlas_upstream_token "{token}";\n', runtime_gid)
PY

cat >"$SITE" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $HOST;
    root $WEB_CURRENT;
    index index.html;
    autoindex off;
    include $TOKEN;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), geolocation=(), microphone=()" always;
    add_header Content-Security-Policy "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'" always;
    location ~* /(?:\\.|.*\\.(?:map|env|pem|key))$ { return 404; }
    location ^~ /assets/ { try_files \$uri =404; add_header Cache-Control "public, max-age=31536000, immutable" always; }
    location = /index.html { add_header Cache-Control "no-cache" always; }
    location = /api/v1/web-fit-checks/evaluate {
        if (\$request_method != POST) { return 405; }
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-EOAT-Device-Token \$eoat_atlas_upstream_token; proxy_hide_header X-EOAT-Device-Token;
        proxy_no_cache 1; proxy_cache_bypass 1; proxy_connect_timeout 5s; proxy_read_timeout 30s;
    }
    location ^~ /api/ {
        if (\$request_method !~ ^(GET|HEAD)$) { return 405; }
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-EOAT-Device-Token \$eoat_atlas_upstream_token; proxy_hide_header X-EOAT-Device-Token;
        proxy_no_cache 1; proxy_cache_bypass 1; proxy_connect_timeout 5s; proxy_read_timeout 30s;
    }
    location / { try_files \$uri \$uri/ /index.html; }
}
EOF
chmod 0644 "$SITE"
ln -sfn ../sites-available/eoat-atlas "$ENABLED"
nginx -t
rm -f "$DEFAULT" "$LEGACY_API"
nginx -t
systemctl restart eoat-atlas.service

python3 - "$RUNTIME" <<'PY'
import json, sys, time, urllib.error, urllib.request
from pathlib import Path
token = next(line.split("=", 1)[1] for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if line.startswith("EOAT_API_DEVICE_TOKEN="))
for attempt in range(20):
    try:
        request = urllib.request.Request("http://127.0.0.1:8765/api/v1/eoats", headers={"X-EOAT-Device-Token": token})
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200: raise SystemExit("local authenticated API check failed")
        health = json.loads(urllib.request.urlopen("http://127.0.0.1:8765/api/v1/health", timeout=10).read())
        break
    except (urllib.error.URLError, urllib.error.HTTPError):
        if attempt == 19: raise SystemExit("API did not become ready after restart")
        time.sleep(1)
if health.get("writes_enabled") is not False or health.get("current_schema_revision") != "20260721_0008": raise SystemExit("API safety check failed")
PY

systemctl reload nginx
curl --fail --silent --show-error --resolve $HOST:80:127.0.0.1 http://$HOST/ | grep -qv 'Welcome to nginx!'
curl --fail --silent --show-error --resolve $HOST:80:127.0.0.1 http://$HOST/api/v1/health >/dev/null
curl --fail --silent --show-error --resolve $HOST:80:127.0.0.1 http://$HOST/fit-check | grep -q '<div id="root"></div>'
for suffix in js css; do
    asset=$(python3 - "$WEB_RELEASE/web-static.manifest.json" "$suffix" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
print(next(path for path in manifest if path.endswith("." + sys.argv[2])))
PY
)
    curl --fail --silent --show-error --resolve $HOST:80:127.0.0.1 http://$HOST/$asset >/dev/null
done
status=$(curl --silent --output "$BACKUP/api-404.body" --write-out '%{http_code}' --resolve $HOST:80:127.0.0.1 http://$HOST/api/v1/does-not-exist)
[ "$status" = 404 ] && ! grep -qi '<!doctype html\|<html' "$BACKUP/api-404.body"
! curl --silent --show-error --head --resolve $HOST:80:127.0.0.1 http://$HOST/ | grep -qi '^location: https://'
! ss -ltn | grep -qE '[:.]443[[:space:]]'
! nginx -T 2>&1 | grep -qi 'Strict-Transport-Security'
[ "$(readlink -f /opt/eoat-atlas/current)" = "$API_RELEASE" ]
trap - EXIT INT TERM
sha256sum "$STATIC/web-static.manifest.json" "$SITE"
echo "DEPLOYED backup=$BACKUP static=$STATIC active_api=$API_RELEASE"
