"""Signed, recoverable launcher self-update transactions.

This module deliberately owns only the bootstrap -> launcher boundary.  The
launcher remains responsible for desktop application update and launch.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from release_tools.versioning import Version

LAUNCHER_EXE = "EOAT Atlas Launcher.exe"
LAUNCHER_METADATA = "launcher_release_metadata.json"
LAUNCHER_PACKAGE_MANIFEST = "launcher_package_manifest.json"
LAUNCHER_SMOKE_RECEIPT = "launcher_smoke_receipt.json"
MANIFEST_SCHEMA_VERSION = 1
RECEIPT_SCHEMA_VERSION = 1


class BootstrapError(RuntimeError):
    """Raised for a recoverable, user-safe bootstrap failure."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        Path(temporary).replace(path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


@dataclass(frozen=True)
class LauncherUpdateManifest:
    product_version: str
    launcher_version: str
    minimum_launcher_version: str
    package_filename: str
    package_size: int
    package_sha256: str
    launcher_metadata_sha256: str
    package_manifest_sha256: str
    smoke_receipt_sha256: str
    source_commit: str
    source_tree: str
    release_id: str
    build_id: str
    release_channel: str = "test"
    mandatory: bool = False
    revoked_launcher_versions: tuple[str, ...] = ()
    schema_version: int = MANIFEST_SCHEMA_VERSION
    published_at: str = ""

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["revoked_launcher_versions"] = sorted(value["revoked_launcher_versions"])
        return value

    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self.payload())).hexdigest()

    @classmethod
    def from_payload(cls, value: dict[str, Any]) -> LauncherUpdateManifest:
        required = {
            "product_version",
            "launcher_version",
            "minimum_launcher_version",
            "package_filename",
            "package_size",
            "package_sha256",
            "launcher_metadata_sha256",
            "package_manifest_sha256",
            "smoke_receipt_sha256",
            "source_commit",
            "source_tree",
            "release_id",
            "build_id",
        }
        missing = sorted(key for key in required if not value.get(key) and value.get(key) != 0)
        if missing or int(value.get("schema_version", 0)) != MANIFEST_SCHEMA_VERSION:
            raise BootstrapError(
                f"launcher update manifest is malformed: missing {', '.join(missing) or 'supported schema'}"
            )
        return cls(
            product_version=str(value["product_version"]),
            launcher_version=str(value["launcher_version"]),
            minimum_launcher_version=str(value["minimum_launcher_version"]),
            package_filename=str(value["package_filename"]),
            package_size=int(value["package_size"]),
            package_sha256=str(value["package_sha256"]),
            launcher_metadata_sha256=str(value["launcher_metadata_sha256"]),
            package_manifest_sha256=str(value["package_manifest_sha256"]),
            smoke_receipt_sha256=str(value["smoke_receipt_sha256"]),
            source_commit=str(value["source_commit"]),
            source_tree=str(value["source_tree"]),
            release_id=str(value["release_id"]),
            build_id=str(value["build_id"]),
            release_channel=str(value.get("release_channel") or "test"),
            mandatory=bool(value.get("mandatory")),
            revoked_launcher_versions=tuple(
                str(item) for item in value.get("revoked_launcher_versions", []) if str(item)
            ),
            schema_version=int(value.get("schema_version", MANIFEST_SCHEMA_VERSION)),
            published_at=str(value.get("published_at") or ""),
        )


def sign_launcher_manifest(manifest: LauncherUpdateManifest, *, key_id: str, private_key: bytes) -> dict[str, Any]:
    signature = Ed25519PrivateKey.from_private_bytes(private_key).sign(canonical_bytes(manifest.payload()))
    return {
        "schema_version": 1,
        "manifest": manifest.payload(),
        "manifest_digest": manifest.digest(),
        "signature": {"algorithm": "Ed25519", "key_id": key_id, "value": base64.b64encode(signature).decode("ascii")},
    }


