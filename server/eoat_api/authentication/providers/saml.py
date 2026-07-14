from __future__ import annotations

import os

from ..exceptions import AuthenticationUnavailableError
from ..identity_models import AuthenticatedIdentity, ProviderHealth
from .base import AuthenticationProvider


class SAMLAuthenticationProvider(AuthenticationProvider):
    name = "saml"

    def _configured(self) -> bool:
        return bool(os.getenv("EOAT_SAML_METADATA_URL", "").strip(" <>")) and bool(
            os.getenv("EOAT_SAML_ENTITY_ID", "").strip(" <>")
        )

    def begin_login(self, _context: dict) -> dict:
        raise AuthenticationUnavailableError(
            "SAML is awaiting IT-approved metadata, claims, endpoints, and security review"
        )

    def complete_login(self, _response: dict) -> AuthenticatedIdentity:
        raise AuthenticationUnavailableError("SAML assertion processing is not enabled before IT selection")

    def health_check(self) -> ProviderHealth:
        configured = self._configured()
        return ProviderHealth(
            self.name,
            configured,
            False,
            False,
            "Awaiting IT approval and staging metadata" if not configured else "Configured but not IT-approved",
        )
