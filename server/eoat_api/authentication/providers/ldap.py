from __future__ import annotations

from ..exceptions import AuthenticationUnavailableError
from ..identity_models import AuthenticatedIdentity, ProviderHealth
from ..provider_configuration import LDAPProviderConfiguration
from .base import AuthenticationProvider


class LDAPAuthenticationProvider(AuthenticationProvider):
    name = "ldap"

    def __init__(self, configuration: LDAPProviderConfiguration | None = None):
        self.configuration = configuration or LDAPProviderConfiguration.from_environment()

    def begin_login(self, _context: dict) -> dict:
        raise AuthenticationUnavailableError(
            "LDAP is awaiting IT-approved LDAPS servers, certificate chain, search pattern, and login method"
        )

    def complete_login(self, _response: dict) -> AuthenticatedIdentity:
        raise AuthenticationUnavailableError("LDAP authentication is not enabled before IT selection")

    def health_check(self) -> ProviderHealth:
        missing = self.configuration.missing_fields()
        configured = not missing
        return ProviderHealth(
            self.name,
            configured,
            False,
            False,
            "Awaiting IT approval and secure directory configuration"
            if not configured
            else "Configured but not IT-approved",
            missing,
        )