def verify_launcher_manifest(
    envelope: dict[str, Any], *, trusted_public_keys: dict[str, str], revoked_key_ids: set[str] | None = None
) -> LauncherUpdateManifest:
    if not isinstance(envelope, dict) or int(envelope.get("schema_version", 0)) != 1:
        raise BootstrapError("launcher update envelope has an unsupported schema")
    payload = envelope.get("manifest")
    signature = envelope.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, dict):
        raise BootstrapError("launcher update envelope is malformed")
    manifest = LauncherUpdateManifest.from_payload(payload)
    if envelope.get("manifest_digest") != manifest.digest():
        raise BootstrapError("launcher update manifest digest is invalid")
    key_id = str(signature.get("key_id") or "")
    if not key_id or key_id in (revoked_key_ids or set()) or key_id not in trusted_public_keys:
        raise BootstrapError("launcher update signing key is unknown or revoked")
    if signature.get("algorithm") != "Ed25519":
        raise BootstrapError("launcher update signature algorithm is not supported")
    try:
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(trusted_public_keys[key_id], validate=True))
        public.verify(
            base64.b64decode(str(signature.get("value") or ""), validate=True), canonical_bytes(manifest.payload())
        )
    except Exception as exc:  # cryptography has several intentionally private error types
        raise BootstrapError("launcher update signature verification failed") from exc
    return manifest


@dataclass(frozen=True)
class BootstrapResult:
    state: str
    active_version: str = ""
    target_version: str = ""
    next_safe_action: str = ""
    diagnostics: tuple[str, ...] = ()


class LauncherStore:
    """Immutable per-user launcher versions and atomic active/LKG pointers."""

    def __init__(self, root: Path):
        self.root = root
        self.versions = root / "launcher_versions"
        self.receipts = root / "launcher_update_receipts"
        self.logs = root / "launcher_logs"
        self.active_pointer = root / "active_launcher.json"
        self.lkg_pointer = root / "last_known_good_launcher.json"
        self.cached_policy = root / "bootstrap" / "cached_launcher_manifest.json"

    def pointer(self, path: Path) -> dict[str, Any]:
        value = _read_json(path)
        target = Path(str(value.get("path") or ""))
        if not value or not target.is_absolute() or target.parent != self.versions or not target.is_dir():
            return {}
        return value

    def valid_pointer(self, path: Path) -> dict[str, Any]:
        pointer = self.pointer(path)
        if not pointer:
            return {}
        try:
            self.validate_installed(Path(str(pointer["path"])), expected=pointer)
        except BootstrapError:
            return {}
        return pointer

    def validate_installed(self, directory: Path, *, expected: dict[str, Any] | None = None) -> dict[str, Any]:
        if directory.parent != self.versions or directory.is_symlink() or not directory.is_dir():
            raise BootstrapError("launcher version directory is unsafe")
        exe = directory / LAUNCHER_EXE
        metadata_path = directory / LAUNCHER_METADATA
        package_manifest = directory / LAUNCHER_PACKAGE_MANIFEST
        if not exe.is_file() or exe.is_symlink() or not metadata_path.is_file() or not package_manifest.is_file():
            raise BootstrapError("launcher version directory is incomplete")
        metadata = _read_json(metadata_path)
        required = ("component_version", "product_version", "release_id", "build_id", "source_commit", "source_tree")
        if any(not metadata.get(key) for key in required):
            raise BootstrapError("launcher metadata is incomplete")
        package = _read_json(package_manifest)
        files = package.get("files") if isinstance(package, dict) else None
        if not isinstance(files, list) or not files:
            raise BootstrapError("launcher package manifest is malformed")
        for item in files:
            relative = Path(str(item.get("path") or ""))
            target = directory / relative
            if (
                not relative.parts
                or relative.is_absolute()
                or ".." in relative.parts
                or not target.is_file()
                or target.is_symlink()
            ):
                raise BootstrapError("launcher package manifest has an unsafe path")
            if int(item.get("size", -1)) != target.stat().st_size or str(item.get("sha256") or "") != sha256_file(
                target
            ):
                raise BootstrapError("launcher package manifest detected a mutation")
        if expected:
            for pointer_key, metadata_key in (
                ("version", "component_version"),
                ("release_id", "release_id"),
                ("build_id", "build_id"),
                ("source_commit", "source_commit"),
                ("source_tree", "source_tree"),
            ):
                if expected.get(pointer_key) and expected[pointer_key] != metadata.get(metadata_key):
                    raise BootstrapError("launcher pointer contradicts immutable launcher metadata")
        return metadata

    def write_pointer(self, path: Path, metadata: dict[str, Any], directory: Path, *, manifest_digest: str) -> None:
        _atomic_json(
            path,
            {
                "version": metadata["component_version"],
                "release_id": metadata["release_id"],
                "build_id": metadata["build_id"],
                "source_commit": metadata["source_commit"],
                "source_tree": metadata["source_tree"],
                "path": str(directory),
                "manifest_digest": manifest_digest,
                "activated_at": _utc_now(),
            },
        )

    def receipt(self, transaction_id: str, value: dict[str, Any]) -> None:
        _atomic_json(self.receipts / f"{transaction_id}.json", value)

    def reconcile(self) -> None:
        for staging in self.versions.glob(".staging-*") if self.versions.exists() else []:
            if staging.is_dir():
                shutil.rmtree(staging, ignore_errors=True)


