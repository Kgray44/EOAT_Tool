"""Identity-bound Windows attachment bundles for unsigned schema-2 candidates."""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from deployment.common import DeploymentError, read_json_object, sha256_file, utc_text, write_json_atomic

from .artifacts import candidate_locator
from .release_set import ComponentKind

_PLATFORM_KINDS = {
    ComponentKind.DESKTOP.value,
    ComponentKind.DESKTOP_UPDATE_MANIFEST.value,
    ComponentKind.LAUNCHER.value,
    ComponentKind.LAUNCHER_UPDATE_MANIFEST.value,
    ComponentKind.BOOTSTRAP.value,
    ComponentKind.BOOTSTRAP_UPDATE_MANIFEST.value,
}


def _expected_platform_kinds(candidate: dict[str, Any] | None) -> set[str]:
    """Derive required Windows components from the immutable candidate, not a phase-specific constant."""
    if candidate is None:
        return set(_PLATFORM_KINDS)
    working = candidate.get("working_release_set") or {}
    components = working.get("components") if isinstance(working, dict) else []
    return {
        str(item.get("kind") or "")
        for item in components if isinstance(item, dict)
        and str(item.get("kind") or "") in _PLATFORM_KINDS
        and str(item.get("disposition") or "") == "PENDING"
    }


@dataclass(frozen=True)
class AttachmentComponent:
    kind: str
    artifact: str
    sha256: str
    size_bytes: int
    metadata: str = ""
    package_manifest: str = ""
    smoke_receipt: str = ""
    target_locator: str = ""


def _safe_relative(value: str) -> Path:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise DeploymentError("attachment contains an unsafe relative path")
    return Path(*path.parts)


