from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .audit.coach import (
    STATE_FOLLOW_UP_NEEDED,
    STATE_MISSING,
    STATE_STALE_CONFLICT,
    STATE_UNKNOWN_NOT_CHECKED,
    calculate_audit_coach_summary,
)
from .audit_field_registry import audit_sections


@dataclass(frozen=True)
class CompletionPolicy:
    name: str = "default"
    sections: Mapping[str, list[str] | tuple[str, ...]] = field(default_factory=audit_sections)
    require_no_actionable_fields: bool = True
    allow_manual_override: bool = True


@dataclass(frozen=True)
class CompletionResult:
    audit_id: str
    policy_name: str
    percent_complete: int
    can_finish: bool
    manual_completion_override: bool
    applicable_field_count: int
    verified_complete_count: int
    missing_required_fields: tuple[str, ...]
    missing_important_fields: tuple[str, ...]
    guided_fields: tuple[str, ...]
    blocker_count: int
    warning_count: int
    ignored_empty_fields_at_override: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ACTIONABLE_STATES = {
    STATE_MISSING,
    STATE_UNKNOWN_NOT_CHECKED,
    STATE_FOLLOW_UP_NEEDED,
    STATE_STALE_CONFLICT,
}


def evaluate_completion(
    entry: Mapping[str, Any],
    policy: CompletionPolicy | None = None,
    *,
    mode: str = "",
) -> CompletionResult:
    policy = policy or CompletionPolicy()
    summary = calculate_audit_coach_summary(entry, policy.sections, mode=mode)
    actionable = tuple(summary.guided_fields)
    blockers = tuple(finding for finding in summary.findings if finding.severity == "error")
    warnings = tuple(finding for finding in summary.findings if finding.severity == "warning")
    override = summary.manual_completion_override and policy.allow_manual_override
    can_finish = summary.can_finish
    if not policy.allow_manual_override and summary.manual_completion_override:
        can_finish = False
    if policy.require_no_actionable_fields and actionable and not override:
        can_finish = False
    return CompletionResult(
        audit_id=summary.audit_id,
        policy_name=policy.name,
        percent_complete=summary.percent_complete if override or policy.allow_manual_override else min(summary.percent_complete, 99),
        can_finish=can_finish,
        manual_completion_override=override,
        applicable_field_count=summary.applicable_field_count,
        verified_complete_count=summary.verified_complete_count,
        missing_required_fields=summary.missing_required_fields,
        missing_important_fields=summary.missing_important_fields,
        guided_fields=actionable,
        blocker_count=len(blockers),
        warning_count=len(warnings),
        ignored_empty_fields_at_override=summary.ignored_empty_fields_at_override,
    )


def next_completion_actions(entry: Mapping[str, Any], limit: int = 5, policy: CompletionPolicy | None = None) -> list[dict[str, str]]:
    policy = policy or CompletionPolicy()
    summary = calculate_audit_coach_summary(entry, policy.sections, mode=policy.name)
    actions: list[dict[str, str]] = []
    by_field = {status.field: status for section in summary.sections for status in section.fields}
    for field_name in summary.guided_fields[: max(0, limit)]:
        status = by_field.get(field_name)
        if status is None:
            continue
        actions.append(
            {
                "field": status.field,
                "section": status.section,
                "state": status.state,
                "reason": status.reason,
            }
        )
    return actions

