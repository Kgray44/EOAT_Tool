from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from deployment.common import DeploymentError
from deployment.convergence.artifacts import build_web_package, validate_web_package
from deployment.convergence.platform_artifacts import _expected_platform_kinds
from deployment.convergence.services import ReleaseDeploymentService


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _working(candidate_id: str) -> dict[str, object]:
    identity = {"product_version": "0.24.0", "release_id": "release-24", "build_id": "build-24", "source_commit": "a" * 40, "source_tree": "b" * 40, "candidate_id": candidate_id}
    kinds = ("server", "web", "desktop", "desktop_update_manifest", "launcher", "launcher_update_manifest", "bootstrap", "bootstrap_update_manifest", "release_set_manifest", "release_set_signature", "source_bundle", "release_notes")
    components = []
    for kind in kinds:
        disposition = "NOT_APPLICABLE" if kind in {"bootstrap", "bootstrap_update_manifest"} else ("BUILT" if kind in {"server", "web", "source_bundle", "release_notes"} else "PENDING")
        components.append({"kind": kind, "disposition": disposition, "validation_status": "NOT_APPLICABLE" if disposition == "NOT_APPLICABLE" else "NOT_RUN", "not_applicable_justification": "Bootstrap implementation is owned by Unified Release Train Phase 2." if disposition == "NOT_APPLICABLE" else ""})
    return {"schema_version": 2, "identity": identity, "components": components}


def _candidate(service: ReleaseDeploymentService, candidate_id: str) -> Path:
    root = service.store.root / "candidates" / candidate_id
    root.mkdir(parents=True)
    receipt = {"schema_version": 2, "candidate_id": candidate_id, "version": "0.24.0", "state": "PLATFORM_ARTIFACTS_PENDING", "candidate_commit": "a" * 40, "candidate_tree": "b" * 40, "base_commit": "c" * 40, "bundle_path": str(root / "source" / "candidate.bundle"), "bundle_sha256": "d" * 64, "working_release_set": _working(candidate_id), "publication_eligible": False}
    service.store.write("candidate", candidate_id, receipt)
    return root


def _attachment(root: Path, candidate_id: str, *, mismatch: bool = False) -> Path:
    attachment = root / "input"
    identity = {"candidate_id": candidate_id, "product_version": "0.24.0", "release_id": "release-24", "build_id": "build-24", "source_commit": "a" * 40, "source_tree": "b" * 40}
    components = []
    for kind, folder in (("desktop", "desktop"), ("launcher", "launcher")):
        folder_path = attachment / folder
        folder_path.mkdir(parents=True, exist_ok=True)
        package = folder_path / f"{kind}.zip"
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr(f"EOAT Atlas {kind}.exe", b"real package fixture")
        metadata = folder_path / "metadata.json"
        metadata.write_text(json.dumps(identity), encoding="utf-8")
        package_manifest = folder_path / "package-manifest.json"
        package_manifest.write_text(json.dumps({"files": [{"path": "EOAT", "sha256": "x"}]}), encoding="utf-8")
        smoke = folder_path / "smoke.json"
        smoke.write_text(json.dumps({"schema_version": 1, "component_kind": kind, **identity, "status": "PASS", "started_at_utc": "2026-01-01T00:00:00Z", "completed_at_utc": "2026-01-01T00:00:01Z", "package_sha256": _hash(package)}), encoding="utf-8")
        components.append({"kind": kind, "artifact": f"{folder}/{package.name}", "sha256": _hash(package), "size_bytes": package.stat().st_size, "metadata": f"{folder}/metadata.json", "package_manifest": f"{folder}/package-manifest.json", "smoke_receipt": f"{folder}/smoke.json", "target_locator": f"platform/windows/{kind}/{package.name}"})
    for kind, package_kind, folder in (("desktop_update_manifest", "desktop", "desktop"), ("launcher_update_manifest", "launcher", "launcher")):
        package = next(item for item in components if item["kind"] == package_kind)
        update = attachment / folder / "update-manifest.json"
        update.write_text(json.dumps({**identity, "sha256": package["sha256"], "package_locator": package["artifact"]}), encoding="utf-8")
        components.append({"kind": kind, "artifact": f"{folder}/update-manifest.json", "sha256": _hash(update), "size_bytes": update.stat().st_size, "target_locator": f"platform/windows/{kind}/update-manifest.json"})
    manifest = {"schema_version": 1, **identity, "platform": "windows", "components": components}
    if mismatch:
        manifest["source_tree"] = "e" * 40
    (attachment / "attachment-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return attachment


def test_web_package_is_real_and_rejects_mutated_file(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<main>EOAT</main>", encoding="utf-8")
    manifest = {"index.html": _hash(site / "index.html")}
    (site / "web-static.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    package = build_web_package(site, tmp_path / "web.zip")
    assert package.size_bytes > 0
    validate_web_package(package.path)
    (site / "index.html").write_text("changed", encoding="utf-8")
    with pytest.raises(DeploymentError):
        build_web_package(site, tmp_path / "changed.zip")


def test_attachment_is_identity_bound_idempotent_and_leaves_sealing_pending(tmp_path: Path) -> None:
    service = ReleaseDeploymentService(tmp_path)
    candidate_id = "candidate-0.24.0-aaaaaaaa"
    root = _candidate(service, candidate_id)
    attachment = _attachment(tmp_path, candidate_id)
    assert service.attach_platform_artifacts(candidate_id, attachment).status.value == "PASS"
    assert service.attach_platform_artifacts(candidate_id, attachment).status.value == "PASS"
    receipt = service.store.candidate_representation(candidate_id)
    assert receipt["missing_components"] == ["release_set_manifest", "release_set_signature"]
    assert receipt["publication_eligible"] is False
    assert (root / "platform" / "windows" / "desktop" / "desktop.zip").is_file()


def test_attachment_rejects_same_version_different_source_tree(tmp_path: Path) -> None:
    service = ReleaseDeploymentService(tmp_path)
    candidate_id = "candidate-0.24.0-bbbbbbbb"
    _candidate(service, candidate_id)
    with pytest.raises(DeploymentError):
        service.attach_platform_artifacts(candidate_id, _attachment(tmp_path, candidate_id, mismatch=True))


def test_final_component_profile_requires_bootstrap_attachment() -> None:
    candidate = {
        "working_release_set": {
            "components": [
                {"kind": kind, "disposition": "PENDING"}
                for kind in (
                    "desktop", "desktop_update_manifest", "launcher", "launcher_update_manifest",
                    "bootstrap", "bootstrap_update_manifest",
                )
            ]
        }
    }
    assert _expected_platform_kinds(candidate) == {
        "desktop", "desktop_update_manifest", "launcher", "launcher_update_manifest",
        "bootstrap", "bootstrap_update_manifest",
    }
