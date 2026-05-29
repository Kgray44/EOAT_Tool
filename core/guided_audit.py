from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from .audit_completion import CompletionPolicy, evaluate_completion, next_completion_actions


@dataclass(frozen=True)
class GuidedAuditStep:
    field: str
    section: str
    state: str
    reason: str
    action: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class GuidedAuditPlan:
    audit_id: str
    percent_complete: int
    can_finish: bool
    steps: tuple[GuidedAuditStep, ...]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "percent_complete": self.percent_complete,
            "can_finish": self.can_finish,
            "steps": [step.to_dict() for step in self.steps],
            "summary": self.summary,
        }


def build_guided_audit_plan(
    entry: Mapping[str, Any],
    *,
    limit: int = 8,
    policy: CompletionPolicy | None = None,
) -> GuidedAuditPlan:
    result = evaluate_completion(entry, policy)
    actions = next_completion_actions(entry, limit=limit, policy=policy)
    steps = tuple(
        GuidedAuditStep(
            field=action["field"],
            section=action["section"],
            state=action["state"],
            reason=action["reason"],
            action=_recommended_action(action["state"]),
        )
        for action in actions
    )
    if result.manual_completion_override:
        summary = "Manual completion override is applied; review the recorded ignored blank fields before handoff."
    elif result.can_finish:
        summary = "No guided completion gaps remain."
    elif steps:
        summary = f"{len(steps)} guided step(s) queued. Start with {steps[0].field}."
    else:
        summary = "Review findings before finalizing."
    return GuidedAuditPlan(
        audit_id=result.audit_id,
        percent_complete=result.percent_complete,
        can_finish=result.can_finish,
        steps=steps,
        summary=summary,
    )


def _recommended_action(state: str) -> str:
    if state == "missing":
        return "Fill the field or mark it Unknown / Not Checked if it cannot be verified."
    if state == "unknown_not_checked":
        return "Verify the field or leave the explicit Unknown / Not Checked state with a follow-up if needed."
    if state == "follow_up_needed":
        return "Create or review a follow-up action item."
    if state == "stale_conflict":
        return "Review the controlling answer and save to clear non-applicable stale data."
    return "Review this field."

