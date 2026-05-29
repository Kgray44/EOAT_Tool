from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from core.audit.defaults import DEFAULT_AUDIT_DEFAULTS, merged_audit_defaults
from core.audit.schema import field_by_header
from core.audit_field_rules import field_applies, is_meaningful_value

ALLOWED_SCOPES = ("new_audit", "existing_empty_fields", "manual_only")
OVERWRITE_POLICIES = ("empty_only", "ask", "never")
CONDITION_OPERATORS = ("equals", "not_equals", "contains", "not_contains", "is_empty", "is_not_empty", "in_list")


@dataclass(frozen=True)
class AuditDefaultCondition:
    field: str
    operator: str = "equals"
    value: str = ""
    values: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["values"] = list(self.values)
        return data


@dataclass(frozen=True)
class AuditDefaultRule:
    id: str
    enabled: bool
    field: str
    value: str
    scope: str = "new_audit"
    overwrite_policy: str = "empty_only"
    conditions: tuple[AuditDefaultCondition, ...] = ()
    source: str = "user"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["conditions"] = [condition.to_dict() for condition in self.conditions]
        return data


@dataclass(frozen=True)
class AuditDefaultPreviewRow:
    rule_id: str
    field: str
    current_value: str
    default_value: str
    status: str
    reason: str


@dataclass(frozen=True)
class AuditDefaultApplyResult:
    values: dict[str, str]
    applied_rules: tuple[str, ...]
    skipped_rules: tuple[str, ...]
    preview_rows: tuple[AuditDefaultPreviewRow, ...]
    warnings: tuple[str, ...] = ()

    @property
    def changed_fields(self) -> tuple[str, ...]:
        return tuple(row.field for row in self.preview_rows if row.status == "applied")


ApplicableFields = Collection[str] | Callable[[str], bool] | None


def default_rules_from_audit_defaults(defaults: Mapping[str, Any] | None = None, *, source: str = "system_default") -> list[dict[str, Any]]:
    source_defaults = dict(DEFAULT_AUDIT_DEFAULTS if defaults is None else defaults)
    rules: list[dict[str, Any]] = []
    for field, value in source_defaults.items():
        rule = AuditDefaultRule(
            id=f"default_{_field_id(field)}",
            enabled=True,
            field=str(field),
            value="" if value is None else str(value),
            scope="new_audit",
            overwrite_policy="empty_only",
            source=source,
        )
        rules.append(rule.to_dict())
    return rules


def normalize_default_rules(raw_rules: Iterable[Mapping[str, Any]] | None) -> list[AuditDefaultRule]:
    rules: list[AuditDefaultRule] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_rules or []):
        if not isinstance(raw, Mapping):
            continue
        field = str(raw.get("field") or raw.get("set_field") or "").strip()
        if not field:
            continue
        rule_id = str(raw.get("id") or f"default_{_field_id(field)}_{index + 1}").strip()
        if rule_id in seen_ids:
            rule_id = f"{rule_id}_{index + 1}"
        scope = _choice(raw.get("scope"), ALLOWED_SCOPES, "new_audit")
        overwrite_policy = _choice(raw.get("overwrite_policy"), OVERWRITE_POLICIES, "empty_only")
        rules.append(
            AuditDefaultRule(
                id=rule_id,
                enabled=_bool(raw.get("enabled"), default=True),
                field=field,
                value="" if raw.get("value") is None else str(raw.get("value")),
                scope=scope,
                overwrite_policy=overwrite_policy,
                conditions=tuple(_normalize_conditions(raw.get("conditions"))),
                source=str(raw.get("source") or "user").strip(),
                note=str(raw.get("note") or "").strip(),
            )
        )
        seen_ids.add(rule_id)
    return rules


def audit_default_rules_from_config(config: Any | None) -> list[AuditDefaultRule]:
    raw_rules = getattr(config, "audit_default_rules", None)
    normalized = normalize_default_rules(raw_rules)
    if normalized:
        return normalized
    return normalize_default_rules(default_rules_from_audit_defaults(merged_audit_defaults(config)))


def apply_audit_default_rules(
    entry: Mapping[str, Any],
    rules: Iterable[Mapping[str, Any]] | Iterable[AuditDefaultRule] | None,
    *,
    scope: str = "new_audit",
    applicable_fields: ApplicableFields = None,
    dry_run: bool = False,
) -> AuditDefaultApplyResult:
    values = {str(key): "" if value is None else str(value) for key, value in entry.items()}
    applied: list[str] = []
    skipped: list[str] = []
    warnings: list[str] = []
    rows: list[AuditDefaultPreviewRow] = []
    for rule in _coerce_rules(rules):
        status = "skipped"
        reason = ""
        current = values.get(rule.field, "")
        if not rule.enabled:
            reason = "Rule is disabled."
            skipped.append(rule.id)
        elif rule.scope != scope:
            reason = f"Rule scope is {rule.scope}."
            skipped.append(rule.id)
        elif not _field_is_applicable(values, rule.field, applicable_fields):
            reason = "Field is hidden or not applicable."
            skipped.append(rule.id)
        elif not _conditions_match(values, rule.conditions):
            reason = "Conditions did not match."
            skipped.append(rule.id)
        elif str(current).strip() == str(rule.value).strip():
            status = "already_set"
            reason = "Field already has this value."
            skipped.append(rule.id)
        elif not _can_apply(current, rule.overwrite_policy):
            reason = _overwrite_reason(rule.overwrite_policy)
            if rule.overwrite_policy == "ask":
                warnings.append(f"{rule.field} already has a value; ask before applying {rule.id}.")
            skipped.append(rule.id)
        else:
            status = "would_apply" if dry_run else "applied"
            reason = "Default can be applied."
            if not dry_run:
                values[rule.field] = rule.value
                applied.append(rule.id)
        rows.append(
            AuditDefaultPreviewRow(
                rule_id=rule.id,
                field=rule.field,
                current_value=current,
                default_value=rule.value,
                status=status,
                reason=reason,
            )
        )
    return AuditDefaultApplyResult(
        values=values,
        applied_rules=tuple(applied),
        skipped_rules=tuple(skipped),
        preview_rows=tuple(rows),
        warnings=tuple(warnings),
    )


