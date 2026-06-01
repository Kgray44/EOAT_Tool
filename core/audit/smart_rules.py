from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from core.audit.defaults import merged_connection_defaults
from core.audit_entries import PART_PRESENT_SENSOR_DEFAULTS
from core.audit_field_rules import field_applies

UNSET_VALUES = {"", "n/a", "na", "not applicable", "unknown / not checked", "unknown", "not checked"}
SMART_RULE_OPERATORS = {"equals", "not_equals", "contains", "not_contains", "is_empty", "is_not_empty", "in_list"}
ApplicableFields = Collection[str] | Callable[[str], bool] | None


@dataclass(frozen=True)
class SmartDefaultRule:
    id: str
    when_field: str
    operator: str
    when_value: str
    set_field: str
    set_value: str
    enabled: bool = True
    source: str = "settings"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SmartDefaultResult:
    values: dict[str, str]
    applied_rules: tuple[str, ...]
    skipped_rules: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def default_smart_default_rules() -> list[dict[str, Any]]:
    rules = [
        SmartDefaultRule(
            id="part_present_sensor_type",
            when_field="Part-Present Detection Present?",
            operator="equals",
            when_value="Yes",
            set_field="Sensor Type",
            set_value=PART_PRESENT_SENSOR_DEFAULTS["Sensor Type"],
            source="default_part_present",
        ),
        SmartDefaultRule(
            id="part_present_sensor_model",
            when_field="Part-Present Detection Present?",
            operator="equals",
            when_value="Yes",
            set_field="Sensor Brand/Model",
            set_value=PART_PRESENT_SENSOR_DEFAULTS["Sensor Brand/Model"],
            source="default_part_present",
        ),
        SmartDefaultRule(
            id="connection_default_ati",
            when_field="Connection Type",
            operator="contains",
            when_value="ATI",
            set_field="Changeover Difficulty",
            set_value="Low",
            source="default_connection",
        ),
        SmartDefaultRule(
            id="connection_default_dovetail",
            when_field="Connection Type",
            operator="contains",
            when_value="DoveTail",
            set_field="Changeover Difficulty",
            set_value="Medium",
            source="default_connection",
        ),
    ]
    return [rule.to_dict() for rule in rules]


def normalize_smart_default_rules(raw_rules: Iterable[Mapping[str, Any]] | None) -> list[SmartDefaultRule]:
    rules: list[SmartDefaultRule] = []
    for raw in raw_rules or []:
        if not isinstance(raw, Mapping):
            continue
        rule = SmartDefaultRule(
            id=str(raw.get("id") or "").strip(),
            enabled=_bool(raw.get("enabled"), default=True),
            when_field=str(raw.get("when_field") or "").strip(),
            operator=_normalize_operator(raw.get("operator")),
            when_value=str(raw.get("when_value") or "").strip(),
            set_field=str(raw.get("set_field") or "").strip(),
            set_value=str(raw.get("set_value") or "").strip(),
            source=str(raw.get("source") or "settings").strip(),
        )
        if rule.id and rule.when_field and rule.set_field:
            rules.append(rule)
    return rules


