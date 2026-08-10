# ruff: noqa: B008
from __future__ import annotations

import hmac
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.orm import Session

from ..database.session import get_write_session
from ..errors import APIError
from .configuration import AuthenticationConfigurationError
from .service import AuthenticationService

router = APIRouter(prefix="/api/v1")


class LoginRequest(BaseModel):
    identity: str = Field(min_length=1, max_length=128)


class KerberosFormLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)


class SettingsAuthorizationRequest(BaseModel):
    permission: str = "settings.edit"
    operation: str = "settings.save"


class SettingsAuditRequest(BaseModel):
    event_type: str
    operation: str


class SettingsWriteRequest(BaseModel):
    value: Any
    description: str | None = Field(default=None, max_length=2000)


class SettingsActionRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=64)
    section: str | None = Field(default=None, max_length=64)


class SettingsCatalogOption(BaseModel):
    value: Any
    label: str


class SettingsCatalogItem(BaseModel):
    section: str
    key: str
    label: str
    control: str
    default: Any
    description: str = ""
    options: list[SettingsCatalogOption] = Field(default_factory=list)
    locked: bool = False


class SettingsCatalogSection(BaseModel):
    key: str
    title: str
    glyph: str


class SettingsCatalogResponse(BaseModel):
    sections: list[SettingsCatalogSection]
    items: list[SettingsCatalogItem]


def _service(session: Session) -> AuthenticationService:
    try:
        return AuthenticationService(session)
    except AuthenticationConfigurationError as exc:
        raise APIError(503, "AUTH_CONFIGURATION_INVALID", str(exc)) from exc


def _bearer(request: Request) -> str:
    value = request.headers.get("Authorization", "")
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.casefold() == "bearer" else request.cookies.get("eoat_atlas_session", "")


def _require_csrf(request: Request) -> None:
    if request.headers.get("Authorization", "").partition(" ")[0].casefold() == "bearer":
        return
    session_token = request.cookies.get("eoat_atlas_session", "")
    # Preserve the authentication boundary: an anonymous request is rejected
    # as unauthenticated by the service, while an authenticated cookie request
    # without its paired CSRF token is rejected as CSRF-invalid.
    if not session_token:
        return
    csrf_cookie = request.cookies.get("eoat_atlas_csrf", "")
    csrf_header = request.headers.get("X-EOAT-CSRF-Token", "")
    if session_token and csrf_cookie and hmac.compare_digest(csrf_cookie, csrf_header):
        return
    raise APIError(403, "CSRF_VALIDATION_FAILED", "The request could not be validated.")


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


@router.post("/auth/kerberos/login")
def kerberos_login(request: Request, session: Session = Depends(get_write_session)):
    return _service(session).complete_kerberos_login(
        {
            "source_ip": request.client.host if request.client else "",
            "authenticated_user": request.headers.get("X-EOAT-Authenticated-User", ""),
            "proxy_assertion": request.headers.get("X-EOAT-Proxy-Assertion", ""),
        },
        request_id=getattr(request.state, "request_id", None),
        client_version=request.headers.get("X-EOAT-Client-Version"),
        source_ip=request.client.host if request.client else None,
    )


@router.post("/auth/kerberos-form/login")
def kerberos_form_login(
    payload: KerberosFormLoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_write_session),
):
    result = _service(session).complete_kerberos_form_login(
        {"username": payload.username, "password": payload.password.get_secret_value()},
        request_id=getattr(request.state, "request_id", None),
        client_version=request.headers.get("X-EOAT-Client-Version"),
        source_ip=request.client.host if request.client else None,
    )
    response.set_cookie("eoat_atlas_session", result.pop("access_token"), httponly=True, secure=True, samesite="lax", max_age=300, path="/")
    response.set_cookie("eoat_atlas_csrf", secrets.token_urlsafe(32), httponly=False, secure=True, samesite="lax", max_age=300, path="/")
    return result


@router.get("/auth/session")
def authentication_session(request: Request, session: Session = Depends(get_write_session)):
    row, user = _service(session).resolve_session(_bearer(request))
    return AuthenticationService.session_payload(row, user)


