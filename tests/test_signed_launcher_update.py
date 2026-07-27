from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from release_tools import launcher
from release_tools.release_identity import (
    ArtifactDisposition,
    ProductReleaseIdentity,
    ReleaseArtifact,
    ReleaseSetManifest,
    public_key_bytes,
    sign_manifest,
    signed_envelope,
)


def _identity() -> ProductReleaseIdentity:
    return ProductReleaseIdentity(
        "0.24.0",
        "eoat-atlas-0.24.0",
        "eoat-atlas-0.24.0-abcdef0-20260727T000000Z",
        "abcdef0123456789abcdef0123456789abcdef01",
        "0123456789abcdef0123456789abcdef01234567",
        "codex/unified-release-train",
        "stable",
        "2026-07-27T00:00:00Z",
        "candidate-0.24.0-abcdef012345",
    )


def _package(path: Path, identity: ProductReleaseIdentity, *, unsafe: bool = False) -> None:
    files = {
        "EOAT Atlas.exe": b"not a real executable",
        "release_metadata.json": json.dumps(
            {"app_version": identity.product_version, "release_id": identity.release_id, "build_id": identity.build_id}
        ).encode(),
    }
    manifest = {
        "files": [
            {"path": name, "sha256": hashlib.sha256(value).hexdigest(), "size": len(value)} for name, value in files.items()
        ]
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)
        archive.writestr("package_manifest.json", json.dumps(manifest))
        if unsafe:
            archive.writestr("../escape.txt", "no")


def _envelope(package: Path, identity: ProductReleaseIdentity, private: bytes) -> dict[str, object]:
    desktop = ReleaseArtifact("desktop", ArtifactDisposition.BUILT, package.name, launcher.sha256_file(package), package.stat().st_size)
    artifacts = tuple(
        desktop if component == "desktop" else ReleaseArtifact(component, ArtifactDisposition.NOT_APPLICABLE)
        for component in ReleaseSetManifest.REQUIRED_COMPONENTS
    )
    manifest = ReleaseSetManifest(identity, artifacts)
    return signed_envelope(manifest, sign_manifest(manifest, key_id="test-key", private_key=private))


def test_signed_update_smokes_before_atomic_activation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    identity = _identity()
    package = tmp_path / "desktop.zip"
    _package(package, identity)
    private = Ed25519PrivateKey.generate().private_bytes_raw()
    smokes: list[Path] = []
    monkeypatch.setattr(launcher, "_smoke_test_candidate", lambda executable, _identity, timeout: smokes.append(executable))

    target = launcher.install_signed_release_set(
        _envelope(package, identity, private),
        transport_root=str(tmp_path),
        root=tmp_path / "local",
        trusted_public_keys={"test-key": base64.b64encode(public_key_bytes(private)).decode("ascii")},
    )

    assert target.name == "0.24.0"
    assert smokes == [target / "EOAT Atlas.exe"]
    assert json.loads((tmp_path / "local" / "current.json").read_text())["release_id"] == identity.release_id


def test_signed_update_rejects_unsafe_zip_before_activation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    identity = _identity()
    package = tmp_path / "desktop.zip"
    _package(package, identity, unsafe=True)
    private = Ed25519PrivateKey.generate().private_bytes_raw()
    monkeypatch.setattr(launcher, "_smoke_test_candidate", lambda *_args, **_kwargs: pytest.fail("unsafe archive was smoked"))

    with pytest.raises(launcher.LauncherError, match="Unsafe archive"):
        launcher.install_signed_release_set(
            _envelope(package, identity, private),
            transport_root=str(tmp_path),
            root=tmp_path / "local",
            trusted_public_keys={"test-key": base64.b64encode(public_key_bytes(private)).decode("ascii")},
        )
    assert not (tmp_path / "local" / "current.json").exists()
