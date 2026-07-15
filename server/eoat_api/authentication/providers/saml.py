from __future__ import annotations

from ..exceptions import AuthenticationUnavailableError
from ..identity_models import AuthenticatedIdentity, ProviderHealth
from ..provider_configuration import SAMLProviderConfiguration
from .base import AuthenticationProvider


class SAMLAuthenticationProvider(AuthenticationProvider):
    name = "saml"

    def __init__(self, configuration: SAMLProviderConfiguration | None = None):
        self.configuration = configuration or SAMLProviderConfiguration.from_environment()

    def begin_login(self, _context: dict) -> dict:
        raise AuthenticationUnavailableError(
            "SAML is awaiting IT-approved metadata, claims, endpoints, and security review"
        )

    def complete_login(self, _response: dict) -> AuthenticatedIdentity:
        raise AuthenticationUnavailableError("SAML assertion processing is not enabled before IT selection")

    def health_check(self) -> ProviderHealth:
        missing = self.configuration.missing_fields()
        configured = not missing
        return ProviderHealth(
            self.name,
            configured,
            False,
            False,
            "Awaiting IT approval and staging metadata" if not configured else "Configured but not IT-approved",
            missing,
        )
