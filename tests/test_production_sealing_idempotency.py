from __future__ import annotations

from pathlib import Path

import pytest

from deployment.convergence import production_signing
from deployment.convergence.models import OperationResult, Status
from deployment.convergence.services import ReleaseDeploymentService
from release_tools.release_identity import ProductReleaseIdentity


def test_production_seal_retry_reverifies_matching_immutable_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A production retry verifies retained bytes; it never signs replacement bytes."""

    key_id, public = "eoat-prod-ed25519-unit", b"p" * 32
    identity = ProductReleaseIdentity(
        "0.24.1", "eoat-atlas-0.24.1", "build-unit", "a" * 40, "b" * 40,
        "main", "candidate", "2026-07-29T00:00:00Z", "candidate-unit",
    )

    class _Status:
        def __init__(self, value: str) -> None:
            self.key_id = value

    class _Provider:
        def status(self) -> _Status:
            return _Status(key_id)

        def public_key_bytes(self) -> bytes:
            return public

    monkeypatch.setattr(production_signing, "WindowsDpapiProductionProvider", _Provider)
    monkeypatch.setattr(
        production_signing,
        "load_production_trust_policy",
        lambda: ({key_id: public}, frozenset(), {"schema_version": 1}),
    )
    service = ReleaseDeploymentService(tmp_path)
    service.store.write(
        "candidate",
        identity.candidate_id,
        {
            "schema_version": 2,
            "candidate_id": identity.candidate_id,
            "state": "RELEASE_SET_VALIDATED",
            "publication_eligible": True,
            "release_set_digest": "d" * 64,
            "release_set_signature": {"key_id": key_id},
            "working_release_set": {"identity": identity.to_dict()},
        },
    )
    verified: list[str] = []

    def _verify(candidate_id: str) -> OperationResult:
        verified.append(candidate_id)
        return OperationResult(Status.PASS, "verified", "Phase 1C publication verification.")

    monkeypatch.setattr(service, "verify_sealed_release_set", _verify)
    result = service.seal_release_set_with_production_provider(
        identity.candidate_id,
        "SEAL EOAT ATLAS 0.24.1 WITH PRODUCTION KEY",
    )

    assert result.status is Status.PASS
    assert result.data["idempotent"] is True
    assert result.data["key_id"] == key_id
    assert verified == [identity.candidate_id]
