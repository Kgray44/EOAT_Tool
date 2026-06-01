from __future__ import annotations

from typing import Any

from core.audit.default_rules import apply_audit_default_rules, audit_default_rules_from_config
from core.audit.defaults import audit_default, connection_changeover_default, merged_audit_defaults
from core.audit.smart_rules import SmartDefaultResult, apply_configured_smart_defaults
from core.audit_constants import CYLINDER_TYPE_FIELD


class AuditDefaultsController:
    def __init__(self, config: Any):
        self.config = config

    def initial_form_defaults(self) -> dict[str, str]:
        rules = audit_default_rules_from_config(self.config)
        result = apply_audit_default_rules({}, rules, scope="new_audit")
        if getattr(self.config, "audit_default_rules", None):
            values = dict(result.values)
            values.pop(CYLINDER_TYPE_FIELD, None)
            return values
        if result.applied_rules:
            values = dict(result.values)
            values.pop(CYLINDER_TYPE_FIELD, None)
            return values
        values = merged_audit_defaults(self.config)
        values.pop(CYLINDER_TYPE_FIELD, None)
        return values

    def field_default(self, field_name: str) -> str | None:
        if field_name == CYLINDER_TYPE_FIELD:
            return None
        for rule in audit_default_rules_from_config(self.config):
            if rule.enabled and rule.field == field_name and rule.scope == "new_audit" and not rule.conditions:
                return rule.value
        if getattr(self.config, "audit_default_rules", None):
            return None
        return audit_default(field_name, self.config)

    def quick_disconnect_type_default(self) -> str:
        return self.field_default("Pneumatic Quick Disconnect Type") or "PTC"

    def changeover_default(self, connection_type: str) -> str | None:
        return connection_changeover_default(connection_type, self.config)

    def smart_defaults(
        self, entry: dict[str, Any], *, only_unset: bool = True, applicable_fields=None
    ) -> SmartDefaultResult:
        return apply_configured_smart_defaults(
            entry, self.config, only_unset=only_unset, applicable_fields=applicable_fields
        )
