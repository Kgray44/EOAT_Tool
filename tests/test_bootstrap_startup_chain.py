from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bootstrap.core import BootstrapError, BootstrapService, LauncherUpdateManifest, sign_launcher_manifest


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _package(root: Path, version: str, *, unsafe: bool = False, variant: str = "") -> tuple[Path, dict[str, str]]:
    identity = {
        "component_version": version,
        "product_version": "0.24.0",
        "release_id": "eoat-atlas-0.24.0",
        "build_id": "build-20260727",
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
    }
    files = {
        "EOAT Atlas Launcher.exe": b"launcher-binary-" + version.encode() + variant.encode(),
        "launcher_release_metadata.json": json.dumps(identity, sort_keys=True).encode(),
        "launcher_smoke_receipt.json": json.dumps(
            {"component_kind": "launcher", "component_version": version, "status": "PASS"}, sort_keys=True
        ).encode(),
    }
    files["launcher_package_manifest.json"] = json.dumps(
        {"files": [{"path": key, "size": len(value), "sha256": _sha(value)} for key, value in files.items()]},
        sort_keys=True,
    ).encode()
    package = root / f"launcher-{version}.zip"
    with zipfile.ZipFile(package, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)
        if unsafe:
            archive.writestr("../unsafe.txt", b"unsafe")
    return package, {
        "metadata": _sha(files["launcher_release_metadata.json"]),
        "package_manifest": _sha(files["launcher_package_manifest.json"]),
        "smoke": _sha(files["launcher_smoke_receipt.json"]),
    }


def _envelope(
    root: Path,
    version: str,
    private: bytes,
    *,
    minimum: str = "0.1.0",
    revoked: tuple[str, ...] = (),
    variant: str = "",
) -> dict[str, object]:
    package, hashes = _package(root, version, variant=variant)
    manifest = LauncherUpdateManifest(
        "0.24.0",
        version,
        minimum,
        package.name,
        package.stat().st_size,
        _sha(package.read_bytes()),
        hashes["metadata"],
        hashes["package_manifest"],
        hashes["smoke"],
        "a" * 40,
        "b" * 40,
        "eoat-atlas-0.24.0",
        "build-20260727",
        revoked_launcher_versions=revoked,
    )
    return sign_launcher_manifest(manifest, key_id="test-key", private_key=private)


def _service(root: Path, key: bytes) -> BootstrapService:
    public = Ed25519PrivateKey.from_private_bytes(key).public_key().public_bytes_raw()

    def runner(executable: Path, receipt: Path, _timeout: float) -> dict[str, str]:
        metadata = json.loads((executable.parent / "launcher_release_metadata.json").read_text(encoding="utf-8"))
        result = {"status": "PASS", "component_version": metadata["component_version"]}
        receipt.write_text(json.dumps(result), encoding="utf-8")
        return result

    return BootstrapService(
        root, trusted_public_keys={"test-key": base64.b64encode(public).decode()}, launcher_runner=runner
    )


def test_signed_launcher_update_installs_immutably_and_writes_atomic_pointers(tmp_path: Path) -> None:
    private = Ed25519PrivateKey.generate().private_bytes_raw()
    service = _service(tmp_path / "local", private)
    result = service.update(_envelope(tmp_path, "0.1.0", private), transport=str(tmp_path), launch=False)
    assert result.state == "ACTIVE_CONFIRMED"
    status = service.status()
    assert status["active_launcher"]["version"] == "0.1.0"
    assert status["last_known_good_launcher"]["version"] == "0.1.0"
    assert (tmp_path / "local" / "launcher_versions" / "0.1.0" / "EOAT Atlas Launcher.exe").is_file()


def test_downgrade_and_same_version_different_bytes_are_blocked(tmp_path: Path) -> None:
    private = Ed25519PrivateKey.generate().private_bytes_raw()
    service = _service(tmp_path / "local", private)
    service.update(_envelope(tmp_path, "0.2.0", private), transport=str(tmp_path), launch=False)
    with pytest.raises(BootstrapError, match="downgrade"):
        service.update(_envelope(tmp_path, "0.1.0", private), transport=str(tmp_path), launch=False)
    with pytest.raises(BootstrapError, match="conflicting immutable"):
        service.update(
            _envelope(tmp_path, "0.2.0", private, variant="different"), transport=str(tmp_path), launch=False
        )


def test_failed_startup_health_rolls_back_to_previous_launcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    private = Ed25519PrivateKey.generate().private_bytes_raw()
    service = _service(tmp_path / "local", private)
    service.update(_envelope(tmp_path, "0.1.0", private), transport=str(tmp_path), launch=False)
    monkeypatch.setattr(service, "_start_health", lambda *_args: {"status": "FAILED"})
    result = service.update(_envelope(tmp_path, "0.2.0", private), transport=str(tmp_path), launch=True)
    assert result.state == "ROLLED_BACK"
    assert service.status()["active_launcher"]["version"] == "0.1.0"


def test_revoked_or_below_minimum_cached_policy_blocks_offline_fallback(tmp_path: Path) -> None:
    private = Ed25519PrivateKey.generate().private_bytes_raw()
    service = _service(tmp_path / "local", private)
    service.update(_envelope(tmp_path, "0.1.0", private), transport=str(tmp_path), launch=False)
    envelope = _envelope(tmp_path, "0.2.0", private, minimum="0.2.0", revoked=("0.1.0",))
    (tmp_path / "local" / "bootstrap" / "cached_launcher_manifest.json").write_text(
        json.dumps(envelope), encoding="utf-8"
    )
    assert service.offline_launch().state == "BLOCKED_REQUIRED_UPDATE"


def test_invalid_signature_and_unsafe_package_are_rejected_before_activation(tmp_path: Path) -> None:
    private = Ed25519PrivateKey.generate().private_bytes_raw()
    service = _service(tmp_path / "local", private)
    envelope = _envelope(tmp_path, "0.1.0", private)
    envelope["manifest"]["package_sha256"] = "0" * 64
    with pytest.raises(BootstrapError):
        service.update(envelope, transport=str(tmp_path), launch=False)
    assert not service.status()["active_launcher"]
