"""Typed, raw-response preserving values exposed to the GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OperationResult:
    operation: str
    status: str
    summary: str
    raw: dict[str, Any] = field(default_factory=dict)
    receipt_path: str | None = None

    @property
    def warnings(self) -> list[str]:
        return [str(item) for item in self.raw.get("warnings", [])]

    @property
    def blockers(self) -> list[str]:
        return [str(item) for item in self.raw.get("blocking_failures", [])]


@dataclass(frozen=True)
class RepositoryStatus:
    branch: str
    commit: str
    version: str | None
    clean: bool
    ready: bool
    raw: dict[str, Any]


@dataclass(frozen=True)
class DeploymentReadiness:
    readiness: str
    migration_status: str = "UNKNOWN"
    host_key_trusted: bool = False
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


def result_from_payload(operation: str, payload: dict[str, Any], *, summary: str | None = None) -> OperationResult:
    status = str(
        payload.get("final_status")
        or payload.get("overall_readiness")
        or payload.get("readiness")
        or payload.get("state")
        or payload.get("verification")
        or "UNKNOWN"
    )
    return OperationResult(
        operation=operation,
        status=status,
        summary=summary or status.replace("_", " ").title(),
        raw=payload,
        receipt_path=str(payload["receipt_path"]) if payload.get("receipt_path") else None,
    )


def readiness_from_payload(payload: dict[str, Any]) -> DeploymentReadiness:
    inspection = payload.get("server_inspection", payload)
    if not isinstance(inspection, dict):
        inspection = {}
    migration = inspection.get("migration_requirement", {})
    if not isinstance(migration, dict):
        migration = {}
    host_key = inspection.get("ssh_host_key", {})
    if not isinstance(host_key, dict):
        host_key = {}
    return DeploymentReadiness(
        readiness=str(payload.get("overall_readiness") or inspection.get("readiness") or "UNKNOWN"),
        migration_status=str(migration.get("status") or "UNKNOWN"),
        host_key_trusted=bool(host_key.get("known")),
        blockers=tuple(str(item) for item in inspection.get("blocking_failures", [])),
        warnings=tuple(str(item) for item in inspection.get("warnings", [])),
        raw=payload,
    )
