from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from release_tools.release_identity import (
    ArtifactDisposition,
    ManifestSignature,
    ProductReleaseIdentity,
    ReleaseArtifact,
    ReleaseSetManifest,
    public_key_bytes,
    sign_manifest,
    verify_manifest,
)


def _identity() -> ProductReleaseIdentity:
    return ProductReleaseIdentity(
        product_version="0.24.0",
        release_id="eoat-atlas-0.24.0",
        build_id="eoat-atlas-0.24.0-abcdef0-20260727T000000Z",
        source_commit="abcdef0123456789abcdef0123456789abcdef01",
        source_tree="0123456789abcdef0123456789abcdef01234567",
        source_branch="codex/unified-release-train",
        release_channel="candidate",
        build_timestamp="2026-07-27T00:00:00Z",
        candidate_id="candidate-0.24.0-abcdef012345",
    )


def _manifest() -> ReleaseSetManifest:
    artifacts = tuple(
        ReleaseArtifact(component, ArtifactDisposition.BUILT, f"{component}.zip", "a" * 64, 1)
        for component in ReleaseSetManifest.REQUIRED_COMPONENTS
    )
    return ReleaseSetManifest(_identity(), artifacts, api_contract_version="1.4.0")


def test_release_set_is_deterministic_and_carries_one_product_identity() -> None:
    first = _manifest()
    second = _manifest()

    assert first.digest() == second.digest()
    assert first.finalized_identity().artifact_set_manifest_digest == first.digest()
    assert {artifact.component for artifact in first.artifacts} == ReleaseSetManifest.REQUIRED_COMPONENTS


def test_signed_release_set_rejects_tampering_unknown_and_revoked_keys() -> None:
    private = Ed25519PrivateKey.generate().private_bytes_raw()
    manifest = _manifest()
    signature = sign_manifest(manifest, key_id="test-key-2026", private_key=private)

    verify_manifest(manifest, signature, trusted_public_keys={"test-key-2026": public_key_bytes(private)})
    with pytest.raises(ValueError, match="unknown"):
        verify_manifest(manifest, signature, trusted_public_keys={})
    with pytest.raises(ValueError, match="revoked"):
        verify_manifest(
            manifest,
            signature,
            trusted_public_keys={"test-key-2026": public_key_bytes(private)},
            revoked_key_ids=frozenset({"test-key-2026"}),
        )
    with pytest.raises(ValueError, match="verification failed"):
        verify_manifest(
            manifest,
            ManifestSignature("test-key-2026", "Ed25519", signature.signature[:-2] + "AA"),
            trusted_public_keys={"test-key-2026": public_key_bytes(private)},
        )


def test_reused_and_not_applicable_artifacts_are_explicit() -> None:
    with pytest.raises(ValueError, match="provenance"):
        ReleaseArtifact("launcher", ArtifactDisposition.REUSED, "launcher.zip", "a" * 64, 1)
    with pytest.raises(ValueError, match="not-applicable"):
        ReleaseArtifact("bootstrap", ArtifactDisposition.NOT_APPLICABLE, filename="bootstrap.zip")
