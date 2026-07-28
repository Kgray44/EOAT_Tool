"""Versioned fixed-capability diagnostic protocol and safe compatibility fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deployment.common import DeploymentError

DIAGNOSTIC_SCHEMA_VERSION = 1
REQUIRED_FACTS = {
    "target",
    "active_release",
    "schema_revision",
    "services",
    "health",
    "web",
    "deployment_lock",
    "disk",
    "helper",
    "writes_enabled",
    "transactions",
}


@dataclass(frozen=True)
class DiagnosticEnvelope:
    schema_version: int
    method: str
    facts: dict[str, Any]
    unavailable: tuple[str, ...]
    permission_denied: tuple[str, ...]


def validate_diagnostic_envelope(payload: object) -> DiagnosticEnvelope:
    if not isinstance(payload, dict):
        raise DeploymentError("structured diagnostic response must be a JSON object")
    if payload.get("schema_version") != DIAGNOSTIC_SCHEMA_VERSION:
        raise DeploymentError("structured diagnostic response has an unsupported schema version")
    if payload.get("operation") != "diagnose":
        raise DeploymentError("structured diagnostic response has an invalid operation")
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        raise DeploymentError("structured diagnostic response has no facts object")
    missing = REQUIRED_FACTS - facts.keys()
    if missing:
        raise DeploymentError("structured diagnostic response is missing facts: " + ", ".join(sorted(missing)))
    unavailable = payload.get("unavailable", [])
    denied = payload.get("permission_denied", [])
    if not all(isinstance(value, str) for value in unavailable) or not all(isinstance(value, str) for value in denied):
        raise DeploymentError("structured diagnostic response has invalid unavailable fields")
    return DiagnosticEnvelope(
        DIAGNOSTIC_SCHEMA_VERSION,
        "structured_helper",
        facts,
        tuple(unavailable),
        tuple(denied),
    )


def fallback_envelope(inspection: dict[str, Any], target_name: str) -> DiagnosticEnvelope:
    """Normalize the existing allowlisted SSH inspection without hiding fallback use."""

    current = inspection.get("current_deployment", {})
    identity = current.get("identity") if isinstance(current, dict) else None
    database = inspection.get("database", {})
    facts = {
        "target": {"name": target_name},
        "active_release": identity or {},
        "schema_revision": database.get("revision") if isinstance(database, dict) else None,
        "services": inspection.get("services", {}),
        "health": inspection.get("health", {}),
        "web": inspection.get("reverse_proxy", {}),
        "deployment_lock": inspection.get("deployment_lock", {}),
        "disk": inspection.get("disk_space_preflight", {}),
        "helper": {"status": "UNKNOWN", "reason": "compatibility fallback does not query helper capabilities"},
        "writes_enabled": None,
        "transactions": {
            "status": "UNKNOWN",
            "reason": "compatibility fallback has no structured transaction inventory",
        },
    }
    return DiagnosticEnvelope(
        DIAGNOSTIC_SCHEMA_VERSION,
        "allowlisted_ssh_fallback",
        facts,
        ("helper_capabilities", "writes_enabled", "transaction_inventory"),
        (),
    )


def diagnostic_request() -> dict[str, str]:
    """The only accepted structured diagnostic request; it carries no paths or commands."""

    return {"operation": "diagnose"}