def _safe_extract(archive: Path, destination: Path) -> None:
    seen: set[str] = set()
    with zipfile.ZipFile(archive) as zip_file:
        for member in zip_file.infolist():
            normalized = member.filename.replace("\\", "/")
            candidate = Path(normalized)
            mode = member.external_attr >> 16
            if (
                not normalized
                or normalized.startswith("/")
                or candidate.is_absolute()
                or ".." in candidate.parts
                or normalized.casefold() in seen
            ):
                raise BootstrapError("launcher package has unsafe or duplicate ZIP members")
            if mode and (mode & 0o170000) == 0o120000:
                raise BootstrapError("launcher package contains a symbolic-link member")
            seen.add(normalized.casefold())
            output = destination / candidate
            if member.is_dir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                with zip_file.open(member) as source, output.open("wb") as target:
                    shutil.copyfileobj(source, target)


def _fetch(source: str, filename: str, destination: Path) -> None:
    if source.startswith(("https://", "http://")):
        with (
            urllib.request.urlopen(source.rstrip("/") + "/" + filename, timeout=30) as response,
            destination.open("wb") as target,
        ):
            shutil.copyfileobj(response, target)
    else:
        shutil.copy2(Path(source) / filename, destination)


def _terminate_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15, check=False
            )
        else:
            process.kill()
        process.wait(timeout=15)
    except OSError:
        pass


