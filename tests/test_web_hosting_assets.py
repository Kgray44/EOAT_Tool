from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_nginx_template_keeps_browser_read_only_and_uses_server_only_token() -> None:
    text = (ROOT / "deployment/runtime/nginx/eoat-atlas.conf").read_text(encoding="utf-8")
    assert "listen 80;" in text
    assert "listen 443" not in text
    assert " ssl" not in text
    assert "add_header Strict-Transport-Security" not in text
    assert "location = /api/v1/web-fit-checks/evaluate" in text
    assert "$request_method != POST" in text
    assert "$request_method !~ ^(GET|HEAD)$" in text
    assert "proxy_set_header X-EOAT-Device-Token $eoat_atlas_upstream_token" in text
    assert "proxy_hide_header X-EOAT-Device-Token" in text
    assert "try_files $uri $uri/ /index.html" in text
    assert "location ^~ /api/" in text


def test_http_host_installer_is_fixed_to_the_verified_static_release() -> None:
    text = (ROOT / "deployment/privileged/install_http_web_host_0_20_1.sh").read_text(encoding="utf-8")

    assert "HOST=eoat-atlas.gwplastics.com" in text
    assert "STATIC=/opt/eoat-atlas/releases/eoat-atlas-server-0.20.1-0a75860/web-static" in text
    assert "listen 80;" in text
    assert "server_name $HOST;" in text
    assert "listen 443" not in text
    assert "add_header Strict-Transport-Security" not in text
    assert "proxy_pass http://127.0.0.1:8765;" in text
    assert "proxy_set_header X-EOAT-Device-Token \\$eoat_atlas_upstream_token" in text
    assert "if (\\$request_method !~ ^(GET|HEAD)$)" in text
    assert "runtime_gid = os.stat(runtime_path).st_gid" in text
    assert "atomic(token_path, f'set $eoat_atlas_upstream_token \"{token}\";\\n', runtime_gid)" in text
    assert "LEGACY_API=/etc/nginx/conf.d/eoat-atlas-api.conf" in text
    assert "rm -f \"$DEFAULT\" \"$LEGACY_API\"" in text
    assert "for attempt in range(20):" in text
    assert "WEB_RELEASE=/var/www/eoat-atlas/releases/eoat-atlas-web-0.20.1-0a75860" in text
    assert "root $WEB_CURRENT;" in text
    assert "staged web subtree hash verification failed" in text
    assert "for suffix in js css; do" in text
    assert "[ \"$(readlink -f /opt/eoat-atlas/current)\" = \"$API_RELEASE\" ]" in text


def test_systemd_template_binds_fastapi_to_loopback_and_disables_writes() -> None:
    unit = (ROOT / "deployment/runtime/systemd/eoat-atlas.service").read_text(encoding="utf-8")
    env = (ROOT / "deployment/runtime/runtime.env.example").read_text(encoding="utf-8")
    assert "--host 127.0.0.1 --port 8765" in unit
    assert "User=eoat-atlas" in unit
    assert "ProtectSystem=strict" in unit
    assert "EOAT_API_WRITES_ENABLED=false" in env
    assert "__SERVER_ONLY_DEVICE_TOKEN__" in env
