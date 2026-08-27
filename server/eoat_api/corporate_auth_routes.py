"""Browser endpoints for the approved Kerberos-form corporate provider."""

# ruff: noqa: B008
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.orm import Session

from .corporate_auth import administrator_group_mapping_configured, corporate_provider_state
from .corporate_sessions import (
    CORPORATE_CSRF_COOKIE,
    CORPORATE_CSRF_HEADER,
    CORPORATE_SESSION_COOKIE,
    CorporateAuthenticationFailure,
    CorporateSessionService,
    corporate_csrf_valid,
)
from .corporate_users import access_state, corporate_user_for_user
from .database.session import get_runtime_session, get_write_session
from .errors import APIError
from .security import corporate_group_permissions

router = APIRouter(prefix="/api/v1/auth", tags=["corporate-authentication"])


class KerberosFormLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)


def _approved_provider() -> None:
    if os.getenv("EOAT_AUTH_PROVIDER", "").strip().casefold() != "kerberos_form" or os.getenv(
        "EOAT_AUTH_SCOPE", ""
    ).strip().casefold() != "application":
        raise APIError(503, "CORPORATE_AUTH_UNAVAILABLE", "Corporate authentication is not configured for this application.")


def _cookie_secure() -> bool:
    return os.getenv("EOAT_API_CORPORATE_COOKIE_SECURE", "").strip().casefold() in {"1", "true", "yes", "on"} or os.getenv(
        "EOAT_API_ENVIRONMENT", "development"
    ).strip().casefold() in {"staging", "staging_local", "production"}


def _session_payload(
    *, roles: tuple[str, ...] | list[str], identity: dict[str, str], permissions: set[str] | frozenset[str] | None = None, **values
):
    """Keep browser-session responses aligned with the normal web contract.

    The browser uses the server-derived grants only for presentation; protected
    API routes independently re-evaluate the session and role mapping.
    """

    normalized_roles = tuple(str(role).upper() for role in roles)
    resolved_permissions = permissions
    if resolved_permissions is None:
        # Login responses have no session row yet.  Administrators remain
        # fully capable; every other corporate role starts default-deny.
        resolved_permissions = {"*"} if "ADMINISTRATOR" in normalized_roles else set()
    return {
        "authenticated": True,
        "identity": identity,
        "roles": list(normalized_roles),
        "permissions": sorted(resolved_permissions),
        "scope": "application",
        **values,
    }


def corporate_session_service(session: Session = Depends(get_write_session)) -> CorporateSessionService:
    try:
        return CorporateSessionService(session)
    except CorporateAuthenticationFailure as exc:
        raise APIError(503, "CORPORATE_AUTH_UNAVAILABLE", "Corporate authentication is temporarily unavailable.", retryable=True) from exc


@router.get("/status")
def status(session: Session = Depends(get_runtime_session)):
    state = corporate_provider_state()
    try:
        mapping_configured = administrator_group_mapping_configured(session)
    except Exception:
        mapping_configured = False
    return {"provider": state.provider, "status": state.state.casefold(), "mapping_configured": mapping_configured}


@router.post("/kerberos-form/login")
def kerberos_form_login(
    payload: KerberosFormLoginRequest,
    response: Response,
    service: CorporateSessionService = Depends(corporate_session_service),
):
    _approved_provider()
    try:
        issued = service.login(payload.username, payload.password.get_secret_value())
    except CorporateAuthenticationFailure as exc:
        raise APIError(503, "CORPORATE_AUTH_UNAVAILABLE", "Corporate authentication is temporarily unavailable.", retryable=True) from exc
    max_age = max(1, int((issued.expires_at - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(CORPORATE_SESSION_COOKIE, issued.token, httponly=True, secure=_cookie_secure(), samesite="strict", max_age=max_age, path="/")
    response.set_cookie(CORPORATE_CSRF_COOKIE, issued.csrf_token, httponly=False, secure=_cookie_secure(), samesite="strict", max_age=max_age, path="/")
    return _session_payload(
        roles=issued.roles,
        identity={"username": issued.username, "display_name": issued.display_name},
        session_reference=issued.session_reference,
        expires_at=issued.expires_at,
        access_source=issued.access_source,
        permissions=corporate_group_permissions(
            service.session,
            groups=issued.authorization_groups,
            roles=set(issued.roles),
        ),
    )


@router.get("/session")
def session_status(request: Request, service: CorporateSessionService = Depends(corporate_session_service)):
    _approved_provider()
    try:
        row, user = service.resolve(request.cookies.get(CORPORATE_SESSION_COOKIE, ""))
    except CorporateAuthenticationFailure as exc:
        raise APIError(503, "CORPORATE_AUTH_UNAVAILABLE", "Corporate authentication is temporarily unavailable.", retryable=True) from exc
    registry = corporate_user_for_user(service.session, user.id)
    access = access_state(service.session, registry, groups=tuple(row.authorization_groups_json or ())) if registry else {}
    return _session_payload(
        roles=list(row.roles_json or []),
        identity={"username": user.username, "display_name": user.display_name},
        session_reference=row.session_reference,
        authenticated_at=row.authenticated_at,
        expires_at=row.expires_at,
        access_source=access.get("access_source"),
        permissions=corporate_group_permissions(
            service.session,
            groups=tuple(row.authorization_groups_json or ()),
            roles=set(row.roles_json or ()),
        ),
    )


@router.post("/logout")
def logout(request: Request, response: Response, service: CorporateSessionService = Depends(corporate_session_service)):
    _approved_provider()
    token = request.cookies.get(CORPORATE_SESSION_COOKIE, "")
    row, _user = service.resolve(token)
    if request.cookies.get(CORPORATE_CSRF_COOKIE, "") != request.headers.get(CORPORATE_CSRF_HEADER, "") or not corporate_csrf_valid(
        row, request.headers.get(CORPORATE_CSRF_HEADER, "")
    ):
        raise APIError(403, "CSRF_INVALID", "The logout request could not be verified.")
    service.revoke(token)
    response.delete_cookie(CORPORATE_SESSION_COOKIE, path="/")
    response.delete_cookie(CORPORATE_CSRF_COOKIE, path="/")
    return {"authenticated": False}
