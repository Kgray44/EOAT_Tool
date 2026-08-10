from __future__ import annotations

import hmac
import re
from datetime import datetime, timezone

from ..exceptions import AuthenticationUnavailableError
from ..identity_models import AuthenticatedIdentity, ProviderHealth
from ..provider_configuration import KerberosProviderConfiguration
from .base import AuthenticationProvider

_PRINCIPAL = re.compile(r"^(?P<username>[A-Za-z0-9._-]{1,128})@(?P<realm>[A-Za-z0-9.-]+)$")


class KerberosAuthenticationProvider(AuthenticationProvider):
    """Accept an identity only after the trusted local proxy completed SPNEGO."""

    name = "kerberos"

    def __init__(self, configuration: KerberosProviderConfiguration | None = None):
        self.configuration = configuration or KerberosProviderConfiguration.from_environment()

    def begin_login(self, context: dict) -> dict:
        if self.configuration.missing_fields():
            raise AuthenticationUnavailableError("Kerberos trusted-proxy configuration is incomplete")
        source_ip = str(context.get("source_ip") or "")
        if source_ip not in self.configuration.trusted_proxy_addresses:
            raise AuthenticationUnavailableError("Kerberos identity was not received from the trusted local proxy")
        identity = str(context.get("authenticated_user") or "").strip()
        assertion = str(context.get("proxy_assertion") or "")
        if not identity or not hmac.compare_digest(assertion, self.configuration.assertion):
            raise AuthenticationUnavailableError("Kerberos proxy assertion is missing or invalid")
        return {"authenticated_user": identity}

    def complete_login(self, response: dict) -> AuthenticatedIdentity:
        principal = str(response.get("authenticated_user") or "").strip()
        match = _PRINCIPAL.fullmatch(principal)
        if not match or match.group("realm").upper() != self.configuration.realm:
            raise AuthenticationUnavailableError("Kerberos principal is missing, malformed, or outside the configured realm")
        username = match.group("username")
        return AuthenticatedIdentity(
            external_subject=f"{username.casefold()}@{self.configuration.realm.lower()}",
            username=username,
            display_name=username,
            email=None,
            provider=self.name,
            group_identifiers=(),
            authentication_time=datetime.now(timezone.utc),
            authentication_method="http_negotiate_spnego_trusted_proxy",
        )

    def health_check(self) -> ProviderHealth:
        missing = self.configuration.missing_fields()
        configured = not missing
        return ProviderHealth(
            self.name,
            configured,
            configured,
            False,
            "Kerberos trusted-proxy foundation is configured but requires IT-approved SPN, keytab, and group resolver"
            if configured
            else "Kerberos trusted-proxy foundation is not configured",
            missing,
        )
