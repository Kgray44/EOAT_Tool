"""Focused safety tests for the root-owned EOAT Atlas HTTP web deployment."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

from deployment.http_web_bundle import BundleError, create_bundle, verify_bundle


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("http_web_installer", ROOT / "deployment" / "privileged" / "install_http_web_host.py")
assert SPEC and SPEC.loader
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


def web_source(root: Path) -> Path:
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "app.js").write_text("console.log('EOAT Atlas');", encoding="utf-8")
    (root / "assets" / "app.css").write_text("body{color:#123}", encoding="utf-8")
    (root / "index.html").write_text("<title>EOAT Atlas</title><script src='/assets/app.js'></script><link href='/assets/app.css' rel='stylesheet'>", encoding="utf-8")
    return root


def bundle(tmp_path: Path) -> tuple[Path, str]:
    output = tmp_path / "bundle"
    result = create_bundle(web_source(tmp_path / "web"), ROOT / "deployment" / "runtime" / "nginx" / "eoat-atlas-http-web.conf.template", output, release_id="web-0.20.1-test", app_version="0.20.1")
    return output, result["bundle_sha256"]


def test_bundle_rejects_hash_mismatch_and_unexpected_files(tmp_path: Path) -> None:
    output, digest = bundle(tmp_path)
    assert verify_bundle(output, digest)["bundle_sha256"] == digest
    (output / "web" / "extra.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(BundleError, match="manifest"):
        verify_bundle(output, digest)
    (output / "web" / "extra.txt").unlink()
    (output / "unexpected").write_text("no", encoding="utf-8")
    with pytest.raises(BundleError, match="top-level"):
        verify_bundle(output, digest)


def test_bundle_rejects_browser_secret_or_development_api_host(tmp_path: Path) -> None:
    source = web_source(tmp_path / "web")
    (source / "assets" / "app.js").write_text("fetch('http://127.0.0.1:8765/api')", encoding="utf-8")
    with pytest.raises(BundleError, match="forbidden"):
        create_bundle(source, ROOT / "deployment" / "runtime" / "nginx" / "eoat-atlas-http-web.conf.template", tmp_path / "bundle", release_id="bad", app_version="0.20.1")


def test_root_owned_installer_rejects_writable_or_nonroot() -> None:
    class Info:
        st_uid = 1000
        st_gid = 1000
        st_mode = stat.S_IRWXU | stat.S_IWGRP
    class FakePath:
        def is_symlink(self) -> bool:
            return False
        def stat(self) -> Info:
            return Info()
        def __str__(self) -> str:
            return "fake-installer"
    with pytest.raises(installer.InstallError, match="root ownership"):
        installer.require_root_owned(FakePath(), executable=True)  # type: ignore[arg-type]


def test_copy_file_creates_missing_destination_parent(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_text("safe", encoding="utf-8")
    target = tmp_path / "missing" / "nested" / "target"
    installer.copy_file(source, target)
    assert target.read_text(encoding="utf-8") == "safe"


def test_api_readiness_retries_and_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []
    def eventually(_: dict[str, object]) -> dict[str, object]:
        attempts.append(1)
        if len(attempts) < 3:
            raise installer.InstallError("not ready")
        return {}
    monkeypatch.setattr(installer, "api_health", eventually)
    monkeypatch.setattr(installer.time, "sleep", lambda _: None)
    installer.wait_api({}, attempts=3, interval=0)
    assert len(attempts) == 3
    monkeypatch.setattr(installer, "api_health", lambda _: (_ for _ in ()).throw(installer.InstallError("not ready")))
    with pytest.raises(installer.InstallError, match="readiness timeout"):
        installer.wait_api({}, attempts=2, interval=0)


def test_hostname_and_default_discovery(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.conf"
    legacy.write_text("server_name eoat-atlas.gwplastics.com;", encoding="utf-8")
    other = tmp_path / "other.conf"
    other.write_text("server_name another.example;", encoding="utf-8")
    monkeypatch.setattr(installer, "nginx_files", lambda: [legacy, other])
    assert installer.hostname_owners() == [legacy]
    assert installer.DEFAULT_ENABLED.name == "default"


def test_backup_restore_and_atomic_current_switch(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("Windows test account cannot create symlinks; exercised on Debian deployment host")
    current = tmp_path / "current"
    first = tmp_path / "first"; first.mkdir()
    second = tmp_path / "second"; second.mkdir()
    installer.atomic_symlink(first, current)
    record = installer.copy_path_backup(current, tmp_path / "backup")
    installer.atomic_symlink(second, current)
    installer.restore_backup(record)
    assert current.resolve() == first.resolve()


def test_frontend_release_staging_permissions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = web_source(tmp_path / "source")
    monkeypatch.setattr(installer, "WEB_ROOT", tmp_path / "served")
    monkeypatch.setattr(installer.os, "chown", lambda *_: None, raising=False)
    release = installer.stage_frontend(source, "release-a")
    assert (release / "index.html").is_file()
    if os.name != "nt":
        assert stat.S_IMODE((release / "index.html").stat().st_mode) == 0o644
        assert stat.S_IMODE(release.stat().st_mode) == 0o755


def test_rollback_after_nginx_or_acceptance_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    old = tmp_path / "old"; old.write_text("old", encoding="utf-8")
    live = tmp_path / "live"; live.write_text("new", encoding="utf-8")
    backup = tmp_path / "backup" / "old"
    installer.copy_file(old, backup)
    transaction = tmp_path / "transaction"; transaction.mkdir()
    (transaction / "receipt.json").write_text(json.dumps({"backups": [{"path": str(live), "exists": True, "kind": "file", "backup": str(backup)}], "installed_release": None}), encoding="utf-8")
    monkeypatch.setattr(installer, "nginx_test_reload", lambda: None)
    monkeypatch.setattr(installer, "TRANSACTION_ROOT", tmp_path)
    monkeypatch.setattr(installer, "require_root_chain", lambda _: None)
    monkeypatch.setattr(installer, "require_root_owned", lambda *_args, **_kwargs: None)
    installer.rollback(transaction, {})
    assert live.read_text(encoding="utf-8") == "old"
    receipt = json.loads((transaction / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["rollback_state"] == "complete"


def test_acceptance_failure_logs_exact_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class Completed:
        returncode = 0
        stdout = "HTTP/1.1 404 Not Found\r\ncontent-type: application/json\r\n\r\n{}\nEOAT_STATUS:404\nEOAT_CONTENT_TYPE:application/json\nEOAT_CURL_EXIT:0\n"
        stderr = ""
    monkeypatch.setattr(installer.subprocess, "run", lambda *_, **__: Completed())
    with pytest.raises(installer.InstallError) as failure:
        installer.request_check("homepage", "http://eoat-atlas.gwplastics.com/", 200)
    assert '"url": "http://eoat-atlas.gwplastics.com/"' in str(failure.value)


def test_http_only_template_keeps_api_errors_out_of_spa_fallback() -> None:
    text = (ROOT / "deployment" / "runtime" / "nginx" / "eoat-atlas-http-web.conf.template").read_text(encoding="utf-8")
    assert "location ^~ /api/" in text
    assert "try_files $uri $uri/ /index.html" in text
    assert "listen 443" not in text and "ssl_" not in text and "Strict-Transport-Security" not in text
    assert "proxy_pass http://127.0.0.1:8765;" in text


def test_root_control_directory_is_not_below_service_owned_var_lib_path() -> None:
    assert installer.CONTROL_ROOT == Path("/var/lib/eoat-atlas-http-web-host")
    assert installer.CONTROL_ROOT.parent == Path("/var/lib")
