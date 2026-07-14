# ruff: noqa: B008
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database.session import get_write_session
from ..errors import APIError
from .configuration import AuthenticationConfigurationError
from .service import AuthenticationService

router = APIRouter(prefix="/api/v1")


class LoginRequest(BaseModel):
    identity: str = Field(min_length=1, max_length=128)


class SettingsAuthorizationRequest(BaseModel):
    permission: str = "settings.edit"
    operation: str = "settings.save"


class SettingsAuditRequest(BaseModel):
    event_type: str
    operation: str


def _service(session: Session) -> AuthenticationService:
    try:
        return AuthenticationService(session)
    except AuthenticationConfigurationError as exc:
        raise APIError(503, "AUTH_CONFIGURATION_INVALID", str(exc)) from exc


def _bearer(request: Request) -> str:
    value = request.headers.get("Authorization", "")
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.casefold() == "bearer" else ""


@router.get("/auth/config")
def authentication_config(session: Session = Depends(get_write_session)):
    return _service(session).public_configuration()


@router.get("/auth/health")
def authentication_health(session: Session = Depends(get_write_session)):
    config = _service(session).public_configuration()
    return {**config, "application_available_without_authentication": True}


@router.get("/auth/login")
def begin_enterprise_login(request: Request, session: Session = Depends(get_write_session)):
    return _service(session).begin_login({"request_id": getattr(request.state, "request_id", None)})


@router.post("/auth/development/login")
def development_login(payload: LoginRequest, request: Request, session: Session = Depends(get_write_session)):
    return _service(session).complete_development_login(
        payload.identity,
        request_id=getattr(request.state, "request_id", None),
        client_version=request.headers.get("X-EOAT-Client-Version"),
        source_ip=request.client.host if request.client else None,
    )


@router.get("/auth/session")
def authentication_session(request: Request, session: Session = Depends(get_write_session)):
    row, user = _service(session).resolve_session(_bearer(request))
    return AuthenticationService.session_payload(row, user)


@router.post("/auth/logout")
def authentication_logout(request: Request, session: Session = Depends(get_write_session)):
    _service(session).logout(_bearer(request))
    return {"authenticated": False, "settings_locked": True}


@router.post("/settings/authorization/check")
def authorize_settings(
    payload: SettingsAuthorizationRequest,
    request: Request,
    session: Session = Depends(get_write_session),
) -> dict[str, Any]:
    if not payload.permission.startswith("settings."):
        raise APIError(422, "INVALID_SETTINGS_PERMISSION", "Only Settings permissions may be checked here.")
    result = _service(session).require_permission(_bearer(request), payload.permission)
    return {**result, "authorized": True, "operation": payload.operation}


@router.post("/settings/audit")
def audit_settings_action(
    payload: SettingsAuditRequest,
    request: Request,
    session: Session = Depends(get_write_session),
):
    return _service(session).audit_settings_action(_bearer(request), payload.event_type, payload.operation)
