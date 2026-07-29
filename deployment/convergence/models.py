"""Typed state models for the converged release and deployment workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    NOT_RUN = "NOT_RUN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class CandidateState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PREFLIGHT_COMPLETE = "PREFLIGHT_COMPLETE"
    CANDIDATE_PREPARED = "CANDIDATE_PREPARED"
    CANDIDATE_VALIDATED = "CANDIDATE_VALIDATED"
    FAILED = "FAILED"
    DISCARDED = "DISCARDED"


class PublicationState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PREFLIGHT_COMPLETE = "PREFLIGHT_COMPLETE"
    CANDIDATE_VALIDATED = "CANDIDATE_VALIDATED"
    RELEASE_COMMIT_CREATED = "RELEASE_COMMIT_CREATED"
    TAG_CREATED = "TAG_CREATED"
    BRANCH_PUSHED = "BRANCH_PUSHED"
    TAG_PUSHED = "TAG_PUSHED"
    GITHUB_RELEASE_CREATED = "GITHUB_RELEASE_CREATED"
    PRIMARY_ASSETS_UPLOADED = "PRIMARY_ASSETS_UPLOADED"
    COMPONENT_ASSETS_VERIFIED = "COMPONENT_ASSETS_VERIFIED"
    RECEIPT_ATTACHED = "RECEIPT_ATTACHED"
    PUBLICATION_COMPLETE = "PUBLICATION_COMPLETE"
    FAILED_RECOVERABLE = "FAILED_RECOVERABLE"
    FAILED_MANUAL_INTERVENTION = "FAILED_MANUAL_INTERVENTION"


class DeploymentMode(str, Enum):
    NO_MIGRATION_REQUIRED = "NO_MIGRATION_REQUIRED"
    MIGRATION_REQUIRED = "MIGRATION_REQUIRED"
    MIGRATION_STATE_UNKNOWN = "MIGRATION_STATE_UNKNOWN"
    MIGRATION_BLOCKED = "MIGRATION_BLOCKED"
    ROLLBACK_OR_RECOVERY_REQUIRED = "ROLLBACK_OR_RECOVERY_REQUIRED"


class DeploymentState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PREFLIGHT_COMPLETE = "PREFLIGHT_COMPLETE"
    RELEASE_VERIFIED = "RELEASE_VERIFIED"
    LOCK_ACQUIRED = "LOCK_ACQUIRED"
    BACKUP_STARTED = "BACKUP_STARTED"
    BACKUP_CREATED = "BACKUP_CREATED"
    BACKUP_VERIFIED = "BACKUP_VERIFIED"
    ARTIFACT_TRANSFERRED = "ARTIFACT_TRANSFERRED"
    ARTIFACT_VERIFIED = "ARTIFACT_VERIFIED"
    RELEASE_EXTRACTED = "RELEASE_EXTRACTED"
    RUNTIME_READY = "RUNTIME_READY"
    STAGED_VALIDATED = "STAGED_VALIDATED"
    MIGRATION_APPROVED = "MIGRATION_APPROVED"
    MIGRATION_STARTED = "MIGRATION_STARTED"
    MIGRATION_COMPLETE = "MIGRATION_COMPLETE"
    MIGRATION_VERIFIED = "MIGRATION_VERIFIED"
    ACTIVATION_READY = "ACTIVATION_READY"
    ACTIVATION_STARTED = "ACTIVATION_STARTED"
    API_ACTIVATED = "API_ACTIVATED"
    WEB_ACTIVATED = "WEB_ACTIVATED"
    SERVICES_RESTARTED = "SERVICES_RESTARTED"
    HEALTH_VALIDATED = "HEALTH_VALIDATED"
    ACCEPTANCE_PASSED = "ACCEPTANCE_PASSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    ROLLBACK_STARTED = "ROLLBACK_STARTED"
    APPLICATION_ROLLED_BACK = "APPLICATION_ROLLED_BACK"
    DATABASE_RESTORE_REQUIRED = "DATABASE_RESTORE_REQUIRED"
    DATABASE_RESTORE_STARTED = "DATABASE_RESTORE_STARTED"
    DATABASE_RESTORED = "DATABASE_RESTORED"
    RECOVERY_VALIDATED = "RECOVERY_VALIDATED"
    FAILED_RECOVERABLE = "FAILED_RECOVERABLE"
    FAILED_MANUAL_INTERVENTION = "FAILED_MANUAL_INTERVENTION"


class CoordinatedDeploymentState(str, Enum):
    """Durable Phase 3A states for one API/web activation transaction.

    This deliberately does not reuse the older helper-facing DeploymentState:
    the latter describes privileged production operations, while this model is
    also used by the disposable, black-box activation harness.
    """

    NOT_STARTED = "NOT_STARTED"
    PREFLIGHT_COMPLETE = "PREFLIGHT_COMPLETE"
    INPUT_VERIFIED = "INPUT_VERIFIED"
    BACKUP_REQUIRED = "BACKUP_REQUIRED"
    BACKUP_VERIFIED = "BACKUP_VERIFIED"
    MIGRATION_READY = "MIGRATION_READY"
    SERVER_STAGED = "SERVER_STAGED"
    WEB_STAGED = "WEB_STAGED"
    STAGED_COMPLETE = "STAGED_COMPLETE"
    ACTIVATING = "ACTIVATING"
    API_ACTIVE_PENDING_HEALTH = "API_ACTIVE_PENDING_HEALTH"
    WEB_ACTIVE_PENDING_HEALTH = "WEB_ACTIVE_PENDING_HEALTH"
    LIVE_ACCEPTANCE_RUNNING = "LIVE_ACCEPTANCE_RUNNING"
    ACTIVE_CONFIRMED = "ACTIVE_CONFIRMED"
    FAILED_RECOVERABLE = "FAILED_RECOVERABLE"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    DATABASE_RECOVERY_REQUIRED = "DATABASE_RECOVERY_REQUIRED"
    FAILED_MANUAL_INTERVENTION = "FAILED_MANUAL_INTERVENTION"


@dataclass(frozen=True)
class Diagnostic:
    name: str
    status: Status
    detail: str
    recommended_action: str | None = None
    required: bool = True
    scope: str = "candidate"


@dataclass(frozen=True)
class CommandOutcome:
    operation: str
    command: tuple[str, ...]
    exit_code: int
    started_at_utc: str
    ended_at_utc: str
    duration_seconds: float
    stdout: str
    stderr: str
    category: str
    recommended_action: str | None = None
    retryable: bool = False
    mutation_stage: str = "read_only"
    local_state_changed: bool = False
    remote_state_may_have_changed: bool = False


@dataclass(frozen=True)
class OperationResult:
    status: Status
    summary: str
    next_safe_action: str
    diagnostics: tuple[Diagnostic, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateRecord:
    schema_version: int
    candidate_id: str
    state: CandidateState
    repository: str
    branch: str
    base_commit: str
    candidate_commit: str | None
    candidate_tree: str | None
    version: str
    tag: str
    artifact_filename: str | None
    artifact_sha256: str | None
    manifest_sha256: str | None
    web_manifest_sha256: str | None
    artifact_path: str | None
    bundle_path: str | None
    deterministic_rebuild: Status
    checks: tuple[dict[str, Any], ...]
    next_safe_action: str
    failure: str | None = None


@dataclass(frozen=True)
class PublicationRecord:
    schema_version: int
    publication_id: str
    candidate_id: str
    state: PublicationState
    version: str
    tag: str
    candidate_commit: str
    candidate_tree: str
    artifact_sha256: str
    manifest_sha256: str
    completed_steps: tuple[str, ...]
    next_safe_action: str
    retryable: bool = True
    failure: str | None = None


@dataclass(frozen=True)
class DeploymentPlan:
    schema_version: int
    plan_id: str
    mode: DeploymentMode
    selected_version: str
    selected_commit: str
    release_id: str | None
    build_id: str | None
    source_schema: str | None
    target_schema: str | None
    target_name: str | None
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    expected_mutations: tuple[str, ...]
    rollback_model: str
    next_safe_action: str


@dataclass(frozen=True)
class DeploymentTransaction:
    schema_version: int
    transaction_id: str
    plan_id: str
    state: DeploymentState
    selected_version: str
    selected_commit: str
    release_id: str | None
    build_id: str | None
    artifact_sha256: str | None
    source_schema: str | None
    target_schema: str | None
    migration_mode: DeploymentMode
    target_name: str | None
    helper_version: str | None
    helper_capabilities: tuple[str, ...]
    completed_states: tuple[str, ...]
    backup_identity: dict[str, Any] | None
    failure_category: str | None
    failure_detail: str | None
    rollback_state: str | None
    database_recovery_state: str | None
    next_safe_action: str
    retryable: bool
    mutation_flags: dict[str, bool]
    verification: dict[str, Any]


def next_action_for(state: CandidateState | PublicationState | DeploymentMode | DeploymentState) -> str:
    actions = {
        CandidateState.NOT_STARTED: "Run candidate rehearsal.",
        CandidateState.PREFLIGHT_COMPLETE: "Prepare the candidate in an isolated worktree.",
        CandidateState.CANDIDATE_PREPARED: "Run deterministic candidate validation.",
        CandidateState.CANDIDATE_VALIDATED: "Review immutable hashes, then explicitly confirm publication.",
        CandidateState.FAILED: "Resolve the recorded failure and start a new candidate.",
        CandidateState.DISCARDED: "Prepare a new candidate when needed.",
        PublicationState.NOT_STARTED: "Confirm exact candidate publication.",
        PublicationState.PUBLICATION_COMPLETE: "Select the published release and run read-only target inspection.",
        PublicationState.FAILED_RECOVERABLE: "Resume after reconciling matching local and remote state.",
        PublicationState.FAILED_MANUAL_INTERVENTION: "Inspect the receipt and reconcile the recorded conflicting remote state.",
        DeploymentMode.NO_MIGRATION_REQUIRED: "Stage the selected verified release after explicit confirmation.",
        DeploymentMode.MIGRATION_REQUIRED: "Verify backup capability, then explicitly approve the migration transaction.",
        DeploymentMode.MIGRATION_STATE_UNKNOWN: "Run read-only target inspection to determine the schema state.",
        DeploymentMode.MIGRATION_BLOCKED: "Resolve the missing helper or migration capability before staging.",
        DeploymentMode.ROLLBACK_OR_RECOVERY_REQUIRED: "Inspect the active transaction; recover or roll back the application explicitly.",
        DeploymentState.NOT_STARTED: "Run deployment preflight.",
        DeploymentState.PREFLIGHT_COMPLETE: "Verify the release and acquire the deployment lock.",
        DeploymentState.RELEASE_VERIFIED: "Stage the verified release.",
        DeploymentState.STAGED_VALIDATED: "Activate only after explicit confirmation.",
        DeploymentState.MIGRATION_APPROVED: "Execute the approved migration through the narrow helper.",
        DeploymentState.MIGRATION_COMPLETE: "Verify the target schema before activation.",
        DeploymentState.MIGRATION_VERIFIED: "Activate the staged release after explicit confirmation.",
        DeploymentState.ACTIVATION_READY: "Activate the staged release after explicit confirmation.",
        DeploymentState.ACCEPTANCE_PASSED: "Record completion and retain the receipt.",
        DeploymentState.COMPLETED: "Monitor the deployed release; no transaction action is required.",
        DeploymentState.ABORTED: "Review the receipt before starting a new transaction.",
        DeploymentState.APPLICATION_ROLLED_BACK: "Verify application rollback; database state was not restored.",
        DeploymentState.DATABASE_RESTORE_REQUIRED: "Begin verified database recovery only with explicit authorization.",
        DeploymentState.DATABASE_RESTORED: "Verify restored schema and application compatibility.",
        DeploymentState.RECOVERY_VALIDATED: "Close the recovery transaction after receipt export.",
        DeploymentState.FAILED_RECOVERABLE: "Use the recorded retry or recovery action.",
        DeploymentState.FAILED_MANUAL_INTERVENTION: "Escalate with the redacted receipt; automatic continuation is unsafe.",
    }
    return actions.get(state, "Continue only after reviewing the recorded state.")


_PUBLICATION_ORDER = (
    PublicationState.CANDIDATE_VALIDATED,
    PublicationState.RELEASE_COMMIT_CREATED,
    PublicationState.TAG_CREATED,
    PublicationState.BRANCH_PUSHED,
    PublicationState.TAG_PUSHED,
    PublicationState.GITHUB_RELEASE_CREATED,
    PublicationState.PRIMARY_ASSETS_UPLOADED,
    PublicationState.COMPONENT_ASSETS_VERIFIED,
    PublicationState.RECEIPT_ATTACHED,
    PublicationState.PUBLICATION_COMPLETE,
)


def require_transition(current: PublicationState, target: PublicationState) -> None:
    if current in {PublicationState.FAILED_RECOVERABLE, PublicationState.FAILED_MANUAL_INTERVENTION}:
        return
    if target in {PublicationState.FAILED_RECOVERABLE, PublicationState.FAILED_MANUAL_INTERVENTION}:
        return
    if _PUBLICATION_ORDER.index(target) != _PUBLICATION_ORDER.index(current) + 1:
        raise ValueError(f"invalid publication transition: {current.value} -> {target.value}")


def validate_deployment_transition(current: DeploymentState, target: DeploymentState, mode: DeploymentMode) -> None:
    recovery_edges = {
        (DeploymentState.ROLLBACK_STARTED, DeploymentState.APPLICATION_ROLLED_BACK),
        (DeploymentState.APPLICATION_ROLLED_BACK, DeploymentState.DATABASE_RESTORE_REQUIRED),
        (DeploymentState.DATABASE_RESTORE_REQUIRED, DeploymentState.DATABASE_RESTORE_STARTED),
        (DeploymentState.DATABASE_RESTORE_STARTED, DeploymentState.DATABASE_RESTORED),
        (DeploymentState.DATABASE_RESTORED, DeploymentState.RECOVERY_VALIDATED),
        (DeploymentState.RECOVERY_VALIDATED, DeploymentState.COMPLETED),
        (DeploymentState.FAILED_RECOVERABLE, DeploymentState.ROLLBACK_STARTED),
        (DeploymentState.FAILED_RECOVERABLE, DeploymentState.DATABASE_RESTORE_REQUIRED),
    }
    if (current, target) in recovery_edges:
        return
    if target in {
        DeploymentState.FAILED_RECOVERABLE,
        DeploymentState.FAILED_MANUAL_INTERVENTION,
        DeploymentState.ROLLBACK_STARTED,
        DeploymentState.ABORTED,
        DeploymentState.DATABASE_RESTORE_REQUIRED,
    }:
        return
    no_migration = (
        DeploymentState.NOT_STARTED,
        DeploymentState.PREFLIGHT_COMPLETE,
        DeploymentState.RELEASE_VERIFIED,
        DeploymentState.LOCK_ACQUIRED,
        DeploymentState.BACKUP_CREATED,
        DeploymentState.ARTIFACT_TRANSFERRED,
        DeploymentState.ARTIFACT_VERIFIED,
        DeploymentState.RELEASE_EXTRACTED,
        DeploymentState.RUNTIME_READY,
        DeploymentState.STAGED_VALIDATED,
        DeploymentState.ACTIVATION_READY,
        DeploymentState.ACTIVATION_STARTED,
        DeploymentState.API_ACTIVATED,
        DeploymentState.WEB_ACTIVATED,
        DeploymentState.SERVICES_RESTARTED,
        DeploymentState.HEALTH_VALIDATED,
        DeploymentState.ACCEPTANCE_PASSED,
        DeploymentState.COMPLETED,
    )
    migration = (
        DeploymentState.NOT_STARTED,
        DeploymentState.PREFLIGHT_COMPLETE,
        DeploymentState.RELEASE_VERIFIED,
        DeploymentState.LOCK_ACQUIRED,
        DeploymentState.BACKUP_STARTED,
        DeploymentState.BACKUP_CREATED,
        DeploymentState.BACKUP_VERIFIED,
        DeploymentState.ARTIFACT_TRANSFERRED,
        DeploymentState.ARTIFACT_VERIFIED,
        DeploymentState.RELEASE_EXTRACTED,
        DeploymentState.RUNTIME_READY,
        DeploymentState.STAGED_VALIDATED,
        DeploymentState.MIGRATION_APPROVED,
        DeploymentState.MIGRATION_STARTED,
        DeploymentState.MIGRATION_COMPLETE,
        DeploymentState.MIGRATION_VERIFIED,
        DeploymentState.ACTIVATION_READY,
        DeploymentState.ACTIVATION_STARTED,
        DeploymentState.API_ACTIVATED,
        DeploymentState.WEB_ACTIVATED,
        DeploymentState.SERVICES_RESTARTED,
        DeploymentState.HEALTH_VALIDATED,
        DeploymentState.ACCEPTANCE_PASSED,
        DeploymentState.COMPLETED,
    )
    order = migration if mode is DeploymentMode.MIGRATION_REQUIRED else no_migration
    if current not in order or target not in order or order.index(target) != order.index(current) + 1:
        raise ValueError(f"invalid deployment transition: {current.value} -> {target.value}")