class BootstrapService:
    def __init__(
        self,
        root: Path,
        *,
        trusted_public_keys: dict[str, str],
        revoked_key_ids: set[str] | None = None,
        launcher_runner: Callable[[Path, Path, float], dict[str, Any]] | None = None,
    ):
        self.store = LauncherStore(root)
        self.trusted_public_keys = trusted_public_keys
        self.revoked_key_ids = revoked_key_ids or set()
        self.launcher_runner = launcher_runner or self._run_launcher

    def status(self) -> dict[str, Any]:
        active = self.store.valid_pointer(self.store.active_pointer)
        lkg = self.store.valid_pointer(self.store.lkg_pointer)
        versions = []
        for directory in sorted(self.store.versions.iterdir()) if self.store.versions.exists() else []:
            if directory.is_dir() and not directory.name.startswith("."):
                try:
                    versions.append(self.store.validate_installed(directory))
                except BootstrapError:
                    versions.append({"component_version": directory.name, "invalid": True})
        return {
            "bootstrap_version": "0.1.0",
            "active_launcher": active,
            "last_known_good_launcher": lkg,
            "installed_launchers": versions,
            "active_transaction": self._active_transaction(),
        }

    def _active_transaction(self) -> dict[str, Any]:
        pending = []
        for receipt in self.store.receipts.glob("*.json") if self.store.receipts.exists() else []:
            value = _read_json(receipt)
            if value.get("state") not in {
                "ACTIVE_CONFIRMED",
                "ROLLED_BACK",
                "FAILED_RECOVERABLE",
                "BLOCKED_REQUIRED_UPDATE",
            }:
                pending.append(value)
        return pending[-1] if pending else {}

    def update(
        self, envelope: dict[str, Any], *, transport: str, launch: bool = True, timeout: float = 120.0
    ) -> BootstrapResult:
        manifest = verify_launcher_manifest(
            envelope, trusted_public_keys=self.trusted_public_keys, revoked_key_ids=self.revoked_key_ids
        )
        self.store.reconcile()
        self.store.cached_policy.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.store.cached_policy, envelope)
        transaction_id = uuid.uuid4().hex
        active = self.store.valid_pointer(self.store.active_pointer)
        old_version = str(active.get("version") or "")
        receipt: dict[str, Any] = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "old_launcher_version": old_version,
            "target_launcher_version": manifest.launcher_version,
            "manifest_digest": manifest.digest(),
            "state": "CHECKING",
            "transitions": ["CHECKING"],
            "created_at": _utc_now(),
            "next_safe_action": "verify launcher update",
        }
        self.store.receipt(transaction_id, receipt)
        try:
            target = Version.parse(manifest.launcher_version)
            minimum = Version.parse(manifest.minimum_launcher_version)
            old = Version.parse(old_version) if old_version else None
            if manifest.launcher_version in manifest.revoked_launcher_versions:
                raise BootstrapError("signed launcher policy revokes the candidate launcher version")
            if old is not None and old > target:
                raise BootstrapError("launcher downgrade is blocked")
            if old is not None and old == target:
                existing = self.store.valid_pointer(self.store.active_pointer)
                if existing and existing.get("manifest_digest") == manifest.digest():
                    return BootstrapResult("CURRENT", old_version, str(target), "launch active launcher")
                raise BootstrapError("same launcher component version has conflicting immutable bytes")
            if old is not None and old < minimum and not manifest.mandatory:
                raise BootstrapError("signed policy is inconsistent: unsupported active launcher is not mandatory")
            receipt.update(state="DOWNLOADING", transitions=[*receipt["transitions"], "DOWNLOADING"])
            self.store.receipt(transaction_id, receipt)
            work = Path(tempfile.mkdtemp(prefix="EOATBootstrap_"))
            try:
                package = work / manifest.package_filename
                _fetch(transport, manifest.package_filename, package)
                if package.stat().st_size != manifest.package_size or sha256_file(package) != manifest.package_sha256:
                    raise BootstrapError("launcher package size or SHA-256 does not match signed manifest")
                receipt.update(
                    state="PACKAGE_VERIFIED",
                    package_hash=sha256_file(package),
                    transitions=[*receipt["transitions"], "PACKAGE_VERIFIED"],
                )
                self.store.receipt(transaction_id, receipt)
                staging = self.store.versions / f".staging-{transaction_id}"
                _safe_extract(package, staging)
                candidate_roots = [entry.parent for entry in staging.rglob(LAUNCHER_EXE)]
                if len(candidate_roots) != 1:
                    raise BootstrapError("launcher package must contain exactly one launcher executable")
                candidate = candidate_roots[0]
                metadata = self.store.validate_installed(candidate)
                checks = {
                    "component_version": manifest.launcher_version,
                    "product_version": manifest.product_version,
                    "release_id": manifest.release_id,
                    "build_id": manifest.build_id,
                    "source_commit": manifest.source_commit,
                    "source_tree": manifest.source_tree,
                }
                if any(metadata.get(key) != value for key, value in checks.items()):
                    raise BootstrapError("launcher package embedded identity contradicts signed manifest")
                if (
                    sha256_file(candidate / LAUNCHER_METADATA) != manifest.launcher_metadata_sha256
                    or sha256_file(candidate / LAUNCHER_PACKAGE_MANIFEST) != manifest.package_manifest_sha256
                ):
                    raise BootstrapError("launcher metadata or package manifest digest contradicts signed manifest")
                receipt.update(
                    state="CANDIDATE_SMOKE_TESTING", transitions=[*receipt["transitions"], "CANDIDATE_SMOKE_TESTING"]
                )
                self.store.receipt(transaction_id, receipt)
                packaged_smoke = candidate / LAUNCHER_SMOKE_RECEIPT
                if not packaged_smoke.is_file() or sha256_file(packaged_smoke) != manifest.smoke_receipt_sha256:
                    raise BootstrapError("packaged launcher smoke receipt digest contradicts signed manifest")
                smoke = self.launcher_runner(candidate / LAUNCHER_EXE, candidate / ".bootstrap-smoke.json", timeout)
                if smoke.get("status") != "PASS" or smoke.get("component_version") != manifest.launcher_version:
                    raise BootstrapError("packaged launcher smoke receipt did not validate")
                final = self.store.versions / manifest.launcher_version
                if final.exists():
                    prior = self.store.validate_installed(final)
                    if prior != metadata:
                        raise BootstrapError(
                            "immutable launcher version directory is already occupied by another build"
                        )
                    shutil.rmtree(staging, ignore_errors=True)
                else:
                    candidate.replace(final)
                    shutil.rmtree(staging, ignore_errors=True)
                self.store.validate_installed(final)
                receipt.update(
                    state="ACTIVATING", transitions=[*receipt["transitions"], "CANDIDATE_READY", "ACTIVATING"]
                )
                self.store.receipt(transaction_id, receipt)
                previous = active
                self.store.write_pointer(self.store.active_pointer, metadata, final, manifest_digest=manifest.digest())
                receipt.update(
                    state="ACTIVE_PENDING_HEALTH",
                    target_path=str(final),
                    transitions=[*receipt["transitions"], "ACTIVE_PENDING_HEALTH"],
                )
                self.store.receipt(transaction_id, receipt)
                health = (
                    self._start_health(final / LAUNCHER_EXE, timeout)
                    if launch
                    else {"status": "PASS", "component_version": manifest.launcher_version}
                )
                if health.get("status") != "PASS" or health.get("component_version") != manifest.launcher_version:
                    if previous:
                        self.store.write_pointer(
                            self.store.active_pointer,
                            self.store.validate_installed(Path(previous["path"])),
                            Path(previous["path"]),
                            manifest_digest=str(previous.get("manifest_digest") or ""),
                        )
                        receipt.update(
                            state="ROLLED_BACK",
                            rollback_result="previous launcher restored",
                            transitions=[*receipt["transitions"], "ROLLED_BACK"],
                            next_safe_action="inspect failed launcher diagnostics",
                        )
                        self.store.receipt(transaction_id, receipt)
                        return BootstrapResult(
                            "ROLLED_BACK", old_version, manifest.launcher_version, receipt["next_safe_action"]
                        )
                    receipt.update(state="BLOCKED_REQUIRED_UPDATE", next_safe_action="repair launcher installation")
                    self.store.receipt(transaction_id, receipt)
                    return BootstrapResult(
                        "BLOCKED_REQUIRED_UPDATE", old_version, manifest.launcher_version, receipt["next_safe_action"]
                    )
                self.store.write_pointer(self.store.lkg_pointer, metadata, final, manifest_digest=manifest.digest())
                receipt.update(
                    state="ACTIVE_CONFIRMED",
                    health_result="PASS",
                    transitions=[*receipt["transitions"], "ACTIVE_CONFIRMED"],
                    completed_at=_utc_now(),
                    next_safe_action="launch active launcher",
                )
                self.store.receipt(transaction_id, receipt)
                return BootstrapResult(
                    "ACTIVE_CONFIRMED",
                    manifest.launcher_version,
                    manifest.launcher_version,
                    receipt["next_safe_action"],
                )
            finally:
                shutil.rmtree(work, ignore_errors=True)
        except Exception as exc:
            receipt.update(
                state="FAILED_RECOVERABLE",
                diagnostics=[str(exc)],
                next_safe_action="inspect bootstrap diagnostics and retry",
            )
            self.store.receipt(transaction_id, receipt)
            if isinstance(exc, BootstrapError):
                raise
            raise BootstrapError(str(exc)) from exc

    def offline_launch(self) -> BootstrapResult:
        policy = _read_json(self.store.cached_policy)
        active = self.store.valid_pointer(self.store.active_pointer) or self.store.valid_pointer(self.store.lkg_pointer)
        if not active:
            return BootstrapResult(
                "BLOCKED",
                next_safe_action="repair launcher installation",
                diagnostics=("no trusted installed launcher",),
            )
        try:
            manifest = verify_launcher_manifest(
                policy, trusted_public_keys=self.trusted_public_keys, revoked_key_ids=self.revoked_key_ids
            )
            version = str(active["version"])
            if version in manifest.revoked_launcher_versions or Version.parse(version) < Version.parse(
                manifest.minimum_launcher_version
            ):
                return BootstrapResult(
                    "BLOCKED_REQUIRED_UPDATE", version, next_safe_action="reconnect to approved update transport"
                )
        except BootstrapError:
            return BootstrapResult(
                "BLOCKED", str(active.get("version") or ""), next_safe_action="repair cached launcher policy"
            )
        return BootstrapResult(
            "OFFLINE_FALLBACK", str(active["version"]), next_safe_action="launch confirmed-good launcher"
        )

    def _run_launcher(self, executable: Path, receipt: Path, timeout: float) -> dict[str, Any]:
        receipt.unlink(missing_ok=True)
        environment = os.environ.copy()
        environment.update({"EOAT_ATLAS_SMOKE_TEST": "1", "QT_QPA_PLATFORM": "offscreen"})
        process = subprocess.Popen(
            [str(executable), "--smoke-test", "--smoke-receipt", str(receipt)],
            cwd=executable.parent,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _terminate_tree(process)
            return {"status": "TIMEOUT"}
        payload = _read_json(receipt)
        if process.returncode != 0:
            payload["status"] = "FAILED"
        return payload

    def _start_health(self, executable: Path, timeout: float) -> dict[str, Any]:
        receipt = executable.parent / ".bootstrap-health.json"
        receipt.unlink(missing_ok=True)
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        process = subprocess.Popen(
            [str(executable), "--startup-health-receipt", str(receipt), "--check-only"],
            cwd=executable.parent,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            process.communicate(timeout=min(timeout, 30))
        except subprocess.TimeoutExpired:
            _terminate_tree(process)
            return {"status": "TIMEOUT"}
        payload = _read_json(receipt)
        if process.returncode != 0:
            payload["status"] = "FAILED"
        return payload
