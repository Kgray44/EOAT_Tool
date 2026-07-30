from __future__ import annotations

import os
from dataclasses import dataclass


def _value(name: str) -> str:
    value = os.getenv(name, "").strip()
    return "" if value.startswith("<") and value.endswith(">") else value


@dataclass(frozen=True)
class SAMLProviderConfiguration:
    metadata_url: str
    service_provider_entity_id: str
    assertion_consumer_service_url: str
    username_claim: str
    display_name_claim: str
    email_claim: str
    groups_claim: str
    certificate_fingerprint: str
    allowed_clock_skew_seconds: int

    @classmethod
    def from_environment(cls) -> SAMLProviderConfiguration:
        try:
            clock_skew = int(_value("EOAT_SAML_ALLOWED_CLOCK_SKEW_SECONDS") or "120")
        except ValueError:
            clock_skew = -1
        return cls(
            metadata_url=_value("EOAT_SAML_METADATA_URL"),
            service_provider_entity_id=_value("EOAT_SAML_ENTITY_ID"),
            assertion_consumer_service_url=_value("EOAT_SAML_ACS_URL"),
            username_claim=_value("EOAT_SAML_USERNAME_CLAIM"),
            display_name_claim=_value("EOAT_SAML_DISPLAY_NAME_CLAIM"),
            email_claim=_value("EOAT_SAML_EMAIL_CLAIM"),
            groups_claim=_value("EOAT_SAML_GROUPS_CLAIM"),
            certificate_fingerprint=_value("EOAT_SAML_CERTIFICATE_FINGERPRINT"),
            allowed_clock_skew_seconds=clock_skew,
        )

    def missing_fields(self) -> tuple[str, ...]:
        required = {
            "metadata_url": self.metadata_url,
            "service_provider_entity_id": self.service_provider_entity_id,
            "assertion_consumer_service_url": self.assertion_consumer_service_url,
            "username_claim": self.username_claim,
            "groups_claim": self.groups_claim,
            "certificate_fingerprint": self.certificate_fingerprint,
        }
        missing = [name for name, value in required.items() if not value]
        if not 0 <= self.allowed_clock_skew_seconds <= 600:
            missing.append("allowed_clock_skew_seconds (0-600)")
        return tuple(missing)


@dataclass(frozen=True)
class LDAPProviderConfiguration:
    enabled: bool
    hosts: tuple[str, ...]
    port: int
    use_ldaps: bool
    base_dn: str
    user_search_base: str
    user_search_filter: str
    group_search_base: str
    group_attribute: str
    trust_store_path: str
    service_account_secret_reference: str
    connection_timeout_seconds: int
    operation_timeout_seconds: int
    discover_naming_context: bool
    upn_suffix: str
    authentication_mode: str
    settings_admin_group: str
    nested_group_resolution: bool

    @classmethod
    def from_environment(cls) -> LDAPProviderConfiguration:
        try:
            port = int(_value("EOAT_LDAP_PORT") or "636")
        except ValueError:
            port = -1
        try:
            connection_timeout_seconds = int(_value("EOAT_LDAP_CONNECTION_TIMEOUT_SECONDS") or "5")
            operation_timeout_seconds = int(_value("EOAT_LDAP_OPERATION_TIMEOUT_SECONDS") or "5")
        except ValueError:
            connection_timeout_seconds = operation_timeout_seconds = -1
        hosts = tuple(item.strip() for item in _value("EOAT_LDAP_HOSTS").split(",") if item.strip())
        legacy_host = _value("EOAT_LDAP_HOST")
        if not hosts and legacy_host:
            hosts = (legacy_host,)
        return cls(
            enabled=_value("EOAT_LDAP_ENABLED").casefold() in {"1", "true", "yes", "on"},
            hosts=hosts,
            port=port,
            use_ldaps=_value("EOAT_LDAP_USE_LDAPS").casefold() not in {"0", "false", "no", "off"},
            base_dn=_value("EOAT_LDAP_BASE_DN"),
            user_search_base=_value("EOAT_LDAP_USER_SEARCH_BASE"),
            user_search_filter=_value("EOAT_LDAP_USER_SEARCH_FILTER"),
            group_search_base=_value("EOAT_LDAP_GROUP_SEARCH_BASE"),
            group_attribute=_value("EOAT_LDAP_GROUP_ATTRIBUTE"),
            trust_store_path=_value("EOAT_LDAP_TRUST_STORE_PATH"),
            service_account_secret_reference=_value("EOAT_LDAP_SERVICE_ACCOUNT_SECRET_REFERENCE"),
            connection_timeout_seconds=connection_timeout_seconds,
            operation_timeout_seconds=operation_timeout_seconds,
            discover_naming_context=_value("EOAT_LDAP_DISCOVER_NAMING_CONTEXT").casefold() not in {"0", "false", "no", "off"},
            upn_suffix=_value("EOAT_LDAP_UPN_SUFFIX") or "gwplastics.com",
            authentication_mode=(_value("EOAT_LDAP_AUTHENTICATION_MODE") or "upn").casefold(),
            settings_admin_group=_value("EOAT_LDAP_SETTINGS_ADMIN_GROUP"),
            nested_group_resolution=_value("EOAT_LDAP_NESTED_GROUP_RESOLUTION").casefold() in {"1", "true", "yes", "on"},
        )

    def missing_fields(self) -> tuple[str, ...]:
        required = {
            "hosts": self.hosts,
            "group_attribute": self.group_attribute,
        }
        missing = [name for name, value in required.items() if not value]
        if not 1 <= self.port <= 65535:
            missing.append("port (1-65535)")
        if not self.use_ldaps:
            missing.append("use_ldaps must be true")
        if not self.enabled:
            missing.append("enabled")
        if not 1 <= self.connection_timeout_seconds <= 30:
            missing.append("connection_timeout_seconds (1-30)")
        if not 1 <= self.operation_timeout_seconds <= 30:
            missing.append("operation_timeout_seconds (1-30)")
        if self.authentication_mode not in {"upn", "user_dn"}:
            missing.append("authentication_mode (upn or user_dn)")
        if self.authentication_mode == "user_dn" and not (self.user_search_base or self.base_dn):
            missing.append("user_search_base or base_dn")
        if not self.upn_suffix or any(char.isspace() for char in self.upn_suffix):
            missing.append("upn_suffix")
        return tuple(missing)

    def authorization_missing_fields(self) -> tuple[str, ...]:
        return ("settings_admin_group",) if not self.settings_admin_group else ()
