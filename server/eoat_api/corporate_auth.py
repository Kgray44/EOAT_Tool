"""Provider-neutral corporate-authentication configuration boundary.

This module reports safe readiness for the IT-approved Kerberos-form LDAP
configuration.  The provider authenticates an entered credential with a
temporary private Kerberos cache and queries LDAP through SASL/GSSAPI with the
configured security floor.  It must never be mistaken for an unauthenticated
or plaintext LDAP bind, and this status boundary never exposes configuration
values or group identifiers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import models as db

SUPPORTED_PROVIDERS = frozenset({"kerberos_form"})

_REQUIRED_CONFIGURATION = {
    "kerberos_form": (
        "EOAT_AUTH_SCOPE",
        "EOAT_KERBEROS_REALM",
        "EOAT_KERBEROS_BASE_DN",
        "EOAT_KERBEROS_CACHE_DIRECTORY",
        "EOAT_KERBEROS_LOGIN_TIMEOUT_SECONDS",
        "EOAT_KERBEROS_MIN_SASL_SSF",
    ),
}


@dataclass(frozen=True)
class CorporateProviderState:
    """A browser-safe provider state; it never includes configuration values."""

    provider: str | None
    state: str
    administrator_group_mapping_configured: bool
    missing_configuration_names: tuple[str, ...]
    detail: str


ADMINISTRATOR_GROUP_IDENTIFIER = "CN=GWP-VT - EOAT Atlas Administrators,OU=GW,DC=gwplastics,DC=com"


def _configured(value: str) -> bool:
    return bool(value.strip())


def corporate_provider_state(environment: dict[str, str] | None = None) -> CorporateProviderState:
    """Return safe status without exposing provider endpoints or secret values.

    `READY` is deliberately not inferred from configuration strings.  A
    provider-specific implementation must perform its own verified TLS or
    metadata/signature readiness check before it may report that state.
    """

    values = os.environ if environment is None else environment
    configured_provider = values.get("EOAT_AUTH_PROVIDER", values.get("EOAT_CORPORATE_AUTH_PROVIDER", "")).strip().casefold()
    if not configured_provider or configured_provider == "unselected":
        return CorporateProviderState(
            provider=None,
            state="UNAVAILABLE",
            administrator_group_mapping_configured=False,
            missing_configuration_names=(),
            detail="No IT-approved corporate provider is configured.",
        )
    if configured_provider not in SUPPORTED_PROVIDERS:
        return CorporateProviderState(
            provider=None,
            state="MISCONFIGURED",
            administrator_group_mapping_configured=False,
            missing_configuration_names=(),
            detail="The configured corporate provider is not the approved Kerberos-form LDAP standard.",
        )
    missing = tuple(name for name in _REQUIRED_CONFIGURATION[configured_provider] if not _configured(values.get(name, "")))
    if configured_provider == "kerberos_form" and values.get("EOAT_AUTH_SCOPE", "").strip().casefold() != "application":
        missing = tuple(dict.fromkeys((*missing, "EOAT_AUTH_SCOPE=application")))
    if missing:
        return CorporateProviderState(
            provider=configured_provider,
            state="MISCONFIGURED",
            administrator_group_mapping_configured=False,
            missing_configuration_names=missing,
            detail="The selected corporate provider is missing required protected configuration.",
        )
    return CorporateProviderState(
        provider=configured_provider,
        state="UNKNOWN",
        # The server-side mapping is persisted rather than copied into process
        # configuration.  Its presence must be established by the mapping
        # repository, never by exposing the group identifier here.
        administrator_group_mapping_configured=False,
        missing_configuration_names=(),
        detail="Approved Kerberos-form LDAP configuration is present; provider and persisted role-mapping readiness still require verification.",
    )


def administrator_group_mapping_configured(session: Session) -> bool:
    """Check the approved mapping without returning its group identifier.

    This deliberate exact-match query makes authorization derive from the
    persisted mapping store rather than from a browser assertion or an
    environment variable.  Database errors are allowed to propagate to the
    caller so it can fail closed instead of declaring the mapping available.
    """

    row = session.scalar(
        select(db.ExternalGroupRoleMapping.id).where(
            db.ExternalGroupRoleMapping.provider == "kerberos_form",
            db.ExternalGroupRoleMapping.external_group_identifier == ADMINISTRATOR_GROUP_IDENTIFIER,
            db.ExternalGroupRoleMapping.role_code == "ADMINISTRATOR",
            db.ExternalGroupRoleMapping.explicit_deny.is_(False),
            db.ExternalGroupRoleMapping.is_active.is_(True),
        )
    )
    return row is not None
