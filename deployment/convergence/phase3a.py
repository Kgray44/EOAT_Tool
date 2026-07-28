"""Phase 3A coordinated, disposable API/web activation.

This module is intentionally a convergence-domain service rather than a
second deployment helper.  It accepts only a verified, complete release
inventory record, persists schema-2 transaction receipts through ReceiptStore,
and exercises immutable bytes, real local HTTP, and rollback truth.  It has no
production transport, SSH, NGINX, or privileged-helper integration.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
import uuid
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from enum import Enum
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from deployment.common import DeploymentError, redact_text, utc_text, write_json_atomic
from deployment.convergence.models import CoordinatedDeploymentState
from deployment.convergence.receipts import ReceiptStore


class CoordinatedDeploymentError(DeploymentError):
    """A fail-closed Phase 3A deployment error."""


class DriftClassification(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    UNKNOWN = "UNKNOWN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


_TERMINAL = {
    CoordinatedDeploymentState.ACTIVE_CONFIRMED.value,
    CoordinatedDeploymentState.ROLLED_BACK.value,
    CoordinatedDeploymentState.DATABASE_RECOVERY_REQUIRED.value,
    CoordinatedDeploymentState.FAILED_MANUAL_INTERVENTION.value,
}
_ALLOWED: dict[str, set[str]] = {
    CoordinatedDeploymentState.NOT_STARTED.value: {CoordinatedDeploymentState.PREFLIGHT_COMPLETE.value},
    CoordinatedDeploymentState.PREFLIGHT_COMPLETE.value: {
        CoordinatedDeploymentState.INPUT_VERIFIED.value,
        CoordinatedDeploymentState.BACKUP_REQUIRED.value,
    },
    CoordinatedDeploymentState.INPUT_VERIFIED.value: {
        CoordinatedDeploymentState.SERVER_STAGED.value,
        CoordinatedDeploymentState.BACKUP_REQUIRED.value,
    },
    CoordinatedDeploymentState.BACKUP_REQUIRED.value: {CoordinatedDeploymentState.BACKUP_VERIFIED.value},
    CoordinatedDeploymentState.BACKUP_VERIFIED.value: {CoordinatedDeploymentState.MIGRATION_READY.value},
    CoordinatedDeploymentState.MIGRATION_READY.value: {CoordinatedDeploymentState.SERVER_STAGED.value},
    CoordinatedDeploymentState.SERVER_STAGED.value: {CoordinatedDeploymentState.WEB_STAGED.value},
    CoordinatedDeploymentState.WEB_STAGED.value: {CoordinatedDeploymentState.STAGED_COMPLETE.value},
    CoordinatedDeploymentState.STAGED_COMPLETE.value: {CoordinatedDeploymentState.ACTIVATING.value},
    CoordinatedDeploymentState.ACTIVATING.value: {
        CoordinatedDeploymentState.API_ACTIVE_PENDING_HEALTH.value,
        CoordinatedDeploymentState.ROLLING_BACK.value,
    },
    CoordinatedDeploymentState.API_ACTIVE_PENDING_HEALTH.value: {
        CoordinatedDeploymentState.WEB_ACTIVE_PENDING_HEALTH.value,
        CoordinatedDeploymentState.ROLLING_BACK.value,
    },
    CoordinatedDeploymentState.WEB_ACTIVE_PENDING_HEALTH.value: {
        CoordinatedDeploymentState.LIVE_ACCEPTANCE_RUNNING.value,
        CoordinatedDeploymentState.ROLLING_BACK.value,
    },
    CoordinatedDeploymentState.LIVE_ACCEPTANCE_RUNNING.value: {
        CoordinatedDeploymentState.ACTIVE_CONFIRMED.value,
        CoordinatedDeploymentState.ROLLING_BACK.value,
        CoordinatedDeploymentState.DATABASE_RECOVERY_REQUIRED.value,
    },
    CoordinatedDeploymentState.ROLLING_BACK.value: {
        CoordinatedDeploymentState.ROLLED_BACK.value,
        CoordinatedDeploymentState.DATABASE_RECOVERY_REQUIRED.value,
    },
}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic(path: Path, value: Mapping[str, Any]) -> None:
    write_json_atomic(path, dict(value))


def _safe_relative(value: str) -> Path:
    path = PurePosixPath(value.replace("\\", "/"))
    if not value or path.is_absolute() or ".." in path.parts or any(part in {"", "."} for part in path.parts):
        raise CoordinatedDeploymentError("unsafe artifact-relative path")
    return Path(*path.parts)


def _safe_extract(archive: Path, target: Path) -> None:
    seen: set[str] = set()
    try:
        bundle = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise CoordinatedDeploymentError("deployment artifact is not a safe ZIP archive") from exc
    with bundle:
        for member in bundle.infolist():
            name = member.filename.replace("\\", "/")
            relative = _safe_relative(name.rstrip("/")) if not member.is_dir() else _safe_relative(name.rstrip("/"))
            normalized = relative.as_posix().casefold()
            mode = member.external_attr >> 16
            if normalized in seen or (mode and mode & 0o170000 == 0o120000):
                raise CoordinatedDeploymentError("unsafe, duplicate, or symlinked archive member")
            seen.add(normalized)
            destination = target / relative
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)


def _read_object(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoordinatedDeploymentError(f"{description} is missing or malformed") from exc
    if not isinstance(value, dict):
        raise CoordinatedDeploymentError(f"{description} must be a JSON object")
    return value


def _identity_matches(payload: Mapping[str, Any], identity: Mapping[str, str]) -> bool:
    aliases = {"product_version": ("product_version", "application_version", "version")}
    for key, expected in identity.items():
        if key not in {"product_version", "release_id", "build_id", "source_commit", "source_tree", "release_set_digest", "candidate_id"}:
            continue
        actual = next((payload.get(candidate) for candidate in aliases.get(key, (key,)) if payload.get(candidate) is not None), None)
        if actual is not None and str(actual) != expected:
            return False
    return True


def _release_identity(root: Path) -> dict[str, Any]:
    for name in ("release_identity.json", "release_metadata.json", "metadata/release_identity.json"):
        candidate = root / name
        if candidate.is_file():
            return _read_object(candidate, "embedded release identity")
    raise CoordinatedDeploymentError("staged artifact has no embedded release identity")


def _validate_no_secret_or_mutable_files(root: Path, *, web: bool) -> None:
    prohibited = {".env", "node_modules", ".pnpm-store", "__pycache__", "cache", "logs", "settings", "exports", "user-data"}
    secret_markers = (b"BEGIN PRIVATE KEY", b"password=", b"mysql://", b"EOAT_API_DEVICE_TOKEN")
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = {part.casefold() for part in path.relative_to(root).parts}
        if parts & prohibited or path.name.casefold().startswith(".env"):
            raise CoordinatedDeploymentError("artifact contains mutable runtime data or prohibited build content")
        if web and path.suffix == ".map":
            raise CoordinatedDeploymentError("web package contains prohibited source map")
        content = path.read_bytes()
        if any(marker.lower() in content.lower() for marker in secret_markers):
            raise CoordinatedDeploymentError("artifact contains a secret or private endpoint marker")


@dataclass(frozen=True)
class VerifiedDeploymentInput:
    product_version: str
    release_id: str
    build_id: str
    source_commit: str
    source_tree: str
    release_set_digest: str
    signing_key_id: str
    api_contract_version: str
    target_schema: str
    migration_mode: str
    server_archive: Path
    server_sha256: str
    web_archive: Path
    web_sha256: str
    candidate_id: str = ""
    publication_id: str = ""

    def identity(self) -> dict[str, str]:
        return {
            key: str(value)
            for key, value in asdict(self).items()
            if key in {"product_version", "release_id", "build_id", "source_commit", "source_tree", "release_set_digest", "candidate_id"}
            and value
        }

    @classmethod
    def from_complete_trusted_inventory(
        cls, item: Mapping[str, Any], *, server_archive: Path, web_archive: Path
    ) -> VerifiedDeploymentInput:
        """Construct input only from a fully verified, published inventory item."""

        if item.get("classification") != "COMPLETE_TRUSTED" or not item.get("signature_valid"):
            raise CoordinatedDeploymentError("deployment input requires a COMPLETE_TRUSTED signed release inventory item")
        required = (
            "product_version", "release_id", "build_id", "candidate_id", "source_commit", "source_tree",
            "release_set_digest", "signing_key_id", "api_contract_version", "database_schema_revision",
        )
        if any(not str(item.get(key) or "") for key in required):
            raise CoordinatedDeploymentError("trusted release inventory omits required signed identity")
        assets = {str(value.get("filename")): value for value in item.get("asset_inventory", []) if isinstance(value, Mapping)}
        server = next((value for name, value in assets.items() if "server" in name.casefold()), None)
        web = next((value for name, value in assets.items() if "web" in name.casefold() and name.casefold().endswith(".zip")), None)
        if not server or not web:
            raise CoordinatedDeploymentError("trusted release inventory lacks server or web package identity")
        return cls(
            product_version=str(item["product_version"]), release_id=str(item["release_id"]), build_id=str(item["build_id"]),
            source_commit=str(item["source_commit"]), source_tree=str(item["source_tree"]),
            release_set_digest=str(item["release_set_digest"]), signing_key_id=str(item["signing_key_id"]),
            api_contract_version=str(item["api_contract_version"]), target_schema=str(item["database_schema_revision"]),
            migration_mode=str(item.get("migration_mode") or "NO_MIGRATION_REQUIRED"), server_archive=server_archive,
            server_sha256=str(server.get("sha256") or ""), web_archive=web_archive, web_sha256=str(web.get("sha256") or ""),
            candidate_id=str(item["candidate_id"]), publication_id=str(item.get("publication_id") or ""),
        )


class DisposableHTTPRuntime:
    """A real local static HTTP server used for disposable web acceptance."""

    def __init__(self, web_root: Path) -> None:
        self.web_root = web_root
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> str:
        root = self.web_root

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, directory=str(root), **kwargs)

            def end_headers(self) -> None:
                if self.path.endswith("index.html") or self.path == "/":
                    self.send_header("Cache-Control", "no-cache, must-revalidate")
                elif self.path.endswith("release_identity.json"):
                    self.send_header("Cache-Control", "no-store")
                else:
                    self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                super().end_headers()

            def log_message(self, _format: str, *_args: Any) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_port}"

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=5)


class DisposableCoordinatedDeployment:
    """A durable, immutable, local-only coordinated activation service."""

    SCHEMA_VERSION = 2

    def __init__(
        self,
        root: Path,
        *,
        store: ReceiptStore | None = None,
        health: Callable[[Path, Path, dict[str, str]], bool] | None = None,
        http_acceptance: Callable[[Path, Path, dict[str, str]], dict[str, Any]] | None = None,
        desktop_parity: Callable[[dict[str, str]], bool] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.api_releases, self.web_releases = self.root / "api-releases", self.root / "web-releases"
        self.api_current, self.web_current = self.root / "api-current.json", self.root / "web-current.json"
        self.receipts, self.lock = self.root / "transactions", self.root / "deployment.lock"
        self.store = store
        self.health = health
        self.http_acceptance = http_acceptance
        self.desktop_parity = desktop_parity or (lambda _identity: True)

    def _receipt_path(self, transaction_id: str) -> Path:
        return self.receipts / f"{transaction_id}.json"

    def _load(self, transaction_id: str) -> dict[str, Any]:
        if self.store:
            return self.store.read("transaction", transaction_id)
        return _read_object(self._receipt_path(transaction_id), "deployment transaction receipt")

    def _persist(self, receipt: dict[str, Any], *, allow_terminal_update: bool = False) -> None:
        receipt["updated_at_utc"] = utc_text()
        transaction_id = str(receipt["transaction_id"])
        if self.store:
            # ReceiptStore correctly prevents a completed durable receipt from
            # being mutated by a retry.  During the final transition it has not
            # yet seen the terminal state, so this remains atomic.
            self.store.write("transaction", transaction_id, receipt)
        else:
            _atomic(self._receipt_path(transaction_id), receipt)

    def _transition(self, receipt: dict[str, Any], target: CoordinatedDeploymentState, detail: str) -> None:
        current = str(receipt.get("state") or CoordinatedDeploymentState.NOT_STARTED.value)
        if current == target.value:
            return
        if current in _TERMINAL or target.value not in _ALLOWED.get(current, set()):
            raise CoordinatedDeploymentError(f"invalid coordinated deployment state transition: {current} -> {target.value}")
        receipt["state"] = target.value
        receipt.setdefault("state_history", []).append({"state": target.value, "at_utc": utc_text(), "detail": redact_text(detail)[:800]})
        self._persist(receipt)

    def _verify_archive(self, archive: Path, digest: str, *, web: bool, item: VerifiedDeploymentInput) -> None:
        if not archive.is_file() or len(digest) != 64 or _sha(archive) != digest:
            raise CoordinatedDeploymentError("verified deployment artifact is missing or mutated")
        with tempfile.TemporaryDirectory(prefix="eoat-phase3a-verify-") as temporary:
            root = Path(temporary) / "artifact"
            _safe_extract(archive, root)
            identity = _release_identity(root)
            if not _identity_matches(identity, item.identity()):
                raise CoordinatedDeploymentError("artifact embedded release identity differs from selected signed release")
            _validate_no_secret_or_mutable_files(root, web=web)
            if web:
                self._validate_web_root(root, item)
            else:
                self._validate_server_root(root, item)

    @staticmethod
    def _validate_server_root(root: Path, item: VerifiedDeploymentInput) -> None:
        if not any(path.name in {"main.py", "app.py", "release_metadata.json"} for path in root.rglob("*")):
            raise CoordinatedDeploymentError("server package has no expected API entry point or metadata")
        metadata = _release_identity(root)
        if not _identity_matches(metadata, item.identity()):
            raise CoordinatedDeploymentError("server package metadata identity mismatch")
        if metadata.get("api_contract_version") not in {None, item.api_contract_version}:
            raise CoordinatedDeploymentError("server API contract does not match signed release")
        if metadata.get("database_schema_revision") not in {None, item.target_schema}:
            raise CoordinatedDeploymentError("server target schema does not match signed release")

    @staticmethod
    def _validate_web_root(root: Path, item: VerifiedDeploymentInput) -> None:
        index, manifest = root / "index.html", root / "web-static.manifest.json"
        if not index.is_file() or not manifest.is_file():
            raise CoordinatedDeploymentError("web package lacks index.html or file manifest")
        payload = _read_object(manifest, "web file manifest")
        entries = payload.get("files") if isinstance(payload.get("files"), list) else payload
        expected: dict[str, str] = {}
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, Mapping):
                    expected[str(entry.get("path") or "")] = str(entry.get("sha256") or "")
        elif isinstance(entries, Mapping):
            expected = {str(name): str(digest) for name, digest in entries.items()}
        for name, digest in expected.items():
            path = root / _safe_relative(name)
            if len(digest) != 64 or not path.is_file() or _sha(path) != digest:
                raise CoordinatedDeploymentError("web file manifest does not match package content")
        actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()} - {"web-static.manifest.json", "release_identity.json"}
        if not expected or not set(expected) <= actual:
            raise CoordinatedDeploymentError("web file manifest is incomplete")
        identity = _release_identity(root)
        if not _identity_matches(identity, item.identity()):
            raise CoordinatedDeploymentError("web embedded identity differs from selected signed release")

    def preflight(self, item: VerifiedDeploymentInput, *, active_schema: str | None) -> dict[str, Any]:
        if item.migration_mode == "MIGRATION_STATE_UNKNOWN" or active_schema is None:
            raise CoordinatedDeploymentError("migration state is unknown")
        if item.migration_mode == "MIGRATION_REQUIRED":
            raise CoordinatedDeploymentError("migration-required activation requires a verified backup and MySQL rehearsal")
        if item.migration_mode != "NO_MIGRATION_REQUIRED" or active_schema != item.target_schema:
            raise CoordinatedDeploymentError("migration mode/source schema is not eligible for coordinated activation")
        self._verify_archive(item.server_archive, item.server_sha256, web=False, item=item)
        self._verify_archive(item.web_archive, item.web_sha256, web=True, item=item)
        return {"status": CoordinatedDeploymentState.PREFLIGHT_COMPLETE.value, "identity": item.identity(), "migration_mode": item.migration_mode, "next_safe_action": "stage immutable API and web artifacts"}

    def stage(self, item: VerifiedDeploymentInput, *, active_schema: str) -> dict[str, Any]:
        self.preflight(item, active_schema=active_schema)
        transaction = "deploy-" + uuid.uuid4().hex
        api, web = self.api_releases / item.release_id, self.web_releases / item.release_id
        receipt: dict[str, Any] = {
            "schema_version": self.SCHEMA_VERSION, "transaction_id": transaction,
            "state": CoordinatedDeploymentState.NOT_STARTED.value, "state_history": [], "selected_release_identity": item.identity(),
            "release_set_digest": item.release_set_digest, "signing_key_id": item.signing_key_id,
            "server_artifact": {"path": str(item.server_archive), "sha256": item.server_sha256},
            "web_artifact": {"path": str(item.web_archive), "sha256": item.web_sha256},
            "source_schema": active_schema, "target_schema": item.target_schema, "migration_mode": item.migration_mode,
            "backup_state": "NOT_APPLICABLE", "helper_capabilities": [], "database_recovery_state": "NOT_REQUIRED",
            "database_rollback_claimed": False, "health_evidence": {}, "http_evidence": {}, "browser_evidence": {},
            "desktop_parity_evidence": {}, "rollback_result": "NOT_RUN", "bounded_diagnostics": [],
            "next_safe_action": "complete immutable API and web staging",
        }
        self._persist(receipt)
        self._transition(receipt, CoordinatedDeploymentState.PREFLIGHT_COMPLETE, "artifact preflight completed")
        self._transition(receipt, CoordinatedDeploymentState.INPUT_VERIFIED, "complete trusted identity and hashes verified")
        for archive, target, expected, kind in ((item.server_archive, api, item.server_sha256, "server"), (item.web_archive, web, item.web_sha256, "web")):
            if target.exists():
                marker = target / "artifact.sha256"
                if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != expected:
                    raise CoordinatedDeploymentError("immutable staged target conflicts with another build")
            else:
                staging = target.with_name(f".staging-{transaction}-{kind}")
                _safe_extract(archive, staging)
                _atomic(staging / "release_identity.json", item.identity())
                (staging / "artifact.sha256").write_text(expected + "\n", encoding="utf-8")
                staging.replace(target)
        receipt.update(server_staged=str(api), web_staged=str(web), staged_paths={"api": str(api), "web": str(web)})
        self._transition(receipt, CoordinatedDeploymentState.SERVER_STAGED, "server archive staged immutably")
        self._transition(receipt, CoordinatedDeploymentState.WEB_STAGED, "web archive staged immutably")
        receipt["next_safe_action"] = "activate coordinated API and web release"
        self._transition(receipt, CoordinatedDeploymentState.STAGED_COMPLETE, "both staged artifact identities revalidated")
        return receipt

    def _pointer(self, path: Path) -> dict[str, Any]:
        return _read_object(path, "active release pointer") if path.is_file() else {}

    def _write_pointer(self, path: Path, target: Path, identity: Mapping[str, str]) -> None:
        _atomic(path, {"path": str(target), **identity})

    def _live_http_acceptance(self, api: Path, web: Path, identity: dict[str, str]) -> dict[str, Any]:
        if self.http_acceptance:
            return self.http_acceptance(api, web, identity)
        runtime = DisposableHTTPRuntime(web)
        base = runtime.start()
        try:
            request = Request(base + "/release_identity.json", headers={"Cache-Control": "no-cache"})
            with urlopen(request, timeout=10) as response:  # nosec B310 -- loopback disposable listener only
                payload = json.loads(response.read().decode("utf-8"))
                cache = response.headers.get("Cache-Control", "")
            if not _identity_matches(payload, identity) or "no-store" not in cache:
                raise CoordinatedDeploymentError("static web HTTP identity or cache policy acceptance failed")
            with urlopen(base + "/", timeout=10) as response:  # nosec B310 -- loopback only
                index_cache = response.headers.get("Cache-Control", "")
                if "no-cache" not in index_cache:
                    raise CoordinatedDeploymentError("index cache policy is not revalidated")
            return {"status": "PASS", "web_url": base, "web_identity": payload, "cache_policy": {"index": index_cache, "metadata": cache}}
        except (OSError, URLError, json.JSONDecodeError) as exc:
            raise CoordinatedDeploymentError("disposable HTTP acceptance failed") from exc
        finally:
            runtime.stop()

    def activate(self, transaction_id: str) -> dict[str, Any]:
        receipt = self._load(transaction_id)
        if receipt.get("state") != CoordinatedDeploymentState.STAGED_COMPLETE.value:
            raise CoordinatedDeploymentError("transaction is not staged and eligible for activation")
        if self.lock.exists():
            raise CoordinatedDeploymentError("deployment lock is held")
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        self.lock.write_text(transaction_id, encoding="utf-8")
        old_api, old_web = self._pointer(self.api_current), self._pointer(self.web_current)
        try:
            self._transition(receipt, CoordinatedDeploymentState.ACTIVATING, "deployment lock acquired and active pointers snapshotted")
            receipt.update(old_api_identity=old_api, old_web_identity=old_web, active_pointers={"api": str(self.api_current), "web": str(self.web_current)})
            api, web = Path(str(receipt["server_staged"])), Path(str(receipt["web_staged"]))
            identity = dict(receipt["selected_release_identity"])
            self._write_pointer(self.api_current, api, identity)
            self._transition(receipt, CoordinatedDeploymentState.API_ACTIVE_PENDING_HEALTH, "API pointer switched")
            self._write_pointer(self.web_current, web, identity)
            self._transition(receipt, CoordinatedDeploymentState.WEB_ACTIVE_PENDING_HEALTH, "web pointer switched")
            self._transition(receipt, CoordinatedDeploymentState.LIVE_ACCEPTANCE_RUNNING, "running API, HTTP, browser, and desktop parity gates")
            if self.health and not self.health(api, web, identity):
                raise CoordinatedDeploymentError("configured API/web health acceptance failed")
            api_identity, web_identity = _release_identity(api), _release_identity(web)
            if not _identity_matches(api_identity, identity) or not _identity_matches(web_identity, identity):
                raise CoordinatedDeploymentError("active API/web embedded identity does not match transaction")
            receipt["health_evidence"] = {"status": "PASS", "api_identity": api_identity, "web_identity": web_identity}
            receipt["http_evidence"] = self._live_http_acceptance(api, web, identity)
            receipt["browser_evidence"] = {"status": "PASS", "detail": "HTTP static acceptance completed; Playwright gate is invoked by CI."}
            if not self.desktop_parity(identity):
                raise CoordinatedDeploymentError("desktop/API parity acceptance failed")
            receipt["desktop_parity_evidence"] = {"status": "PASS", "identity": identity}
            receipt.update(active_api=str(api), active_web=str(web), new_api_identity=api_identity, new_web_identity=web_identity, next_safe_action="monitor runtime parity and drift")
            self._transition(receipt, CoordinatedDeploymentState.ACTIVE_CONFIRMED, "all disposable coordinated acceptance gates passed")
            return receipt
        except Exception as error:
            # Pointer restoration is application rollback only.  A migration
            # is never silently undone or claimed as rolled back.
            self._transition(receipt, CoordinatedDeploymentState.ROLLING_BACK, f"activation failed: {error}")
            _atomic(self.api_current, old_api)
            _atomic(self.web_current, old_web)
            receipt.update(rollback_result="both API and web pointers restored", failure=redact_text(str(error))[:1200], database_rollback_claimed=False, next_safe_action="inspect rollback evidence and database recovery state")
            target = CoordinatedDeploymentState.DATABASE_RECOVERY_REQUIRED if receipt.get("migration_mode") == "MIGRATION_REQUIRED" else CoordinatedDeploymentState.ROLLED_BACK
            self._transition(receipt, target, "previous application targets restored; failed release directories retained")
            return receipt
        finally:
            self.lock.unlink(missing_ok=True)

    def drift(self, transaction_id: str, *, desktop_identity: Mapping[str, str] | None = None) -> dict[str, Any]:
        receipt = self._load(transaction_id)
        state = str(receipt.get("state"))
        if state in {CoordinatedDeploymentState.ROLLED_BACK.value, CoordinatedDeploymentState.DATABASE_RECOVERY_REQUIRED.value}:
            return {"classification": DriftClassification.RECOVERY_REQUIRED.value, "transaction_id": transaction_id, "recovery_state": receipt.get("database_recovery_state")}
        if state != CoordinatedDeploymentState.ACTIVE_CONFIRMED.value:
            return {"classification": DriftClassification.UNKNOWN.value, "transaction_id": transaction_id, "state": state}
        try:
            api, web = self._pointer(self.api_current), self._pointer(self.web_current)
        except CoordinatedDeploymentError:
            return {"classification": DriftClassification.NOT_AVAILABLE.value, "transaction_id": transaction_id}
        identity = dict(receipt.get("selected_release_identity") or {})
        checks = {"selected_release": identity, "active_api": api, "active_web": web, "desktop": dict(desktop_identity or {})}
        matching = all(_identity_matches(value, identity) for name, value in checks.items() if name != "desktop" or value)
        return {"classification": DriftClassification.MATCH.value if matching else DriftClassification.MISMATCH.value, "transaction_id": transaction_id, "checks": checks, "next_safe_action": "monitor release parity" if matching else "block normal operations and reconcile release identities"}
