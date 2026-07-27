"""Immutable EOAT Atlas product-release identities and signed release sets.

This module is deliberately transport agnostic.  A release set can be copied
to a test directory, served over HTTPS, or attached to an eventual GitHub
release without changing its identity or signatures.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .versioning import Version

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ArtifactDisposition(str, Enum):
    BUILT = "BUILT"
    REUSED = "REUSED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class ProductReleaseIdentity:
    """The one user-facing identity shared by every product artifact."""

    product_version: str
    release_id: str
    build_id: str
    source_commit: str
    source_tree: str
    source_branch: str
    release_channel: str
    build_timestamp: str
    candidate_id: str
    artifact_set_manifest_digest: str = ""

    def __post_init__(self) -> None:
        version = str(Version.parse(self.product_version))
        if self.release_id != f"eoat-atlas-{version}":
            raise ValueError("release_id must match product_version")
        if not self.build_id or not _SAFE_ID.fullmatch(self.build_id):
            raise ValueError("build_id is missing or unsafe")
        if not _FULL_SHA.fullmatch(self.source_commit):
            raise ValueError("source_commit must be a full lowercase Git SHA")
        if not _FULL_SHA.fullmatch(self.source_tree):
            raise ValueError("source_tree must be a full lowercase Git tree SHA")
        if not self.source_branch or not self.release_channel or not self.candidate_id:
            raise ValueError("source branch, channel, and candidate ID are required")
        _parse_timestamp(self.build_timestamp)
        if self.artifact_set_manifest_digest and not _SHA256.fullmatch(self.artifact_set_manifest_digest):
            raise ValueError("artifact-set manifest digest must be SHA-256")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProductReleaseIdentity:
        return cls(**{name: str(value.get(name) or "") for name in cls.__dataclass_fields__})

    def with_manifest_digest(self, digest: str) -> ProductReleaseIdentity:
        return ProductReleaseIdentity(**{**self.to_dict(), "artifact_set_manifest_digest": digest})


@dataclass(frozen=True)
class ComponentRevision:
    name: str
    value: str

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.name) or not self.value.strip():
            raise ValueError("component revision is invalid")


@dataclass(frozen=True)
class ReleaseArtifact:
    component: str
    disposition: ArtifactDisposition
    filename: str = ""
    sha256: str = ""
    size_bytes: int = 0
    provenance_release_id: str = ""
    provenance_build_id: str = ""
    metadata_sha256: str = ""

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.component):
            raise ValueError("artifact component is invalid")
        if self.disposition is ArtifactDisposition.NOT_APPLICABLE:
            if any((self.filename, self.sha256, self.size_bytes, self.provenance_release_id, self.provenance_build_id)):
                raise ValueError("not-applicable artifacts may not carry mutable artifact identity")
            return
        if not self.filename or "/" in self.filename or "\\" in self.filename:
            raise ValueError("artifact filename must be a basename")
        if not _SHA256.fullmatch(self.sha256) or self.size_bytes <= 0:
            raise ValueError("built/reused artifacts require a SHA-256 and positive size")
        if self.metadata_sha256 and not _SHA256.fullmatch(self.metadata_sha256):
            raise ValueError("artifact metadata digest must be SHA-256")
        if self.disposition is ArtifactDisposition.REUSED and (
            not self.provenance_release_id or not self.provenance_build_id
        ):
            raise ValueError("reused artifacts require exact immutable provenance")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["disposition"] = self.disposition.value
        return data

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ReleaseArtifact:
        return cls(
            component=str(value.get("component") or ""),
            disposition=ArtifactDisposition(str(value.get("disposition") or "")),
            filename=str(value.get("filename") or ""),
            sha256=str(value.get("sha256") or ""),
            size_bytes=int(value.get("size_bytes") or 0),
            provenance_release_id=str(value.get("provenance_release_id") or ""),
            provenance_build_id=str(value.get("provenance_build_id") or ""),
            metadata_sha256=str(value.get("metadata_sha256") or ""),
        )


@dataclass(frozen=True)
class ReleaseSetManifest:
    """Deterministic, immutable declaration of all product artifacts."""

    identity: ProductReleaseIdentity
    artifacts: tuple[ReleaseArtifact, ...]
    component_revisions: tuple[ComponentRevision, ...] = ()
    migration_target_schema: str = ""
    api_contract_version: str = ""
    minimum_supported_desktop_version: str = "0.0.0"
    minimum_supported_launcher_version: str = "0.0.0"
    minimum_supported_bootstrap_version: str = "0.0.0"
    revoked_product_versions: tuple[str, ...] = ()
    release_notes: str = ""
    validation_evidence: tuple[str, ...] = ()
    schema_version: int = 2

    REQUIRED_COMPONENTS = frozenset({"server", "web", "desktop", "desktop_manifest", "launcher", "bootstrap"})

    def __post_init__(self) -> None:
        if self.schema_version != 2:
            raise ValueError("release-set manifests use schema version 2")
        names = [artifact.component for artifact in self.artifacts]
        if set(names) != self.REQUIRED_COMPONENTS or len(names) != len(set(names)):
            raise ValueError("release set must explicitly classify every required component exactly once")
        revision_names = [revision.name for revision in self.component_revisions]
        if len(revision_names) != len(set(revision_names)):
            raise ValueError("component revision names must be unique")
        for version in (
            self.minimum_supported_desktop_version,
            self.minimum_supported_launcher_version,
            self.minimum_supported_bootstrap_version,
            *self.revoked_product_versions,
        ):
            Version.parse(version)

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "artifacts": [artifact.to_dict() for artifact in sorted(self.artifacts, key=lambda item: item.component)],
            "component_revisions": [asdict(item) for item in sorted(self.component_revisions, key=lambda item: item.name)],
            "migration_target_schema": self.migration_target_schema,
            "api_contract_version": self.api_contract_version,
            "minimum_supported_desktop_version": self.minimum_supported_desktop_version,
            "minimum_supported_launcher_version": self.minimum_supported_launcher_version,
            "minimum_supported_bootstrap_version": self.minimum_supported_bootstrap_version,
            "revoked_product_versions": sorted(self.revoked_product_versions),
            "release_notes": self.release_notes,
            "validation_evidence": sorted(self.validation_evidence),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.unsigned_dict())

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def finalized_identity(self) -> ProductReleaseIdentity:
        return self.identity.with_manifest_digest(self.digest())

    def to_dict(self) -> dict[str, Any]:
        return self.unsigned_dict()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ReleaseSetManifest:
        artifacts = tuple(ReleaseArtifact.from_dict(item) for item in value.get("artifacts", ()) if isinstance(item, Mapping))
        revisions = tuple(
            ComponentRevision(str(item.get("name") or ""), str(item.get("value") or ""))
            for item in value.get("component_revisions", ())
            if isinstance(item, Mapping)
        )
        return cls(
            identity=ProductReleaseIdentity.from_dict(_object(value, "identity")),
            artifacts=artifacts,
            component_revisions=revisions,
            migration_target_schema=str(value.get("migration_target_schema") or ""),
            api_contract_version=str(value.get("api_contract_version") or ""),
            minimum_supported_desktop_version=str(value.get("minimum_supported_desktop_version") or "0.0.0"),
            minimum_supported_launcher_version=str(value.get("minimum_supported_launcher_version") or "0.0.0"),
            minimum_supported_bootstrap_version=str(value.get("minimum_supported_bootstrap_version") or "0.0.0"),
            revoked_product_versions=tuple(str(item) for item in value.get("revoked_product_versions", ())),
            release_notes=str(value.get("release_notes") or ""),
            validation_evidence=tuple(str(item) for item in value.get("validation_evidence", ())),
            schema_version=int(value.get("schema_version") or 0),
        )


@dataclass(frozen=True)
class ManifestSignature:
    key_id: str
    algorithm: str
    signature: str

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.key_id) or self.algorithm != "Ed25519" or not self.signature:
            raise ValueError("manifest signature is invalid")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def canonical_json(value: Any) -> bytes:
    """Canonical UTF-8 bytes signed by all release-manifest producers."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sign_manifest(manifest: ReleaseSetManifest, *, key_id: str, private_key: bytes) -> ManifestSignature:
    key = Ed25519PrivateKey.from_private_bytes(private_key)
    signature = key.sign(manifest.canonical_bytes())
    return ManifestSignature(key_id, "Ed25519", base64.b64encode(signature).decode("ascii"))


