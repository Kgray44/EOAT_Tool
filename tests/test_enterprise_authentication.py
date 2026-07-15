from __future__ import annotations

import os
from datetime import timezone

import pytest

from server.eoat_api.authentication.configuration import (
    AuthenticationConfiguration,
    AuthenticationConfigurationError,
)
from server.eoat_api.authentication.permissions import effective_permissions
from server.eoat_api.authentication.provider_configuration import (
    LDAPProviderConfiguration,
    SAMLProviderConfiguration,
)
from server.eoat_api.authentication.providers.development import DevelopmentAuthenticationProvider
from server.eoat_api.authentication.providers.ldap import LDAPAuthenticationProvider
from server.eoat_api.authentication.providers.saml import SAMLAuthenticationProvider
from server.eoat_api.security import ActorContext


def test_development_provider_normalizes_identity_without_password(monkeypatch) -> None:
    monkeypatch.setenv("EOAT_API_ENVIRONMENT", "development")
    provider = DevelopmentAuthenticationProvider("development")
    identity = provider.complete_login(provider.begin_login({"identity": "dev.admin"}))

    assert identity.external_subject == "dev.admin"
    assert identity.display_name == "Development Administrator"
    assert identity.provider == "development"
    assert identity.authentication_time.tzinfo == timezone.utc
    assert identity.group_identifiers == ("development-role:ADMINISTRATOR",)


def test_development_authentication_is_rejected_in_production(monkeypatch) -> None:
    monkeypatch.setenv("EOAT_API_ENVIRONMENT", "production")
    monkeypatch.setenv("EOAT_AUTH_PROVIDER", "development")

    with pytest.raises(AuthenticationConfigurationError, match="forbidden in production"):
        AuthenticationConfiguration.from_environment()


def test_unselected_production_provider_is_a_safe_locked_state(monkeypatch) -> None:
    monkeypatch.setenv("EOAT_API_ENVIRONMENT", "production")
    monkeypatch.setenv("EOAT_AUTH_PROVIDER", "unselected")

    configuration = AuthenticationConfiguration.from_environment()

    assert configuration.provider == "unselected"
    assert configuration.scope == "settings_only"


def test_provider_selection_is_settings_only(monkeypatch) -> None:
    monkeypatch.setenv("EOAT_API_ENVIRONMENT", "development")
    monkeypatch.setenv("EOAT_AUTH_PROVIDER", "saml")
    monkeypatch.setenv("EOAT_AUTH_SCOPE", "settings_only")

    configuration = AuthenticationConfiguration.from_environment()

    assert configuration.provider == "saml"
    assert configuration.scope == "settings_only"


def test_saml_and_ldap_adapters_fail_closed_without_it_configuration(monkeypatch) -> None:
    for name in tuple(name for name in os.environ if name.startswith(("EOAT_SAML_", "EOAT_LDAP_"))):
        monkeypatch.delenv(name, raising=False)

    saml = SAMLAuthenticationProvider().health_check()
    ldap = LDAPAuthenticationProvider().health_check()

    assert not saml.configured and not saml.available and not saml.production_approved
    assert not ldap.configured and not ldap.available and not ldap.production_approved
    assert "assertion_consumer_service_url" in saml.missing_configuration
    assert "trust_store_path" in ldap.missing_configuration


def test_provider_configuration_schemas_do_not_contain_password_values(monkeypatch) -> None:
    monkeypatch.setenv("EOAT_SAML_METADATA_URL", "https://identity.example/metadata")
    monkeypatch.setenv("EOAT_LDAP_HOSTS", "directory-1.example,directory-2.example")
    monkeypatch.setenv("EOAT_LDAP_SERVICE_ACCOUNT_SECRET_REFERENCE", "vault://eoat/ldap-bind")

    saml = SAMLProviderConfiguration.from_environment()
    ldap = LDAPProviderConfiguration.from_environment()

    assert saml.metadata_url == "https://identity.example/metadata"
    assert ldap.hosts == ("directory-1.example", "directory-2.example")
    assert ldap.service_account_secret_reference == "vault://eoat/ldap-bind"
    assert not hasattr(ldap, "password")


def test_settings_permissions_do_not_gate_ordinary_application_work() -> None:
    administrator = effective_permissions(("ADMINISTRATOR",))
    viewer = effective_permissions(("VIEWER",))
    ordinary_actor = ActorContext(1, "application.unauthenticated", "EOAT Atlas", "APPLICATION_USER", "r", None, None)

    assert "settings.edit" in administrator
    assert "settings.edit" not in viewer
    assert ordinary_actor.permits("asset.write")
    assert ordinary_actor.permits("history.export")
    assert not ordinary_actor.permits("settings.edit")


def test_invalid_authentication_scope_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("EOAT_API_ENVIRONMENT", "development")
    monkeypatch.setenv("EOAT_AUTH_PROVIDER", "development")
    monkeypatch.setenv("EOAT_AUTH_SCOPE", "application_wide")

    with pytest.raises(AuthenticationConfigurationError, match="settings_only"):
        AuthenticationConfiguration.from_environment()
