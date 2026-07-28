from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from deployment.convergence.release_set import (
    ComponentKind,
    ComponentValidation,
    ReleaseSetComponent,
    SignedReleaseSet,
    verify_signed_release_set,
)
from release_tools.release_identity import ArtifactDisposition, ProductReleaseIdentity, public_key_bytes


def _identity() -> ProductReleaseIdentity:
    return ProductReleaseIdentity(
        "0.24.0", "eoat-atlas-0.24.0", "eoat-atlas-0.24.0-abcdef0-20260727T000000Z",
        "abcdef0123456789abcdef0123456789abcdef01", "0123456789abcdef0123456789abcdef01234567",
        "codex/unified-release-train", "candidate", "2026-07-27T00:00:00Z", "candidate-0.24.0-abcdef012345",
    )


def _component(kind: ComponentKind, identity: ProductReleaseIdentity) -> ReleaseSetComponent:
    built = kind in {ComponentKind.SERVER, ComponentKind.WEB, ComponentKind.DESKTOP}
    return ReleaseSetComponent(
        kind, ArtifactDisposition.BUILT if built else ArtifactDisposition.NOT_APPLICABLE,
        identity.product_version, identity.release_id, identity.build_id, identity.source_commit, identity.source_tree, identity.candidate_id,
        artifact_filename=f"{kind.value}.zip" if built else "", artifact_locator=f"artifacts/{kind.value}.zip" if built else "",
        size_bytes=1 if built else 0, sha256="a" * 64 if built else "", media_type="application/zip" if built else "",
        validation_status=ComponentValidation.PASS if built else ComponentValidation.NOT_APPLICABLE,
        not_applicable_justification="Deferred to a later approved phase." if not built else "",
    )


def _release_set() -> SignedReleaseSet:
    identity = _identity()
    return SignedReleaseSet(
        identity, tuple(_component(kind, identity) for kind in ComponentKind), "1.4.0", "20260721_0008", "NO_MIGRATION_REQUIRED", "0.24.0", "0.1.0", "0.1.0"
    )


def test_schema_two_release_set_is_deterministic_and_signed() -> None:
    release_set = _release_set()
    private = Ed25519PrivateKey.generate().private_bytes_raw()
    signature = release_set.sign(key_id="test-key", private_key=private)
    envelope = release_set.envelope(signature)

    verified = verify_signed_release_set(envelope, trusted_public_keys={"test-key": public_key_bytes(private)})
    assert verified.digest() == release_set.digest()
    assert len(verified.components) == len(ComponentKind)


def test_schema_two_rejects_missing_duplicate_and_wrong_identity_components() -> None:
    release_set = _release_set()
    with pytest.raises(ValueError, match="every component"):
        SignedReleaseSet(
            release_set.identity, release_set.components[:-1], "1.4.0", "20260721_0008", "NO_MIGRATION_REQUIRED", "0.24.0", "0.1.0", "0.1.0"
        )
    broken = list(release_set.components)
    broken[0] = ReleaseSetComponent(
        broken[0].kind, broken[0].disposition, "9.9.9", broken[0].release_id, broken[0].build_id,
        broken[0].source_commit, broken[0].source_tree, broken[0].candidate_id, artifact_filename=broken[0].artifact_filename,
        artifact_locator=broken[0].artifact_locator, size_bytes=1, sha256="a" * 64,
    )
    with pytest.raises(ValueError, match="disagrees"):
        SignedReleaseSet(release_set.identity, tuple(broken), "1.4.0", "20260721_0008", "NO_MIGRATION_REQUIRED", "0.24.0", "0.1.0", "0.1.0")


def test_signature_invalidates_after_component_mutation() -> None:
    release_set = _release_set()
    private = Ed25519PrivateKey.generate().private_bytes_raw()
    envelope = release_set.envelope(release_set.sign(key_id="test-key", private_key=private))
    envelope["release_set"]["components"][0]["sha256"] = "b" * 64
    with pytest.raises(ValueError, match="digest"):
        verify_signed_release_set(envelope, trusted_public_keys={"test-key": public_key_bytes(private)})
