from __future__ import annotations

import ssl
from datetime import datetime, timezone

from ..exceptions import AuthenticationUnavailableError, DirectoryProtocolError, InvalidCredentialsError
from ..identity_models import AuthenticatedIdentity, ProviderHealth
from ..provider_configuration import LDAPProviderConfiguration
from .base import AuthenticationProvider


class LDAPAuthenticationProvider(AuthenticationProvider):
    name = "ldap"

    def __init__(self, configuration: LDAPProviderConfiguration | None = None):
        self.configuration = configuration or LDAPProviderConfiguration.from_environment()

    @staticmethod
    def normalize_identifier(value: str, upn_suffix: str) -> str:
        value = value.strip()
        if not value or "\x00" in value or len(value) > 256:
            raise InvalidCredentialsError("Invalid administrator sign-in details.")
        if "\\" in value:
            _domain, separator, account = value.partition("\\")
            if not separator or not account or "\\" in account:
                raise InvalidCredentialsError("Invalid administrator sign-in details.")
            value = account
        if "@" not in value:
            value = f"{value}@{upn_suffix}"
        return value.casefold()

    @staticmethod
    def escape_filter_value(value: str) -> str:
        # ldap3's implementation handles RFC 4515 escaping, including NUL.
        from ldap3.utils.conv import escape_filter_chars

        return escape_filter_chars(value)

    def begin_login(self, context: dict) -> dict:
        missing = self.configuration.missing_fields()
        if missing:
            raise AuthenticationUnavailableError("LDAPS is not configured for administrator sign-in.")
        identifier = self.normalize_identifier(str(context.get("identity") or ""), self.configuration.upn_suffix)
        # A password is intentionally accepted only in this in-memory request
        # object. It is never logged, stored, returned, or attached to a challenge.
        password = context.get("password")
        if not isinstance(password, str) or not password:
            raise InvalidCredentialsError("Invalid administrator sign-in details.")
        return {"identifier": identifier, "password": password}

    def complete_login(self, response: dict) -> AuthenticatedIdentity:
        identifier = self.normalize_identifier(str(response.get("identifier") or ""), self.configuration.upn_suffix)
        password = response.get("password")
        if not isinstance(password, str) or not password:
            raise InvalidCredentialsError("Invalid administrator sign-in details.")
        missing = self.configuration.missing_fields()
        if missing:
            raise AuthenticationUnavailableError("LDAPS is not configured for administrator sign-in.")
        last_error: Exception | None = None
        for host in self.configuration.hosts:
            try:
                return self._bind_and_read(host, identifier, password)
            except InvalidCredentialsError:
                raise
            except Exception as exc:  # no server detail is released to callers
                last_error = exc
        raise DirectoryProtocolError("LDAPS directory service is unavailable.") from last_error

    def _bind_and_read(self, host: str, identifier: str, password: str) -> AuthenticatedIdentity:
        try:
            from ldap3 import ALL_ATTRIBUTES, BASE, SUBTREE, Connection, Server, Tls
            from ldap3.core.exceptions import LDAPBindError, LDAPException
        except ImportError as exc:
            raise AuthenticationUnavailableError("The approved LDAP client dependency is unavailable.") from exc
        tls = Tls(
            validate=ssl.CERT_REQUIRED,
            ca_certs_file=self.configuration.trust_store_path or None,
            version=ssl.PROTOCOL_TLS_CLIENT,
        )
        server = Server(host, port=self.configuration.port, use_ssl=True, tls=tls, connect_timeout=self.configuration.connection_timeout_seconds)
        try:
            bind_name = identifier
            if self.configuration.authentication_mode == "user_dn":
                search_base = self.configuration.user_search_base or self.configuration.base_dn
                with Connection(server, auto_bind=True, receive_timeout=self.configuration.operation_timeout_seconds, raise_exceptions=True) as discovery:
                    safe_filter = f"(userPrincipalName={self.escape_filter_value(identifier)})"
                    discovery.search(search_base, safe_filter, search_scope=SUBTREE, attributes=["distinguishedName"])
                    if len(discovery.entries) != 1:
                        raise InvalidCredentialsError("Invalid administrator sign-in details.")
                    bind_name = discovery.entries[0].entry_dn
            with Connection(
                server,
                user=bind_name,
                password=password,
                auto_bind=True,
                receive_timeout=self.configuration.operation_timeout_seconds,
                raise_exceptions=True,
            ) as connection:
                who = connection.extend.standard.who_am_i() or ""
                dn = who.removeprefix("dn:").strip()
                if not dn:
                    raise DirectoryProtocolError("LDAPS did not return a canonical identity.")
                if not connection.search(dn, "(objectClass=*)", search_scope=BASE, attributes=ALL_ATTRIBUTES):
                    raise DirectoryProtocolError("LDAPS identity lookup failed.")
                entry = connection.entries[0]
                attributes = entry.entry_attributes_as_dict
        except LDAPBindError as exc:
            raise InvalidCredentialsError("Invalid administrator sign-in details.") from exc
        except LDAPException as exc:
            raise DirectoryProtocolError("LDAPS directory service is unavailable.") from exc
        username = self._attribute(attributes, "sAMAccountName") or identifier.partition("@")[0]
        upn = self._attribute(attributes, "userPrincipalName") or identifier
        external_subject = self._attribute(attributes, "objectGUID") or dn.casefold()
        groups = {str(value) for value in attributes.get(self.configuration.group_attribute, []) if value}
        if self.configuration.nested_group_resolution and self.configuration.group_search_base:
            nested_filter = "(&(objectClass=group)(member:1.2.840.113556.1.4.1941:=" + self.escape_filter_value(dn) + "))"
            with Connection(server, user=bind_name, password=password, auto_bind=True, receive_timeout=self.configuration.operation_timeout_seconds, raise_exceptions=True) as nested:
                nested.search(self.configuration.group_search_base, nested_filter, search_scope=SUBTREE, attributes=["distinguishedName"])
                groups.update(entry.entry_dn for entry in nested.entries)
        return AuthenticatedIdentity(
            external_subject=f"ldap:{external_subject}",
            username=username.casefold(),
            display_name=self._attribute(attributes, "displayName") or username,
            email=self._attribute(attributes, "mail"),
            provider=self.name,
            group_identifiers=tuple(sorted(groups)),
            authentication_time=datetime.now(timezone.utc),
            authentication_method="ldaps_upn_direct_bind" if self.configuration.authentication_mode == "upn" else "ldaps_user_dn_discovery_bind",
        )

    @staticmethod
    def _attribute(attributes: dict, name: str) -> str | None:
        value = attributes.get(name)
        if isinstance(value, list | tuple):
            value = value[0] if value else None
        return str(value) if value not in (None, "") else None

    def health_check(self) -> ProviderHealth:
        missing = self.configuration.missing_fields()
        configured = not missing
        authorization_missing = self.configuration.authorization_missing_fields()
        return ProviderHealth(
            self.name,
            configured,
            configured,
            configured,
            "LDAPS authentication is configured; administrator authorization is awaiting approved group mapping"
            if configured and authorization_missing
            else "LDAPS authentication is ready for controlled Settings administration"
            if configured
            else "LDAPS remains unavailable until TLS-verified configuration is complete",
            (*missing, *authorization_missing),
        )
