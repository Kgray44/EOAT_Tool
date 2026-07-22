from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from deployment.active_deployment import DEPLOYMENT_ID, PrivilegedHelperClient, deployment_id
from deployment.common import DeploymentError
from deployment.server_updater import ServerConfig, parse_args


def _config() -> ServerConfig:
    return ServerConfig(
        "eoat-atlas",
        22,
        "kgray",
        "/opt/eoat-atlas",
        8765,
        ("eoat-atlas.service",),
        "nginx.service",
        "eoat-atlas-prod-runtime",
        "eoat_atlas_prod",
        "/var/lock/eoat-atlas-deploy.lock",
        "eoat-atlas.gwplastics.com",
        "http",
        80,
    )


class Transport:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command, **_kwargs):
        self.commands.append(command)
        output = json.dumps({"state": "STAGED_VALIDATED"}) if command[0] == "ssh" else ""
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")


def test_helper_client_uses_strict_ssh_and_exact_sudo_helper_only(tmp_path: Path) -> None:
    transport = Transport()
    client = PrivilegedHelperClient(_config(), transport)
    response = client.invoke({"operation": "status", "deployment_id": "deploy-20260721t010203z-35dea12"})
    assert response["state"] == "STAGED_VALIDATED"
    command = transport.commands[0]
    assert command[:5] == ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes"]
    remote = command[-1]
    assert "sudo -n /usr/bin/python3 /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py --request-b64" in remote
    assert "systemctl" not in remote and "sh -c" not in remote and "--request-b64" in remote


def test_upload_is_fixed_to_hidden_incoming_name_and_rejects_paths(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.tar.gz"
    artifact.write_bytes(b"artifact")
    transport = Transport()
    client = PrivilegedHelperClient(_config(), transport)
    client.upload(artifact, ".deploy-20260721t010203z-35dea12.artifact.tar.gz")
    assert transport.commands[0][0] == "scp"
    assert (
        transport.commands[0][-1]
        == "kgray@eoat-atlas:/opt/eoat-atlas/incoming/.deploy-20260721t010203z-35dea12.artifact.tar.gz"
    )
    with pytest.raises(DeploymentError, match="unsafe"):
        client.upload(artifact, "../../etc/passwd")


def test_generated_deployment_identifier_is_safe_and_time_bound(monkeypatch) -> None:
    monkeypatch.setattr("deployment.active_deployment.utc_text", lambda: "2026-07-21T01:02:03Z")
    identifier = deployment_id("35dea122f0ee9fc0fd3a0ca6130de6a6f78d8811")
    assert identifier == "deploy-20260721t010203z-35dea12"
    assert DEPLOYMENT_ID.fullmatch(identifier)


def test_privileged_bootstrap_surface_is_fixed_and_validated() -> None:
    root = Path(__file__).resolve().parents[1]
    sudoers = (root / "deployment" / "privileged" / "eoat-atlas-deploy.sudoers").read_text(encoding="utf-8")
    installer = (root / "deployment" / "privileged" / "install_helper.sh").read_text(encoding="utf-8")
    assert "NOPASSWD: EOAT_ATLAS_DEPLOY" in sudoers
    assert "eoat_atlas_deploy_helper.py --request-b64 *" in sudoers
    assert "ALL=(ALL)" not in sudoers and "sudo -l" not in sudoers
    assert "visudo -cf /etc/sudoers.d/eoat-atlas-deploy" in installer
    assert "/opt/eoat-atlas/current" not in installer and "systemctl" not in installer


def test_cli_requires_explicit_stage_or_explicit_activation() -> None:
    staged = parse_args(["deploy-latest", "--stage-only"])
    assert staged.stage_only and not staged.dry_run
    activated = parse_args(["activate", "deploy-20260721t010203z-35dea12"])
    assert activated.command == "activate"
    with pytest.raises(SystemExit):
        parse_args(["deploy-latest"])
