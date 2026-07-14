from __future__ import annotations

from datetime import datetime, timezone

from ..exceptions import AuthenticationUnavailableError
from ..identity_models import AuthenticatedIdentity, ProviderHealth
from .base import AuthenticationProvider

DEVELOPMENT_IDENTITIES = {
    "dev.viewer": ("Development Viewer", "VIEWER"),
    "dev.technician": ("Development Technician", "TECHNICIAN"),
    "dev.engineer": ("Development Engineer", "ENGINEER"),
    "dev.admin": ("Development Administrator", "ADMINISTRATOR"),
}


class DevelopmentAuthenticationProvider(AuthenticationProvider):
    name = "development"

    def __init__(self, environment: str):
        self.environment = environment
        if environment not in {"development", "staging_local"}:
            raise AuthenticationUnavailableError("Development authentication is unavailable in this environment")

    def begin_login(self, context: dict) -> dict:
        identity_key = str(context.get("identity") or "").strip()
        if identity_key not in DEVELOPMENT_IDENTITIES:
            raise AuthenticationUnavailableError("Unknown development identity")
        return {"identity": identity_key}

    def complete_login(self, response: dict) -> AuthenticatedIdentity:
        identity_key = str(response.get("identity") or "").strip()
        display_name, role = DEVELOPMENT_IDENTITIES[identity_key]
        now = datetime.now(timezone.utc)
        return AuthenticatedIdentity(
            external_subject=identity_key,
            username=identity_key,
            display_name=display_name,
            email=None,
            provider=self.name,
            group_identifiers=(f"development-role:{role}",),
            authentication_time=now,
            authentication_method="development_settings_test",
        )

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(self.name, True, True, False, "Development-only Settings authentication is active")