def verify_manifest(
    manifest: ReleaseSetManifest,
    signature: ManifestSignature,
    *,
    trusted_public_keys: Mapping[str, bytes],
    revoked_key_ids: frozenset[str] = frozenset(),
) -> None:
    if signature.key_id in revoked_key_ids:
        raise ValueError("manifest signing key is revoked")
    public_key = trusted_public_keys.get(signature.key_id)
    if public_key is None:
        raise ValueError("manifest signing key is unknown")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            base64.b64decode(signature.signature.encode("ascii"), validate=True), manifest.canonical_bytes()
        )
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("manifest signature verification failed") from exc


def public_key_bytes(private_key: bytes) -> bytes:
    return (
        Ed25519PrivateKey.from_private_bytes(private_key)
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )


def signed_envelope(manifest: ReleaseSetManifest, signature: ManifestSignature) -> dict[str, Any]:
    return {"manifest": manifest.to_dict(), "signature": signature.to_dict()}


def read_signed_envelope(value: Mapping[str, Any]) -> tuple[ReleaseSetManifest, ManifestSignature]:
    signature = _object(value, "signature")
    return (
        ReleaseSetManifest.from_dict(_object(value, "manifest")),
        ManifestSignature(str(signature.get("key_id") or ""), str(signature.get("algorithm") or ""), str(signature.get("signature") or "")),
    )


def _object(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    result = value.get(key)
    if not isinstance(result, Mapping):
        raise ValueError(f"{key} must be an object")
    return result


def _parse_timestamp(value: str) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError("build_timestamp must be ISO-8601") from exc
