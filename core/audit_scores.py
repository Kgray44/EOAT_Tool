from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from .audit_constants import (
    AUDIT_CONTEXT_BENCH,
    AUDIT_CONTEXT_COMPATIBILITY,
    AUDIT_CONTEXT_HISTORICAL,
    AUDIT_CONTEXT_INSTALLED,
)
from .audit_context import (
    EOAT_DOCUMENTATION_FIELDS,
    INSTALLATION_ONLY_FIELDS,
    INSTALLATION_READINESS_FIELDS,
    INSTALLED_CELL_VALIDATION_FIELDS,
    infer_audit_context,
)
from .audit_field_rules import field_applies, is_meaningful_value, is_na_value


@dataclass(frozen=True)
class FieldScoreStatus:
    field: str
    status: str
    counted: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScoreBreakdown:
    label: str
    score: int | str
    complete_count: int
    counted_count: int
    missing_fields: tuple[str, ...] = ()
    unknown_fields: tuple[str, ...] = ()
    not_applicable_fields: tuple[str, ...] = ()
    follow_up_fields: tuple[str, ...] = ()
    not_observable_fields: tuple[str, ...] = ()
    field_statuses: tuple[FieldScoreStatus, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditSplitScores:
    audit_context: str
    eoat_documentation: ScoreBreakdown
    installation_readiness: ScoreBreakdown
    installed_cell_validation: ScoreBreakdown

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_split_scores(entry: Mapping[str, Any]) -> AuditSplitScores:
    row = dict(entry)
    context = infer_audit_context(row)
    documentation = _score_fields(
        "EOAT Documentation Score",
        row,
        EOAT_DOCUMENTATION_FIELDS,
        context=context,
    )
    readiness = _score_fields(
        "Installation Readiness Score",
        row,
        INSTALLATION_READINESS_FIELDS,
        context=context,
    )
    if context == AUDIT_CONTEXT_INSTALLED:
        installed_validation = _score_fields(
            "Installed-Cell Validation Score",
            row,
            INSTALLED_CELL_VALIDATION_FIELDS,
            context=context,
        )
    elif context == AUDIT_CONTEXT_COMPATIBILITY:
        installed_validation = _pending_score(
            "Installed-Cell Validation Score",
            "Pending / Not physically verified",
            INSTALLED_CELL_VALIDATION_FIELDS,
        )
    elif context == AUDIT_CONTEXT_BENCH:
        installed_validation = _pending_score(
            "Installed-Cell Validation Score",
            "Not Installed / Pending",
            INSTALLED_CELL_VALIDATION_FIELDS,
        )
    elif context == AUDIT_CONTEXT_HISTORICAL:
        installed_validation = _pending_score(
            "Installed-Cell Validation Score",
            "Historical/imported - needs verification",
            INSTALLED_CELL_VALIDATION_FIELDS,
        )
    else:
        installed_validation = _pending_score(
            "Installed-Cell Validation Score",
            "Needs review",
            INSTALLED_CELL_VALIDATION_FIELDS,
        )
    return AuditSplitScores(
        audit_context=context,
        eoat_documentation=documentation,
        installation_readiness=readiness,
        installed_cell_validation=installed_validation,
    )


def _score_fields(
    label: str,
    entry: Mapping[str, Any],
    fields: Iterable[str],
    *,
    context: str,
) -> ScoreBreakdown:
    statuses: list[FieldScoreStatus] = []
    complete = 0
    counted = 0
    missing: list[str] = []
    unknown: list[str] = []
    not_applicable: list[str] = []
    follow_up: list[str] = []
    not_observable: list[str] = []
    row = dict(entry)
    for field in fields:
        if context in {AUDIT_CONTEXT_BENCH, AUDIT_CONTEXT_COMPATIBILITY} and field in INSTALLATION_ONLY_FIELDS:
            not_observable.append(field)
            statuses.append(
                FieldScoreStatus(
                    field,
                    "Not Observable" if context == AUDIT_CONTEXT_BENCH else "Follow-up Required",
                    counted=False,
                    reason="Machine-specific installation validation is not observable in this audit context.",
                )
            )
            continue
        value = row.get(field)
        if not field_applies(row, field):
            not_applicable.append(field)
            statuses.append(
                FieldScoreStatus(field, "Not Applicable", counted=False, reason="Field does not apply to this EOAT.")
            )
            continue
        counted += 1
        text = _text(value)
        folded = text.casefold()
        if _is_unknown(text):
            unknown.append(field)
            statuses.append(FieldScoreStatus(field, "Unknown", counted=True, reason="Field should be checked."))
        elif _needs_follow_up(text):
            follow_up.append(field)
            statuses.append(
                FieldScoreStatus(field, "Follow-up Required", counted=True, reason="Field is marked for follow-up.")
            )
        elif not text or is_na_value(text):
            missing.append(field)
            statuses.append(FieldScoreStatus(field, "Unknown", counted=True, reason="Applicable field is missing."))
        elif is_meaningful_value(text):
            complete += 1
            statuses.append(FieldScoreStatus(field, "Pass", counted=True, reason="Field has documented evidence."))
        else:
            missing.append(field)
            statuses.append(FieldScoreStatus(field, "Unknown", counted=True, reason="Field is not documented."))
    score = round((complete / counted) * 100) if counted else 100
    return ScoreBreakdown(
        label=label,
        score=score,
        complete_count=complete,
        counted_count=counted,
        missing_fields=tuple(missing),
        unknown_fields=tuple(unknown),
        not_applicable_fields=tuple(not_applicable),
        follow_up_fields=tuple(follow_up),
        not_observable_fields=tuple(not_observable),
        field_statuses=tuple(statuses),
    )


def _pending_score(label: str, message: str, fields: Iterable[str]) -> ScoreBreakdown:
    field_tuple = tuple(fields)
    return ScoreBreakdown(
        label=label,
        score=message,
        complete_count=0,
        counted_count=0,
        follow_up_fields=field_tuple,
        not_observable_fields=field_tuple,
        field_statuses=tuple(
            FieldScoreStatus(
                field,
                "Follow-up Required" if message.startswith("Pending") else "Not Observable",
                counted=False,
                reason=message,
            )
            for field in field_tuple
        ),
    )


def _is_unknown(value: str) -> bool:
    folded = value.casefold()
    return not value or folded in {"unknown / not checked", "unknown", "not checked"} or folded.startswith("unknown")


def _needs_follow_up(value: str) -> bool:
    folded = value.casefold()
    return "follow-up" in folded or "follow up" in folded or "needs review" in folded


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


__all__ = [
    "AuditSplitScores",
    "FieldScoreStatus",
    "ScoreBreakdown",
    "calculate_split_scores",
]
