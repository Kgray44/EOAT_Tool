from __future__ import annotations

import os
from dataclasses import dataclass

from .exceptions import AuthenticationConfigurationError


@dataclass(frozen=True)
class AuthenticationConfiguration:
    environment: str
    provider: str
    scope: str
    session_minutes: int
    jit_provisioning: bool

    @classmethod
    def from_environment(cls) -> AuthenticationConfiguration:
        environment = os.getenv("EOAT_API_ENVIRONMENT", "development").strip().casefold()
        provider = os.getenv("EOAT_AUTH_PROVIDER", "development" if environment == "development" else "unselected")
        provider = provider.strip().casefold()
        scope = os.getenv("EOAT_AUTH_SCOPE", "settings_only").strip().casefold()
        try:
            session_minutes = int(os.getenv("EOAT_AUTH_SESSION_MINUTES", "5"))
        except ValueError as exc:
            raise AuthenticationConfigurationError("EOAT_AUTH_SESSION_MINUTES must be an integer") from exc
        config = cls(
            environment=environment,
            provider=provider,
            scope=scope,
            session_minutes=max(1, min(session_minutes, 60)),
            jit_provisioning=os.getenv("EOAT_AUTH_JIT_PROVISIONING", "true").strip().casefold()
            in {"1", "true", "yes", "on"},
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.provider not in {"development", "saml", "ldap", "unselected"}:
            raise AuthenticationConfigurationError(f"Unsupported authentication provider: {self.provider}")
        if self.scope != "settings_only":
            raise AuthenticationConfigurationError("Phase 10 authentication scope must be settings_only")
        if self.environment == "production" and self.provider == "development":
            raise AuthenticationConfigurationError("Development authentication is forbidden in production")
