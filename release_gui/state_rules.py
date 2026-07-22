"""One auditable place for every sensitive-action availability decision."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolState:
    busy: bool = False
    repository_ready: bool = False
    validation_passed: bool = False
    config_loaded: bool = False
    server_inspected: bool = False
    release_verified: bool = False
    rehearsal_passed: bool = False
    rehearsal_matches_selection: bool = False
    migration_status: str = "UNKNOWN"
    host_key_trusted: bool = False
    helper_available: bool = False
    blockers: bool = True
    deployment_state: str = "UNKNOWN"


@dataclass(frozen=True)
class ActionAvailability:
    enabled: bool
    reason: str


def _blocked(state: ToolState) -> bool:
    return state.busy or state.blockers


def publish_rule(state: ToolState) -> ActionAvailability:
    ok = state.repository_ready and state.validation_passed and not _blocked(state)
    return ActionAvailability(ok, "Validation and a clean, current repository are required" if not ok else "Ready")


def stage_rule(state: ToolState) -> ActionAvailability:
    ok = all(
        (
            state.config_loaded,
            state.server_inspected,
            state.release_verified,
            state.rehearsal_passed,
            state.rehearsal_matches_selection,
            state.host_key_trusted,
            state.helper_available,
            state.migration_status == "NOT_REQUIRED",
        )
    ) and not _blocked(state)
    return ActionAvailability(
        ok, "Stage requires a matching successful rehearsal and NOT_REQUIRED migration" if not ok else "Ready"
    )


def activate_rule(state: ToolState) -> ActionAvailability:
    ok = (
        state.deployment_state == "STAGED_VALIDATED"
        and state.config_loaded
        and state.host_key_trusted
        and not _blocked(state)
    )
    return ActionAvailability(ok, "Activation requires backend state STAGED_VALIDATED" if not ok else "Ready")


def abort_rule(state: ToolState) -> ActionAvailability:
    ok = state.deployment_state in {"STARTED", "STAGING", "STAGED", "STAGED_VALIDATED"} and not _blocked(state)
    return ActionAvailability(ok, "Abort is only available before activation" if not ok else "Ready")


def recover_rule(state: ToolState) -> ActionAvailability:
    ok = (
        state.config_loaded
        and state.host_key_trusted
        and state.deployment_state not in {"", "UNKNOWN"}
        and not state.busy
    )
    return ActionAvailability(ok, "Enter a backend deployment ID and inspect its state" if not ok else "Ready")


def rollback_rule(state: ToolState) -> ActionAvailability:
    ok = state.deployment_state in {"ACTIVATED", "COMPLETED", "FAILED_HEALTH"} and not _blocked(state)
    return ActionAvailability(
        ok, "Rollback is available only when the backend permits a post-activation recovery" if not ok else "Ready"
    )
