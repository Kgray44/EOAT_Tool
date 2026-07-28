"""Typed schema-2 EOAT Atlas multi-artifact release-set receipts.

The signed canonical payload intentionally includes component declarations but
not the outer manifest/signature file hashes: those two files are created only
after the canonical payload digest is known.  Their outer-envelope hashes are
verified separately, avoiding a circular self-hash.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from release_tools.release_identity import (
    ArtifactDisposition,
    ManifestSignature,
    ProductReleaseIdentity,
    canonical_json,
    sign_manifest,
    verify_manifest,
)


class ComponentKind(str, Enum):
    SERVER = "server"
    WEB = "web"
    DESKTOP = "desktop"
    DESKTOP_UPDATE_MANIFEST = "desktop_update_manifest"
    LAUNCHER = "launcher"
    LAUNCHER_UPDATE_MANIFEST = "launcher_update_manifest"
    BOOTSTRAP = "bootstrap"
    BOOTSTRAP_UPDATE_MANIFEST = "bootstrap_update_manifest"
    RELEASE_SET_MANIFEST = "release_set_manifest"
    RELEASE_SET_SIGNATURE = "release_set_signature"
    SOURCE_BUNDLE = "source_bundle"
    RELEASE_NOTES = "release_notes"


class ComponentValidation(str, Enum):
    PASS = "PASS"
    BLOCKED_PLATFORM = "BLOCKED_PLATFORM"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_RUN = "NOT_RUN"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ReleaseSetComponent:
    kind: ComponentKind
    disposition: ArtifactDisposition
    product_version: str
    release_id: str
    build_id: str
    source_commit: str
    source_tree: str
    candidate_id: str
    component_version: str = ""
    artifact_filename: str = ""
    artifact_locator: str = ""
    size_bytes: int = 0
    sha256: str = ""
    media_type: str = ""
    embedded_manifest_digest: str = ""
    source_release_identity: str = ""
    reuse_justification: str = ""
    validation_status: ComponentValidation = ComponentValidation.NOT_RUN
    smoke_test_status: ComponentValidation = ComponentValidation.NOT_APPLICABLE
    not_applicable_justification: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.disposition is ArtifactDisposition.BUILT and self.kind not in {
            ComponentKind.RELEASE_SET_MANIFEST,
            ComponentKind.RELEASE_SET_SIGNATURE,
        }:
            if not self.artifact_filename or not self.artifact_locator or self.size_bytes <= 0 or len(self.sha256) != 64:
                raise ValueError(f"built {self.kind.value} needs immutable artifact identity")
        if self.disposition is ArtifactDisposition.REUSED and (
            not self.source_release_identity or not self.reuse_justification or len(self.sha256) != 64
        ):
            raise ValueError(f"reused {self.kind.value} needs immutable source identity and justification")
        if self.disposition is ArtifactDisposition.NOT_APPLICABLE and not self.not_applicable_justification:
            raise ValueError(f"not-applicable {self.kind.value} needs a truthful justification")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["disposition"] = self.disposition.value
        data["validation_status"] = self.validation_status.value
        data["smoke_test_status"] = self.smoke_test_status.value
        data["metadata"] = dict(sorted(self.metadata.items()))
        return data

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ReleaseSetComponent:
        return cls(
            kind=ComponentKind(str(value.get("kind") or "")),
            disposition=ArtifactDisposition(str(value.get("disposition") or "")),
            product_version=str(value.get("product_version") or ""),
            release_id=str(value.get("release_id") or ""),
            build_id=str(value.get("build_id") or ""),
            source_commit=str(value.get("source_commit") or ""),
            source_tree=str(value.get("source_tree") or ""),
            candidate_id=str(value.get("candidate_id") or ""),
            component_version=str(value.get("component_version") or ""),
            artifact_filename=str(value.get("artifact_filename") or ""),
            artifact_locator=str(value.get("artifact_locator") or ""),
            size_bytes=int(value.get("size_bytes") or 0),
            sha256=str(value.get("sha256") or ""),
            media_type=str(value.get("media_type") or ""),
            embedded_manifest_digest=str(value.get("embedded_manifest_digest") or ""),
            source_release_identity=str(value.get("source_release_identity") or ""),
            reuse_justification=str(value.get("reuse_justification") or ""),
            validation_status=ComponentValidation(str(value.get("validation_status") or "NOT_RUN")),
            smoke_test_status=ComponentValidation(str(value.get("smoke_test_status") or "NOT_APPLICABLE")),
            not_applicable_justification=str(value.get("not_applicable_justification") or ""),
            metadata={str(key): str(item) for key, item in dict(value.get("metadata") or {}).items()},
        )


@dataclass(frozen=True)
class SignedReleaseSet:
    identity: ProductReleaseIdentity
    components: tuple[ReleaseSetComponent, ...]
    api_contract_version: str
    database_schema_revision: str
    migration_state: str
    minimum_supported_desktop_version: str
    minimum_supported_launcher_version: str
    minimum_supported_bootstrap_version: str
    validation_checks: tuple[str, ...] = ()
    next_safe_action: str = "Review the validated candidate before publication."
    schema_version: int = 2

    def __post_init__(self) -> None:
        expected = {item.value for item in ComponentKind}
        actual = [item.kind.value for item in self.components]
        if set(actual) != expected or len(actual) != len(set(actual)):
            raise ValueError("schema-2 release set must explicitly declare every component exactly once")
        for component in self.components:
            if (
                component.product_version != self.identity.product_version
                or component.release_id != self.identity.release_id
                or component.build_id != self.identity.build_id
                or component.source_commit != self.identity.source_commit
                or component.source_tree != self.identity.source_tree
                or component.candidate_id != self.identity.candidate_id
            ):
                raise ValueError(f"component {component.kind.value} identity disagrees with release set")

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "components": [item.to_dict() for item in sorted(self.components, key=lambda item: item.kind.value)],
            "api_contract_version": self.api_contract_version,
            "database_schema_revision": self.database_schema_revision,
            "migration_state": self.migration_state,
            "minimum_supported_desktop_version": self.minimum_supported_desktop_version,
            "minimum_supported_launcher_version": self.minimum_supported_launcher_version,
            "minimum_supported_bootstrap_version": self.minimum_supported_bootstrap_version,
            "validation_checks": sorted(self.validation_checks),
            "next_safe_action": self.next_safe_action,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.unsigned_dict())

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def sign(self, *, key_id: str, private_key: bytes) -> ManifestSignature:
        # The repository signature primitive signs an object exposing
        # canonical_bytes; this avoids duplicate crypto implementations.
        return sign_manifest(self, key_id=key_id, private_key=private_key)  # type: ignore[arg-type]

    def sign_with_provider(self, *, key_id: str, signer: Callable[[bytes], bytes]) -> ManifestSignature:
        """Sign canonical bytes without exposing a provider's private seed."""

        signature = signer(self.canonical_bytes())
        if not isinstance(signature, bytes) or len(signature) != 64:
            raise ValueError("Ed25519 signing provider returned an invalid signature")
        return ManifestSignature(key_id, "Ed25519", base64.b64encode(signature).decode("ascii"))

    def envelope(self, signature: ManifestSignature) -> dict[str, Any]:
        return {"release_set": self.unsigned_dict(), "canonical_digest": self.digest(), "signature": signature.to_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SignedReleaseSet:
        identity = ProductReleaseIdentity.from_dict(dict(value.get("identity") or {}))
        return cls(
            identity=identity,
            components=tuple(ReleaseSetComponent.from_dict(item) for item in value.get("components", ()) if isinstance(item, Mapping)),
            api_contract_version=str(value.get("api_contract_version") or ""),
            database_schema_revision=str(value.get("database_schema_revision") or ""),
            migration_state=str(value.get("migration_state") or "UNKNOWN"),
            minimum_supported_desktop_version=str(value.get("minimum_supported_desktop_version") or "0.0.0"),
            minimum_supported_launcher_version=str(value.get("minimum_supported_launcher_version") or "0.0.0"),
            minimum_supported_bootstrap_version=str(value.get("minimum_supported_bootstrap_version") or "0.0.0"),
            validation_checks=tuple(str(item) for item in value.get("validation_checks", ())),
            next_safe_action=str(value.get("next_safe_action") or "Review the validated candidate before publication."),
            schema_version=int(value.get("schema_version") or 0),
        )


def verify_signed_release_set(
    envelope: Mapping[str, Any], *, trusted_public_keys: Mapping[str, bytes], revoked_key_ids: frozenset[str] = frozenset()
) -> SignedReleaseSet:
    payload = envelope.get("release_set")
    signature = envelope.get("signature")
    if not isinstance(payload, Mapping) or not isinstance(signature, Mapping):
        raise ValueError("release-set envelope is incomplete")
    release_set = SignedReleaseSet.from_dict(payload)
    if envelope.get("canonical_digest") != release_set.digest():
        raise ValueError("release-set canonical digest does not match its payload")
    parsed_signature = ManifestSignature(
        str(signature.get("key_id") or ""), str(signature.get("algorithm") or ""), str(signature.get("signature") or "")
    )
    verify_manifest(release_set, parsed_signature, trusted_public_keys=trusted_public_keys, revoked_key_ids=revoked_key_ids)  # type: ignore[arg-type]
    return release_set


def decode_public_keys(keys: Mapping[str, str]) -> dict[str, bytes]:
    return {key_id: base64.b64decode(value.encode("ascii"), validate=True) for key_id, value in keys.items()}
