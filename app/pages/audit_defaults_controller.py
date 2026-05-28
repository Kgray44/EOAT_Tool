from __future__ import annotations

from typing import Any

from core.audit.defaults import audit_default, connection_changeover_default, merged_audit_defaults
from core.audit.smart_rules import SmartDefaultResult, apply_configured_smart_defaults


class AuditDefaultsController:
    def __init__(self, config: Any):
        self.config = config

    def initial_form_defaults(self) -> dict[str, str]:
        return merged_audit_defaults(self.config)

    def field_default(self, field_name: str) -> str | None:
        return audit_default(field_name, self.config)

    def quick_disconnect_type_default(self) -> str:
        return self.field_default("Pneumatic Quick Disconnect Type") or "PTC"

    def changeover_default(self, connection_type: str) -> str | None:
        return connection_changeover_default(connection_type, self.config)

    def smart_defaults(self, entry: dict[str, Any], *, only_unset: bool = True) -> SmartDefaultResult:
        return apply_configured_smart_defaults(entry, self.config, only_unset=only_unset)
