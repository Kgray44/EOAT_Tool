"""Fail-closed Phase 1C publication, inventory, and planning primitives.

The implementation deliberately targets an explicit disposable Git/filesystem
backend.  It shares receipt and release-set validation with the convergence
service but never selects a production remote or calls GitHub state-changing
commands.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

from deployment.common import DeploymentError, read_json_object, sha256_file, utc_text, write_json_atomic
from deployment.convergence.artifacts import validate_web_package, verify_source_bundle
from deployment.manifest import validate_external_manifest
from deployment.release_manager import validate_deployment_archive
from release_tools.release_identity import ArtifactDisposition

from .release_set import ComponentKind, ComponentValidation, verify_signed_release_set
from .sealing import _BOOTSTRAP_REASON, _validate_smoke, _validate_zip, trust_material_from_environment


class Phase1CPublicationState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PREFLIGHT_COMPLETE = "PREFLIGHT_COMPLETE"
    SEALED_CANDIDATE_VERIFIED = "SEALED_CANDIDATE_VERIFIED"
    SOURCE_COMMIT_PROMOTED = "SOURCE_COMMIT_PROMOTED"
    TAG_PREPARED = "TAG_PREPARED"
    BRANCH_PUSHED = "BRANCH_PUSHED"
    TAG_PUSHED = "TAG_PUSHED"
    RELEASE_RECORD_CREATED = "RELEASE_RECORD_CREATED"
    PRIMARY_RELEASE_SET_ASSETS_UPLOADED = "PRIMARY_RELEASE_SET_ASSETS_UPLOADED"
    COMPONENT_ASSETS_VERIFIED = "COMPONENT_ASSETS_VERIFIED"
    PUBLICATION_RECEIPT_ATTACHED = "PUBLICATION_RECEIPT_ATTACHED"
    PUBLICATION_COMPLETE = "PUBLICATION_COMPLETE"
    FAILED_RECOVERABLE = "FAILED_RECOVERABLE"
    FAILED_MANUAL_INTERVENTION = "FAILED_MANUAL_INTERVENTION"


class ReleaseClassification(str, Enum):
    COMPLETE_TRUSTED = "COMPLETE_TRUSTED"
    COMPLETE_UNTRUSTED = "COMPLETE_UNTRUSTED"
    INCOMPLETE = "INCOMPLETE"
    CONFLICTING = "CONFLICTING"
    LEGACY_SINGLE_ARTIFACT = "LEGACY_SINGLE_ARTIFACT"
    DRAFT = "DRAFT"
    PRERELEASE = "PRERELEASE"
    REVOKED = "REVOKED"
    UNKNOWN = "UNKNOWN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


@dataclass(frozen=True)
class PublicationEligibility:
    eligible: bool
    candidate_id: str
    product_version: str
    release_id: str
    build_id: str
    source_commit: str
    source_tree: str
    release_set_digest: str
    signing_key_id: str
    signature_trusted: bool
    component_summary: dict[str, str]
    blocking_reasons: tuple[str, ...]
    next_safe_action: str


@dataclass(frozen=True)
class PublicationAsset:
    component_kind: str
    filename: str
    locator: str
    size_bytes: int
    sha256: str
    media_type: str


_REQUIRED_BUILT = {
    ComponentKind.SERVER.value, ComponentKind.WEB.value, ComponentKind.DESKTOP.value,
    ComponentKind.DESKTOP_UPDATE_MANIFEST.value, ComponentKind.LAUNCHER.value,
    ComponentKind.LAUNCHER_UPDATE_MANIFEST.value, ComponentKind.SOURCE_BUNDLE.value,
    ComponentKind.RELEASE_NOTES.value, ComponentKind.RELEASE_SET_MANIFEST.value,
    ComponentKind.RELEASE_SET_SIGNATURE.value,
}


def _required_built(*, final_current_components: bool) -> set[str]:
    """Return the publication components required by the candidate profile.

    Phase 1 receipts predate the Bootstrap implementation, so their sealed
    inventory legitimately preserves the governed Phase 2 exclusion.  A fresh
    final candidate explicitly opts into the current-component profile and
    must instead carry real Bootstrap bytes and its update-policy artifact.
    """

    required = set(_REQUIRED_BUILT)
    if final_current_components:
        required.update({ComponentKind.BOOTSTRAP.value, ComponentKind.BOOTSTRAP_UPDATE_MANIFEST.value})
    return required


def _relative(root: Path, locator: str) -> Path:
    pure = PurePosixPath(locator)
    if not locator or pure.is_absolute() or ".." in pure.parts or "\\" in locator:
        raise DeploymentError("release-set asset locator is unsafe")
    path = root.joinpath(*pure.parts)
    if root not in path.resolve().parents:
        raise DeploymentError("release-set asset locator escapes candidate storage")
    return path


def _require_bytes(root: Path, component: Mapping[str, Any]) -> Path:
    path = _relative(root, str(component.get("artifact_locator") or ""))
    if not path.is_file() or path.stat().st_size != int(component.get("size_bytes") or 0):
        raise DeploymentError(f"component {component.get('kind')} file is missing or has an unexpected size")
    if sha256_file(path) != str(component.get("sha256") or ""):
        raise DeploymentError(f"component {component.get('kind')} digest differs from the signed release set")
    if path.suffix.casefold() == ".zip":
        _validate_zip(path)
    return path


def verify_sealed_candidate(root: Path, receipt: Mapping[str, Any], *, repository: Path | None = None) -> PublicationEligibility:
    """Reopen seal, trust policy, and all immutable component bytes."""

    reasons: list[str] = []
    if receipt.get("schema_version") != 2:
        reasons.append("candidate receipt is not schema version 2")
    if receipt.get("state") != "RELEASE_SET_VALIDATED":
        reasons.append("candidate is not in RELEASE_SET_VALIDATED state")
    if receipt.get("publication_eligible") is not True:
        reasons.append("candidate does not declare publication eligibility")
    try:
        manifest_path = _relative(root, str(receipt.get("release_set_manifest_path") or ""))
        signature_info = dict(receipt.get("release_set_signature") or {})
        signature_path = _relative(root, str(signature_info.get("path") or ""))
        if sha256_file(manifest_path) != receipt.get("release_set_manifest_sha256"):
            raise DeploymentError("release-set manifest digest differs from receipt")
        if sha256_file(signature_path) != signature_info.get("sha256"):
            raise DeploymentError("release-set signature digest differs from receipt")
        manifest, signature = read_json_object(manifest_path), read_json_object(signature_path)
        trusted, revoked = trust_material_from_environment()
        release_set = verify_signed_release_set(
            {"release_set": manifest.get("canonical_payload"), "canonical_digest": manifest.get("canonical_payload_sha256"),
             "signature": {"key_id": signature.get("key_id"), "algorithm": signature.get("algorithm"), "signature": signature.get("signature")}},
            trusted_public_keys=trusted, revoked_key_ids=revoked,
        )
        if release_set.digest() != receipt.get("release_set_digest"):
            raise DeploymentError("release-set digest differs from sealed candidate receipt")
    except (DeploymentError, ValueError, OSError) as exc:
        reasons.append(str(exc))
        release_set = None

    component_summary: dict[str, str] = {}
    identity: dict[str, str] = {}
    final_current_components = receipt.get("release_set_profile") == "FINAL_CURRENT_COMPONENTS"
    if release_set is not None:
        identity = release_set.identity.to_dict()
        components = {component.kind.value: component.to_dict() for component in release_set.components}
        if set(components) != {kind.value for kind in ComponentKind}:
            reasons.append("release-set component inventory is incomplete")
        for kind, component in components.items():
            disposition, validation = component["disposition"], component["validation_status"]
            component_summary[kind] = f"{disposition}/{validation}"
            if kind in {ComponentKind.BOOTSTRAP.value, ComponentKind.BOOTSTRAP_UPDATE_MANIFEST.value}:
                if not final_current_components:
                    if disposition != ArtifactDisposition.NOT_APPLICABLE.value or component["not_applicable_justification"] != _BOOTSTRAP_REASON:
                        reasons.append(f"{kind} is not the governed Phase 2 exclusion")
                    continue
            if kind in _required_built(final_current_components=final_current_components) and (disposition != ArtifactDisposition.BUILT.value or validation != ComponentValidation.PASS.value):
                reasons.append(f"required component {kind} is not built and validated")
                continue
            # Outer files are bound by the receipt/envelope checks above.
            if kind not in {ComponentKind.RELEASE_SET_MANIFEST.value, ComponentKind.RELEASE_SET_SIGNATURE.value}:
                try:
                    artifact = _require_bytes(root, component)
                    metadata = dict(component.get("metadata") or {})
                    if kind == ComponentKind.SERVER.value and metadata.get("external_manifest_locator") and metadata.get("checksum_locator"):
                        manifest_path = _relative(root, str(metadata["external_manifest_locator"]))
                        checksum_path = _relative(root, str(metadata["checksum_locator"]))
                        validate_deployment_archive(artifact, manifest_path, checksum_path)
                        validate_external_manifest(read_json_object(manifest_path))
                    elif kind == ComponentKind.WEB.value and metadata.get("file_manifest_locator"):
                        validate_web_package(artifact)
                    elif kind == ComponentKind.SOURCE_BUNDLE.value and repository is not None:
                        verified = verify_source_bundle(artifact, candidate_root=root, commit=release_set.identity.source_commit, tree=release_set.identity.source_tree, base_commit=str(receipt.get("base_commit") or ""), repository=repository)
                        if verified.sha256 != component["sha256"]:
                            raise DeploymentError("source recovery bundle digest changed during verification")
                    elif kind in {
                        ComponentKind.DESKTOP.value,
                        ComponentKind.LAUNCHER.value,
                        ComponentKind.BOOTSTRAP.value,
                    } and metadata.get("smoke_receipt_locator"):
                        _validate_smoke(_relative(root, str(metadata["smoke_receipt_locator"])), component, release_set.identity)
                except DeploymentError as exc:
                    reasons.append(str(exc))
    if receipt.get("recovery_required") or receipt.get("publication_recovery_required"):
        reasons.append("candidate has an active recovery-required transaction")
    return PublicationEligibility(
        eligible=not reasons,
        candidate_id=str(receipt.get("candidate_id") or identity.get("candidate_id") or ""),
        product_version=str(identity.get("product_version") or receipt.get("version") or ""),
        release_id=str(identity.get("release_id") or ""), build_id=str(identity.get("build_id") or ""),
        source_commit=str(identity.get("source_commit") or receipt.get("candidate_commit") or ""),
        source_tree=str(identity.get("source_tree") or receipt.get("candidate_tree") or ""),
        release_set_digest=str(receipt.get("release_set_digest") or ""),
        signing_key_id=str((receipt.get("release_set_signature") or {}).get("key_id") or ""),
        signature_trusted=release_set is not None and not reasons,
        component_summary=component_summary, blocking_reasons=tuple(reasons),
        next_safe_action="Start disposable publication with exact typed confirmation." if not reasons else "Correct sealed-candidate evidence; do not publish.",
    )


def publication_assets(root: Path, receipt: Mapping[str, Any]) -> list[PublicationAsset]:
    """Return the complete publishable asset inventory without absolute paths."""

    working = receipt.get("working_release_set") or {}
    components = working.get("components") if isinstance(working, Mapping) else None
    if not isinstance(components, list):
        raise DeploymentError("sealed candidate has no component inventory")
    output: list[PublicationAsset] = []
    names: set[str] = set()
    for component in components:
        if not isinstance(component, Mapping) or component.get("disposition") != "BUILT":
            continue
        locator = str(component.get("artifact_locator") or "")
        if not locator:
            continue
        path = _require_bytes(root, component)
        asset = PublicationAsset(str(component["kind"]), path.name, locator, path.stat().st_size, sha256_file(path), str(component.get("media_type") or "application/octet-stream"))
        if asset.filename.casefold() in names:
            asset = PublicationAsset(asset.component_kind, f"{asset.component_kind}-{asset.filename}", asset.locator, asset.size_bytes, asset.sha256, asset.media_type)
        if asset.filename.casefold() in names:
            raise DeploymentError("duplicate normalized publication asset name")
        names.add(asset.filename.casefold())
        output.append(asset)
        metadata = dict(component.get("metadata") or {})
        for key in ("external_manifest_locator", "checksum_locator", "file_manifest_locator", "metadata_locator", "package_manifest_locator", "smoke_receipt_locator"):
            locator = str(metadata.get(key) or "")
            if not locator:
                continue
            support = _relative(root, locator)
            if not support.is_file():
                raise DeploymentError(f"supporting publication asset {key} is missing")
            filename = support.name if support.name.casefold() not in names else f"{asset.component_kind}-{support.name}"
            names.add(filename.casefold())
            output.append(PublicationAsset(asset.component_kind, filename, locator, support.stat().st_size, sha256_file(support), "application/json"))
    if {item.component_kind for item in output} < _required_built(
        final_current_components=receipt.get("release_set_profile") == "FINAL_CURRENT_COMPONENTS"
    ):
        raise DeploymentError("complete publication asset inventory is missing a required component")
    return sorted(output, key=lambda item: item.filename.casefold())


class DisposablePublicationBackend:
    """Real Git refs plus immutable filesystem assets, exclusively for tests."""

    def __init__(self, source: Path, remote: Path, registry: Path, *, fault_after: Phase1CPublicationState | None = None) -> None:
        self.source, self.remote, self.registry, self.fault_after = source, remote, registry, fault_after
        self.registry.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _git(cwd: Path, *args: str) -> str:
        result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
        if result.returncode:
            raise DeploymentError(f"disposable Git operation failed: {result.stderr.strip() or result.stdout.strip()}")
        return result.stdout.strip()

    def _release_dir(self, tag: str) -> Path:
        safe = tag.replace("/", "_")
        if not safe or ".." in safe:
            raise DeploymentError("unsafe disposable tag")
        return self.registry / safe

    def _inject(self, state: Phase1CPublicationState) -> None:
        if state is self.fault_after:
            raise DeploymentError(f"injected disposable publication failure after {state.value}")

    def promote(self, eligibility: PublicationEligibility, bundle: Path) -> None:
        head = self._git(self.source, "rev-parse", "HEAD")
        if head != eligibility.source_commit:
            known = subprocess.run(["git", "cat-file", "-e", f"{eligibility.source_commit}^{{commit}}"], cwd=self.source, text=True, capture_output=True)
            if known.returncode:
                self._git(self.source, "fetch", str(bundle), eligibility.source_commit)
                self._git(self.source, "merge", "--ff-only", "FETCH_HEAD")
            else:
                self._git(self.source, "merge", "--ff-only", eligibility.source_commit)
        if self._git(self.source, "rev-parse", "HEAD") != eligibility.source_commit:
            raise DeploymentError("disposable source promotion does not resolve candidate commit")

    def tag(self, tag: str, commit: str) -> None:
        existing = subprocess.run(["git", "rev-parse", "--verify", f"refs/tags/{tag}"], cwd=self.source, text=True, capture_output=True)
        if existing.returncode == 0:
            if self._git(self.source, "rev-list", "-n", "1", tag) != commit:
                raise DeploymentError("conflicting immutable disposable tag")
            return
        self._git(self.source, "tag", "-a", tag, commit, "-m", f"EOAT disposable {tag}")

    def push(self, tag: str, commit: str) -> None:
        self._git(self.source, "push", "origin", "HEAD:refs/heads/main")
        self._git(self.source, "push", "origin", tag)
        remote_tag = self._git(self.source, "ls-remote", str(self.remote), f"refs/tags/{tag}^{{}}")
        if commit not in remote_tag:
            raise DeploymentError("disposable remote tag does not resolve candidate commit")

    def release(self, tag: str, eligibility: PublicationEligibility) -> Path:
        directory = self._release_dir(tag)
        metadata = directory / "release.json"
        payload = {"tag": tag, "candidate_id": eligibility.candidate_id, "release_set_digest": eligibility.release_set_digest, "source_commit": eligibility.source_commit, "source_tree": eligibility.source_tree}
        if metadata.exists() and read_json_object(metadata) != payload:
            raise DeploymentError("conflicting disposable release record")
        directory.mkdir(parents=True, exist_ok=True)
        if not metadata.exists():
            write_json_atomic(metadata, payload)
        return directory

    def upload(self, release_dir: Path, candidate_root: Path, assets: list[PublicationAsset]) -> None:
        asset_dir = release_dir / "assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        index: dict[str, Any] = {}
        for asset in assets:
            target, source = asset_dir / asset.filename, _relative(candidate_root, asset.locator)
            if target.exists():
                if target.stat().st_size != asset.size_bytes or sha256_file(target) != asset.sha256:
                    raise DeploymentError(f"conflicting immutable disposable asset: {asset.filename}")
            else:
                shutil.copyfile(source, target)
                if sha256_file(target) != asset.sha256:
                    raise DeploymentError("disposable asset transfer digest mismatch")
            index[asset.filename] = {**asdict(asset), "remote_sha256": asset.sha256, "verification": "PASS"}
        write_json_atomic(release_dir / "asset-index.json", {"schema_version": 1, "assets": index})

    def verify(self, release_dir: Path, assets: list[PublicationAsset]) -> None:
        payload = read_json_object(release_dir / "asset-index.json")
        indexed = dict(payload.get("assets") or {})
        if set(indexed) != {item.filename for item in assets}:
            raise DeploymentError("disposable asset inventory is incomplete or contains unexpected assets")
        for asset in assets:
            target = release_dir / "assets" / asset.filename
            if not target.is_file() or target.stat().st_size != asset.size_bytes or sha256_file(target) != asset.sha256:
                raise DeploymentError(f"disposable remote asset verification failed: {asset.filename}")


def inventory_disposable(registry: Path, *, trusted_public_keys: Mapping[str, bytes], revoked_key_ids: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """Inventory filesystem release records without trusting their metadata."""

    output: list[dict[str, Any]] = []
    for directory in sorted(path for path in registry.iterdir() if path.is_dir()) if registry.is_dir() else []:
        reasons: list[str] = []
        try:
            meta = read_json_object(directory / "release.json")
            index = read_json_object(directory / "asset-index.json")
            assets = dict(index.get("assets") or {})
            manifest_name = next(name for name in assets if "release-set-manifest" in name)
            signature_name = next(name for name in assets if "release-set-signature" in name)
            manifest = read_json_object(directory / "assets" / manifest_name)
            signature = read_json_object(directory / "assets" / signature_name)
            release_set = verify_signed_release_set(
                {"release_set": manifest.get("canonical_payload"), "canonical_digest": manifest.get("canonical_payload_sha256"),
                 "signature": {"key_id": signature.get("key_id"), "algorithm": signature.get("algorithm"), "signature": signature.get("signature")}},
                trusted_public_keys=trusted_public_keys, revoked_key_ids=revoked_key_ids,
            )
            for asset in assets.values():
                target = directory / "assets" / str(asset.get("filename"))
                if not target.is_file() or sha256_file(target) != asset.get("sha256"):
                    reasons.append(f"asset mismatch: {asset.get('filename')}")
            classification = ReleaseClassification.COMPLETE_TRUSTED if not reasons else ReleaseClassification.INCOMPLETE
            output.append({"tag": meta.get("tag"), "candidate_id": meta.get("candidate_id"), "release_set_digest": release_set.digest(), "product_version": release_set.identity.product_version, "release_id": release_set.identity.release_id, "build_id": release_set.identity.build_id, "source_commit": release_set.identity.source_commit, "source_tree": release_set.identity.source_tree, "database_schema_revision": release_set.database_schema_revision, "api_contract_version": release_set.api_contract_version, "signing_key_id": signature.get("key_id"), "signature_valid": not reasons, "classification": classification.value, "deployable": not reasons, "client_promotable": not reasons, "assets": sorted(assets), "blocking_reasons": reasons, "next_safe_action": "Select this trusted release for disposable deployment planning." if not reasons else "Resolve immutable release inventory conflict."})
        except (DeploymentError, ValueError, OSError, StopIteration) as exc:
            output.append({"tag": directory.name, "classification": ReleaseClassification.INCOMPLETE.value, "deployable": False, "client_promotable": False, "blocking_reasons": [str(exc)], "next_safe_action": "Inspect incomplete disposable release evidence."})
    by_version: dict[str, list[dict[str, Any]]] = {}
    for item in output:
        if item.get("product_version"):
            by_version.setdefault(str(item["product_version"]), []).append(item)
    for entries in by_version.values():
        if len({item.get("build_id") for item in entries}) > 1:
            for item in entries:
                item.update({"classification": ReleaseClassification.CONFLICTING.value, "deployable": False, "blocking_reasons": [*item.get("blocking_reasons", []), "same product version has conflicting build identity"]})
    return output


def run_disposable_publication(
    *, root: Path, store: Any, candidate_id: str, confirmation: str, backend: DisposablePublicationBackend
) -> dict[str, Any]:
    """Advance a durable multi-asset publication transaction against only a disposable backend."""

    if confirmation != f"PUBLISH {candidate_id}":
        raise DeploymentError("disposable publication requires exact confirmation: PUBLISH <candidate-id>")
    candidate = store.read("candidate", candidate_id)
    candidate_root = store.root / "candidates" / candidate_id
    eligibility = verify_sealed_candidate(candidate_root, candidate, repository=root)
    if not eligibility.eligible:
        raise DeploymentError("sealed candidate is publication-ineligible: " + "; ".join(eligibility.blocking_reasons))
    assets = publication_assets(candidate_root, candidate)
    publication_id = f"publication-{candidate_id}"
    existing: dict[str, Any] | None = None
    try:
        existing = store.read("publication", publication_id)
    except DeploymentError:
        pass
    if existing and existing.get("state") == Phase1CPublicationState.PUBLICATION_COMPLETE.value:
        if existing.get("release_set_digest") != eligibility.release_set_digest:
            raise DeploymentError("completed immutable publication receipt conflicts with sealed candidate")
        backend.verify(backend._release_dir(str(existing.get("tag") or "")), assets)
        return existing
    tag = str((existing or {}).get("tag") or f"v{eligibility.product_version}-{eligibility.source_commit[:12]}")
    record: dict[str, Any] = dict(existing or {})
    record.update({
        "schema_version": 2, "publication_id": publication_id, "candidate_id": candidate_id,
        "product_version": eligibility.product_version, "release_id": eligibility.release_id, "build_id": eligibility.build_id,
        "source_commit": eligibility.source_commit, "source_tree": eligibility.source_tree,
        "release_set_digest": eligibility.release_set_digest, "signing_key_id": eligibility.signing_key_id,
        "tag": tag, "backend": "DISPOSABLE_GIT_FILESYSTEM", "repository_identity": str(backend.remote), "registry_identity": str(backend.registry),
        "asset_inventory": [asdict(asset) for asset in assets], "completed_steps": list(record.get("completed_steps") or []),
        "updated_at_utc": utc_text(), "next_safe_action": "Resume disposable publication.",
    })

    def checkpoint(state: Phase1CPublicationState) -> None:
        record["state"] = state.value
        if state.value not in record["completed_steps"]:
            record["completed_steps"].append(state.value)
        record["updated_at_utc"] = utc_text()
        store.write("publication", publication_id, record)
        backend._inject(state)

    try:
        checkpoint(Phase1CPublicationState.PREFLIGHT_COMPLETE)
        checkpoint(Phase1CPublicationState.SEALED_CANDIDATE_VERIFIED)
        bundle: Path | None = None
        # The source bundle is addressed by component kind, never by a guessed
        # absolute receipt path.
        for component in (candidate.get("working_release_set") or {}).get("components", []):
            if isinstance(component, Mapping) and component.get("kind") == ComponentKind.SOURCE_BUNDLE.value:
                bundle = _relative(candidate_root, str(component.get("artifact_locator") or ""))
                break
        if bundle is None:
            raise DeploymentError("sealed candidate has no source recovery bundle")
        backend.promote(eligibility, bundle)
        checkpoint(Phase1CPublicationState.SOURCE_COMMIT_PROMOTED)
        backend.tag(tag, eligibility.source_commit)
        checkpoint(Phase1CPublicationState.TAG_PREPARED)
        backend.push(tag, eligibility.source_commit)
        checkpoint(Phase1CPublicationState.BRANCH_PUSHED)
        checkpoint(Phase1CPublicationState.TAG_PUSHED)
        release_dir = backend.release(tag, eligibility)
        checkpoint(Phase1CPublicationState.RELEASE_RECORD_CREATED)
        backend.upload(release_dir, candidate_root, assets)
        checkpoint(Phase1CPublicationState.PRIMARY_RELEASE_SET_ASSETS_UPLOADED)
        backend.verify(release_dir, assets)
        checkpoint(Phase1CPublicationState.COMPONENT_ASSETS_VERIFIED)
        publication_evidence = {"schema_version": 2, "publication_id": publication_id, "candidate_id": candidate_id, "release_set_digest": eligibility.release_set_digest, "asset_count": len(assets), "status": "PASS", "recorded_at_utc": utc_text()}
        receipt_name = f"{publication_id}.json"
        write_json_atomic(release_dir / "assets" / receipt_name, publication_evidence)
        index = read_json_object(release_dir / "asset-index.json")
        index["assets"][receipt_name] = {"component_kind": "publication_receipt", "filename": receipt_name, "locator": "", "size_bytes": (release_dir / "assets" / receipt_name).stat().st_size, "sha256": sha256_file(release_dir / "assets" / receipt_name), "media_type": "application/json", "remote_sha256": sha256_file(release_dir / "assets" / receipt_name), "verification": "PASS"}
        write_json_atomic(release_dir / "asset-index.json", index)
        record["publication_receipt_asset"] = {"filename": receipt_name, "sha256": index["assets"][receipt_name]["sha256"]}
        checkpoint(Phase1CPublicationState.PUBLICATION_RECEIPT_ATTACHED)
        record.update({"state": Phase1CPublicationState.PUBLICATION_COMPLETE.value, "next_safe_action": "Refresh disposable release inventory and create a read-only deployment plan.", "failure": None})
        checkpoint(Phase1CPublicationState.PUBLICATION_COMPLETE)
        return record
    except Exception as exc:
        record.update({"state": Phase1CPublicationState.FAILED_RECOVERABLE.value, "failure": str(exc), "next_safe_action": "Reconcile matching immutable disposable state and resume publication.", "updated_at_utc": utc_text()})
        store.write("publication", publication_id, record)
        raise
