"""Fail-closed final sealing for schema-2 EOAT Atlas release-set candidates.

The signed bytes deliberately exclude the hashes of the outer manifest and
detached-signature files.  Those files are generated *from* the canonical
payload and are tracked in the receipt-only component inventory afterwards,
which avoids a circular self-hash.
"""

from __future__ import annotations

import base64
import json
import shutil
import tempfile
import zipfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from deployment.common import (
    DeploymentError,
    read_json_object,
    sha256_file,
    utc_text,
    write_json_atomic,
)
from deployment.convergence.artifacts import validate_web_package, verify_source_bundle
from deployment.manifest import validate_external_manifest
from deployment.release_manager import validate_deployment_archive
from release_tools.release_identity import (
    ArtifactDisposition,
    ManifestSignature,
    ProductReleaseIdentity,
    public_key_bytes,
)

from .release_set import (
    ComponentKind,
    ComponentValidation,
    ReleaseSetComponent,
    SignedReleaseSet,
    verify_signed_release_set,
)

_BOOTSTRAP_REASON = "Bootstrap implementation is owned by Unified Release Train Phase 2."
_PENDING_OUTER = {ComponentKind.RELEASE_SET_MANIFEST.value, ComponentKind.RELEASE_SET_SIGNATURE.value}
_REQUIRED_BUILT = {kind.value for kind in ComponentKind} - _PENDING_OUTER


def _safe_locator(candidate_root: Path, locator: str) -> Path:
    pure = PurePosixPath(locator)
    if not locator or pure.is_absolute() or ".." in pure.parts or "\\" in locator:
        raise DeploymentError("candidate component has an unsafe relative locator")
    path = candidate_root.joinpath(*pure.parts)
    if candidate_root not in path.resolve().parents and path.resolve() != candidate_root:
        raise DeploymentError("candidate component locator escapes candidate storage")
    return path


def _validate_zip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            seen: set[str] = set()
            for member in archive.infolist():
                if member.is_dir():
                    continue
                name = member.filename
                pure = PurePosixPath(name)
                if not name or pure.is_absolute() or ".." in pure.parts or "\\" in name or name.casefold() in seen:
                    raise DeploymentError("component archive contains unsafe or duplicate paths")
                seen.add(name.casefold())
    except zipfile.BadZipFile as exc:
        raise DeploymentError("component archive is malformed") from exc


def _identity(receipt: Mapping[str, Any]) -> ProductReleaseIdentity:
    working = receipt.get("working_release_set")
    if not isinstance(working, Mapping) or not isinstance(working.get("identity"), Mapping):
        raise DeploymentError("schema-2 candidate has no working release-set identity")
    try:
        return ProductReleaseIdentity.from_dict(working["identity"])
    except ValueError as exc:
        raise DeploymentError("candidate release identity is malformed") from exc


