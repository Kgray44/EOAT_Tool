"""Durable, versioned local receipt storage with corrupt-record quarantine."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from deployment.common import DeploymentError, read_json_object, utc_text, write_json_atomic


class ReceiptStore:
    """Local operator-state store. It intentionally never stores secrets."""

    KINDS = (
        "candidate",
        "publication",
        "inspection",
        "plan",
        "transaction",
        "migration",
        "recovery",
    )

    def __init__(self, root: Path) -> None:
        self.root = root / ".local" / "release-deployment-console"

    @staticmethod
    def _safe(value: str) -> bool:
        return bool(value) and value.replace("-", "").replace("_", "").replace(".", "").isalnum()

    def _path(self, kind: str, identifier: str) -> Path:
        if kind not in self.KINDS or not self._safe(identifier):
            raise DeploymentError("unsafe receipt identity")
        return self.root / kind / f"{identifier}.json"

    def write(self, kind: str, identifier: str, payload: dict[str, Any]) -> Path:
        path = self._path(kind, identifier)
        payload = dict(payload)
        payload.setdefault("schema_version", 1)
        payload.setdefault("recorded_at_utc", utc_text())
        payload["receipt_kind"] = kind
        payload["receipt_id"] = identifier
        payload["receipt_path"] = str(path)
        if kind == "publication" and path.is_file():
            existing = self.read(kind, identifier)
            complete_states = {"PUBLICATION_COMPLETE"}
            if existing.get("schema_version") == 2 and existing.get("state") in complete_states and existing != payload:
                raise DeploymentError("completed schema-2 publication receipts are immutable")
        write_json_atomic(path, payload)
        return path

    def read(self, kind: str, identifier: str) -> dict[str, Any]:
        path = self._path(kind, identifier)
        try:
            payload = read_json_object(path)
        except DeploymentError as exc:
            if path.exists():
                quarantine = self.root / "quarantine"
                quarantine.mkdir(parents=True, exist_ok=True)
                target = quarantine / f"{kind}-{path.stem}-{utc_text().replace(':', '')}.json"
                shutil.move(str(path), str(target))
                raise DeploymentError(f"corrupt {kind} receipt was quarantined: {target.name}") from exc
            raise
        if payload.get("receipt_kind") not in {None, kind}:
            raise DeploymentError("receipt kind does not match its storage location")
        if payload.get("receipt_id") not in {None, identifier}:
            raise DeploymentError("receipt ID does not match its storage location")
        if kind == "publication" and payload.get("schema_version", 1) not in {1, 2}:
            raise DeploymentError("unsupported future publication receipt schema")
        return payload

    def list(self, kind: str) -> list[dict[str, Any]]:
        if kind not in self.KINDS:
            raise DeploymentError("unknown receipt kind")
        directory = self.root / kind
        if not directory.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            try:
                records.append(self.read(kind, path.stem))
            except DeploymentError:
                # read() has quarantined the corrupt document; normal list use
                # remains safe and visibly reports it through quarantine().
                continue
        return records

    def list_all(self) -> dict[str, list[dict[str, Any]]]:
        return {kind: self.list(kind) for kind in self.KINDS}

    def quarantine(self) -> list[dict[str, Any]]:
        directory = self.root / "quarantine"
        if not directory.is_dir():
            return []
        return [
            {"filename": path.name, "size_bytes": path.stat().st_size, "path": str(path)}
            for path in sorted(directory.glob("*.json"))
        ]

    def find(self, identifier: str) -> tuple[str, dict[str, Any]]:
        for kind in self.KINDS:
            path = self._path(kind, identifier)
            if path.is_file():
                return kind, self.read(kind, identifier)
        raise DeploymentError("receipt was not found")

    def candidate_representation(self, identifier: str) -> dict[str, Any]:
        """Return a non-mutating compatibility view of a candidate receipt."""

        payload = self.read("candidate", identifier)
        schema = payload.get("schema_version", 1)
        if schema == 1:
            required = {"candidate_id", "state", "version", "candidate_commit", "artifact_path", "artifact_sha256"}
            if not required <= payload.keys():
                raise DeploymentError("malformed legacy schema-1 candidate receipt")
            return {
                **payload,
                "receipt_compatibility": "LEGACY_SINGLE_ARTIFACT",
                "publication_eligible": False,
                "missing_components": ["web", "desktop", "launcher", "bootstrap", "signed_release_set"],
            }
        if schema != 2:
            raise DeploymentError(f"unsupported future candidate receipt schema: {schema}")
        if payload.get("state") == "PLATFORM_ARTIFACTS_PENDING":
            required = {"candidate_id", "working_release_set", "candidate_commit", "candidate_tree", "bundle_path", "bundle_sha256"}
            if not required <= payload.keys():
                raise DeploymentError("malformed unsigned schema-2 candidate receipt")
            working = payload.get("working_release_set", {})
            components = working.get("components", []) if isinstance(working, dict) else []
            missing = sorted(
                str(component.get("kind"))
                for component in components
                if isinstance(component, dict) and component.get("disposition") == "PENDING"
            )
            return {**payload, "receipt_compatibility": "SCHEMA_2_UNSIGNED", "publication_eligible": False, "missing_components": missing}
        required = {
            "candidate_id", "state", "release_set", "release_set_manifest_path", "release_set_manifest_sha256",
            "release_set_signature", "candidate_commit", "candidate_tree", "bundle_path", "bundle_sha256",
        }
        if not required <= payload.keys():
            raise DeploymentError("malformed schema-2 candidate receipt")
        return {**payload, "receipt_compatibility": "SCHEMA_2", "publication_eligible": True, "missing_components": []}

    def discard_candidate(self, identifier: str) -> None:
        payload = self.read("candidate", identifier)
        if payload.get("state") != "CANDIDATE_VALIDATED":
            raise DeploymentError("only an unpromoted validated candidate can be discarded")
        for publication in self.list("publication"):
            if publication.get("candidate_id") == identifier:
                raise DeploymentError("candidate is referenced by a publication transaction and cannot be discarded")
        candidate_dir = self.root / "candidates" / identifier
        if candidate_dir.exists():
            tombstone = self.root / "discarded" / f"{identifier}-{utc_text().replace(':', '')}"
            tombstone.parent.mkdir(parents=True, exist_ok=True)
            os.replace(candidate_dir, tombstone)
        payload["state"] = "DISCARDED"
        payload["next_safe_action"] = "Prepare a new candidate when needed."
        self.write("candidate", identifier, payload)

    def export_text(self, identifier: str, destination: Path) -> Path:
        kind, receipt = self.find(identifier)
        if destination.exists():
            raise DeploymentError("refusing to overwrite an existing exported receipt")
        destination.parent.mkdir(parents=True, exist_ok=True)
        summary = [
            f"EOAT Atlas {kind} receipt",
            f"ID: {identifier}",
            f"State: {receipt.get('state', 'UNKNOWN')}",
            f"Next safe action: {receipt.get('next_safe_action', 'Review the receipt.')}",
            "",
            json.dumps(receipt, indent=2, sort_keys=True),
            "",
        ]
        destination.write_text("\n".join(summary), encoding="utf-8", newline="\n")
        return destination
