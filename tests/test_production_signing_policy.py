from __future__ import annotations

import json
from pathlib import Path

import pytest

from deployment.common import DeploymentError
from deployment.convergence.production_signing import load_production_trust_policy


def test_governed_production_policy_has_one_active_ed25519_key() -> None:
    trusted, revoked, policy = load_production_trust_policy()
    assert policy["environment"] == "PRODUCTION"
    assert len(trusted) == 1
    assert not revoked
    assert len(next(iter(trusted.values()))) == 32


def test_policy_rejects_public_key_fingerprint_mismatch(tmp_path: Path) -> None:
    source = Path("release_trust/production_manifest_keys.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["keys"][0]["public_key_sha256"] = "0" * 64
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DeploymentError, match="fingerprint"):
        load_production_trust_policy(path)