def _components(receipt: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    working = receipt.get("working_release_set")
    raw = working.get("components") if isinstance(working, Mapping) else None
    if not isinstance(raw, list):
        raise DeploymentError("candidate has no explicit component inventory")
    values = {str(item.get("kind") or ""): dict(item) for item in raw if isinstance(item, Mapping)}
    expected = {kind.value for kind in ComponentKind}
    if set(values) != expected or len(values) != len(raw):
        raise DeploymentError("candidate component inventory is incomplete or duplicated")
    return values


def _validate_smoke(path: Path, component: dict[str, Any], identity: ProductReleaseIdentity) -> None:
    receipt = read_json_object(path)
    required = {"schema_version", "component_kind", "candidate_id", "product_version", "release_id", "build_id", "source_commit", "source_tree", "status", "package_sha256", "started_at_utc", "completed_at_utc", "checks"}
    if not required <= receipt.keys() or receipt.get("status") != "PASS":
        raise DeploymentError("packaged smoke receipt is incomplete or did not pass")
    expected = {
        "component_kind": component["kind"], "candidate_id": identity.candidate_id,
        "product_version": identity.product_version, "release_id": identity.release_id,
        "build_id": identity.build_id, "source_commit": identity.source_commit,
        "source_tree": identity.source_tree, "package_sha256": component["sha256"],
    }
    if any(str(receipt.get(key) or "") != value for key, value in expected.items()):
        raise DeploymentError("packaged smoke receipt identity does not match component")
    if not isinstance(receipt.get("checks"), list) or not receipt["checks"]:
        raise DeploymentError("packaged smoke receipt has no validation checks")


def revalidate_candidate(candidate_root: Path, receipt: Mapping[str, Any], repository: Path) -> tuple[SignedReleaseSet, dict[str, str]]:
    """Reopen every retained component before canonical bytes are created."""

    if receipt.get("schema_version") != 2 or receipt.get("state") != "PLATFORM_ARTIFACTS_PENDING":
        raise DeploymentError("only an attached unsigned schema-2 candidate may be sealed")
    identity = _identity(receipt)
    components = _components(receipt)
    evidence: dict[str, str] = {}
    for kind, component in components.items():
        disposition = str(component.get("disposition") or "")
        if kind in {ComponentKind.BOOTSTRAP.value, ComponentKind.BOOTSTRAP_UPDATE_MANIFEST.value} and disposition == ArtifactDisposition.NOT_APPLICABLE.value:
            if receipt.get("release_set_profile") == "FINAL_CURRENT_COMPONENTS":
                raise DeploymentError("final integrated candidates require built Bootstrap components")
            if component.get("not_applicable_justification") != _BOOTSTRAP_REASON or component.get("artifact_locator"):
                raise DeploymentError("bootstrap legacy exclusion is not governed")
            continue
        if kind in _PENDING_OUTER:
            if disposition != ArtifactDisposition.PENDING.value:
                raise DeploymentError("outer sealing components must remain pending before sealing")
            continue
        if disposition != ArtifactDisposition.BUILT.value or component.get("validation_status") != ComponentValidation.PASS.value:
            raise DeploymentError(f"required component {kind} is not built and validated")
        for field, expected in (("product_version", identity.product_version), ("release_id", identity.release_id), ("build_id", identity.build_id), ("source_commit", identity.source_commit), ("source_tree", identity.source_tree), ("candidate_id", identity.candidate_id)):
            if str(component.get(field) or "") != expected:
                raise DeploymentError(f"component {kind} has conflicting {field}")
        artifact = _safe_locator(candidate_root, str(component.get("artifact_locator") or ""))
        if not artifact.is_file() or artifact.stat().st_size != int(component.get("size_bytes") or 0) or sha256_file(artifact) != component.get("sha256"):
            raise DeploymentError(f"component {kind} bytes do not match immutable receipt identity")
        if artifact.suffix.casefold() == ".zip":
            _validate_zip(artifact)
        evidence[kind] = str(component["sha256"])

    server = _safe_locator(candidate_root, str(components[ComponentKind.SERVER.value]["artifact_locator"]))
    server_dir = server.parent
    validate_deployment_archive(server, server_dir / "release_manifest.json", server_dir / f"{server.name}.sha256")
    external, _ = validate_external_manifest(read_json_object(server_dir / "release_manifest.json"))
    if str(external.get("release_id") or "") != identity.release_id or str(external.get("build_id") or "") != identity.build_id:
        raise DeploymentError("server external manifest identity does not match candidate")
    validate_web_package(_safe_locator(candidate_root, str(components[ComponentKind.WEB.value]["artifact_locator"])))
    bundle = _safe_locator(candidate_root, str(components[ComponentKind.SOURCE_BUNDLE.value]["artifact_locator"]))
    verified_bundle = verify_source_bundle(bundle, candidate_root=candidate_root, commit=identity.source_commit, tree=identity.source_tree, base_commit=str(receipt.get("base_commit") or ""), repository=repository)
    if verified_bundle.sha256 != components[ComponentKind.SOURCE_BUNDLE.value]["sha256"]:
        raise DeploymentError("source bundle verification changed immutable digest")

    # Windows support evidence is copied into candidate storage at attachment
    # time; require it here rather than trusting a runner-local attachment.
    for kind in (ComponentKind.DESKTOP.value, ComponentKind.LAUNCHER.value, ComponentKind.BOOTSTRAP.value):
        metadata = dict(components[kind].get("metadata") or {})
        smoke_locator = metadata.get("smoke_receipt_locator", "")
        if not smoke_locator:
            raise DeploymentError(f"{kind} has no retained smoke receipt")
        _validate_smoke(_safe_locator(candidate_root, smoke_locator), components[kind], identity)
        evidence[f"{kind}_smoke"] = sha256_file(_safe_locator(candidate_root, smoke_locator))

    typed: list[ReleaseSetComponent] = []
    for kind in sorted(components):
        item = dict(components[kind])
        if kind in _PENDING_OUTER:
            # Canonical payload acknowledges outer components as being created
            # by this transaction but deliberately omits their future hashes.
            item.update({"disposition": "BUILT", "validation_status": "PASS", "metadata": {"outer_artifact": "excluded from canonical self-hash"}})
        typed.append(ReleaseSetComponent.from_dict(item))
    working = receipt["working_release_set"]
    release_set = SignedReleaseSet(
        identity, tuple(typed), str(working.get("api_contract_version") or ""),
        str(working.get("database_schema_revision") or ""), str(working.get("migration_state") or "UNKNOWN"),
        str(working.get("minimum_supported_desktop_version") or "0.0.0"), str(working.get("minimum_supported_launcher_version") or "0.0.0"),
        str(working.get("minimum_supported_bootstrap_version") or "0.0.0"),
        validation_checks=tuple(sorted(f"{key}:{value}" for key, value in evidence.items())),
        next_safe_action="Phase 1C publication verification.",
    )
    return release_set, evidence


def _signature_payload(signature: ManifestSignature, digest: str) -> dict[str, Any]:
    return {"schema_version": 1, "algorithm": signature.algorithm, "key_id": signature.key_id, "canonical_payload_sha256": digest, "signature": signature.signature}


def seal_candidate(
    candidate_root: Path,
    receipt: Mapping[str, Any],
    repository: Path,
    *,
    key_id: str,
    private_key: bytes,
    trusted_public_keys: Mapping[str, bytes],
    revoked_key_ids: frozenset[str] = frozenset(),
) -> tuple[dict[str, Any], dict[str, Any]]:
    release_set, evidence = revalidate_candidate(candidate_root, receipt, repository)
    digest = release_set.digest()
    signature = release_set.sign(key_id=key_id, private_key=private_key)
    verify_signed_release_set(release_set.envelope(signature), trusted_public_keys=trusted_public_keys, revoked_key_ids=revoked_key_ids)
    sealing = candidate_root / "sealing"
    manifest = sealing / "release-set-manifest.json"
    detached = sealing / "release-set-signature.json"
    envelope = {"envelope_schema_version": 1, "canonical_payload": release_set.unsigned_dict(), "canonical_payload_sha256": digest, "signature_metadata": {"key_id": signature.key_id, "algorithm": signature.algorithm}}
    signature_payload = _signature_payload(signature, digest)
    if manifest.exists() or detached.exists():
        if not (manifest.is_file() and detached.is_file()):
            raise DeploymentError("partially present immutable sealing outputs require reconciliation")
        if read_json_object(manifest) != envelope or read_json_object(detached) != signature_payload:
            raise DeploymentError("existing immutable sealing output conflicts with this candidate")
    else:
        with tempfile.TemporaryDirectory(prefix="eoat-sealing-", dir=candidate_root) as temporary:
            stage = Path(temporary)
            staged_manifest, staged_signature = stage / manifest.name, stage / detached.name
            write_json_atomic(staged_manifest, envelope)
            write_json_atomic(staged_signature, signature_payload)
            if read_json_object(staged_manifest) != envelope or read_json_object(staged_signature) != signature_payload:
                raise DeploymentError("staged sealing outputs failed reopen verification")
            sealing.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staged_manifest), manifest)
            shutil.move(str(staged_signature), detached)
    # Reopen independent files and verify their canonical payload one last time.
    reopened = read_json_object(manifest)
    detached_payload = read_json_object(detached)
    if reopened != envelope or detached_payload != signature_payload:
        raise DeploymentError("sealed output changed before receipt update")
    verify_signed_release_set(
        {"release_set": reopened["canonical_payload"], "canonical_digest": reopened["canonical_payload_sha256"], "signature": {"key_id": detached_payload["key_id"], "algorithm": detached_payload["algorithm"], "signature": detached_payload["signature"]}},
        trusted_public_keys=trusted_public_keys, revoked_key_ids=revoked_key_ids,
    )
    updated = dict(receipt)
    working = dict(updated["working_release_set"])
    components = [dict(item) for item in working.get("components", [])]
    for component in components:
        if component.get("kind") == ComponentKind.RELEASE_SET_MANIFEST.value:
            component.update({"disposition": "BUILT", "validation_status": "PASS", "artifact_filename": manifest.name, "artifact_locator": "sealing/release-set-manifest.json", "size_bytes": manifest.stat().st_size, "sha256": sha256_file(manifest), "media_type": "application/json", "metadata": {"canonical_payload_sha256": digest, "envelope_schema_version": "1"}})
        elif component.get("kind") == ComponentKind.RELEASE_SET_SIGNATURE.value:
            component.update({"disposition": "BUILT", "validation_status": "PASS", "artifact_filename": detached.name, "artifact_locator": "sealing/release-set-signature.json", "size_bytes": detached.stat().st_size, "sha256": sha256_file(detached), "media_type": "application/json", "metadata": {"canonical_payload_sha256": digest, "key_id": key_id, "algorithm": "Ed25519"}})
    working["components"] = components
    updated.update({
        "state": "RELEASE_SET_VALIDATED", "working_release_set": working, "release_set": release_set.unsigned_dict(),
        "release_set_digest": digest, "release_set_manifest_path": "sealing/release-set-manifest.json", "release_set_manifest_sha256": sha256_file(manifest),
        "release_set_signature": {"path": "sealing/release-set-signature.json", "sha256": sha256_file(detached), "key_id": key_id, "algorithm": "Ed25519", "trusted": True},
        "sealing_validation_evidence": evidence, "publication_eligible": True, "blocking_reasons": [],
        # This persisted value is deliberately derived from the final inventory
        # rather than carrying the unsigned receipt's stale pending list.
        "missing_components": sorted(
            str(component.get("kind"))
            for component in components
            if component.get("disposition") == ArtifactDisposition.PENDING.value
        ),
        "next_safe_action": "Phase 1C publication verification.",
    })
    receipt_payload = {"schema_version": 1, "candidate_id": identity.candidate_id if (identity := release_set.identity) else "", "status": "PASS", "release_set_digest": digest, "manifest_sha256": sha256_file(manifest), "signature_sha256": sha256_file(detached), "key_id": key_id, "recorded_at_utc": utc_text()}
    return updated, receipt_payload


