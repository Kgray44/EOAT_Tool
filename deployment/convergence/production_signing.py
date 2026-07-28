"""Windows DPAPI production release-signing provider.

Private key material never crosses this module's public API.  The only
durable private representation is a CurrentUser DPAPI blob outside the Git
worktree; callers receive public metadata or a signature only.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import subprocess
import tempfile
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from deployment.common import DeploymentError, write_json_atomic


class ProviderClassification(StrEnum):
    EPHEMERAL_TEST = "EPHEMERAL_TEST"
    WINDOWS_DPAPI_PRODUCTION = "WINDOWS_DPAPI_PRODUCTION"
    UNAVAILABLE = "UNAVAILABLE"
    MALFORMED = "MALFORMED"
    REVOKED = "REVOKED"
    UNTRUSTED = "UNTRUSTED"


_STORE_NAME = "ProductionSigning"
_BLOB_NAME = "production-signing-key.dpapi"
_METADATA_NAME = "production-signing-key.metadata.json"
_ENTROPY_PREFIX = b"EOAT Atlas production release signing|"
_POLICY_PATH = Path(__file__).resolve().parents[2] / "release_trust" / "production_manifest_keys.json"


def _utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _store_root() -> Path:
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local:
        raise DeploymentError("LOCALAPPDATA is unavailable for the protected production signing store")
    return Path(local) / "EOAT_Atlas" / _STORE_NAME


def _owner_sid() -> str:
    completed = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=False)
    if completed.returncode or not completed.stdout.strip():
        raise DeploymentError("cannot resolve current Windows owner SID")
    fields = completed.stdout.strip().strip('"').split('","')
    if len(fields) < 2 or not fields[-1].startswith("S-"):
        raise DeploymentError("current Windows owner SID is malformed")
    return fields[-1]


def _owner_principal() -> str:
    user = os.environ.get("USERNAME", "").strip()
    domain = os.environ.get("USERDOMAIN", "").strip()
    if not user or not domain:
        raise DeploymentError("cannot resolve current Windows account for protected-store ACL")
    return f"{domain}\\{user}"


def _require_windows() -> None:
    if os.name != "nt":
        raise DeploymentError("Windows DPAPI production signing is unavailable on this platform")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _dpapi(value: bytes, entropy: bytes, *, protect: bool) -> bytes:
    _require_windows()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source = ctypes.create_string_buffer(value)
    salt = ctypes.create_string_buffer(entropy)
    source_blob = _Blob(len(value), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
    entropy_blob = _Blob(len(entropy), ctypes.cast(salt, ctypes.POINTER(ctypes.c_byte)))
    output_blob = _Blob()
    if protect:
        ok = crypt32.CryptProtectData(ctypes.byref(source_blob), "EOAT Atlas production signing key", ctypes.byref(entropy_blob), None, None, 0, ctypes.byref(output_blob))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(source_blob), None, ctypes.byref(entropy_blob), None, None, 0, ctypes.byref(output_blob))
    if not ok:
        raise DeploymentError("Windows DPAPI operation failed")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _verify_acl(root: Path, sid: str) -> None:
    result = subprocess.run(["icacls", str(root)], capture_output=True, text=True, check=False)
    text = (result.stdout + result.stderr).casefold()
    principal = _owner_principal().casefold()
    if result.returncode or "everyone:" in text or "builtin\\users:" in text or principal not in text:
        raise DeploymentError("protected signing-store ACL verification failed")


def _harden_acl(root: Path, sid: str) -> None:
    principal = _owner_principal()
    commands = (
        ["icacls", str(root), "/inheritance:r"],
        ["icacls", str(root), "/grant:r", f"{principal}:(OI)(CI)F", "SYSTEM:(OI)(CI)F"],
    )
    for command in commands:
        if subprocess.run(command, capture_output=True, text=True, check=False).returncode:
            raise DeploymentError("cannot govern protected signing-store ACL")
    _verify_acl(root, sid)


@dataclass(frozen=True)
class ProductionSigningStatus:
    key_id: str
    public_key_b64: str
    public_key_sha256: str
    algorithm: str
    provider: ProviderClassification
    owner_sid_sha256: str
    readiness: str
    protected_store: str

    def to_dict(self) -> dict[str, str]:
        return {"key_id": self.key_id, "public_key": self.public_key_b64, "public_key_sha256": self.public_key_sha256, "algorithm": self.algorithm, "provider": self.provider.value, "owner_sid_sha256": self.owner_sid_sha256, "readiness": self.readiness, "protected_store": self.protected_store}


class WindowsDpapiProductionProvider:
    classification = ProviderClassification.WINDOWS_DPAPI_PRODUCTION

    def __init__(self, root: Path | None = None) -> None:
        _require_windows()
        self.root = root or _store_root()
        self.blob_path = self.root / _BLOB_NAME
        self.metadata_path = self.root / _METADATA_NAME

    def _metadata(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeploymentError("production signing metadata is unavailable or malformed") from exc
        if not isinstance(payload, dict) or payload.get("provider") != self.classification.value or payload.get("algorithm") != "Ed25519":
            raise DeploymentError("production signing metadata is not an active Ed25519 DPAPI provider")
        return payload

    @staticmethod
    def provision(*, confirmation: str, root: Path | None = None) -> ProductionSigningStatus:
        if confirmation != "PROVISION EOAT ATLAS PRODUCTION SIGNING KEY":
            raise DeploymentError("exact production-key provisioning confirmation is required")
        provider = WindowsDpapiProductionProvider(root)
        if provider.blob_path.exists() or provider.metadata_path.exists():
            raise DeploymentError("production signing key already exists; replacement is forbidden")
        sid = _owner_sid()
        provider.root.mkdir(parents=True, exist_ok=False)
        _harden_acl(provider.root, sid)
        private = bytearray(Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()))
        try:
            public = Ed25519PrivateKey.from_private_bytes(bytes(private)).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            fingerprint = hashlib.sha256(public).hexdigest()
            key_id = f"eoat-prod-ed25519-{fingerprint[:16]}"
            encrypted = _dpapi(bytes(private), _ENTROPY_PREFIX + key_id.encode("ascii"), protect=True)
            with tempfile.NamedTemporaryFile(dir=provider.root, delete=False) as handle:
                handle.write(encrypted)
                temporary = Path(handle.name)
            temporary.replace(provider.blob_path)
            metadata = {"schema_version": 1, "key_id": key_id, "public_key": base64.b64encode(public).decode("ascii"), "public_key_sha256": fingerprint, "algorithm": "Ed25519", "provider": provider.classification.value, "environment": "PRODUCTION", "purpose": "EOAT Atlas production release-set and update-manifest signing", "status": "ACTIVE", "revoked": False, "owner_sid_sha256": hashlib.sha256(sid.encode("ascii")).hexdigest(), "created_at_utc": _utc()}
            write_json_atomic(provider.metadata_path, metadata)
            _verify_acl(provider.root, sid)
            return provider.status()
        finally:
            for index in range(len(private)):
                private[index] = 0

    def status(self) -> ProductionSigningStatus:
        metadata = self._metadata()
        sid = _owner_sid()
        _verify_acl(self.root, sid)
        return ProductionSigningStatus(str(metadata["key_id"]), str(metadata["public_key"]), str(metadata["public_key_sha256"]), "Ed25519", self.classification, str(metadata["owner_sid_sha256"]), "READY" if self.blob_path.is_file() else "MISSING", "LOCALAPPDATA/EOAT_Atlas/ProductionSigning")

    def public_key_bytes(self) -> bytes:
        return base64.b64decode(self.status().public_key_b64, validate=True)

    def sign(self, payload: bytes) -> bytes:
        status = self.status()
        encrypted = self.blob_path.read_bytes()
        private = bytearray(_dpapi(encrypted, _ENTROPY_PREFIX + status.key_id.encode("ascii"), protect=False))
        try:
            if len(private) != 32:
                raise DeploymentError("protected production signing seed has an invalid length")
            return Ed25519PrivateKey.from_private_bytes(bytes(private)).sign(payload)
        finally:
            for index in range(len(private)):
                private[index] = 0


def load_production_trust_policy(path: Path = _POLICY_PATH) -> tuple[dict[str, bytes], frozenset[str], dict[str, Any]]:
    """Load the one repository-governed public production trust policy."""

    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentError("production trust policy is unavailable or malformed") from exc
    if not isinstance(policy, dict) or policy.get("schema_version") != 1 or policy.get("environment") != "PRODUCTION":
        raise DeploymentError("production trust policy schema or environment is invalid")
    revoked = frozenset(str(value) for value in policy.get("revoked_key_ids", []) if str(value))
    trusted: dict[str, bytes] = {}
    for item in policy.get("keys", []):
        if not isinstance(item, dict) or item.get("algorithm") != "Ed25519":
            raise DeploymentError("production trust policy contains an unsupported key")
        key_id, encoded, fingerprint = str(item.get("key_id") or ""), str(item.get("public_key") or ""), str(item.get("public_key_sha256") or "")
        if not key_id or key_id in trusted or item.get("revoked") or item.get("status") != "ACTIVE":
            raise DeploymentError("production trust policy has an invalid active key")
        try:
            public = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise DeploymentError("production trust policy key encoding is malformed") from exc
        if len(public) != 32 or hashlib.sha256(public).hexdigest() != fingerprint:
            raise DeploymentError("production trust policy key fingerprint differs from public bytes")
        trusted[key_id] = public
    if set(policy.get("active_key_ids", [])) != set(trusted):
        raise DeploymentError("production trust policy active-key list differs from key records")
    return trusted, revoked, policy
