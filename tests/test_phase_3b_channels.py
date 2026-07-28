from __future__ import annotations

from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from deployment.convergence.phase3b import (
    ChannelError,
    ChannelManifest,
    ChannelPromotionService,
    ImmutableChannelStore,
    build_change_package,
    cohort_included,
    evaluate_observation,
    production_readiness,
    sign_channel_manifest,
    verify_channel_manifest,
)


def _manifest(sequence: int = 1, previous: str = "") -> ChannelManifest:
    return ChannelManifest(
        "candidate",
        sequence,
        "0.24.0",
        "eoat-atlas-0.24.0",
        "build-1",
        "candidate-1",
        "a" * 40,
        "b" * 40,
        "c" * 64,
        "d" * 64,
        "e" * 64,
        "f" * 64,
        "test",
        {
            "package_locator": "desktop.zip",
            "package_sha256": "1" * 64,
            "update_manifest_locator": "desktop.json",
            "update_manifest_sha256": "2" * 64,
        },
        {
            "package_locator": "launcher.zip",
            "package_sha256": "3" * 64,
            "update_manifest_locator": "launcher.json",
            "update_manifest_sha256": "4" * 64,
        },
        {"minimum_version": "0.1.0"},
        "1.4.0",
        "schema-1",
        {"percentage": 25, "salt": "public-ring"},
        previous_manifest_digest=previous,
    )


def test_signed_manifest_history_and_sequence_rollback_are_fail_closed(tmp_path) -> None:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    first = sign_channel_manifest(_manifest(), private_key=private.private_bytes_raw())
    assert verify_channel_manifest(first, trusted_public_keys={"test": public})["sequence"] == 1
    store = ImmutableChannelStore(tmp_path)
    pointer = store.publish("candidate", first, trusted_public_keys={"test": public})
    assert store.publish("candidate", first, trusted_public_keys={"test": public}) == pointer
    second = sign_channel_manifest(_manifest(2, pointer["manifest_digest"]), private_key=private.private_bytes_raw())
    assert store.publish("candidate", second, trusted_public_keys={"test": public})["sequence"] == 2
    with pytest.raises(ChannelError, match="sequence"):
        store.publish("candidate", first, trusted_public_keys={"test": public})
    with pytest.raises(ChannelError, match="revoked"):
        verify_channel_manifest(first, trusted_public_keys={"test": public}, revoked_key_ids=frozenset({"test"}))


def test_cohort_observation_and_change_control_are_privacy_safe() -> None:
    policy = {"percentage": 50, "salt": "ring-a", "allow": ["always"], "exclude": ["never"]}
    assert cohort_included("always", policy) and not cohort_included("never", policy)
    assert cohort_included("installation-1", policy) == cohort_included("installation-1", policy)
    with pytest.raises(ChannelError):
        cohort_included("alice", {"percentage": 1, "salt": "x", "username": "alice"})
    assert evaluate_observation(
        [{"update_state": "SUCCESS", "rolled_back": False, "compatibility_state": "MATCH"}], {"minimum_sample": 1}
    )[0]
    release = {
        "classification": "COMPLETE_TRUSTED",
        "signature_valid": True,
        "release_id": "eoat-atlas-0.24.0",
        "release_set_digest": "c" * 64,
        "product_version": "0.24.0",
    }
    result = production_readiness(release, authorization=None, helper_verified=True, baseline_known=True)
    assert result["classification"] == "IMPLEMENTATION_READY_LIVE_AUTHORIZATION_REQUIRED"
    package = build_change_package(release)
    assert len(package["sha256"]) == 64 and "password" not in str(package).casefold()


def test_candidate_canary_stable_promotion_requires_live_acceptance_and_observation(tmp_path) -> None:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    from deployment.convergence.receipts import ReceiptStore

    channels = ImmutableChannelStore(tmp_path / "channels")
    service = ChannelPromotionService(ReceiptStore(tmp_path / "repo"), channels, trusted_public_keys={"test": public})
    candidate = _manifest()
    result = service.promote(
        candidate, private_key=private.private_bytes_raw(), confirmation="PROMOTE CANDIDATE eoat-atlas-0.24.0"
    )
    assert result["state"] == "PROMOTION_COMPLETE"
    canary = replace(candidate, channel="canary", sequence=1, previous_manifest_digest=result["manifest_digest"])
    with pytest.raises(ChannelError, match="confirmed"):
        service.promote(
            canary, private_key=private.private_bytes_raw(), confirmation="PROMOTE CANARY eoat-atlas-0.24.0"
        )
    canary_result = service.promote(
        canary,
        private_key=private.private_bytes_raw(),
        confirmation="PROMOTE CANARY eoat-atlas-0.24.0",
        server_acceptance={"state": "ACTIVE_CONFIRMED"},
    )
    stable = replace(candidate, channel="stable", sequence=1, previous_manifest_digest=canary_result["manifest_digest"])
    with pytest.raises(ChannelError, match="observation"):
        service.promote(
            stable,
            private_key=private.private_bytes_raw(),
            confirmation="PROMOTE STABLE eoat-atlas-0.24.0",
            server_acceptance={"state": "ACTIVE_CONFIRMED"},
        )
    assert (
        service.promote(
            stable,
            private_key=private.private_bytes_raw(),
            confirmation="PROMOTE STABLE eoat-atlas-0.24.0",
            server_acceptance={"state": "ACTIVE_CONFIRMED"},
            observation=(True, []),
        )["state"]
        == "PROMOTION_COMPLETE"
    )
