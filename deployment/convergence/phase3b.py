"""Signed, append-only disposable client-channel promotion for Phase 3B.

No object here can publish a real GitHub release, mutate a production channel,
or call a production deployment helper.  Production adapters only produce
fail-closed preflight/change-package evidence until an external authorization
record is verified by a later execution phase.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from deployment.common import DeploymentError, utc_text, write_json_atomic
from deployment.convergence.receipts import ReceiptStore


class ChannelError(DeploymentError):
    pass


class PromotionState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RELEASE_REVALIDATING = "RELEASE_REVALIDATING"
    RELEASE_VALIDATED = "RELEASE_VALIDATED"
    SERVER_ACCEPTANCE_REQUIRED = "SERVER_ACCEPTANCE_REQUIRED"
    SERVER_ACCEPTANCE_VERIFIED = "SERVER_ACCEPTANCE_VERIFIED"
    CHANNEL_BASELINE_VERIFIED = "CHANNEL_BASELINE_VERIFIED"
    MANIFEST_STAGED = "MANIFEST_STAGED"
    MANIFEST_SIGNED = "MANIFEST_SIGNED"
    MANIFEST_VERIFIED = "MANIFEST_VERIFIED"
    CHANNEL_POINTER_PENDING = "CHANNEL_POINTER_PENDING"
    CHANNEL_PROMOTED = "CHANNEL_PROMOTED"
    OBSERVATION_REQUIRED = "OBSERVATION_REQUIRED"
    OBSERVATION_PASSED = "OBSERVATION_PASSED"
    PROMOTION_COMPLETE = "PROMOTION_COMPLETE"
    PAUSED = "PAUSED"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED_RECOVERABLE = "FAILED_RECOVERABLE"
    FAILED_MANUAL_INTERVENTION = "FAILED_MANUAL_INTERVENTION"


CHANNELS = frozenset({"candidate", "canary", "stable"})
CHANNEL_SCHEMA_VERSION = 1


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _safe_locator(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if not value or path.is_absolute() or ".." in path.parts or any(not part or part == "." for part in path.parts):
        raise ChannelError("channel component locator is unsafe")
    return path.as_posix()


@dataclass(frozen=True)
class ChannelManifest:
    channel: str
    sequence: int
    product_version: str
    release_id: str
    build_id: str
    candidate_id: str
    source_commit: str
    source_tree: str
    release_set_digest: str
    publication_receipt_digest: str
    release_set_manifest_digest: str
    release_set_signature_digest: str
    signing_key_id: str
    desktop: Mapping[str, str]
    launcher: Mapping[str, str]
    bootstrap_policy: Mapping[str, Any]
    api_contract_version: str
    database_schema_revision: str
    rollout_policy: Mapping[str, Any]
    previous_manifest_digest: str = ""
    promotion_receipt_id: str = ""
    published_at: str = ""
    schema_version: int = CHANNEL_SCHEMA_VERSION

    def payload(self) -> dict[str, Any]:
        if self.channel not in CHANNELS or self.sequence < 1 or self.schema_version != CHANNEL_SCHEMA_VERSION:
            raise ChannelError("channel name, schema, or sequence is invalid")
        if any(
            not str(getattr(self, field))
            for field in (
                "product_version",
                "release_id",
                "build_id",
                "candidate_id",
                "source_commit",
                "source_tree",
                "release_set_digest",
                "publication_receipt_digest",
                "release_set_manifest_digest",
                "release_set_signature_digest",
                "signing_key_id",
                "api_contract_version",
                "database_schema_revision",
            )
        ):
            raise ChannelError("channel manifest omits required release identity")
        for component in (self.desktop, self.launcher):
            for key in ("package_locator", "package_sha256", "update_manifest_locator", "update_manifest_sha256"):
                if not str(component.get(key) or ""):
                    raise ChannelError("channel manifest omits component identity")
            _safe_locator(str(component["package_locator"]))
            _safe_locator(str(component["update_manifest_locator"]))
        return {
            "schema_version": self.schema_version,
            "channel": self.channel,
            "sequence": self.sequence,
            "product_version": self.product_version,
            "release_id": self.release_id,
            "build_id": self.build_id,
            "candidate_id": self.candidate_id,
            "source_commit": self.source_commit,
            "source_tree": self.source_tree,
            "release_set_digest": self.release_set_digest,
            "publication_receipt_digest": self.publication_receipt_digest,
            "release_set_manifest_digest": self.release_set_manifest_digest,
            "release_set_signature_digest": self.release_set_signature_digest,
            "signing_key_id": self.signing_key_id,
            "desktop": dict(self.desktop),
            "launcher": dict(self.launcher),
            "bootstrap_policy": dict(self.bootstrap_policy),
            "api_contract_version": self.api_contract_version,
            "database_schema_revision": self.database_schema_revision,
            "rollout_policy": dict(self.rollout_policy),
            "previous_manifest_digest": self.previous_manifest_digest,
            "promotion_receipt_id": self.promotion_receipt_id,
            "published_at": self.published_at or utc_text(),
        }


def sign_channel_manifest(manifest: ChannelManifest, *, private_key: bytes) -> dict[str, Any]:
    payload = manifest.payload()
    signature = Ed25519PrivateKey.from_private_bytes(private_key).sign(canonical_bytes(payload))
    return {
        "schema_version": 1,
        "canonical_payload": payload,
        "canonical_payload_sha256": _digest(payload),
        "signature": {
            "algorithm": "Ed25519",
            "key_id": manifest.signing_key_id,
            "value": base64.b64encode(signature).decode("ascii"),
        },
    }


def verify_channel_manifest(
    envelope: Mapping[str, Any],
    *,
    trusted_public_keys: Mapping[str, bytes],
    revoked_key_ids: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    if int(envelope.get("schema_version", 0)) != 1 or not isinstance(envelope.get("canonical_payload"), Mapping):
        raise ChannelError("channel envelope is malformed or has an unsupported schema")
    payload = dict(envelope["canonical_payload"])
    if envelope.get("canonical_payload_sha256") != _digest(payload):
        raise ChannelError("channel manifest canonical digest is invalid")
    try:
        manifest = ChannelManifest(**payload)
        verified = manifest.payload()
    except (TypeError, ChannelError) as exc:
        raise ChannelError("channel manifest payload is invalid") from exc
    signature = envelope.get("signature")
    if not isinstance(signature, Mapping) or signature.get("algorithm") != "Ed25519":
        raise ChannelError("channel signature envelope is invalid")
    key_id = str(signature.get("key_id") or "")
    if key_id != manifest.signing_key_id or key_id in revoked_key_ids or key_id not in trusted_public_keys:
        raise ChannelError("channel signing key is unknown or revoked")
    try:
        Ed25519PublicKey.from_public_bytes(trusted_public_keys[key_id]).verify(
            base64.b64decode(str(signature.get("value") or ""), validate=True), canonical_bytes(verified)
        )
    except Exception as exc:
        raise ChannelError("channel signature verification failed") from exc
    return verified


class ImmutableChannelStore:
    """Append-only filesystem channel history for a disposable transport."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _base(self, channel: str) -> Path:
        if channel not in CHANNELS:
            raise ChannelError("unknown channel")
        return self.root / "channels" / channel

    def current(self, channel: str) -> dict[str, Any] | None:
        path = self._base(channel) / "current.json"
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ChannelError("channel pointer is malformed")
        return value

    def _known_digest(self, digest: str) -> bool:
        for channel in CHANNELS:
            for envelope in self.history(channel):
                payload = envelope.get("canonical_payload")
                if isinstance(payload, Mapping) and _digest(payload) == digest:
                    return True
        return False

    def publish(
        self,
        channel: str,
        envelope: Mapping[str, Any],
        *,
        trusted_public_keys: Mapping[str, bytes],
        revoked_key_ids: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        payload = verify_channel_manifest(
            envelope, trusted_public_keys=trusted_public_keys, revoked_key_ids=revoked_key_ids
        )
        if payload["channel"] != channel:
            raise ChannelError("manifest channel contradicts requested channel")
        base, history = self._base(channel), self._base(channel) / "history"
        history.mkdir(parents=True, exist_ok=True)
        sequence = int(payload["sequence"])
        digest = _digest(payload)
        current = self.current(channel)
        if current:
            if sequence <= int(current["sequence"]):
                if sequence == int(current["sequence"]) and current.get("manifest_digest") == digest:
                    return current
                raise ChannelError("channel sequence regression or conflicting same-sequence manifest")
            if payload.get("previous_manifest_digest") != current.get("manifest_digest"):
                raise ChannelError("channel manifest breaks previous-manifest chain")
        elif payload.get("previous_manifest_digest") and not self._known_digest(str(payload["previous_manifest_digest"])):
            raise ChannelError("first channel manifest claims an unavailable previous manifest")
        manifest_path, signature_path = history / f"{sequence:08d}.json", history / f"{sequence:08d}.sig.json"
        encoded = canonical_bytes(dict(envelope))
        if manifest_path.exists() and manifest_path.read_bytes() != encoded:
            raise ChannelError("immutable history sequence already has conflicting bytes")
        if not manifest_path.exists():
            manifest_path.write_bytes(encoded)
            signature_path.write_text(json.dumps(dict(envelope["signature"]), sort_keys=True) + "\n", encoding="utf-8")
        pointer = {
            "channel": channel,
            "sequence": sequence,
            "manifest_digest": digest,
            "manifest": f"history/{sequence:08d}.json",
            "signature": f"history/{sequence:08d}.sig.json",
        }
        write_json_atomic(base / "current.json", pointer)
        return pointer

    def history(self, channel: str) -> list[dict[str, Any]]:
        base = self._base(channel) / "history"
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(base.glob("*.json"))
            if not path.name.endswith(".sig.json")
        ]


