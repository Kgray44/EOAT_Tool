from __future__ import annotations

import os
from datetime import timezone

import pytest
from fastapi import Response

from server.eoat_api.authentication.configuration import (
    AuthenticationConfiguration,
    AuthenticationConfigurationError,
)
from server.eoat_api.authentication.exceptions import InvalidCredentialsError
from server.eoat_api.authentication.permissions import effective_permissions
from server.eoat_api.authentication.provider_configuration import (
    LDAPProviderConfiguration,
    SAMLProviderConfiguration,
)
from server.eoat_api.authentication.providers.development import DevelopmentAuthenticationProvider
from server.eoat_api.authentication.providers.ldap import LDAPAuthenticationProvider
from server.eoat_api.authentication.providers.saml import SAMLAuthenticationProvider
from server.eoat_api.authentication.routes import _issue_browser_session
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
    assert "enabled" in ldap.missing_configuration


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


def test_ldap_identifier_normalization_and_filter_escaping_are_safe() -> None:
    provider = LDAPAuthenticationProvider(
        LDAPProviderConfiguration(
            enabled=True, hosts=("gwplastics.com",), port=636, use_ldaps=True,
            base_dn="", user_search_base="", user_search_filter="", group_search_base="",
            group_attribute="memberOf", trust_store_path="", service_account_secret_reference="",
            connection_timeout_seconds=5, operation_timeout_seconds=5, discover_naming_context=True,
            upn_suffix="gwplastics.com", authentication_mode="upn", settings_admin_group="", nested_group_resolution=False,
        )
    )
    assert provider.normalize_identifier(" GWPLASTICS\\Alice ", "gwplastics.com") == "alice@gwplastics.com"
    assert provider.escape_filter_value("*(a)\\\x00 O'Brien@GWPLASTICS") == "\\2a\\28a\\29\\5c\\00 O'Brien@GWPLASTICS"
    with pytest.raises(InvalidCredentialsError):
        provider.normalize_identifier("bad\x00identity", "gwplastics.com")


def test_ldap_missing_administrator_group_keeps_authorization_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("EOAT_LDAP_ENABLED", "true")
    monkeypatch.setenv("EOAT_LDAP_HOSTS", "gwplastics.com")
    monkeypatch.setenv("EOAT_LDAP_GROUP_ATTRIBUTE", "memberOf")
    health = LDAPAuthenticationProvider().health_check()
    assert health.configured and health.available
    assert "settings_admin_group" in health.missing_configuration


def test_production_browser_session_cookie_is_httponly_secure_and_strict(monkeypatch) -> None:
    monkeypatch.setenv("EOAT_API_ENVIRONMENT", "production")
    response = Response()
    payload = _issue_browser_session(response, {"access_token": "test-only-token", "authenticated": True})
    cookie_headers = response.headers.getlist("set-cookie")
    assert payload == {"authenticated": True}
    assert any("eoat_atlas_settings_session=" in value and "HttpOnly" in value and "Secure" in value and "SameSite=strict" in value for value in cookie_headers)
    assert all("test-only-token" not in value or "HttpOnly" in value for value in cookie_headers)