def _read_attachment(path: Path) -> tuple[Path, dict[str, Any], tempfile.TemporaryDirectory[str] | None]:
    if path.is_dir():
        manifest = path / "attachment-manifest.json"
        return path, read_json_object(manifest), None
    if not path.is_file() or path.suffix.casefold() != ".zip":
        raise DeploymentError("attachment must be a directory or immutable ZIP bundle")
    temporary = tempfile.TemporaryDirectory(prefix="eoat-attachment-")
    root = Path(temporary.name)
    try:
        with zipfile.ZipFile(path) as archive:
            seen: set[str] = set()
            for member in archive.infolist():
                if member.is_dir():
                    continue
                relative = member.filename
                if relative.casefold() in seen:
                    raise DeploymentError("attachment ZIP has duplicate normalized paths")
                seen.add(relative.casefold())
                _safe_relative(relative)
                destination = root / _safe_relative(relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
        return root, read_json_object(root / "attachment-manifest.json"), temporary
    except Exception:
        temporary.cleanup()
        raise


def _identity_matches(manifest: dict[str, Any], candidate: dict[str, Any]) -> None:
    identity = manifest.get("identity") if isinstance(manifest.get("identity"), dict) else manifest
    expected = {
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "product_version": str(candidate.get("version") or ""),
        "source_commit": str(candidate.get("candidate_commit") or ""),
        "source_tree": str(candidate.get("candidate_tree") or ""),
    }
    working = candidate.get("working_release_set") or {}
    declared = working.get("identity") if isinstance(working, dict) else {}
    expected["release_id"] = str((declared or {}).get("release_id") or "")
    expected["build_id"] = str((declared or {}).get("build_id") or "")
    for key, value in expected.items():
        if not value or str(identity.get(key) or manifest.get(key) or "") != value:
            raise DeploymentError(f"attachment identity mismatch for {key}")
    if str(manifest.get("platform") or "").casefold() != "windows":
        raise DeploymentError("platform attachment is not a Windows build")


def _validate_receipt(path: Path, component: AttachmentComponent, candidate: dict[str, Any], package_hash: str) -> None:
    receipt = read_json_object(path)
    required = ("schema_version", "component_kind", "candidate_id", "product_version", "release_id", "build_id", "source_commit", "source_tree", "status", "started_at_utc", "completed_at_utc")
    if not all(key in receipt for key in required):
        raise DeploymentError("packaged smoke receipt is incomplete")
    if str(receipt.get("component_kind")) != component.kind or str(receipt.get("status")) != "PASS":
        raise DeploymentError("packaged smoke receipt did not pass for attached component")
    expected = {
        "candidate_id": candidate["candidate_id"], "product_version": candidate["version"],
        "source_commit": candidate["candidate_commit"], "source_tree": candidate["candidate_tree"],
    }
    identity = (candidate.get("working_release_set") or {}).get("identity") or {}
    expected.update({"release_id": identity.get("release_id"), "build_id": identity.get("build_id")})
    if any(str(receipt.get(key)) != str(value) for key, value in expected.items()):
        raise DeploymentError("packaged smoke receipt identity does not match candidate")
    if receipt.get("package_sha256") and str(receipt["package_sha256"]) != package_hash:
        raise DeploymentError("packaged smoke receipt package hash does not match attachment")


def inspect_attachment(path: Path, candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    root, manifest, temporary = _read_attachment(path)
    try:
        if int(manifest.get("schema_version") or 0) != 1:
            raise DeploymentError("unsupported platform attachment schema")
        if candidate is not None:
            _identity_matches(manifest, candidate)
        raw_components = manifest.get("components")
        expected_kinds = _expected_platform_kinds(candidate)
        # A byte-identical retry remains valid after the first transaction
        # changes the inventory from PENDING to BUILT.  It is still checked
        # against the declared immutable component set below.
        declared_platform_kinds: set[str] = set()
        if candidate is not None:
            working = candidate.get("working_release_set") or {}
            declared_platform_kinds = {
                str(item.get("kind") or "") for item in working.get("components", [])
                if isinstance(item, dict)
                and str(item.get("kind") or "") in _PLATFORM_KINDS
                and str(item.get("disposition") or "") in {"PENDING", "BUILT"}
            }
        allowed_kinds = expected_kinds or declared_platform_kinds
        if not isinstance(raw_components, list):
            raise DeploymentError("attachment must declare a component inventory")
        components: list[AttachmentComponent] = []
        seen: set[str] = set()
        for raw in raw_components:
            if not isinstance(raw, dict):
                raise DeploymentError("attachment contains a malformed component record")
            component = AttachmentComponent(
                kind=str(raw.get("kind") or ""), artifact=str(raw.get("artifact") or ""),
                sha256=str(raw.get("sha256") or ""), size_bytes=int(raw.get("size_bytes") or 0),
                metadata=str(raw.get("metadata") or ""), package_manifest=str(raw.get("package_manifest") or ""),
                smoke_receipt=str(raw.get("smoke_receipt") or ""), target_locator=str(raw.get("target_locator") or ""),
            )
            if component.kind not in allowed_kinds or component.kind in seen or len(component.sha256) != 64 or component.size_bytes <= 0:
                raise DeploymentError("attachment has invalid or duplicate component identity")
            seen.add(component.kind)
            file = root / _safe_relative(component.artifact)
            if not file.is_file() or file.stat().st_size != component.size_bytes or sha256_file(file) != component.sha256:
                raise DeploymentError("attachment artifact bytes do not match declared identity")
            if file.suffix.casefold() == ".zip":
                try:
                    with zipfile.ZipFile(file) as package:
                        names: set[str] = set()
                        for member in package.infolist():
                            if member.is_dir():
                                continue
                            if member.filename.casefold() in names:
                                raise DeploymentError("attached package ZIP has duplicate normalized paths")
                            names.add(member.filename.casefold())
                            _safe_relative(member.filename)
                except zipfile.BadZipFile as exc:
                    raise DeploymentError("attached package is not a safe readable ZIP") from exc
            if not component.target_locator:
                raise DeploymentError("attachment component has no candidate-relative target locator")
            _safe_relative(component.target_locator)
            if component.metadata:
                metadata = read_json_object(root / _safe_relative(component.metadata))
                for key in ("candidate_id", "product_version", "release_id", "build_id", "source_commit", "source_tree"):
                    if candidate is not None:
                        identity = (candidate.get("working_release_set") or {}).get("identity") or {}
                        expected = candidate.get(key) or identity.get(key)
                        actual = metadata.get(key)
                        if actual is None and key == "product_version":
                            actual = metadata.get("app_version")
                        if actual is None and key == "source_commit":
                            actual = metadata.get("source_git_commit")
                        if str(actual or "") != str(expected or ""):
                            raise DeploymentError("attachment embedded metadata identity mismatch")
            if component.kind in {ComponentKind.DESKTOP.value, ComponentKind.LAUNCHER.value, ComponentKind.BOOTSTRAP.value}:
                if not component.smoke_receipt:
                    raise DeploymentError("desktop, launcher, and bootstrap attachments require smoke receipts")
                if candidate is not None:
                    _validate_receipt(root / _safe_relative(component.smoke_receipt), component, candidate, component.sha256)
                if not component.package_manifest:
                    raise DeploymentError("desktop and launcher attachments require package manifests")
                package_manifest = read_json_object(root / _safe_relative(component.package_manifest))
                if not isinstance(package_manifest.get("files"), list) or not package_manifest["files"]:
                    raise DeploymentError("attached package manifest has no file inventory")
            components.append(component)
        if seen != allowed_kinds:
            raise DeploymentError("attachment does not declare every required Windows component exactly once")
        by_kind = {component.kind: component for component in components}
        for kind, package_kind in ((ComponentKind.DESKTOP_UPDATE_MANIFEST.value, ComponentKind.DESKTOP.value), (ComponentKind.LAUNCHER_UPDATE_MANIFEST.value, ComponentKind.LAUNCHER.value), (ComponentKind.BOOTSTRAP_UPDATE_MANIFEST.value, ComponentKind.BOOTSTRAP.value)):
            if kind not in by_kind:
                continue
            update = by_kind[kind]
            update_payload = read_json_object(root / _safe_relative(update.artifact))
            package = by_kind[package_kind]
            if str(update_payload.get("sha256") or "") != package.sha256 or str(update_payload.get("package_locator") or "") != package.artifact:
                raise DeploymentError("update manifest does not bind its immutable package")
            if candidate is not None:
                for key in ("candidate_id", "product_version", "release_id", "build_id", "source_commit", "source_tree"):
                    expected = candidate.get(key) or ((candidate.get("working_release_set") or {}).get("identity") or {}).get(key)
                    if str(update_payload.get(key) or "") != str(expected or ""):
                        raise DeploymentError("update manifest identity does not match candidate")
        return {"root": root, "manifest": manifest, "components": components}
    finally:
        if temporary is not None:
            temporary.cleanup()


def attach_platform_artifacts(candidate_root: Path, candidate: dict[str, Any], attachment_path: Path) -> dict[str, Any]:
    """Stage, validate and atomically promote one identity-bound attachment."""

    root, manifest, temporary = _read_attachment(attachment_path)
    try:
        if int(manifest.get("schema_version") or 0) != 1:
            raise DeploymentError("unsupported platform attachment schema")
        _identity_matches(manifest, candidate)
        raw_components = manifest.get("components")
        if not isinstance(raw_components, list):
            raise DeploymentError("attachment has no component inventory")
        # Validate while the source bundle remains intact.  This duplicate is
        # intentional: the transfer boundary is not trusted merely because a
        # caller inspected it first.
        info = inspect_attachment(attachment_path, candidate)
        components: list[AttachmentComponent] = info["components"]
        working = dict(candidate.get("working_release_set") or {})
        declared = {str(item.get("kind")): item for item in working.get("components", []) if isinstance(item, dict)}
        staging = candidate_root / "attachment-staging" / f"{utc_text().replace(':', '').replace('+', '')}"
        staging.mkdir(parents=True, exist_ok=False)
        try:
            support_targets: dict[tuple[str, str], tuple[Path, Path]] = {}
            for component in components:
                current = declared.get(component.kind)
                if current is None:
                    raise DeploymentError("attachment component is not expected by the release set")
                if current.get("disposition") == "BUILT":
                    if current.get("sha256") != component.sha256:
                        raise DeploymentError("attachment conflicts with an immutable existing component")
                    continue
                if current.get("disposition") != "PENDING":
                    raise DeploymentError("attachment cannot replace a non-pending component")
                source = root / _safe_relative(component.artifact)
                # Keep staging paths short enough for Windows runners; target
                # locators are validated separately and are only used at the
                # final promotion boundary.
                staged = staging / f"{component.kind}.part"
                shutil.copy2(source, staged)
                if staged.stat().st_size != component.size_bytes or sha256_file(staged) != component.sha256:
                    raise DeploymentError("attachment changed while staging")
                # Retain the supporting evidence with the package, rather
                # than depending on a transient CI download during Phase 1B-3
                # revalidation.  These paths never become absolute release
                # identity and are revalidated after promotion.
                for label, locator in (("metadata", component.metadata), ("package_manifest", component.package_manifest), ("smoke_receipt", component.smoke_receipt)):
                    if not locator:
                        continue
                    source_support = root / _safe_relative(locator)
                    if not source_support.is_file():
                        raise DeploymentError("attachment supporting evidence is missing")
                    staged_support = staging / f"{component.kind}-{label}.part"
                    shutil.copy2(source_support, staged_support)
                    destination = candidate_root / "platform" / "windows" / component.kind / source_support.name
                    support_targets[(component.kind, label)] = (staged_support, destination)
            # Promote only after *all* bytes validate. os.replace is atomic per
            # file; the receipt is written last and is the visibility gate.
            for component in components:
                current = declared[component.kind]
                if current.get("disposition") == "BUILT":
                    continue
                staged = staging / f"{component.kind}.part"
                target = candidate_root / _safe_relative(component.target_locator)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and sha256_file(target) != component.sha256:
                    raise DeploymentError("immutable candidate locator already contains conflicting bytes")
                if not target.exists():
                    os_replace(staged, target)
                retained_metadata: dict[str, str] = {"attachment_manifest_sha256": sha256_file(root / "attachment-manifest.json"), "attachment_artifact": component.artifact}
                for label in ("metadata", "package_manifest", "smoke_receipt"):
                    retained = support_targets.get((component.kind, label))
                    if retained is None:
                        continue
                    staged_support, destination = retained
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if destination.exists() and sha256_file(destination) != sha256_file(staged_support):
                        raise DeploymentError("immutable candidate support evidence conflicts with attachment")
                    if not destination.exists():
                        os_replace(staged_support, destination)
                    retained_metadata[f"{label}_locator"] = candidate_locator(candidate_root, destination)
                    retained_metadata[f"{label}_sha256"] = sha256_file(destination)
                current.update({
                    "disposition": "BUILT", "artifact_filename": target.name,
                    "artifact_locator": candidate_locator(candidate_root, target), "size_bytes": component.size_bytes,
                    "sha256": component.sha256, "media_type": "application/json" if component.kind.endswith("manifest") else "application/zip",
                    "validation_status": "PASS", "smoke_test_status": "PASS" if component.smoke_receipt else "NOT_APPLICABLE",
                    "metadata": retained_metadata,
                })
            working["components"] = list(declared.values())
            candidate["working_release_set"] = working
            candidate["state"] = "PLATFORM_ARTIFACTS_PENDING"
            candidate["publication_eligible"] = False
            candidate["blocking_reasons"] = ["Final release-set manifest and signature are pending Phase 1B-3 sealing."]
            candidate["next_safe_action"] = "Complete final artifact verification and Phase 1B-3 release-set sealing."
            return {"candidate": candidate, "attachment": manifest, "components": [item.kind for item in components]}
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    finally:
        if temporary is not None:
            temporary.cleanup()


def os_replace(source: Path, target: Path) -> None:
    """Small seam for testing transfer promotion without a generic move."""

    source.replace(target)


def write_attachment_receipt(candidate_root: Path, *, candidate_id: str, manifest: dict[str, Any], components: list[str]) -> Path:
    path = candidate_root / "receipts" / f"windows-attachment-{utc_text().replace(':', '')}.json"
    write_json_atomic(path, {
        "schema_version": 1, "candidate_id": candidate_id, "status": "PASS", "components": sorted(components),
        "attachment_manifest_sha256": sha256_file(candidate_root / "attachment-staging" / "does-not-exist") if False else str(manifest.get("manifest_sha256") or ""),
        "recorded_at_utc": utc_text(),
    })
    return path
