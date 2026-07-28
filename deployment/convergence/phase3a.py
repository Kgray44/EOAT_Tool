"""Disposable coordinated API/web activation with durable, truthful rollback."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class CoordinatedDeploymentError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        Path(temporary).replace(path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _safe_extract(archive: Path, target: Path) -> None:
    seen: set[str] = set()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            name = member.filename.replace("\\", "/")
            path = Path(name)
            mode = member.external_attr >> 16
            if (
                not name
                or name.startswith("/")
                or path.is_absolute()
                or ".." in path.parts
                or name.casefold() in seen
                or (mode and mode & 0o170000 == 0o120000)
            ):
                raise CoordinatedDeploymentError("unsafe or duplicate archive member")
            seen.add(name.casefold())
            destination = target / path
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)


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

    def identity(self) -> dict[str, str]:
        return {
            key: str(value)
            for key, value in asdict(self).items()
            if key
            in {"product_version", "release_id", "build_id", "source_commit", "source_tree", "release_set_digest"}
        }


class DisposableCoordinatedDeployment:
    """Real filesystem bytes/pointers; never a production transport."""

    def __init__(self, root: Path, *, health: Callable[[Path, Path, dict[str, str]], bool] | None = None):
        self.root = root
        self.api_releases, self.web_releases = root / "api-releases", root / "web-releases"
        self.api_current, self.web_current = root / "api-current.json", root / "web-current.json"
        self.receipts, self.lock = root / "transactions", root / "deployment.lock"
        self.health = health or (
            lambda api, web, identity: (api / "release_identity.json").is_file()
            and (web / "release_identity.json").is_file()
        )

    def preflight(self, item: VerifiedDeploymentInput, *, active_schema: str | None) -> dict[str, Any]:
        if item.migration_mode == "MIGRATION_STATE_UNKNOWN" or active_schema is None:
            raise CoordinatedDeploymentError("migration state is unknown")
        if item.migration_mode == "MIGRATION_REQUIRED":
            raise CoordinatedDeploymentError(
                "migration-required activation is blocked pending governed MySQL rehearsal"
            )
        if item.migration_mode != "NO_MIGRATION_REQUIRED" or active_schema != item.target_schema:
            raise CoordinatedDeploymentError("migration mode/source schema is not eligible for coordinated activation")
        for path, digest in ((item.server_archive, item.server_sha256), (item.web_archive, item.web_sha256)):
            if not path.is_file() or _sha(path) != digest:
                raise CoordinatedDeploymentError("verified deployment artifact is missing or mutated")
        return {
            "status": "PREFLIGHT_COMPLETE",
            "identity": item.identity(),
            "migration_mode": item.migration_mode,
            "next_safe_action": "stage immutable API and web artifacts",
        }

    def stage(self, item: VerifiedDeploymentInput, *, active_schema: str) -> dict[str, Any]:
        self.preflight(item, active_schema=active_schema)
        transaction = "deploy-" + uuid.uuid4().hex
        api, web = self.api_releases / item.release_id, self.web_releases / item.release_id
        for archive, target, expected in (
            (item.server_archive, api, item.server_sha256),
            (item.web_archive, web, item.web_sha256),
        ):
            if target.exists():
                if (target / "artifact.sha256").read_text(encoding="utf-8").strip() != expected:
                    raise CoordinatedDeploymentError("immutable staged target conflicts with another build")
                continue
            staging = target.with_name(".staging-" + transaction)
            _safe_extract(archive, staging)
            _atomic(staging / "release_identity.json", item.identity())
            (staging / "artifact.sha256").write_text(expected + "\n", encoding="utf-8")
            staging.replace(target)
        receipt = {
            "schema_version": 1,
            "transaction_id": transaction,
            "state": "STAGED_COMPLETE",
            "identity": item.identity(),
            "server_staged": str(api),
            "web_staged": str(web),
            "migration_mode": item.migration_mode,
            "database_rollback_claimed": False,
            "next_safe_action": "activate coordinated API/web release",
        }
        _atomic(self.receipts / f"{transaction}.json", receipt)
        return receipt

    def activate(self, transaction_id: str) -> dict[str, Any]:
        receipt_path = self.receipts / f"{transaction_id}.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("state") != "STAGED_COMPLETE":
            raise CoordinatedDeploymentError("transaction is not staged and eligible for activation")
        if self.lock.exists():
            raise CoordinatedDeploymentError("deployment lock is held")
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        self.lock.write_text(transaction_id, encoding="utf-8")
        old_api = json.loads(self.api_current.read_text()) if self.api_current.exists() else {}
        old_web = json.loads(self.web_current.read_text()) if self.web_current.exists() else {}
        try:
            receipt.update(state="ACTIVATING", old_api=old_api, old_web=old_web)
            _atomic(receipt_path, receipt)
            new_api, new_web = Path(receipt["server_staged"]), Path(receipt["web_staged"])
            _atomic(self.api_current, {"path": str(new_api), **receipt["identity"]})
            _atomic(self.web_current, {"path": str(new_web), **receipt["identity"]})
            if not self.health(new_api, new_web, receipt["identity"]):
                raise CoordinatedDeploymentError("API/web identity or live acceptance health failed")
            receipt.update(
                state="ACTIVE_CONFIRMED",
                active_api=str(new_api),
                active_web=str(new_web),
                next_safe_action="monitor release parity",
            )
            _atomic(receipt_path, receipt)
            return receipt
        except Exception as error:
            _atomic(self.api_current, old_api)
            _atomic(self.web_current, old_web)
            receipt.update(
                state="ROLLED_BACK",
                rollback_result="both API and web pointers restored",
                failure=str(error),
                database_rollback_claimed=False,
                recovery_requirement="NONE",
            )
            _atomic(receipt_path, receipt)
            return receipt
        finally:
            self.lock.unlink(missing_ok=True)

    def drift(self, transaction_id: str) -> dict[str, str]:
        receipt = json.loads((self.receipts / f"{transaction_id}.json").read_text(encoding="utf-8"))
        if receipt.get("state") != "ACTIVE_CONFIRMED":
            return {"classification": "RECOVERY_REQUIRED" if receipt.get("state") == "ROLLED_BACK" else "UNKNOWN"}
        api, web = json.loads(self.api_current.read_text()), json.loads(self.web_current.read_text())
        return {
            "classification": "MATCH"
            if all(api.get(key) == web.get(key) == value for key, value in receipt["identity"].items())
            else "MISMATCH",
            "api_release": api.get("release_id", ""),
            "web_release": web.get("release_id", ""),
        }
