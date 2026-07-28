from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from deployment.common import DeploymentError, read_json_object
from deployment.convergence import sealing
from deployment.convergence.release_set import (
    ComponentKind,
    ComponentValidation,
    ReleaseSetComponent,
    SignedReleaseSet,
    verify_signed_release_set,
)
from release_tools.release_identity import ArtifactDisposition, ProductReleaseIdentity


def _release_set() -> SignedReleaseSet:
    identity = ProductReleaseIdentity(
        "0.24.0", "eoat-atlas-0.24.0", "eoat-atlas-0.24.0-aaaaaaa-20260727T000000Z",
        "a" * 40, "b" * 40, "codex/unified-release-train", "candidate", "2026-07-27T00:00:00Z", "candidate-0.24.0-aaaaaaaa",
    )
    components = []
    for kind in ComponentKind:
        disposition = ArtifactDisposition.NOT_APPLICABLE if kind in {ComponentKind.BOOTSTRAP, ComponentKind.BOOTSTRAP_UPDATE_MANIFEST} else ArtifactDisposition.BUILT
        components.append(ReleaseSetComponent(
            kind, disposition, identity.product_version, identity.release_id, identity.build_id, identity.source_commit, identity.source_tree, identity.candidate_id,
            artifact_filename="" if kind in {ComponentKind.RELEASE_SET_MANIFEST, ComponentKind.RELEASE_SET_SIGNATURE} or disposition is ArtifactDisposition.NOT_APPLICABLE else f"{kind.value}.bin",
            artifact_locator="" if kind in {ComponentKind.RELEASE_SET_MANIFEST, ComponentKind.RELEASE_SET_SIGNATURE} or disposition is ArtifactDisposition.NOT_APPLICABLE else f"core/{kind.value}.bin",
            size_bytes=0 if kind in {ComponentKind.RELEASE_SET_MANIFEST, ComponentKind.RELEASE_SET_SIGNATURE} or disposition is ArtifactDisposition.NOT_APPLICABLE else 1,
            sha256="" if kind in {ComponentKind.RELEASE_SET_MANIFEST, ComponentKind.RELEASE_SET_SIGNATURE} or disposition is ArtifactDisposition.NOT_APPLICABLE else "c" * 64,
            media_type="" if kind in {ComponentKind.RELEASE_SET_MANIFEST, ComponentKind.RELEASE_SET_SIGNATURE} or disposition is ArtifactDisposition.NOT_APPLICABLE else "application/octet-stream",
            validation_status=ComponentValidation.NOT_APPLICABLE if disposition is ArtifactDisposition.NOT_APPLICABLE else ComponentValidation.PASS,
            not_applicable_justification=sealing._BOOTSTRAP_REASON if disposition is ArtifactDisposition.NOT_APPLICABLE else "",
        ))
    return SignedReleaseSet(identity, tuple(components), "v1", "schema", "UNKNOWN", "0.0.0", "0.0.0", "0.0.0")


def _receipt(release_set: SignedReleaseSet) -> dict[str, object]:
    return {"schema_version": 2, "state": "PLATFORM_ARTIFACTS_PENDING", "working_release_set": release_set.unsigned_dict()}


def test_sealing_is_deterministic_idempotent_and_detached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release_set = _release_set()
    monkeypatch.setattr(sealing, "revalidate_candidate", lambda *_args, **_kwargs: (release_set, {"server": "c" * 64}))
    private = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public = Ed25519PrivateKey.from_private_bytes(private).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()

    first, _ = sealing.seal_candidate(candidate_root, _receipt(release_set), tmp_path, key_id="test-key", private_key=private, trusted_public_keys={"test-key": public})
    second, _ = sealing.seal_candidate(candidate_root, _receipt(release_set), tmp_path, key_id="test-key", private_key=private, trusted_public_keys={"test-key": public})

    assert first["release_set_digest"] == second["release_set_digest"] == hashlib.sha256(release_set.canonical_bytes()).hexdigest()
    assert (candidate_root / "sealing" / "release-set-manifest.json").is_file()
    assert (candidate_root / "sealing" / "release-set-signature.json").is_file()
    assert first["publication_eligible"] is True
    assert first["missing_components"] == []
    assert read_json_object(candidate_root / "sealing" / "release-set-signature.json")["algorithm"] == "Ed25519"


def test_sealing_rejects_conflicting_immutable_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release_set = _release_set()
    monkeypatch.setattr(sealing, "revalidate_candidate", lambda *_args, **_kwargs: (release_set, {}))
    private = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public = Ed25519PrivateKey.from_private_bytes(private).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    sealing.seal_candidate(candidate_root, _receipt(release_set), tmp_path, key_id="test-key", private_key=private, trusted_public_keys={"test-key": public})
    (candidate_root / "sealing" / "release-set-manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DeploymentError, match="conflicts"):
        sealing.seal_candidate(candidate_root, _receipt(release_set), tmp_path, key_id="test-key", private_key=private, trusted_public_keys={"test-key": public})


def test_signature_trust_unknown_revoked_and_mutated_payload_fail() -> None:
    release_set = _release_set()
    private = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public = Ed25519PrivateKey.from_private_bytes(private).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    signature = release_set.sign(key_id="test-key", private_key=private)
    envelope = release_set.envelope(signature)
    verify_signed_release_set(envelope, trusted_public_keys={"test-key": public})
    with pytest.raises(ValueError, match="unknown"):
        verify_signed_release_set(envelope, trusted_public_keys={})
    with pytest.raises(ValueError, match="revoked"):
        verify_signed_release_set(envelope, trusted_public_keys={"test-key": public}, revoked_key_ids=frozenset({"test-key"}))
    envelope["canonical_digest"] = "0" * 64
    with pytest.raises(ValueError, match="digest"):
        verify_signed_release_set(envelope, trusted_public_keys={"test-key": public})


def test_public_verification_trust_does_not_require_private_key(monkeypatch: pytest.MonkeyPatch) -> None:
    private = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    public = Ed25519PrivateKey.from_private_bytes(private).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    monkeypatch.delenv("EOAT_RELEASE_TEST_PRIVATE_KEY_B64", raising=False)
    monkeypatch.delenv("EOAT_RELEASE_TEST_PRIVATE_KEY_FILE", raising=False)
    monkeypatch.setenv("EOAT_RELEASE_TRUSTED_PUBLIC_KEYS_JSON", json.dumps({"public-only": base64.b64encode(public).decode("ascii")}))
    trusted, revoked = sealing.trust_material_from_environment()
    assert trusted == {"public-only": public}
    assert not revoked
    with pytest.raises(DeploymentError, match="signing material"):
        sealing.signing_material_from_environment()