class ChannelPromotionService:
    """Durable promotion state machine over a disposable channel transport."""

    def __init__(
        self, store: ReceiptStore, channels: ImmutableChannelStore, *, trusted_public_keys: Mapping[str, bytes]
    ) -> None:
        self.store, self.channels, self.trusted_public_keys = store, channels, trusted_public_keys

    def promote(
        self,
        manifest: ChannelManifest,
        *,
        private_key: bytes,
        confirmation: str,
        server_acceptance: Mapping[str, Any] | None = None,
        observation: tuple[bool, list[str]] | None = None,
    ) -> dict[str, Any]:
        expected = f"PROMOTE {manifest.channel.upper()} {manifest.release_id}"
        if confirmation != expected:
            raise ChannelError(f"channel promotion requires exact confirmation: {expected}")
        if manifest.channel in {"canary", "stable"} and (
            not server_acceptance or server_acceptance.get("state") != "ACTIVE_CONFIRMED"
        ):
            raise ChannelError("canary/stable promotion requires confirmed API/web activation")
        previous = self.channels.current(manifest.channel)
        if manifest.channel == "canary":
            candidate = self.channels.current("candidate")
            if not candidate or candidate.get("manifest_digest") != manifest.previous_manifest_digest:
                raise ChannelError("canary promotion requires the exact candidate channel baseline")
        if manifest.channel == "stable":
            canary = self.channels.current("canary")
            if not canary or canary.get("manifest_digest") != manifest.previous_manifest_digest:
                raise ChannelError("stable promotion requires the exact canary channel baseline")
            if not observation or not observation[0]:
                raise ChannelError("stable promotion requires a passing explicit canary observation")
        promotion_id = f"promotion-{manifest.channel}-{manifest.sequence:08d}-{manifest.release_set_digest[:12]}"
        receipt = {
            "schema_version": 2,
            "promotion_id": promotion_id,
            "target_channel": manifest.channel,
            "target_release_identity": manifest.payload(),
            "release_set_digest": manifest.release_set_digest,
            "current_channel_sequence": int(previous["sequence"]) if previous else 0,
            "next_channel_sequence": manifest.sequence,
            "previous_manifest_digest": manifest.previous_manifest_digest,
            "state": PromotionState.RELEASE_VALIDATED.value,
            "state_history": [{"state": PromotionState.RELEASE_VALIDATED.value, "at_utc": utc_text()}],
            "blocking_reasons": [],
            "next_safe_action": "verify signed channel manifest",
        }
        self.store.write("promotion", promotion_id, receipt)
        envelope = sign_channel_manifest(manifest, private_key=private_key)
        receipt["state"] = PromotionState.MANIFEST_SIGNED.value
        receipt["state_history"].append({"state": receipt["state"], "at_utc": utc_text()})
        self.store.write("promotion", promotion_id, receipt)
        verify_channel_manifest(envelope, trusted_public_keys=self.trusted_public_keys)
        pointer = self.channels.publish(manifest.channel, envelope, trusted_public_keys=self.trusted_public_keys)
        receipt.update(
            state=PromotionState.PROMOTION_COMPLETE.value,
            manifest_digest=pointer["manifest_digest"],
            channel_pointer=pointer,
            next_safe_action="observe canary health" if manifest.channel != "stable" else "monitor stable rollout",
        )
        receipt["state_history"].append({"state": receipt["state"], "at_utc": utc_text()})
        self.store.write("promotion", promotion_id, receipt)
        return receipt


