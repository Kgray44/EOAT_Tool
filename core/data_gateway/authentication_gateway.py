from __future__ import annotations

from typing import Any

from .api_client import AtlasApiClient
from .configuration import GatewayConfiguration


class AuthenticationGateway:
    """Memory-only desktop boundary for Settings administrator sessions."""

    def __init__(self, configuration: GatewayConfiguration | None = None):
        self.configuration = configuration or GatewayConfiguration.from_environment()
        self.api = AtlasApiClient(
            self.configuration.api_base_url,
            timeout=self.configuration.timeout_seconds,
            application_instance_id=self.configuration.application_instance_id,
            client_version=self.configuration.client_version,
        )

    def close(self) -> None:
        self.api.clear_settings_session()
        self.api.close()

    def get_authentication_status(self) -> dict[str, Any]:
        return self.api.authentication_config()

    def health(self) -> dict[str, Any]:
        return self.api.authentication_health()

    def begin_login(self, identity: str = "dev.admin") -> dict[str, Any]:
        return self.api.begin_settings_login(identity)

    def get_current_identity(self) -> dict[str, Any]:
        return self.api.settings_session()

    def get_permissions(self) -> list[str]:
        return list(self.get_current_identity().get("permissions") or [])

    def authorize(self, permission: str = "settings.edit", operation: str = "settings.save") -> dict[str, Any]:
        return self.api.authorize_settings(permission, operation)

    def logout(self) -> None:
        self.api.logout_settings()

    def audit_settings_action(self, event_type: str, operation: str) -> dict[str, Any]:
        return self.api.audit_settings_action(event_type, operation)
