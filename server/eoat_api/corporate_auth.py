"""Provider-neutral corporate-authentication configuration boundary.

This module intentionally does not implement an LDAPS bind or SAML assertion
consumer.  Phase 5 may not select either provider until IT approves its
configuration.  It provides safe, non-secret readiness information so callers
cannot mistake the Phase 3/4 rehearsal path for enterprise authentication.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

SUPPORTED_PROVIDERS = frozenset({"ldaps", "saml"})

_REQUIRED_CONFIGURATION = {
    "ldaps": (
        "EOAT_LDAPS_HOSTS",
        "EOAT_LDAPS_TRUST_STORE_PATH",
        "EOAT_LDAPS_USER_SEARCH_BASE",
        "EOAT_LDAPS_USER_SEARCH_FILTER",
        "EOAT_LDAPS_STABLE_ID_ATTRIBUTE",
        "EOAT_LDAPS_GROUP_ATTRIBUTE",
        "EOAT_CORPORATE_ADMIN_GROUP",
    ),
    "saml": (
        "EOAT_SAML_METADATA_URL",
        "EOAT_SAML_ENTITY_ID",
        "EOAT_SAML_ACS_URL",
        "EOAT_SAML_STABLE_SUBJECT_CLAIM",
        "EOAT_SAML_GROUPS_CLAIM",
        "EOAT_CORPORATE_ADMIN_GROUP",
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


def _configured(value: str) -> bool:
    return bool(value.strip())


def corporate_provider_state(environment: dict[str, str] | None = None) -> CorporateProviderState:
    """Return safe status without exposing provider endpoints or secret values.

    `READY` is deliberately not inferred from configuration strings.  A
    provider-specific implementation must perform its own verified TLS or
    metadata/signature readiness check before it may report that state.
    """

    values = os.environ if environment is None else environment
    configured_provider = values.get("EOAT_CORPORATE_AUTH_PROVIDER", "").strip().casefold()
    if not configured_provider or configured_provider == "unselected":
        return CorporateProviderState(
            provider=None,
            state="UNAVAILABLE",
            administrator_group_mapping_configured=False,
            missing_configuration_names=(),
            detail="No IT-approved LDAPS or SAML provider is configured.",
        )
    if configured_provider not in SUPPORTED_PROVIDERS:
        return CorporateProviderState(
            provider=None,
            state="MISCONFIGURED",
            administrator_group_mapping_configured=False,
            missing_configuration_names=(),
            detail="The configured corporate provider is not approved for this Phase 5 boundary.",
        )
    missing = tuple(name for name in _REQUIRED_CONFIGURATION[configured_provider] if not _configured(values.get(name, "")))
    if missing:
        return CorporateProviderState(
            provider=configured_provider,
            state="MISCONFIGURED",
            administrator_group_mapping_configured="EOAT_CORPORATE_ADMIN_GROUP" not in missing,
            missing_configuration_names=missing,
            detail="The selected corporate provider is missing required protected configuration.",
        )
    return CorporateProviderState(
        provider=configured_provider,
        state="UNKNOWN",
        administrator_group_mapping_configured=True,
        missing_configuration_names=(),
        detail="Provider configuration is present but has not completed a verified enterprise readiness check.",
    )
