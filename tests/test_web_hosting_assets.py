from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_nginx_template_keeps_browser_read_only_and_uses_server_only_token() -> None:
    text = (ROOT / "deployment/runtime/nginx/eoat-atlas.conf").read_text(encoding="utf-8")
    assert "location = /api/v1/web-fit-checks/evaluate" in text
    assert "$request_method != POST" in text
    assert "$request_method !~ ^(GET|HEAD)$" in text
    assert "proxy_set_header X-EOAT-Device-Token $eoat_atlas_upstream_token" in text
    assert "proxy_hide_header X-EOAT-Device-Token" in text
    assert "try_files $uri $uri/ /index.html" in text
    assert "location ^~ /api/" in text


def test_systemd_template_binds_fastapi_to_loopback_and_disables_writes() -> None:
    unit = (ROOT / "deployment/runtime/systemd/eoat-atlas.service").read_text(encoding="utf-8")
    env = (ROOT / "deployment/runtime/runtime.env.example").read_text(encoding="utf-8")
    assert "--host 127.0.0.1 --port 8765" in unit
    assert "User=eoat-atlas" in unit
    assert "ProtectSystem=strict" in unit
    assert "EOAT_API_WRITES_ENABLED=false" in env
    assert "__SERVER_ONLY_DEVICE_TOKEN__" in env
