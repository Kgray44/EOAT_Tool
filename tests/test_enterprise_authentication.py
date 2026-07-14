from __future__ import annotations

from datetime import timezone

import pytest

from server.eoat_api.authentication.configuration import (
    AuthenticationConfiguration,
    AuthenticationConfigurationError,
)
from server.eoat_api.authentication.permissions import effective_permissions
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


def test_provider_selection_is_settings_only(monkeypatch) -> None:
    monkeypatch.setenv("EOAT_API_ENVIRONMENT", "development")
    monkeypatch.setenv("EOAT_AUTH_PROVIDER", "saml")
    monkeypatch.setenv("EOAT_AUTH_SCOPE", "settings_only")

    configuration = AuthenticationConfiguration.from_environment()

    assert configuration.provider == "saml"
    assert configuration.scope == "settings_only"


def test_saml_and_ldap_adapters_fail_closed_without_it_configuration(monkeypatch) -> None:
    for name in ("EOAT_SAML_METADATA_URL", "EOAT_SAML_ENTITY_ID", "EOAT_LDAP_HOST", "EOAT_LDAP_BASE_DN"):
        monkeypatch.delenv(name, raising=False)

    saml = SAMLAuthenticationProvider().health_check()
    ldap = LDAPAuthenticationProvider().health_check()

    assert not saml.configured and not saml.available and not saml.production_approved
    assert not ldap.configured and not ldap.available and not ldap.production_approved


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
