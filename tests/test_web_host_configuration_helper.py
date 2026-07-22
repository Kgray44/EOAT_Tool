from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from deployment.privileged.eoat_atlas_deploy_helper import HostConfiguration, Paths, Rejected


class Runner:
    def __init__(self, fail: str | None = None) -> None:
        self.fail, self.commands = fail, []

    def __call__(self, command, **_kwargs):
        self.commands.append(command)
        failed = bool(self.fail and self.fail in " ".join(command))
        if failed:
            self.fail = None
        return subprocess.CompletedProcess(command, 1 if failed else 0, "", "")


def _paths(tmp_path: Path) -> Paths:
    root = tmp_path / "opt" / "eoat-atlas"
    return Paths(
        root=root,
        lock=tmp_path / "var" / "lock" / "eoat.lock",
        proc=tmp_path / "proc",
        nginx_site=tmp_path / "etc" / "nginx" / "sites-available" / "eoat-atlas",
        nginx_enabled=tmp_path / "etc" / "nginx" / "sites-enabled" / "eoat-atlas",
        nginx_default=tmp_path / "etc" / "nginx" / "sites-enabled" / "default",
        nginx_token=tmp_path / "etc" / "eoat-atlas" / "nginx-upstream-token.conf",
        runtime_env=tmp_path / "etc" / "eoat-atlas" / "runtime.env",
        systemd_unit=tmp_path / "etc" / "systemd" / "system" / "eoat-atlas.service",
    )


def _release(paths: Paths) -> str:
    release = paths.releases / "eoat-atlas-server-0.20.2-aaaaaaaa"
    nginx_source = Path("deployment/runtime/nginx/eoat-atlas.conf").read_bytes()
    unit_source = Path("deployment/runtime/systemd/eoat-atlas.service").read_bytes()
    for relative, contents in {
        "deployment/runtime/nginx/eoat-atlas.conf": nginx_source,
        "deployment/runtime/systemd/eoat-atlas.service": unit_source,
        "web-static/index.html": b"<html>EOAT</html>",
    }.items():
        path = release / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    static = release / "web-static"
    (static / "web-static.manifest.json").write_text(
        json.dumps({"index.html": hashlib.sha256((static / "index.html").read_bytes()).hexdigest()}), encoding="utf-8"
    )
    manifest = {
        "version": "0.20.2",
        "release_id": "eoat-atlas-0.20.2",
        "build_id": "eoat-atlas-0.20.2-aaaaaaaa-20260722T000000Z",
        "commit_sha": "a" * 40,
        "payload_sha256": "b" * 64,
        "host_templates": {
            "nginx": {
                "path": "deployment/runtime/nginx/eoat-atlas.conf",
                "sha256": hashlib.sha256(nginx_source).hexdigest(),
            },
            "systemd": {
                "path": "deployment/runtime/systemd/eoat-atlas.service",
                "sha256": hashlib.sha256(unit_source).hexdigest(),
            },
            "static_manifest": {
                "path": "web-static/web-static.manifest.json",
                "sha256": hashlib.sha256((static / "web-static.manifest.json").read_bytes()).hexdigest(),
            },
        },
    }
    (release / "release_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest["release_id"]


def _install(paths: Paths, runner: Runner, ident: str = "hostcfg-0001"):
    return HostConfiguration(paths, runner).dispatch(
        {"operation": "install-web-host-config", "host_config_id": ident, "release_id": _release(paths)}
    )


def test_install_is_transactional_and_redacts_token(tmp_path: Path) -> None:
    paths, runner = _paths(tmp_path), Runner()
    paths.runtime_env.parent.mkdir(parents=True)
    paths.runtime_env.write_bytes(b"EOAT_DB_PASSWORD=secret\n")
    result = _install(paths, runner)
    receipt = (paths.host_receipts / "hostcfg-0001.json").read_text(encoding="utf-8")
    assert result["state"] == "COMMITTED" and not paths.lock.exists()
    assert paths.nginx_enabled.exists() and not paths.nginx_default.exists()
    assert "secret" not in receipt and "EOAT_API_DEVICE_TOKEN" not in receipt
    assert ["/usr/sbin/nginx", "-t"] in runner.commands


def test_reinstall_preserves_matching_token_and_rotation_is_explicit(tmp_path: Path) -> None:
    paths, runner = _paths(tmp_path), Runner()
    _install(paths, runner)
    before = paths.nginx_token.read_bytes()
    _install(paths, runner, "hostcfg-0002")
    assert paths.nginx_token.read_bytes() == before
    HostConfiguration(paths, runner).dispatch(
        {"operation": "rotate-web-upstream-token", "host_config_id": "hostcfg-0003", "release_id": "eoat-atlas-0.20.2"}
    )
    assert paths.nginx_token.read_bytes() != before


def test_mismatched_existing_representations_fail_closed(tmp_path: Path) -> None:
    paths, runner = _paths(tmp_path), Runner()
    _install(paths, runner)
    paths.runtime_env.write_bytes(
        paths.runtime_env.read_bytes().replace(b"EOAT_API_DEVICE_TOKEN=", b"EOAT_API_DEVICE_TOKEN=x")
    )
    with pytest.raises(Rejected, match="do not match"):
        _install(paths, runner, "hostcfg-0002")


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("shell", {}),
        ("install-web-host-config", {"path": "/tmp/x"}),
        ("validate-web-host-config", {"release_id": "../../x"}),
    ],
)
def test_only_fixed_operations_and_identities_are_accepted(
    tmp_path: Path, operation: str, payload: dict[str, str]
) -> None:
    with pytest.raises(Rejected):
        HostConfiguration(_paths(tmp_path), Runner()).dispatch({"operation": operation, **payload})


def test_modified_tls_template_and_validation_failure_roll_back(tmp_path: Path) -> None:
    paths, runner = _paths(tmp_path), Runner()
    release_id = _release(paths)
    nginx = next(paths.releases.rglob("eoat-atlas.conf"))
    nginx.write_text(nginx.read_text() + "\nlisten 443;\n", encoding="utf-8")
    with pytest.raises(Rejected, match="immutable"):
        HostConfiguration(paths, runner).dispatch(
            {"operation": "install-web-host-config", "host_config_id": "hostcfg-0001", "release_id": release_id}
        )
    _release(paths)
    with pytest.raises(Rejected, match="NGINX validation"):
        _install(paths, Runner("nginx"), "hostcfg-0002")
    assert not paths.nginx_site.exists() and not paths.lock.exists()


def test_runtime_parser_rejects_injection_and_unknown_values() -> None:
    for value in (
        b"EOAT_X=y\n",
        b"EOAT_DB_HOST=x\r\n",
        b"EOAT_DB_HOST=x\x00",
        b"EOAT_DB_HOST=$(id)\n",
        b"EOAT_DB_HOST=x\nEOAT_DB_HOST=y\n",
    ):
        with pytest.raises(Rejected):
            HostConfiguration._parse_runtime(value)