def preview_audit_default_rules(
    entry: Mapping[str, Any],
    rules: Iterable[Mapping[str, Any]] | Iterable[AuditDefaultRule] | None,
    *,
    scope: str = "new_audit",
    applicable_fields: ApplicableFields = None,
) -> AuditDefaultApplyResult:
    return apply_audit_default_rules(entry, rules, scope=scope, applicable_fields=applicable_fields, dry_run=True)


def _coerce_rules(rules: Iterable[Mapping[str, Any]] | Iterable[AuditDefaultRule] | None) -> list[AuditDefaultRule]:
    normalized: list[AuditDefaultRule] = []
    for raw_rule in rules or []:
        if isinstance(raw_rule, AuditDefaultRule):
            normalized.append(raw_rule)
        elif isinstance(raw_rule, Mapping):
            normalized.extend(normalize_default_rules([raw_rule]))
    return normalized


def _normalize_conditions(raw_conditions: Any) -> list[AuditDefaultCondition]:
    conditions: list[AuditDefaultCondition] = []
    if not isinstance(raw_conditions, list):
        return conditions
    for raw in raw_conditions:
        if not isinstance(raw, Mapping):
            continue
        field = str(raw.get("field") or raw.get("when_field") or "").strip()
        if not field:
            continue
        values = raw.get("values")
        conditions.append(
            AuditDefaultCondition(
                field=field,
                operator=_choice(raw.get("operator"), CONDITION_OPERATORS, "equals"),
                value="" if raw.get("value", raw.get("when_value")) is None else str(raw.get("value", raw.get("when_value"))),
                values=_string_tuple(values),
            )
        )
    return conditions


def _conditions_match(values: Mapping[str, str], conditions: tuple[AuditDefaultCondition, ...]) -> bool:
    return all(_condition_matches(values.get(condition.field, ""), condition) for condition in conditions)


def _condition_matches(current: Any, condition: AuditDefaultCondition) -> bool:
    current_text = str(current or "").strip()
    current_folded = current_text.casefold()
    expected = str(condition.value or "").strip()
    expected_folded = expected.casefold()
    if condition.operator == "equals":
        return current_folded == expected_folded
    if condition.operator == "not_equals":
        return current_folded != expected_folded
    if condition.operator == "contains":
        return bool(expected_folded) and expected_folded in current_folded
    if condition.operator == "not_contains":
        return bool(expected_folded) and expected_folded not in current_folded
    if condition.operator == "is_empty":
        return not current_text
    if condition.operator == "is_not_empty":
        return bool(current_text)
    if condition.operator == "in_list":
        choices = condition.values or _split_values(expected)
        return current_folded in {choice.casefold() for choice in choices}
    return False


def _can_apply(current: Any, overwrite_policy: str) -> bool:
    if overwrite_policy in {"empty_only", "never"}:
        return not is_meaningful_value(current)
    if overwrite_policy == "ask":
        return not is_meaningful_value(current)
    return False


def _overwrite_reason(overwrite_policy: str) -> str:
    if overwrite_policy == "ask":
        return "Field already has a value; confirmation is required."
    if overwrite_policy == "never":
        return "Rule never overwrites an existing value."
    return "Field already has a meaningful value."


def _field_is_applicable(values: Mapping[str, str], field: str, applicable_fields: ApplicableFields) -> bool:
    if applicable_fields is None:
        return field_applies(dict(values), field)
    if callable(applicable_fields):
        return bool(applicable_fields(field))
    return field in applicable_fields


def _field_id(field: str) -> str:
    try:
        return field_by_header(field).field_id
    except KeyError:
        text = str(field or "").strip().casefold()
        return "".join(character if character.isalnum() else "_" for character in text).strip("_") or "field"


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().casefold()
    return text if text in allowed else default


def _bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "on"}


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, tuple):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return _split_values(value)
    return ()


def _split_values(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value or "").split(",") if item.strip())


__all__ = [
    "ALLOWED_SCOPES",
    "CONDITION_OPERATORS",
    "OVERWRITE_POLICIES",
    "AuditDefaultApplyResult",
    "AuditDefaultCondition",
    "AuditDefaultPreviewRow",
    "AuditDefaultRule",
    "apply_audit_default_rules",
    "audit_default_rules_from_config",
    "default_rules_from_audit_defaults",
    "normalize_default_rules",
    "preview_audit_default_rules",
]
