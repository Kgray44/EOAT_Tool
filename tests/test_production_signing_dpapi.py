"""Windows-only coverage for the isolated DPAPI production-provider store.

The tests deliberately use a pytest-owned temporary directory.  They never
read, replace, or depend on the workstation's real production key store.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from deployment.common import DeploymentError
from deployment.convergence.production_signing import WindowsDpapiProductionProvider

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI is required")


def test_dpapi_provider_provisions_signs_and_refuses_replacement(tmp_path: Path) -> None:
    root = tmp_path / "protected-store"
    status = WindowsDpapiProductionProvider.provision(
        confirmation="PROVISION EOAT ATLAS PRODUCTION SIGNING KEY",
        root=root,
    )

    assert status.provider.value == "WINDOWS_DPAPI_PRODUCTION"
    assert status.readiness == "READY"
    assert status.key_id.startswith("eoat-prod-ed25519-")
    assert len(status.public_key_sha256) == 64

    provider = WindowsDpapiProductionProvider(root)
    payload = b"temporary-DPAPI-provider-test-payload"
    signature = provider.sign(payload)
    Ed25519PublicKey.from_public_bytes(provider.public_key_bytes()).verify(signature, payload)

    metadata = json.loads((root / "production-signing-key.metadata.json").read_text(encoding="utf-8"))
    protected = (root / "production-signing-key.dpapi").read_bytes()
    assert "private" not in json.dumps(metadata).casefold()
    assert len(protected) > 32
    assert payload not in protected

    with pytest.raises(DeploymentError, match="already exists"):
        WindowsDpapiProductionProvider.provision(
            confirmation="PROVISION EOAT ATLAS PRODUCTION SIGNING KEY",
            root=root,
        )


def test_dpapi_provider_rejects_corrupt_protected_blob(tmp_path: Path) -> None:
    root = tmp_path / "protected-store"
    WindowsDpapiProductionProvider.provision(
        confirmation="PROVISION EOAT ATLAS PRODUCTION SIGNING KEY",
        root=root,
    )
    (root / "production-signing-key.dpapi").write_bytes(b"truncated")
    with pytest.raises(DeploymentError, match="DPAPI"):
        WindowsDpapiProductionProvider(root).sign(b"payload")