@router.post("/auth/logout")
def authentication_logout(request: Request, response: Response, session: Session = Depends(get_write_session)):
    _require_csrf(request)
    _service(session).logout(_bearer(request))
    response.delete_cookie("eoat_atlas_session", path="/")
    response.delete_cookie("eoat_atlas_csrf", path="/")
    return {"authenticated": False, "settings_locked": True}


@router.post("/settings/authorization/check")
def authorize_settings(
    payload: SettingsAuthorizationRequest,
    request: Request,
    session: Session = Depends(get_write_session),
) -> dict[str, Any]:
    _require_csrf(request)
    if not payload.permission.startswith("settings."):
        raise APIError(422, "INVALID_SETTINGS_PERMISSION", "Only Settings permissions may be checked here.")
    result = _service(session).require_permission(_bearer(request), payload.permission)
    return {**result, "authorized": True, "operation": payload.operation}


@router.get("/settings")
def read_settings(session: Session = Depends(get_write_session)):
    """Return only non-secret shared Settings; ordinary reads never require login."""
    return {"items": _service(session).public_settings(), "authentication_required": False}


@router.get("/settings/catalog", response_model=SettingsCatalogResponse)
def read_settings_catalog() -> SettingsCatalogResponse:
    """Expose the desktop Settings registry so browser controls cannot drift.

    This is descriptive only: sensitive values, paths, and authentication
    material are not returned. Values still come from the ordinary shared
    Settings endpoint and writes remain permission-gated.
    """
    from app.atlas.minimalist.settings_page import SECTIONS, SETTINGS_REGISTRY

    return SettingsCatalogResponse(
        sections=[SettingsCatalogSection(key=item.key, title=item.title, glyph=item.glyph) for item in SECTIONS],
        items=[
            SettingsCatalogItem(
                section=item.section,
                key=item.key,
                label=item.label,
                control=item.control,
                default=item.default,
                description=item.description,
                options=[SettingsCatalogOption(value=option.value, label=option.label) for option in item.options],
                locked=item.locked,
            )
            for item in SETTINGS_REGISTRY
            if item.visible and item.implemented
        ],
    )


@router.put("/settings/{setting_key}")
def write_setting(
    setting_key: str,
    payload: SettingsWriteRequest,
    request: Request,
    session: Session = Depends(get_write_session),
):
    _require_csrf(request)
    normalized_key = setting_key.strip()
    allowed_characters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not normalized_key or len(normalized_key) > 128 or any(char not in allowed_characters for char in normalized_key):
        raise APIError(
            422,
            "INVALID_SETTING_KEY",
            "Setting keys may contain only letters, numbers, dots, underscores, and hyphens.",
        )
    return _service(session).write_public_setting(
        _bearer(request), normalized_key, payload.value, payload.description
    )


@router.post("/settings/actions/{action}")
def settings_action(
    action: str,
    payload: SettingsActionRequest,
    request: Request,
    session: Session = Depends(get_write_session),
):
    _require_csrf(request)
    confirmations = {
        "reset-section": "RESET SECTION",
        "reset-all": "RESET ALL SETTINGS",
        "set-defaults": "SET DEFAULTS",
        "factory-reset": "FACTORY RESET",
    }
    required = confirmations.get(action)
    if required is None:
        raise APIError(404, "SETTINGS_ACTION_NOT_FOUND", "This Settings action is not available.")
    if payload.confirmation.strip() != required:
        raise APIError(422, "SETTINGS_CONFIRMATION_REQUIRED", f'Type "{required}" to continue.')
    return _service(session).apply_browser_settings_action(
        _bearer(request), action, section=payload.section
    )


@router.post("/settings/audit")
def audit_settings_action(
    payload: SettingsAuditRequest,
    request: Request,
    session: Session = Depends(get_write_session),
):
    _require_csrf(request)
    return _service(session).audit_settings_action(_bearer(request), payload.event_type, payload.operation)