def trust_material_from_environment() -> tuple[dict[str, bytes], frozenset[str]]:
    """Load public verification policy without requiring a private signing key."""

    import os

    trusted_encoded = os.environ.get("EOAT_RELEASE_TRUSTED_PUBLIC_KEYS_JSON", "").strip()
    if not trusted_encoded:
        raise DeploymentError("trusted public release-set keys are not configured")
    try:
        raw_keys = json.loads(trusted_encoded)
        trusted = {str(name): base64.b64decode(str(value).encode("ascii"), validate=True) for name, value in dict(raw_keys).items()}
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise DeploymentError("trusted public release-set keys are malformed") from exc
    revoked = frozenset(item.strip() for item in os.environ.get("EOAT_RELEASE_REVOKED_KEY_IDS", "").split(",") if item.strip())
    return trusted, revoked


def signing_material_from_environment() -> tuple[str, bytes, dict[str, bytes], frozenset[str]]:
    """Load ephemeral development material without echoing private bytes."""

    import os

    key_id = os.environ.get("EOAT_RELEASE_SIGNING_KEY_ID", "").strip()
    private_encoded = os.environ.get("EOAT_RELEASE_TEST_PRIVATE_KEY_B64", "").strip()
    private_file = os.environ.get("EOAT_RELEASE_TEST_PRIVATE_KEY_FILE", "").strip()
    if not key_id or not (private_encoded or private_file):
        raise DeploymentError("non-production signing material is not configured")
    try:
        private_key = Path(private_file).read_bytes() if private_file else base64.b64decode(private_encoded.encode("ascii"), validate=True)
    except (ValueError, OSError) as exc:
        raise DeploymentError("non-production signing material is malformed") from exc
    trusted, revoked = trust_material_from_environment()
    if len(private_key) != 32 or public_key_bytes(private_key) != trusted.get(key_id):
        raise DeploymentError("configured trusted key does not match signing key")
    if key_id in revoked:
        raise DeploymentError("configured signing key is revoked")
    return key_id, private_key, trusted, revoked
