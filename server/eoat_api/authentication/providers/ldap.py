from __future__ import annotations

import os

from ..exceptions import AuthenticationUnavailableError
from ..identity_models import AuthenticatedIdentity, ProviderHealth
from .base import AuthenticationProvider


class LDAPAuthenticationProvider(AuthenticationProvider):
    name = "ldap"

    def _configured(self) -> bool:
        return bool(os.getenv("EOAT_LDAP_HOST", "").strip(" <>")) and bool(
            os.getenv("EOAT_LDAP_BASE_DN", "").strip(" <>")
        )

    def begin_login(self, _context: dict) -> dict:
        raise AuthenticationUnavailableError(
            "LDAP is awaiting IT-approved LDAPS servers, certificate chain, search pattern, and login method"
        )

    def complete_login(self, _response: dict) -> AuthenticatedIdentity:
        raise AuthenticationUnavailableError("LDAP authentication is not enabled before IT selection")

    def health_check(self) -> ProviderHealth:
        configured = self._configured()
        return ProviderHealth(
            self.name,
            configured,
            False,
            False,
            "Awaiting IT approval and secure directory configuration"
            if not configured
            else "Configured but not IT-approved",
        )
