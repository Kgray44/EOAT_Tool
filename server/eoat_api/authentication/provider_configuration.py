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

    @classmethod
    def from_environment(cls) -> LDAPProviderConfiguration:
        try:
            port = int(_value("EOAT_LDAP_PORT") or "636")
        except ValueError:
            port = -1
        hosts = tuple(item.strip() for item in _value("EOAT_LDAP_HOSTS").split(",") if item.strip())
        legacy_host = _value("EOAT_LDAP_HOST")
        if not hosts and legacy_host:
            hosts = (legacy_host,)
        return cls(
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
        )

    def missing_fields(self) -> tuple[str, ...]:
        required = {
            "hosts": self.hosts,
            "base_dn": self.base_dn,
            "user_search_base": self.user_search_base,
            "user_search_filter": self.user_search_filter,
            "group_attribute": self.group_attribute,
            "trust_store_path": self.trust_store_path,
        }
        missing = [name for name, value in required.items() if not value]
        if not 1 <= self.port <= 65535:
            missing.append("port (1-65535)")
        if not self.use_ldaps:
            missing.append("use_ldaps must be true")
        return tuple(missing)


@dataclass(frozen=True)
class KerberosProviderConfiguration:
    realm: str
    trusted_proxy_addresses: tuple[str, ...]
    assertion: str

    @classmethod
    def from_environment(cls) -> KerberosProviderConfiguration:
        addresses = tuple(
            item.strip()
            for item in _value("EOAT_KERBEROS_TRUSTED_PROXY_ADDRESSES").split(",")
            if item.strip()
        )
        return cls(
            realm=_value("EOAT_KERBEROS_REALM").upper(),
            trusted_proxy_addresses=addresses,
            assertion=_value("EOAT_KERBEROS_PROXY_ASSERTION"),
        )

    def missing_fields(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, value in {
                "realm": self.realm,
                "trusted_proxy_addresses": self.trusted_proxy_addresses,
                "proxy_assertion": self.assertion,
            }.items()
            if not value
        )


@dataclass(frozen=True)
class KerberosFormProviderConfiguration:
    realm: str
    base_dn: str
    cache_directory: str
    login_timeout_seconds: int
    min_sasl_ssf: int
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 60
    test_mode: bool = False
    test_admin_upns: tuple[str, ...] = ()

    @classmethod
    def from_environment(cls) -> KerberosFormProviderConfiguration:
        try:
            timeout = int(_value("EOAT_KERBEROS_LOGIN_TIMEOUT_SECONDS") or "15")
            min_ssf = int(_value("EOAT_KERBEROS_MIN_SASL_SSF") or "256")
        except ValueError:
            timeout, min_ssf = -1, -1
        try:
            attempts = int(_value("EOAT_KERBEROS_LOGIN_RATE_LIMIT_ATTEMPTS") or "5")
            window = int(_value("EOAT_KERBEROS_LOGIN_RATE_LIMIT_WINDOW_SECONDS") or "60")
        except ValueError:
            attempts, window = -1, -1
        return cls(
            realm=_value("EOAT_KERBEROS_REALM").upper(),
            base_dn=_value("EOAT_KERBEROS_BASE_DN"),
            cache_directory=_value("EOAT_KERBEROS_CACHE_DIRECTORY"),
            login_timeout_seconds=timeout,
            min_sasl_ssf=min_ssf,
            login_rate_limit_attempts=attempts,
            login_rate_limit_window_seconds=window,
            test_mode=_value("EOAT_KERBEROS_FORM_TEST_MODE").casefold() in {"1", "true", "yes", "on"},
            test_admin_upns=tuple(
                value.strip().casefold()
                for value in _value("EOAT_KERBEROS_FORM_TEST_ADMIN_UPNS").split(",")
                if value.strip()
            ),
        )

    def missing_fields(self) -> tuple[str, ...]:
        missing = tuple(
            name
            for name, value in {
                "realm": self.realm,
                "base_dn": self.base_dn,
                "cache_directory": self.cache_directory,
            }.items()
            if not value
        )
        if not 1 <= self.login_timeout_seconds <= 60:
            missing += ("login_timeout_seconds (1-60)",)
        if self.min_sasl_ssf < 56:
            missing += ("min_sasl_ssf (at least 56)",)
        if not 1 <= self.login_rate_limit_attempts <= 20:
            missing += ("login_rate_limit_attempts (1-20)",)
        if not 1 <= self.login_rate_limit_window_seconds <= 3600:
            missing += ("login_rate_limit_window_seconds (1-3600)",)
        if self.test_admin_upns and not self.test_mode:
            missing += ("test_mode required for test_admin_upns",)
        return missing
