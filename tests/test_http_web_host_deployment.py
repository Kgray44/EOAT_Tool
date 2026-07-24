"""Focused safety tests for the root-owned EOAT Atlas HTTP web deployment."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from types import SimpleNamespace
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


def cli_preflight(monkeypatch: pytest.MonkeyPatch, bundle_root: Path, bundle_sha: str, policy_path: Path) -> int:
    """Exercise installer.main() with its real CLI parser and verify_bundle path."""
    policy_path.write_text(json.dumps({
        "installer_sha256": installer.sha256(Path(SPEC.origin)),
        "bundle_path": str(bundle_root),
        "bundle_sha256": bundle_sha,
        "application_version": "0.20.1",
        "api_release": "/approved/api-release",
        "schema": "20260721_0008",
    }), encoding="utf-8")
    legacy = policy_path.with_name("legacy.conf")
    legacy.write_text("server_name eoat-atlas.gwplastics.com;", encoding="utf-8")
    class DefaultSite:
        def is_symlink(self) -> bool:
            return True
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(installer, "require_root_owned", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(installer, "require_root_chain", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(installer, "require_root_tree", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(installer, "active_release", lambda: "/approved/api-release")
    monkeypatch.setattr(installer, "api_health", lambda _: {"writes_enabled": False})
    monkeypatch.setattr(installer, "api_loopback_only", lambda: True)
    monkeypatch.setattr(installer, "mysql_loopback_only", lambda: True)
    monkeypatch.setattr(installer, "no_tls_listener", lambda: True)
    monkeypatch.setattr(installer, "hostname_owners", lambda: [legacy])
    monkeypatch.setattr(installer, "LEGACY_CONFIG", legacy)
    monkeypatch.setattr(installer, "DEFAULT_ENABLED", DefaultSite())
    monkeypatch.setattr(installer.os, "readlink", lambda _: "/etc/nginx/sites-available/default")
    monkeypatch.setattr(installer, "validate_isolated", lambda *_args: None)
    monkeypatch.setattr(installer, "nginx_worker_user", lambda: "www-data")
    monkeypatch.setattr(installer.shutil, "disk_usage", lambda _: SimpleNamespace(free=1024 * 1024 * 1024))
    monkeypatch.setattr(sys, "argv", [str(SPEC.origin), "--policy", str(policy_path), "preflight"])
    return installer.main()


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


def test_cli_preflight_separates_payload_and_complete_bundle_hash_domains(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output, complete_bundle_sha = bundle(tmp_path)
    payload_sha = json.loads((output / "bundle.json").read_text(encoding="utf-8"))["content_sha256"]
    assert payload_sha != complete_bundle_sha
    assert cli_preflight(monkeypatch, output, complete_bundle_sha, tmp_path / "policy.json") == 0
    assert json.loads(capsys.readouterr().out)["bundle_sha256"] == complete_bundle_sha


def test_cli_preflight_rejects_each_hash_domain_mutation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload_bundle, bundle_sha = bundle(tmp_path / "payload")
    (payload_bundle / "web" / "assets" / "app.js").write_text("mutated", encoding="utf-8")
    with pytest.raises(installer.InstallError, match="payload file SHA-256"):
        cli_preflight(monkeypatch, payload_bundle, bundle_sha, tmp_path / "payload-policy.json")

    manifest_bundle, bundle_sha = bundle(tmp_path / "manifest")
    manifest_path = manifest_bundle / "manifest.json"
    manifest_path.write_text(manifest_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(installer.InstallError, match="complete bundle SHA-256"):
        cli_preflight(monkeypatch, manifest_bundle, bundle_sha, tmp_path / "manifest-policy.json")

    metadata_bundle, bundle_sha = bundle(tmp_path / "metadata")
    metadata_path = metadata_bundle / "bundle.json"
    metadata_path.write_text(metadata_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(installer.InstallError, match="complete bundle SHA-256"):
        cli_preflight(monkeypatch, metadata_bundle, bundle_sha, tmp_path / "metadata-policy.json")

    policy_bundle, bundle_sha = bundle(tmp_path / "policy")
    with pytest.raises(installer.InstallError, match="complete bundle SHA-256") as failure:
        cli_preflight(monkeypatch, policy_bundle, "0" * 64, tmp_path / "wrong-policy.json")
    assert "verification_stage=complete_bundle_policy" in str(failure.value)
    assert "expected_hash_type=complete_bundle_sha256" in str(failure.value)
    assert "computed_hash_type=complete_bundle_sha256" in str(failure.value)

    content_bundle, bundle_sha = bundle(tmp_path / "content")
    metadata = json.loads((content_bundle / "bundle.json").read_text(encoding="utf-8"))
    metadata["content_sha256"] = "f" * 64
    (content_bundle / "bundle.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(installer.InstallError, match="payload content SHA-256"):
        cli_preflight(monkeypatch, content_bundle, bundle_sha, tmp_path / "content-policy.json")


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


def test_api_health_accepts_the_production_flat_schema_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"current_schema_revision": "20260721_0008", "expected_schema_revision": "20260721_0008", "writes_enabled": False}
    monkeypatch.setattr(installer, "http_json", lambda _: (200, "application/json", payload))
    assert installer.api_health({"schema": "20260721_0008"}) == payload
    payload["expected_schema_revision"] = "wrong"
    with pytest.raises(installer.InstallError, match="schema"):
        installer.api_health({"schema": "20260721_0008"})


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


def test_deployed_frontend_hashes_reject_a_changed_asset(tmp_path: Path) -> None:
    release = web_source(tmp_path / "release")
    approved = {"web/" + path.relative_to(release).as_posix(): installer.sha256(path) for path in release.rglob("*") if path.is_file()}
    assert installer.deployed_frontend_hashes(release, approved)["index.html"] == installer.sha256(release / "index.html")
    (release / "assets" / "app.js").write_text("changed", encoding="utf-8")
    with pytest.raises(installer.InstallError, match="asset hashes"):
        installer.deployed_frontend_hashes(release, approved)


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