def apply_smart_default_rules(
    entry: Mapping[str, Any],
    rules: Iterable[Mapping[str, Any]] | Iterable[SmartDefaultRule] | None,
    *,
    only_unset: bool = True,
    applicable_fields: ApplicableFields = None,
) -> SmartDefaultResult:
    values = {str(key): "" if value is None else str(value) for key, value in entry.items()}
    applied: list[str] = []
    skipped: list[str] = []
    warnings: list[str] = []
    normalized: list[SmartDefaultRule] = []
    for raw_rule in rules or []:
        if isinstance(raw_rule, SmartDefaultRule):
            normalized.append(raw_rule)
        elif isinstance(raw_rule, Mapping):
            normalized.extend(normalize_smart_default_rules([raw_rule]))
    matching_by_field: dict[str, dict[str, list[str]]] = {}
    for rule in normalized:
        if not rule.enabled:
            continue
        if not _field_is_applicable(values, rule.set_field, applicable_fields):
            continue
        if not _matches(values.get(rule.when_field, ""), rule.operator, rule.when_value):
            continue
        matching_by_field.setdefault(rule.set_field, {}).setdefault(rule.set_value, []).append(rule.id)
    for field, value_rules in matching_by_field.items():
        if len(value_rules) > 1:
            rule_ids = [rule_id for ids in value_rules.values() for rule_id in ids]
            warnings.append(f"{field} has conflicting smart defaults from {', '.join(rule_ids)}.")
    proposed_by_field: dict[str, tuple[str, str]] = {}
    for rule in normalized:
        if not rule.enabled:
            skipped.append(rule.id)
            continue
        if not _field_is_applicable(values, rule.set_field, applicable_fields):
            skipped.append(rule.id)
            continue
        if not _matches(values.get(rule.when_field, ""), rule.operator, rule.when_value):
            skipped.append(rule.id)
            continue
        existing = proposed_by_field.get(rule.set_field)
        if existing and existing[1] != rule.set_value:
            warnings.append(f"{rule.set_field} has conflicting smart defaults from {existing[0]} and {rule.id}.")
            skipped.append(rule.id)
            continue
        current = values.get(rule.set_field, "")
        if only_unset and not _is_unset(current):
            skipped.append(rule.id)
            continue
        proposed_by_field[rule.set_field] = (rule.id, rule.set_value)
        values[rule.set_field] = rule.set_value
        applied.append(rule.id)
    return SmartDefaultResult(
        values=values, applied_rules=tuple(applied), skipped_rules=tuple(skipped), warnings=tuple(warnings)
    )


def smart_default_rules_from_config(config: Any | None) -> list[SmartDefaultRule]:
    raw = getattr(config, "smart_default_rules", None)
    rules = normalize_smart_default_rules(raw if raw is not None else default_smart_default_rules())
    connection_defaults = merged_connection_defaults(config)
    adjusted: list[SmartDefaultRule] = []
    for rule in rules:
        if rule.source == "default_connection" and rule.set_field == "Changeover Difficulty":
            value = _connection_default_value(rule.when_value, connection_defaults)
            if value:
                rule = SmartDefaultRule(
                    id=rule.id,
                    enabled=rule.enabled,
                    when_field=rule.when_field,
                    operator=rule.operator,
                    when_value=rule.when_value,
                    set_field=rule.set_field,
                    set_value=value,
                    source=rule.source,
                )
        adjusted.append(rule)
    return adjusted


def apply_configured_smart_defaults(
    entry: Mapping[str, Any],
    config: Any | None,
    *,
    only_unset: bool = True,
    applicable_fields: ApplicableFields = None,
) -> SmartDefaultResult:
    return apply_smart_default_rules(
        entry,
        smart_default_rules_from_config(config),
        only_unset=only_unset,
        applicable_fields=applicable_fields,
    )


def _matches(current: Any, operator: str, expected: str) -> bool:
    current_text = str(current or "").strip().casefold()
    expected_text = str(expected or "").strip().casefold()
    normalized_operator = operator if operator in SMART_RULE_OPERATORS else "equals"
    if normalized_operator == "equals":
        return current_text == expected_text
    if normalized_operator == "not_equals":
        return current_text != expected_text
    if normalized_operator == "contains":
        return bool(expected_text) and expected_text in current_text
    if normalized_operator == "not_contains":
        return bool(expected_text) and expected_text not in current_text
    if normalized_operator == "is_empty":
        return _is_unset(current_text)
    if normalized_operator == "is_not_empty":
        return not _is_unset(current_text)
    if normalized_operator == "in_list":
        return current_text in {item.strip().casefold() for item in expected.split(",") if item.strip()}
    return False


def _field_is_applicable(values: Mapping[str, str], field: str, applicable_fields: ApplicableFields) -> bool:
    if applicable_fields is None:
        return field_applies(dict(values), field)
    if callable(applicable_fields):
        return bool(applicable_fields(field))
    return field in applicable_fields


def _is_unset(value: Any) -> bool:
    return str(value or "").strip().casefold() in UNSET_VALUES


def _bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "on"}


def _normalize_operator(value: Any) -> str:
    text = str(value or "equals").strip().casefold()
    aliases = {"!=": "not_equals", "is_blank": "is_empty", "blank": "is_empty", "not_blank": "is_not_empty"}
    return aliases.get(text, text if text in SMART_RULE_OPERATORS else "equals")


def _connection_default_value(key: str, defaults: Mapping[str, str]) -> str | None:
    folded = str(key or "").strip().casefold()
    for default_key, value in defaults.items():
        if str(default_key or "").strip().casefold() == folded:
            return value
    return None