def consume_signed_channel(
    envelope: Mapping[str, Any],
    *,
    installation_id: str,
    trusted_public_keys: Mapping[str, bytes],
    last_sequence: int = 0,
    revoked_key_ids: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Shared Bootstrap/Launcher policy check; never trust a filename alone."""
    payload = verify_channel_manifest(
        envelope, trusted_public_keys=trusted_public_keys, revoked_key_ids=revoked_key_ids
    )
    if int(payload["sequence"]) < last_sequence:
        raise ChannelError("channel sequence rollback is blocked")
    policy = dict(payload["rollout_policy"])
    if not cohort_included(installation_id, policy):
        return {"state": "NOT_IN_COHORT", "sequence": payload["sequence"], "release_id": payload["release_id"]}
    if bool(dict(payload["bootstrap_policy"]).get("paused")):
        return {"state": "PAUSED", "sequence": payload["sequence"], "release_id": payload["release_id"]}
    return {
        "state": "ACCEPTED",
        "sequence": payload["sequence"],
        "release_id": payload["release_id"],
        "release_set_digest": payload["release_set_digest"],
        "launcher": payload["launcher"],
        "desktop": payload["desktop"],
    }


def cohort_included(installation_id: str, policy: Mapping[str, Any]) -> bool:
    if (
        not installation_id
        or len(installation_id) > 160
        or any(key in str(policy).casefold() for key in ("username", "workstation", "ip_address", "path"))
    ):
        raise ChannelError("cohort policy or installation identity is unsafe")
    if bool(policy.get("paused")) or installation_id in {str(value) for value in policy.get("exclude", [])}:
        return False
    if installation_id in {str(value) for value in policy.get("allow", [])}:
        return True
    percentage = int(policy.get("percentage", 100))
    if not 0 <= percentage <= 100:
        raise ChannelError("cohort percentage is invalid")
    salt = str(policy.get("salt") or "")
    if not salt:
        raise ChannelError("cohort policy requires a non-secret public salt")
    return int(hashlib.sha256(f"{salt}:{installation_id}".encode()).hexdigest()[:8], 16) % 100 < percentage


def evaluate_observation(statuses: list[Mapping[str, Any]], policy: Mapping[str, Any]) -> tuple[bool, list[str]]:
    minimum = int(policy.get("minimum_sample", 1))
    maximum_failure = float(policy.get("maximum_failure_rate", 0))
    maximum_rollback = float(policy.get("maximum_rollback_rate", 0))
    if len(statuses) < minimum:
        return False, ["insufficient rollout-status sample"]
    reasons: list[str] = []
    failures = sum(str(row.get("update_state")) not in {"SUCCESS", "CURRENT"} for row in statuses) / len(statuses)
    rollbacks = sum(bool(row.get("rolled_back")) for row in statuses) / len(statuses)
    if failures > maximum_failure:
        reasons.append("update failure threshold exceeded")
    if rollbacks > maximum_rollback:
        reasons.append("rollback threshold exceeded")
    if any(str(row.get("compatibility_state")) != "MATCH" for row in statuses):
        reasons.append("runtime compatibility is unknown or mismatched")
    return not reasons, reasons


@dataclass(frozen=True)
class ProductionAuthorization:
    operator_id: str
    target_environment: str
    release_id: str
    release_set_digest: str
    operation: str
    change_reference: str
    expires_at_utc: str
    nonce: str

    def valid_for(self, *, operation: str, release_id: str, digest: str) -> bool:
        try:
            expiry = datetime.fromisoformat(self.expires_at_utc.replace("Z", "+00:00"))
        except ValueError:
            return False
        return (
            bool(self.operator_id and self.nonce and self.change_reference)
            and self.target_environment == "production"
            and self.operation == operation
            and self.release_id == release_id
            and self.release_set_digest == digest
            and expiry > datetime.now(timezone.utc)
        )


def production_readiness(
    release: Mapping[str, Any],
    *,
    authorization: ProductionAuthorization | None,
    helper_verified: bool,
    baseline_known: bool,
    operation: str = "PROMOTE_STABLE",
) -> dict[str, Any]:
    blockers: list[str] = []
    if release.get("classification") != "COMPLETE_TRUSTED" or not release.get("signature_valid"):
        blockers.append("release is not COMPLETE_TRUSTED")
    if not helper_verified:
        blockers.append("production helper capability/binary identity is not verified")
    if not baseline_known:
        blockers.append("production baseline or schema state is unknown")
    if not authorization or not authorization.valid_for(
        operation=operation,
        release_id=str(release.get("release_id") or ""),
        digest=str(release.get("release_set_digest") or ""),
    ):
        blockers.append("valid external production authorization is required")
    return {
        "classification": "GO" if not blockers else "IMPLEMENTATION_READY_LIVE_AUTHORIZATION_REQUIRED",
        "blockers": blockers,
        "next_safe_action": "Provide an unexpired external production authorization and read-only baseline evidence."
        if blockers
        else "Authorized execution may be considered by a separately approved phase.",
    }


def build_change_package(
    release: Mapping[str, Any], *, authorization: ProductionAuthorization | None = None
) -> dict[str, Any]:
    safe = {
        key: release.get(key)
        for key in (
            "product_version",
            "release_id",
            "build_id",
            "candidate_id",
            "source_commit",
            "source_tree",
            "release_set_digest",
            "signing_key_id",
            "database_schema_revision",
            "api_contract_version",
            "assets",
        )
    }
    payload = {
        "schema_version": 1,
        "kind": "EOAT_ATLAS_PRODUCTION_CHANGE_PACKAGE",
        "release": safe,
        "authorization_present": bool(authorization),
        "publication_plan": "immutable tag/release/assets; no clobber",
        "deployment_plan": "verify helper, backup/migration gates, stage API+web, live acceptance",
        "channel_plan": "signed candidate then canary observation then explicitly authorized stable",
        "rollback_plan": "new higher signed channel sequence; application rollback never claims database rollback",
        "stop_conditions": [
            "unknown identity",
            "signature failure",
            "schema unknown",
            "recovery required",
            "authorization invalid",
        ],
        "confirmations": [
            f"PROMOTE CANDIDATE {release.get('release_id','')}",
            f"PROMOTE CANARY {release.get('release_id','')}",
            f"PROMOTE STABLE {release.get('release_id','')}",
        ],
    }
    payload["sha256"] = _digest(payload)
    return payload
