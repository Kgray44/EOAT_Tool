from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .audit.completion import (
    ACTIONABLE_STATES,
    AuditCompletionSummary,
    calculate_audit_completion,
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
    raw_percent_complete: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_completion(
    entry: Mapping[str, Any],
    policy: CompletionPolicy | None = None,
    *,
    mode: str = "",
) -> CompletionResult:
    policy = policy or CompletionPolicy()
    summary = calculate_audit_completion(entry, policy.sections, allow_manual_override=policy.allow_manual_override, mode=mode or policy.name)
    actionable = tuple(summary.guided_fields)
    can_finish = summary.can_finish
    if not policy.allow_manual_override and summary.manual_completion_override:
        can_finish = False
    if policy.require_no_actionable_fields and actionable and not summary.manual_completion_override_applied:
        can_finish = False
    warnings = tuple(finding for finding in summary.findings if finding.startswith("warning:"))
    errors = tuple(finding for finding in summary.findings if finding.startswith("error:"))
    return CompletionResult(
        audit_id=summary.audit_id,
        policy_name=policy.name,
        percent_complete=summary.percent_complete,
        raw_percent_complete=summary.raw_percent_complete,
        can_finish=can_finish,
        manual_completion_override=summary.manual_completion_override_applied,
        applicable_field_count=summary.applicable_field_count,
        verified_complete_count=summary.verified_complete_count,
        missing_required_fields=summary.missing_required_fields,
        missing_important_fields=summary.missing_important_fields,
        guided_fields=actionable,
        blocker_count=len(errors),
        warning_count=len(warnings),
        ignored_empty_fields_at_override=summary.ignored_empty_fields_at_override,
    )


def next_completion_actions(entry: Mapping[str, Any], limit: int = 5, policy: CompletionPolicy | None = None) -> list[dict[str, str]]:
    policy = policy or CompletionPolicy()
    summary: AuditCompletionSummary = calculate_audit_completion(entry, policy.sections, allow_manual_override=policy.allow_manual_override, mode=policy.name)
    actions: list[dict[str, str]] = []
    by_field = {status.field: status for section in summary.sections for status in section.fields}
    for field_name in summary.guided_fields[: max(0, limit)]:
        status = by_field.get(field_name)
        if status is None or status.state not in ACTIONABLE_STATES:
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


__all__ = ["CompletionPolicy", "CompletionResult", "evaluate_completion", "next_completion_actions"]
