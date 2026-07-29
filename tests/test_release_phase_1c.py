from __future__ import annotations

import base64
import json
import subprocess
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from deployment.common import DeploymentError, sha256_file, write_json_atomic
from deployment.convergence.cli import parse_args
from deployment.convergence.models import DeploymentMode, PublicationState
from deployment.convergence.phase1c import Phase1CPublicationState, _required_built, publication_assets
from deployment.convergence.release_set import ComponentKind, ComponentValidation, ReleaseSetComponent, SignedReleaseSet
from deployment.convergence.services import ReleaseDeploymentService
from release_tools.release_identity import ArtifactDisposition, ProductReleaseIdentity


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def _zip(path: Path, name: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, "phase-1c disposable artifact")


def _sealed_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ReleaseDeploymentService, str, Path, Path]:
    remote, source, candidate = tmp_path / "remote.git", tmp_path / "source", tmp_path / "candidate-source"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    _git(tmp_path, "init", "--initial-branch=main", str(source))
    for repo in (source,):
        _git(repo, "config", "user.email", "phase1c@example.invalid")
        _git(repo, "config", "user.name", "Phase 1C disposable")
    (source / "README.md").write_text("base\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "base")
    base = _git(source, "rev-parse", "HEAD")
    _git(source, "remote", "add", "origin", str(remote))
    _git(source, "push", "-u", "origin", "main")
    _git(tmp_path, "clone", str(source), str(candidate))
    _git(candidate, "config", "user.email", "phase1c@example.invalid")
    _git(candidate, "config", "user.name", "Phase 1C disposable")
    (candidate / "README.md").write_text("candidate\n", encoding="utf-8")
    _git(candidate, "add", "README.md")
    _git(candidate, "commit", "-m", "candidate")
    commit, tree = _git(candidate, "rev-parse", "HEAD"), _git(candidate, "rev-parse", "HEAD^{tree}")

    service = ReleaseDeploymentService(source)
    candidate_id = f"candidate-0.24.0-{commit[:12]}"
    root = service.store.root / "candidates" / candidate_id
    root.mkdir(parents=True)
    files: dict[str, Path] = {}
    for kind, suffix in (("server", ".tar.gz"), ("web", ".zip"), ("desktop", ".zip"), ("desktop_update_manifest", ".json"), ("launcher", ".zip"), ("launcher_update_manifest", ".json"), ("release_notes", ".md")):
        folder = root / "core" / kind if kind in {"server", "web", "release_notes"} else root / "platform" / "windows" / kind
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{kind}{suffix}"
        path = folder / name
        if suffix == ".zip":
            _zip(path, f"{kind}/payload.txt")
        elif suffix == ".json":
            write_json_atomic(path, {"product_version": "0.24.0", "candidate_id": candidate_id, "source_commit": commit, "source_tree": tree})
        else:
            path.write_text(f"{kind} 0.24.0\n", encoding="utf-8")
        files[kind] = path
    bundle = root / "source" / "candidate.bundle"
    bundle.parent.mkdir(parents=True)
    _git(candidate, "bundle", "create", str(bundle), "HEAD", f"^{base}")
    files["source_bundle"] = bundle

    identity = ProductReleaseIdentity("0.24.0", "eoat-atlas-0.24.0", "build-phase1c", commit, tree, "main", "candidate", "2026-07-27T00:00:00Z", candidate_id)
    components: list[ReleaseSetComponent] = []
    working: list[dict[str, object]] = []
    for kind in ComponentKind:
        if kind in {ComponentKind.BOOTSTRAP, ComponentKind.BOOTSTRAP_UPDATE_MANIFEST}:
            component = ReleaseSetComponent(kind, ArtifactDisposition.NOT_APPLICABLE, identity.product_version, identity.release_id, identity.build_id, commit, tree, candidate_id, validation_status=ComponentValidation.NOT_APPLICABLE, not_applicable_justification="Bootstrap implementation is owned by Unified Release Train Phase 2.")
            components.append(component)
            working.append(component.to_dict())
            continue
        if kind in {ComponentKind.RELEASE_SET_MANIFEST, ComponentKind.RELEASE_SET_SIGNATURE}:
            component = ReleaseSetComponent(kind, ArtifactDisposition.BUILT, identity.product_version, identity.release_id, identity.build_id, commit, tree, candidate_id, validation_status=ComponentValidation.PASS)
            components.append(component)
            working.append(component.to_dict())
            continue
        path = files[kind.value]
        locator = path.relative_to(root).as_posix()
        component = ReleaseSetComponent(kind, ArtifactDisposition.BUILT, identity.product_version, identity.release_id, identity.build_id, commit, tree, candidate_id, artifact_filename=path.name, artifact_locator=locator, size_bytes=path.stat().st_size, sha256=sha256_file(path), media_type="application/zip" if path.suffix == ".zip" else "application/json", validation_status=ComponentValidation.PASS, smoke_test_status=ComponentValidation.PASS if kind in {ComponentKind.DESKTOP, ComponentKind.LAUNCHER} else ComponentValidation.NOT_APPLICABLE)
        components.append(component)
        working.append(component.to_dict())
    release_set = SignedReleaseSet(identity, tuple(components), "1.4.0", "schema-1", "NO_MIGRATION_REQUIRED", "0.0.0", "0.0.0", "0.0.0")
    private = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public = Ed25519PrivateKey.from_private_bytes(private).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    signature = release_set.sign(key_id="phase1c-test", private_key=private)
    sealing = root / "sealing"
    sealing.mkdir()
    manifest = sealing / "release-set-manifest.json"
    detached = sealing / "release-set-signature.json"
    write_json_atomic(manifest, {"envelope_schema_version": 1, "canonical_payload": release_set.unsigned_dict(), "canonical_payload_sha256": release_set.digest()})
    write_json_atomic(detached, {"schema_version": 1, "algorithm": signature.algorithm, "key_id": signature.key_id, "canonical_payload_sha256": release_set.digest(), "signature": signature.signature})
    for item in working:
        if item["kind"] == "release_set_manifest":
            item.update({"artifact_filename": manifest.name, "artifact_locator": "sealing/release-set-manifest.json", "size_bytes": manifest.stat().st_size, "sha256": sha256_file(manifest), "media_type": "application/json"})
        if item["kind"] == "release_set_signature":
            item.update({"artifact_filename": detached.name, "artifact_locator": "sealing/release-set-signature.json", "size_bytes": detached.stat().st_size, "sha256": sha256_file(detached), "media_type": "application/json"})
    service.store.write("candidate", candidate_id, {"schema_version": 2, "candidate_id": candidate_id, "state": "RELEASE_SET_VALIDATED", "publication_eligible": True, "version": "0.24.0", "candidate_commit": commit, "candidate_tree": tree, "base_commit": base, "release_set": release_set.unsigned_dict(), "release_set_digest": release_set.digest(), "release_set_manifest_path": "sealing/release-set-manifest.json", "release_set_manifest_sha256": sha256_file(manifest), "release_set_signature": {"path": "sealing/release-set-signature.json", "sha256": sha256_file(detached), "key_id": "phase1c-test", "algorithm": "Ed25519"}, "working_release_set": {**release_set.unsigned_dict(), "components": working}})
    monkeypatch.setenv("EOAT_RELEASE_TRUSTED_PUBLIC_KEYS_JSON", json.dumps({"phase1c-test": base64.b64encode(public).decode("ascii")}))
    return service, candidate_id, remote, tmp_path / "registry"


def test_disposable_publication_inventory_and_no_migration_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, candidate_id, remote, registry = _sealed_candidate(tmp_path, monkeypatch)
    assert service.publication_readiness(candidate_id).status.value == "PASS"
    result = service.publish_disposable(candidate_id, f"PUBLISH {candidate_id}", remote=remote, registry=registry)
    assert result.status.value == "PASS"
    publication = result.data["publication"]
    assert publication["state"] == Phase1CPublicationState.PUBLICATION_COMPLETE.value
    inventory = service.inventory_disposable(registry).data["releases"]
    assert inventory[0]["classification"] == "COMPLETE_TRUSTED"
    service.store.write("inspection", "inspection-phase1c", {"state": "TARGET_INSPECTED", "target_name": "disposable.invalid", "facts": {"schema_revision": "schema-1", "helper": {"operations": []}, "transactions": []}, "blocking_failures": [], "warnings": []})
    plan = service.create_disposable_plan(publication["publication_id"], "inspection-phase1c").data["plan"]
    assert plan["mode"] == DeploymentMode.NO_MIGRATION_REQUIRED.value
    assert plan["expected_mutations"] == []


def test_disposable_publication_resumes_and_conflicting_asset_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, candidate_id, remote, registry = _sealed_candidate(tmp_path, monkeypatch)
    failed = service.publish_disposable(candidate_id, f"PUBLISH {candidate_id}", remote=remote, registry=registry, fault_after=Phase1CPublicationState.RELEASE_RECORD_CREATED)
    assert failed.status.value == "BLOCKED"
    resumed = service.publish_disposable(candidate_id, f"PUBLISH {candidate_id}", remote=remote, registry=registry)
    assert resumed.status.value == "PASS"
    asset = next((registry / resumed.data["publication"]["tag"] / "assets").iterdir())
    asset.write_bytes(b"conflict")
    retried = service.publish_disposable(candidate_id, f"PUBLISH {candidate_id}", remote=remote, registry=registry)
    assert retried.status.value == "BLOCKED"


def test_publication_readiness_rejects_unsealed_mutated_and_revoked_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, candidate_id, _remote, _registry = _sealed_candidate(tmp_path, monkeypatch)
    receipt = service.store.read("candidate", candidate_id)
    receipt["state"] = "PLATFORM_ARTIFACTS_PENDING"
    service.store.write("candidate", candidate_id, receipt)
    assert service.publication_readiness(candidate_id).status.value == "BLOCKED"
    receipt["state"] = "RELEASE_SET_VALIDATED"
    service.store.write("candidate", candidate_id, receipt)
    manifest = service.store.root / "candidates" / candidate_id / "sealing" / "release-set-manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    assert service.publication_readiness(candidate_id).status.value == "BLOCKED"
    monkeypatch.setenv("EOAT_RELEASE_REVOKED_KEY_IDS", "phase1c-test")
    assert service.publication_readiness(candidate_id).status.value == "BLOCKED"


def test_completed_publication_receipt_is_immutable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, candidate_id, remote, registry = _sealed_candidate(tmp_path, monkeypatch)
    publication = service.publish_disposable(candidate_id, f"PUBLISH {candidate_id}", remote=remote, registry=registry).data["publication"]
    with pytest.raises(DeploymentError, match="immutable"):
        service.store.write("publication", publication["publication_id"], {**publication, "failure": "changed"})


class _SchemaTwoPublisher:
    """No-network publisher seam that still requires every durable checkpoint."""

    def __init__(self) -> None:
        self.steps: list[str] = []

    def promote(self, _candidate: dict[str, object]) -> None: self.steps.append("promote")
    def ensure_tag(self, _candidate: dict[str, object]) -> None: self.steps.append("tag")
    def push_branch(self, _candidate: dict[str, object]) -> None: self.steps.append("branch")
    def push_tag(self, _candidate: dict[str, object]) -> None: self.steps.append("push-tag")
    def ensure_release(self, _candidate: dict[str, object]) -> None: self.steps.append("release")
    def upload_assets(self, _candidate: dict[str, object]) -> None: self.steps.append("assets")
    def attach_receipt(self, _candidate: dict[str, object], receipt: Path) -> None:
        assert receipt.is_file()
        self.steps.append("receipt")
    def verify_step(self, _candidate: dict[str, object], _step: PublicationState, _receipt: dict[str, object]) -> bool: return True


def test_schema2_publisher_records_complete_asset_inventory_and_public_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, candidate_id, _remote, _registry = _sealed_candidate(tmp_path, monkeypatch)
    candidate = service.store.read("candidate", candidate_id)
    bundle = service.store.root / "candidates" / candidate_id / "source" / "candidate.bundle"
    candidate["bundle_path"] = str(bundle)
    candidate["bundle_sha256"] = sha256_file(bundle)
    server_manifest = service.store.root / "candidates" / candidate_id / "core" / "server" / "external-manifest.json"
    write_json_atomic(server_manifest, {"schema_version": 1, "candidate_id": candidate_id})
    for component in candidate["working_release_set"]["components"]:
        if component["kind"] == "server":
            component["metadata"] = {"external_manifest_locator": server_manifest.relative_to(service.store.root / "candidates" / candidate_id).as_posix()}
    service.store.write("candidate", candidate_id, candidate)
    publisher = _SchemaTwoPublisher()
    result = service.publish_start(candidate_id, "0.24.0", publisher=publisher)
    publication = result.data["publication"]
    assert result.status.value == "PASS"
    assert publication["schema_version"] == 2
    assert publication["state"] == PublicationState.PUBLICATION_COMPLETE.value
    assert PublicationState.COMPONENT_ASSETS_VERIFIED.value in publication["completed_steps"]
    assert publication["asset_inventory"]
    receipt = service.store.root / "candidates" / candidate_id / "publication" / publication["public_receipt_filename"]
    assert receipt.is_file()
    assert "receipt_path" not in receipt.read_text(encoding="utf-8")
    assert publisher.steps == ["promote", "tag", "branch", "push-tag", "release", "assets", "receipt"]


def test_phase1c_cli_requires_disposable_parameters_and_typed_confirmation() -> None:
    args = parse_args(["publish", "start-disposable", "candidate-unit", "--remote", "remote.git", "--registry", "registry", "--confirm", "PUBLISH candidate-unit"])
    assert args.publish_command == "start-disposable"
    assert args.confirm == "PUBLISH candidate-unit"
    args = parse_args(["publish", "begin-production", "candidate-unit", "--confirm", "PUBLISH EOAT ATLAS 0.24.1 TO Kgray44/EOAT_Tool"])
    assert args.publish_command == "begin-production"
    assert args.confirm.endswith("Kgray44/EOAT_Tool")
    args = parse_args(["plan", "create-disposable", "--publication", "publication-unit", "--inspection", "inspection-unit"])
    assert args.plan_command == "create-disposable"


def test_final_current_component_profile_requires_bootstrap_publication_assets() -> None:
    legacy = _required_built(final_current_components=False)
    final = _required_built(final_current_components=True)
    assert ComponentKind.BOOTSTRAP.value not in legacy
    assert ComponentKind.BOOTSTRAP_UPDATE_MANIFEST.value not in legacy
    assert ComponentKind.BOOTSTRAP.value in final
    assert ComponentKind.BOOTSTRAP_UPDATE_MANIFEST.value in final


def test_publication_inventory_rejects_missing_governed_supporting_bytes(tmp_path: Path) -> None:
    package = tmp_path / "platform" / "windows" / "bootstrap" / "bootstrap.zip"
    package.parent.mkdir(parents=True)
    _zip(package, "EOAT Atlas Bootstrap.exe")
    receipt = {
        "release_set_profile": "FINAL_CURRENT_COMPONENTS",
        "working_release_set": {"components": [
            {
                "kind": "bootstrap", "disposition": "BUILT", "artifact_locator": "platform/windows/bootstrap/bootstrap.zip",
                "size_bytes": package.stat().st_size, "sha256": sha256_file(package), "media_type": "application/zip",
                "metadata": {"installer_package_locator": "platform/windows/bootstrap/missing-installer.zip"},
            },
        ]},
    }
    with pytest.raises(DeploymentError, match="supporting publication asset"):
        publication_assets(tmp_path, receipt)
