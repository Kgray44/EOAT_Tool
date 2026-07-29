from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from core.versioning import configure_release_logging, get_release_info
from release_tools.versioning import Version

from .authentication.audit import record_auth_event
from .authentication.configuration import AuthenticationConfiguration
from .authentication.routes import router as authentication_router
from .compatibility import COMPATIBLE_STATUS_CODES
from .contracts import (
    CurrentEOATLocation,
    DataStatusResponse,
    DocumentMetadata,
    EOATProfile,
    FitCheckOption,
    FitCheckRequest,
    FitCheckResult,
    HealthResult,
    HistoryEvent,
    MachineCurrentSetup,
    MachineProfile,
    PaginatedEOATs,
    PaginatedHistory,
    PaginatedMachines,
    PaginatedTools,
    PhotoMetadata,
    RelationshipSummary,
    SearchResult,
    ToolProfile,
    WebDocumentMetadata,
    WebFitCheckOptions,
    WebFitCheckRequest,
    WebPhotoMetadata,
)
from .database import models as db
from .database.session import (
    create_session_factory,
    dispose_database_engines,
    finalize_request_write_session,
    get_runtime_session,
    get_write_session,
)
from .errors import APIError
from .repositories import LOOKUP_MODELS, AtlasRepository
from .security import actor_context
from .services import API_VERSION, EXPECTED_SCHEMA_REVISION, SERVER_REVISION, AtlasService
from .web_content import content_is_available, content_response, thumbnail_response
from .write_routes import router as write_router

logging.basicConfig(
    level=os.getenv("EOAT_API_LOG_LEVEL", "INFO"),
    format=(
        '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s",'
        '"application_version":"%(application_version)s","release_id":"%(release_id)s",'
        '"build_id":"%(build_id)s","database_schema_revision":"%(database_schema_revision)s",'
        '"api_contract_version":"%(api_contract_version)s","message":"%(message)s"}'
    ),
)
configure_release_logging()
LOGGER = logging.getLogger("eoat_api")
RELEASE_INFO = get_release_info()
if RELEASE_INFO.api_contract_version != API_VERSION:
    raise RuntimeError("Canonical release API contract version does not match server API_VERSION")
if RELEASE_INFO.database_schema_revision != EXPECTED_SCHEMA_REVISION:
    raise RuntimeError("Canonical release schema revision does not match server expectation")


def runtime_release_identity() -> dict[str, str | None]:
    """The one safe runtime identity source used by parity-aware API routes.

    Activation writes these values as process environment in a real target;
    development uses the governed immutable release metadata defaults.  No
    route reads deployment pointers or filesystem paths directly.
    """

    return {
        "product_version": RELEASE_INFO.application_version,
        "release_id": RELEASE_INFO.release_id,
        "build_id": RELEASE_INFO.build_id,
        "candidate_id": os.getenv("EOAT_RELEASE_CANDIDATE_ID", "").strip() or None,
        "source_commit": RELEASE_INFO.source_git_commit,
        "source_tree": os.getenv("EOAT_RELEASE_SOURCE_TREE", "").strip() or None,
        "release_set_digest": os.getenv("EOAT_RELEASE_SET_DIGEST", "").strip() or None,
        "release_channel": RELEASE_INFO.release_channel,
        "deployment_transaction_id": os.getenv("EOAT_DEPLOYMENT_TRANSACTION_ID", "").strip() or None,
    }


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Reject development authentication in production without contacting an IdP."""
    AuthenticationConfiguration.from_environment()
    try:
        yield
    finally:
        dispose_database_engines()


def _api_documentation_path(path: str) -> str | None:
    environment = os.getenv("EOAT_API_ENVIRONMENT", "development").strip().casefold()
    enabled_default = environment in {"development", "staging_local"}
    enabled = os.getenv("EOAT_API_DOCS_ENABLED", str(enabled_default)).strip().casefold() in {"1", "true", "yes", "on"}
    return path if enabled else None


app = FastAPI(
    title="EOAT Atlas API",
    version=API_VERSION,
    docs_url=_api_documentation_path("/api/docs"),
    openapi_url=_api_documentation_path("/api/openapi.json"),
    lifespan=lifespan,
)
app.include_router(authentication_router)


@app.middleware("http")
async def finalize_write_transaction(request: Request, call_next):
    """Commit successful request writes before the corresponding response leaves the API."""
    try:
        response = await call_next(request)
    except Exception:
        finalize_request_write_session(request, commit=False)
        raise
    finalize_request_write_session(request, commit=response.status_code < 400)
    return response


@app.middleware("http")
async def request_logging(request: Request, call_next):
    started = datetime.now(timezone.utc)
    request.state.request_id = request.headers.get("X-Request-ID") or str(uuid4())
    status: int | str = "UNHANDLED_EXCEPTION"
    try:
        environment = os.getenv("EOAT_API_ENVIRONMENT", "development").strip().casefold()
        protected = request.url.path.startswith("/api/v1/") and request.url.path not in {
            "/api/v1/health",
            "/api/v1/version",
            "/api/v1/release-status",
            "/api/v1/data-status",
        }
        # Phase 3A runtime parity is opt-in for existing deployments until the
        # signed release-set activation path provisions its authoritative
        # identity.  Once enabled, ordinary API operations fail closed while
        # health, release discovery, and diagnostics remain recoverable.
        if protected and os.getenv("EOAT_REQUIRE_CLIENT_RELEASE_PARITY", "false").strip().casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            active = {key: value or "" for key, value in runtime_release_identity().items() if key in {
                "product_version", "release_id", "build_id", "release_set_digest"
            }}
            supplied = {
                "product_version": request.headers.get("X-EOAT-Client-Version", "").strip(),
                "release_id": request.headers.get("X-EOAT-Client-Release-ID", "").strip(),
                "build_id": request.headers.get("X-EOAT-Client-Build-ID", "").strip(),
                "release_set_digest": request.headers.get("X-EOAT-Client-Release-Set-Digest", "").strip(),
            }
            if any(active[key] and supplied[key] != active[key] for key in active):
                status = 409
                return JSONResponse(
                    status_code=409,
                    content={
                        "error_code": "CLIENT_RELEASE_MISMATCH",
                        "active_release": active,
                        "supplied_client": supplied,
                        "restart_action": "restart-through-bootstrap",
                        "retryable": True,
                        "request_id": request.state.request_id,
                    },
                    headers={"X-Request-ID": request.state.request_id},
                )
        if environment == "production" and protected:
            configured_token = os.getenv("EOAT_API_DEVICE_TOKEN", "")
            supplied_token = request.headers.get("X-EOAT-Device-Token", "")
            if not configured_token:
                status = 503
                return JSONResponse(
                    status_code=503,
                    content={
                        "error_code": "DEVICE_AUTH_NOT_CONFIGURED",
                        "message": "Production read authentication is not configured.",
                        "request_id": request.state.request_id,
                    },
                    headers={"X-Request-ID": request.state.request_id},
                )
            if not supplied_token or not secrets.compare_digest(supplied_token, configured_token):
                status = 401
                return JSONResponse(
                    status_code=401,
                    content={
                        "error_code": "DEVICE_AUTH_REQUIRED",
                        "message": "An approved device credential is required.",
                        "request_id": request.state.request_id,
                    },
                    headers={"X-Request-ID": request.state.request_id},
                )
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request.state.request_id
        return response
    except Exception:
        LOGGER.exception("request_failed request_id=%s", request.state.request_id)
        raise
    finally:
        elapsed = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        LOGGER.info(
            "request_id=%s method=%s path=%s status=%s elapsed_ms=%.2f",
            request.state.request_id,
            request.method,
            request.url.path,
            status,
            elapsed,
        )


@app.exception_handler(APIError)
async def api_error(request: Request, exc: APIError):
    if exc.status_code in {401, 403}:
        LOGGER.warning(
            "security_denial request_id=%s code=%s identity=%s",
            getattr(request.state, "request_id", ""),
            exc.error_code,
            request.headers.get("X-EOAT-Identity", "<missing>"),
        )
        if request.url.path.startswith(("/api/v1/auth", "/api/v1/settings")):
            try:
                factory = create_session_factory(migration=False)
                with factory() as audit_session, audit_session.begin():
                    record_auth_event(
                        audit_session,
                        "SETTINGS_ADMIN_LOGIN_FAILED" if exc.status_code == 401 else "SETTINGS_ADMIN_ACCESS_DENIED",
                        result="DENIED",
                        provider=os.getenv("EOAT_AUTH_PROVIDER", "development"),
                        request_id=getattr(request.state, "request_id", None),
                        operation=request.url.path,
                        reason_code=exc.error_code,
                        source_ip=request.client.host if request.client else None,
                    )
            except SQLAlchemyError:
                LOGGER.exception("authentication_denial_audit_failed request_id=%s", request.state.request_id)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error_code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
            "request_id": getattr(request.state, "request_id", None),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "retryable": exc.retryable,
            "current_record_version": exc.current_record_version,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": "The request contains invalid values.",
            "details": exc.errors(),
            "request_id": getattr(request.state, "request_id", None),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "retryable": False,
            "current_record_version": None,
        },
    )


@app.exception_handler(IntegrityError)
async def integrity_conflict(_request: Request, exc: IntegrityError):
    """Map expected database uniqueness races to a safe client conflict."""
    LOGGER.info("write_conflict type=%s", type(exc).__name__)
    return JSONResponse(
        status_code=409,
        content={
            "error_code": "CONCURRENT_WRITE_CONFLICT",
            "message": "The record changed concurrently; refresh and retry with current data.",
            "details": None,
            "request_id": getattr(getattr(_request, "state", None), "request_id", None),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "retryable": True,
            "current_record_version": None,
        },
    )


@app.exception_handler(SQLAlchemyError)
async def database_error(_request: Request, exc: SQLAlchemyError):
    LOGGER.error("database_unavailable type=%s", type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={
            "error_code": "DATABASE_UNAVAILABLE",
            "message": "The EOAT Atlas database is unavailable.",
            "details": None,
            "request_id": getattr(getattr(_request, "state", None), "request_id", None),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "retryable": True,
            "current_record_version": None,
        },
    )


def repository(session: Session = Depends(get_runtime_session)) -> AtlasRepository:
    return AtlasRepository(session)


def service(session: Session = Depends(get_runtime_session)) -> AtlasService:
    return AtlasService(session)


def not_found(entity: str, identifier: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail={"code": "NOT_FOUND", "message": f"{entity} '{identifier}' was not found."}
    )


@app.get("/api/v1/health", response_model=HealthResult)
def health(svc: AtlasService = Depends(service)):
    svc.session.execute(text("SELECT 1"))
    revision = svc.schema_revision()
    return HealthResult(
        database_reachable=True,
        current_schema_revision=revision,
        expected_schema_revision=EXPECTED_SCHEMA_REVISION,
        compatible=revision == EXPECTED_SCHEMA_REVISION,
        environment=os.getenv("EOAT_API_ENVIRONMENT", "development"),
        writes_enabled=os.getenv("EOAT_API_WRITES_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"},
        api_version=API_VERSION,
        application_version=RELEASE_INFO.application_version,
        release_id=RELEASE_INFO.release_id,
        build_id=RELEASE_INFO.build_id,
        api_contract_version=API_VERSION,
        database_schema_revision=EXPECTED_SCHEMA_REVISION,
        database_server_version=svc.database_server_version(),
        server_timestamp=datetime.now(timezone.utc),
    )


@app.get("/api/v1/version")
def version():
    return {
        "service": "EOAT Atlas API",
        "application_version": RELEASE_INFO.application_version,
        "release_id": RELEASE_INFO.release_id,
        "build_id": RELEASE_INFO.build_id,
        "api_version": API_VERSION,
        "api_contract_version": API_VERSION,
        "database_schema_revision": EXPECTED_SCHEMA_REVISION,
        "server_revision": SERVER_REVISION,
    }


@app.get("/api/v1/release-status")
def release_status(request: Request):
    """Safe, authoritative active-release status for launchers and web clients."""

    minimum_desktop = os.getenv("EOAT_MINIMUM_SUPPORTED_DESKTOP_VERSION", "0.0.0").strip()
    client_version = request.headers.get("X-EOAT-Client-Version", "").strip()
    supplied_release = request.headers.get("X-EOAT-Client-Release-ID", "").strip()
    supplied_build = request.headers.get("X-EOAT-Client-Build-ID", "").strip()
    supplied_digest = request.headers.get("X-EOAT-Client-Release-Set-Digest", "").strip()
    identity = runtime_release_identity()
    release_set_digest = str(identity["release_set_digest"] or "")
    try:
        supported = not client_version or Version.parse(client_version) >= Version.parse(minimum_desktop)
    except ValueError:
        supported = False
    identity_match = (
        (not supplied_release or supplied_release == identity["release_id"])
        and (not supplied_build or supplied_build == identity["build_id"])
        and (not release_set_digest or supplied_digest == release_set_digest)
    )
    return {
        **identity,
        "api_contract_version": API_VERSION,
        "database_schema_revision": EXPECTED_SCHEMA_REVISION,
        "minimum_supported_desktop_version": minimum_desktop,
        "minimum_supported_launcher_version": os.getenv("EOAT_MINIMUM_SUPPORTED_LAUNCHER_VERSION", "0.1.0"),
        "minimum_supported_bootstrap_version": os.getenv("EOAT_MINIMUM_SUPPORTED_BOOTSTRAP_VERSION", "0.1.0"),
        "client_version": client_version or None,
        "client_identity": {
            "product_version": client_version or None,
            "release_id": supplied_release or None,
            "build_id": supplied_build or None,
            "release_set_digest": supplied_digest or None,
        },
        "client_supported": supported and identity_match,
        "client_compatibility": "MATCH" if supported and identity_match else "MISMATCH",
        "mismatch_reason": "release identity does not match active API"
        if not identity_match
        else ("minimum desktop version is not met" if not supported else None),
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/schema-status")
def schema_status(svc: AtlasService = Depends(service)):
    current = svc.schema_revision()
    return {
        "current_revision": current,
        "expected_revision": EXPECTED_SCHEMA_REVISION,
        "compatible": current == EXPECTED_SCHEMA_REVISION,
    }


@app.get("/api/v1/server-status")
def server_status(svc: AtlasService = Depends(service)):
    status = svc.sync_status()
    return {
        **status.model_dump(),
        "application_version": RELEASE_INFO.application_version,
        "release_id": RELEASE_INFO.release_id,
        "build_id": RELEASE_INFO.build_id,
        "api_contract_version": API_VERSION,
        "database_schema_revision": EXPECTED_SCHEMA_REVISION,
        "environment": os.getenv("EOAT_API_ENVIRONMENT", "development"),
        "read_only_phase": False,
        "writes_enabled": os.getenv("EOAT_API_WRITES_ENABLED", "false").strip().casefold()
        in {"1", "true", "yes", "on"},
    }


@app.get("/api/v1/data-status", response_model=DataStatusResponse)
def data_status(svc: AtlasService = Depends(service)):
    """Return only transaction-authoritative freshness metadata; never data rows."""
    return svc.data_status()


@app.get("/api/v1/lookups")
def lookups(repo: AtlasRepository = Depends(repository)):
    return repo.lookups()


@app.get("/api/v1/lookups/{lookup_type}")
def lookup(lookup_type: str, repo: AtlasRepository = Depends(repository)):
    if lookup_type not in LOOKUP_MODELS:
        raise not_found("Lookup type", lookup_type)
    return repo.lookups(lookup_type)[lookup_type]


@app.get("/api/v1/eoats", response_model=PaginatedEOATs)
def eoats(
    search: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    sort: str = "business_identifier",
    active: bool | None = True,
    eoat_type: str | None = None,
    area: str | None = None,
    cleanroom: str | None = None,
    machine_number: str | None = None,
    tool_number: str | None = None,
    include_inactive: bool = False,
    repo: AtlasRepository = Depends(repository),
):
    items, pagination = repo.list_eoats(
        search=search,
        page=page,
        page_size=page_size,
        sort=sort,
        active=None if include_inactive else active,
        eoat_type=eoat_type,
        area=area,
        cleanroom=cleanroom,
        machine_number=machine_number,
        tool_number=tool_number,
    )
    return PaginatedEOATs(items=items, pagination=pagination)


@app.get("/api/v1/eoats/{identifier}", response_model=EOATProfile)
def eoat(identifier: str, repo: AtlasRepository = Depends(repository)):
    value = repo.eoat(identifier)
    if value is None:
        raise not_found("EOAT", identifier)
    return value


def _eoat_entity(repo: AtlasRepository, identifier: str):
    entity = repo.resolve_eoat_identity(identifier)
    if entity is None:
        raise not_found("EOAT", identifier)
    return entity


@app.get("/api/v1/eoats/{identifier}/current-location", response_model=CurrentEOATLocation)
def eoat_current_location(identifier: str, repo: AtlasRepository = Depends(repository)):
    entity = _eoat_entity(repo, identifier)
    from .location_resolver import resolve_eoat_location

    return resolve_eoat_location(repo.session, entity.id)


@app.get("/api/v1/eoats/{identifier}/location-observations")
def eoat_location_observations(identifier: str, repo: AtlasRepository = Depends(repository)):
    entity = _eoat_entity(repo, identifier)
    rows = repo.session.scalars(
        __import__("sqlalchemy")
        .select(db.EOATLocationObservation)
        .where(db.EOATLocationObservation.eoat_id == entity.id)
        .order_by(db.EOATLocationObservation.observed_on.desc(), db.EOATLocationObservation.id.desc())
    )
    return [
        {
            "event_kind": "OBSERVED_CURRENT_STATE",
            "observation_uuid": row.observation_uuid,
            "state": row.state,
            "observed_at": row.observed_at,
            "observed_on": row.observed_on,
            "observation_precision": row.observation_precision,
            "confidence": row.confidence,
            "resolution_status": row.resolution_status,
            "source_workbook": row.source_workbook,
            "source_worksheet": row.source_worksheet,
            "source_row_number": row.source_row_number,
            "evidence": row.original_source_wording,
        }
        for row in rows
    ]


@app.get("/api/v1/eoats/{identifier}/relationships", response_model=list[RelationshipSummary])
def eoat_relationships(identifier: str, repo: AtlasRepository = Depends(repository)):
    if repo.eoat(identifier) is None:
        raise not_found("EOAT", identifier)
    return repo.eoat_relationships(identifier)


@app.get("/api/v1/eoats/{identifier}/history", response_model=PaginatedHistory)
def eoat_history(
    identifier: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    event_category: str | None = None,
    event_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str = Query("", max_length=200),
    repo: AtlasRepository = Depends(repository),
):
    entity = _eoat_entity(repo, identifier)
    return repo.history_page(
        "eoat",
        entity.id,
        eoat_identifier=entity.business_identifier,
        page=page,
        page_size=page_size,
        sort_order=sort_order,
        event_category=event_category,
        event_type=event_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )


@app.get("/api/v1/eoats/{identifier}/documents")
def eoat_documents(identifier: str, repo: AtlasRepository = Depends(repository)):
    entity = _eoat_entity(repo, identifier)
    return repo.documents("eoat", entity.id)


@app.get("/api/v1/eoats/{identifier}/photos")
def eoat_photos(identifier: str, repo: AtlasRepository = Depends(repository)):
    entity = _eoat_entity(repo, identifier)
    return repo.documents("eoat", entity.id, photos_only=True)


def _web_document_metadata(value: DocumentMetadata | PhotoMetadata) -> WebDocumentMetadata | WebPhotoMetadata:
    """Remove internal path details before a document is visible to browser clients."""
    common = {
        "document_uuid": value.document_uuid,
        "document_number": value.document_number,
        "title": value.title,
        "description": value.description,
        "file_name": value.file_name,
        "mime_type": value.mime_type,
        "related_entities": value.related_entities,
        "content_delivery_state": "AVAILABLE"
        if content_is_available(value.storage_path)
        else "NOT_AVAILABLE_THROUGH_WEB",
    }
    if isinstance(value, PhotoMetadata):
        return WebPhotoMetadata(
            **common,
            photo_view_type=value.photo_view_type,
            captured_at=value.captured_at,
            caption=value.caption,
            is_profile_photo=value.is_profile_photo,
        )
    return WebDocumentMetadata(**common)


@app.get("/api/v1/eoats/{identifier}/web-documents", response_model=list[WebDocumentMetadata])
def eoat_web_documents(identifier: str, repo: AtlasRepository = Depends(repository)):
    """Return EOAT document metadata without server or network storage paths."""
    entity = _eoat_entity(repo, identifier)
    return [
        _web_document_metadata(value)
        for value in repo.documents("eoat", entity.id)
        if not isinstance(value, PhotoMetadata)
    ]


@app.get("/api/v1/eoats/{identifier}/web-photos", response_model=list[WebPhotoMetadata])
def eoat_web_photos(identifier: str, repo: AtlasRepository = Depends(repository)):
    """Return EOAT photo metadata without exposing a browser-reachable file path."""
    entity = _eoat_entity(repo, identifier)
    return [
        _web_document_metadata(value)
        for value in repo.documents("eoat", entity.id, photos_only=True)
        if isinstance(value, PhotoMetadata)
    ]


@app.get("/api/v1/web-documents/{document_uuid}/content", response_model=None)
def web_document_content(document_uuid: str, session: Session = Depends(get_runtime_session)):
    """Serve a document only after UUID lookup and approved-root validation."""
    return content_response(session, document_uuid, photo_only=False)


@app.get("/api/v1/web-photos/{document_uuid}/content", response_model=None)
def web_photo_content(document_uuid: str, session: Session = Depends(get_runtime_session)):
    """Serve a photo only after UUID lookup and approved-root validation."""
    return content_response(session, document_uuid, photo_only=True)


@app.get("/api/v1/web-photos/{document_uuid}/thumbnail", response_model=None)
def web_photo_thumbnail(document_uuid: str, session: Session = Depends(get_runtime_session)):
    return thumbnail_response(session, document_uuid)


def _machine_entity(repo: AtlasRepository, number: str, plant_code: str | None = None):
    profile = repo.machine(number, plant_code=plant_code)
    if profile is None:
        raise not_found("Machine", number)
    statement = __import__("sqlalchemy").select(db.Machine).where(db.Machine.machine_number == number)
    statement = statement.join(db.Plant).where(db.Plant.plant_code == profile.plant_code)
    return repo.session.scalar(statement)


def _tool_entity(repo: AtlasRepository, identifier: str):
    profile = repo.tool(identifier)
    if profile is None:
        raise not_found("Tool", identifier)
    return repo.session.scalar(
        __import__("sqlalchemy").select(db.Tool).where(db.Tool.business_identifier == profile.business_identifier)
    )


def _web_documents(repo: AtlasRepository, entity_type: str, entity_id: int, *, photos_only: bool):
    return [
        _web_document_metadata(value)
        for value in repo.documents(entity_type, entity_id, photos_only=photos_only)
        if isinstance(value, PhotoMetadata) is photos_only
    ]


@app.get("/api/v1/machines", response_model=PaginatedMachines)
def machines(
    search: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    active: bool | None = True,
    plant: str | None = None,
    area: str | None = None,
    cleanroom: str | None = None,
    eoat_identifier: str | None = None,
    tool_number: str | None = None,
    robot_number: str | None = None,
    sort: str = "machine_number",
    include_inactive: bool = False,
    repo: AtlasRepository = Depends(repository),
):
    items, pagination = repo.list_machines(
        search=search,
        page=page,
        page_size=page_size,
        active=None if include_inactive else active,
        plant=plant,
        area=area,
        cleanroom=cleanroom,
        eoat_identifier=eoat_identifier,
        tool_number=tool_number,
        robot_number=robot_number,
        sort=sort,
    )
    return PaginatedMachines(items=items, pagination=pagination)


@app.get("/api/v1/machines/{number}", response_model=MachineProfile)
def machine(number: str, plant_code: str | None = None, repo: AtlasRepository = Depends(repository)):
    value = repo.machine(number, plant_code=plant_code)
    if value is None:
        raise not_found("Machine", number)
    return value


@app.get("/api/v1/machines/{number}/relationships", response_model=list[RelationshipSummary])
def machine_relationships(number: str, plant_code: str | None = None, repo: AtlasRepository = Depends(repository)):
    value = repo.machine(number, plant_code=plant_code)
    if value is None:
        raise not_found("Machine", number)
    return value.relationships + value.robots


@app.get("/api/v1/machines/{number}/current-setup", response_model=MachineCurrentSetup)
def machine_current_setup(number: str, plant_code: str | None = None, repo: AtlasRepository = Depends(repository)):
    value = repo.machine(number, plant_code=plant_code)
    if value is None:
        raise not_found("Machine", number)
    return {
        "machine_number": number,
        "current_eoat": value.current_eoat,
        "current_tool": "UNKNOWN_NOT_VERIFIED",
        "verified": value.current_eoat not in {"NONE_OBSERVED", "UNKNOWN_NOT_VERIFIED"},
        "location_semantics": "OBSERVATION_OR_LATER_LIFECYCLE_EVENT",
    }


@app.get("/api/v1/machines/{number}/history", response_model=list[HistoryEvent])
def machine_history(number: str, plant_code: str | None = None, repo: AtlasRepository = Depends(repository)):
    profile = repo.machine(number, plant_code=plant_code)
    if profile is None:
        raise not_found("Machine", number)
    statement = __import__("sqlalchemy").select(db.Machine).where(db.Machine.machine_number == number)
    statement = statement.join(db.Plant).where(db.Plant.plant_code == profile.plant_code)
    entity = repo.session.scalar(statement)
    return repo.history("machine", entity.id)


@app.get("/api/v1/machines/{number}/web-documents", response_model=list[WebDocumentMetadata])
def machine_web_documents(number: str, plant_code: str | None = None, repo: AtlasRepository = Depends(repository)):
    entity = _machine_entity(repo, number, plant_code)
    return _web_documents(repo, "machine", entity.id, photos_only=False)


@app.get("/api/v1/machines/{number}/web-photos", response_model=list[WebPhotoMetadata])
def machine_web_photos(number: str, plant_code: str | None = None, repo: AtlasRepository = Depends(repository)):
    entity = _machine_entity(repo, number, plant_code)
    return _web_documents(repo, "machine", entity.id, photos_only=True)


@app.get("/api/v1/tools", response_model=PaginatedTools)
def tools(
    search: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    active: bool | None = True,
    mold: str | None = None,
    machine_number: str | None = None,
    eoat_identifier: str | None = None,
    sort: str = "business_identifier",
    include_inactive: bool = False,
    repo: AtlasRepository = Depends(repository),
):
    items, pagination = repo.list_tools(
        search=search,
        page=page,
        page_size=page_size,
        active=None if include_inactive else active,
        mold=mold,
        machine_number=machine_number,
        eoat_identifier=eoat_identifier,
        sort=sort,
    )
    return PaginatedTools(items=items, pagination=pagination)


@app.get("/api/v1/tools/{identifier}", response_model=ToolProfile)
def tool(identifier: str, repo: AtlasRepository = Depends(repository)):
    value = repo.tool(identifier)
    if value is None:
        raise not_found("Tool", identifier)
    return value


@app.get("/api/v1/tools/{identifier}/relationships", response_model=list[RelationshipSummary])
def tool_relationships(identifier: str, repo: AtlasRepository = Depends(repository)):
    value = repo.tool(identifier)
    if value is None:
        raise not_found("Tool", identifier)
    return value.relationships


@app.get("/api/v1/tools/{identifier}/history", response_model=list[HistoryEvent])
def tool_history(identifier: str, repo: AtlasRepository = Depends(repository)):
    entity = repo.session.scalar(
        __import__("sqlalchemy").select(db.Tool).where(db.Tool.business_identifier == identifier)
    )
    if entity is None:
        raise not_found("Tool", identifier)
    return repo.history("tool", entity.id)


@app.get("/api/v1/tools/{identifier}/web-documents", response_model=list[WebDocumentMetadata])
def tool_web_documents(identifier: str, repo: AtlasRepository = Depends(repository)):
    entity = _tool_entity(repo, identifier)
    return _web_documents(repo, "tool", entity.id, photos_only=False)


@app.get("/api/v1/tools/{identifier}/web-photos", response_model=list[WebPhotoMetadata])
def tool_web_photos(identifier: str, repo: AtlasRepository = Depends(repository)):
    entity = _tool_entity(repo, identifier)
    return _web_documents(repo, "tool", entity.id, photos_only=True)


@app.get("/api/v1/search", response_model=list[SearchResult])
def search(
    q: str = Query(..., min_length=1), limit: int = Query(50, ge=1, le=250), repo: AtlasRepository = Depends(repository)
):
    return repo.search(q, limit=limit)


@app.post("/api/v1/web-fit-checks/evaluate", response_model=FitCheckResult)
def evaluate_web_fit_check(payload: WebFitCheckRequest, session: Session = Depends(get_runtime_session)):
    """Browser-only compatibility evaluation; this route has no persistence path."""
    request = FitCheckRequest(**payload.model_dump(), persist=False)
    return AtlasService(session).fit_check(request)


@app.get("/api/v1/web-fit-checks/options", response_model=WebFitCheckOptions)
def web_fit_check_options(
    machine_number: str | None = None,
    plant_code: str | None = None,
    tool_number: str | None = None,
    eoat_identifier: str | None = None,
    session: Session = Depends(get_runtime_session),
):
    """Return candidates compatible with a partial browser Fit Check selection.

    The endpoint deliberately excludes inactive and archived assets and only
    suggests relationships whose status is explicitly compatible and effective
    now. It does not turn an absent relationship into a compatibility claim.
    """
    now = datetime.now(timezone.utc)

    archived_statuses = select(db.AssetStatus.id).where(db.AssetStatus.code == "archived")

    def available(model):
        return (
            model.is_active.is_(True),
            or_(model.status_id.is_(None), model.status_id.not_in(archived_statuses)),
        )

    def available_object(value) -> bool:
        if value is None or not value.is_active:
            return False
        status_code = (
            session.scalar(select(db.AssetStatus.code).where(db.AssetStatus.id == value.status_id))
            if value.status_id is not None
            else None
        )
        return (status_code or "").strip().casefold() != "archived"

    def compatible_ids(model, column, *criteria):
        return set(
            session.scalars(
                select(column)
                .join(db.CompatibilityStatus, db.CompatibilityStatus.id == model.compatibility_status_id)
                .where(
                    *criteria,
                    model.is_active.is_(True),
                    model.effective_from <= now,
                    or_(model.effective_to.is_(None), model.effective_to >= now),
                    db.CompatibilityStatus.code.in_(COMPATIBLE_STATUS_CODES),
                )
            )
        )

    machine_query = select(db.Machine).where(db.Machine.machine_number == machine_number) if machine_number else None
    if machine_query is not None and plant_code:
        machine_query = machine_query.join(db.Plant, db.Plant.id == db.Machine.plant_id).where(
            db.Plant.plant_code == plant_code,
            db.Plant.is_active.is_(True),
        )
    machine_candidates = (
        [value for value in session.scalars(machine_query.order_by(db.Machine.id)).all() if available_object(value)]
        if machine_query is not None
        else []
    )
    machine = machine_candidates[0] if len(machine_candidates) == 1 else None
    tool_candidates = (
        list(
            session.scalars(
                select(db.Tool)
                .where(or_(db.Tool.business_identifier == tool_number, db.Tool.tool_number == tool_number))
                .order_by(db.Tool.id)
            ).all()
        )
        if tool_number
        else []
    )
    tool = tool_candidates[0] if len(tool_candidates) == 1 and available_object(tool_candidates[0]) else None
    resolved_eoat = AtlasRepository(session).resolve_eoat_identity(eoat_identifier) if eoat_identifier else None
    eoat = resolved_eoat if resolved_eoat is not None and available_object(resolved_eoat) else None
    machine_ids: set[int] | None = None
    tool_ids: set[int] | None = None
    eoat_ids: set[int] | None = None

    def intersect(current, values):
        return values if current is None else current & values

    if machine:
        tool_ids = intersect(
            tool_ids,
            compatible_ids(
                db.ToolMachineCompatibility,
                db.ToolMachineCompatibility.tool_id,
                db.ToolMachineCompatibility.machine_id == machine.id,
            ),
        )
        eoat_ids = intersect(
            eoat_ids,
            compatible_ids(
                db.EOATMachineCompatibility,
                db.EOATMachineCompatibility.eoat_id,
                db.EOATMachineCompatibility.machine_id == machine.id,
            ),
        )
    if tool:
        machine_ids = intersect(
            machine_ids,
            compatible_ids(
                db.ToolMachineCompatibility,
                db.ToolMachineCompatibility.machine_id,
                db.ToolMachineCompatibility.tool_id == tool.id,
            ),
        )
        eoat_ids = intersect(
            eoat_ids,
            compatible_ids(
                db.EOATToolCompatibility,
                db.EOATToolCompatibility.eoat_id,
                db.EOATToolCompatibility.tool_id == tool.id,
            ),
        )
    if eoat:
        machine_ids = intersect(
            machine_ids,
            compatible_ids(
                db.EOATMachineCompatibility,
                db.EOATMachineCompatibility.machine_id,
                db.EOATMachineCompatibility.eoat_id == eoat.id,
            ),
        )
        tool_ids = intersect(
            tool_ids,
            compatible_ids(
                db.EOATToolCompatibility,
                db.EOATToolCompatibility.tool_id,
                db.EOATToolCompatibility.eoat_id == eoat.id,
            ),
        )

    machine_filters = [*available(db.Machine)]
    if machine_ids is not None:
        machine_filters.append(db.Machine.id.in_(machine_ids))
    tool_filters = [*available(db.Tool)]
    if tool_ids is not None:
        tool_filters.append(db.Tool.id.in_(tool_ids))
    eoat_filters = [*available(db.EOAT)]
    if eoat_ids is not None:
        eoat_filters.append(db.EOAT.id.in_(eoat_ids))

    machines = list(
        session.execute(
            select(db.Machine, db.Plant.plant_code)
            .join(db.Plant, db.Plant.id == db.Machine.plant_id)
            .where(*machine_filters, db.Plant.is_active.is_(True))
            .order_by(db.Plant.plant_code, db.Machine.machine_number)
        ).all()
    )
    tools = list(session.scalars(select(db.Tool).where(*tool_filters).order_by(db.Tool.business_identifier)).all())
    eoats = list(session.scalars(select(db.EOAT).where(*eoat_filters).order_by(db.EOAT.business_identifier)).all())
    warnings: list[str] = []
    unresolved_inputs: list[str] = []
    if machine_number and len(machine_candidates) != 1:
        warnings.append("Machine selection is unknown, unavailable, or ambiguous; choose a plant code when necessary.")
        unresolved_inputs.append("machine")
    if tool_number and tool is None:
        warnings.append("Tool selection is unknown, unavailable, or ambiguous; use its business identifier.")
        unresolved_inputs.append("tool")
    if eoat_identifier and eoat is None:
        warnings.append("EOAT selection is unknown or unavailable.")
        unresolved_inputs.append("eoat")

    return {
        "machines": [
            FitCheckOption(
                identifier=value.machine_number,
                label=value.machine_name or value.machine_number,
                plant_code=plant_code_value,
            )
            for value, plant_code_value in machines
        ],
        "tools": [
            FitCheckOption(
                identifier=value.business_identifier,
                label=value.display_name or value.tool_number or value.business_identifier,
            )
            for value in tools
        ],
        "eoats": [
            FitCheckOption(
                identifier=value.business_identifier,
                label=value.display_name or value.business_identifier,
            )
            for value in eoats
        ],
        "warnings": warnings,
        "unresolved_inputs": unresolved_inputs,
    }


@app.post("/api/v1/fit-checks/evaluate")
def evaluate_fit_check(
    payload: FitCheckRequest,
    request: Request,
    session: Session = Depends(get_write_session),
):
    svc = AtlasService(session)
    result = svc.fit_check(payload)
    if not payload.persist:
        return result
    actor = actor_context(request, session)
    if not actor.permits("fit_check.write"):
        raise APIError(403, "PERMISSION_DENIED", "This identity cannot store Fit Check history.")
    try:
        with session.begin_nested():
            return svc.persist_fit_check(payload, result, actor)
    except SQLAlchemyError:
        LOGGER.exception("optional_fit_check_history_failed request_id=%s", actor.request_id)
        return result.model_copy(
            update={"warnings": [*result.warnings, "The evaluation succeeded, but optional history storage failed."]}
        )


@app.get("/api/v1/fit-checks/recent")
def recent_fit_checks(limit: int = Query(25, ge=1, le=250), repo: AtlasRepository = Depends(repository)):
    rows = repo.session.scalars(
        __import__("sqlalchemy").select(db.FitCheckRecord).order_by(db.FitCheckRecord.performed_at.desc()).limit(limit)
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "machine_id": row.machine_id,
                "tool_id": row.tool_id,
                "eoat_id": row.eoat_id,
                "performed_at": row.performed_at,
                "evaluation_engine_version": row.evaluation_engine_version,
                "request_id": row.request_id,
                "result_summary": row.result_summary,
                "result_details": row.result_details_json,
            }
            for row in rows
        ],
        "storage_enabled": True,
    }


@app.get("/api/v1/compatibility/alternatives")
def alternatives(
    machine_number: str,
    tool_number: str,
    eoat_identifier: str,
    plant_code: str | None = None,
    svc: AtlasService = Depends(service),
):
    result = svc.fit_check(
        FitCheckRequest(
            plant_code=plant_code,
            machine_number=machine_number,
            tool_number=tool_number,
            eoat_identifier=eoat_identifier,
        )
    )
    return {
        "alternatives": result.alternative_compatible_eoats,
        "evaluation_engine_version": result.evaluation_engine_version,
    }


@app.get("/api/v1/setup-packets/data")
def setup_packet_data(
    machine_number: str,
    tool_number: str,
    eoat_identifier: str,
    plant_code: str | None = None,
    repo: AtlasRepository = Depends(repository),
    svc: AtlasService = Depends(service),
):
    machine_value = repo.machine(machine_number, plant_code=plant_code)
    tool_value = repo.tool(tool_number)
    eoat_value = repo.eoat(eoat_identifier)
    if not all((machine_value, tool_value, eoat_value)):
        raise HTTPException(
            status_code=404,
            detail={"code": "SETUP_CONTEXT_NOT_FOUND", "message": "One or more setup entities were not found."},
        )
    return {
        "machine": machine_value,
        "tool": tool_value,
        "eoat": eoat_value,
        "fit_check": svc.fit_check(
            FitCheckRequest(
                plant_code=plant_code,
                machine_number=machine_number,
                tool_number=tool_number,
                eoat_identifier=eoat_identifier,
            )
        ),
        "generated_at": datetime.now(timezone.utc),
        "source": "mysql_api",
    }


@app.get("/api/v1/sync/status")
def sync_status(svc: AtlasService = Depends(service)):
    return svc.sync_status()


@app.get("/api/v1/sync/changes")
def sync_changes(
    after_cursor: int = Query(0, ge=0), limit: int = Query(1000, ge=1, le=5000), svc: AtlasService = Depends(service)
):
    return svc.changes(after_cursor, limit)


@app.get("/api/v1/sync/snapshot")
def sync_snapshot(svc: AtlasService = Depends(service)):
    return svc.snapshot()


@app.get("/api/v1/home-summary")
def home_summary(repo: AtlasRepository = Depends(repository)):
    eoats_count = (
        repo.session.scalar(__import__("sqlalchemy").select(__import__("sqlalchemy").func.count(db.EOAT.id))) or 0
    )
    machines_count = (
        repo.session.scalar(__import__("sqlalchemy").select(__import__("sqlalchemy").func.count(db.Machine.id))) or 0
    )
    tools_count = (
        repo.session.scalar(__import__("sqlalchemy").select(__import__("sqlalchemy").func.count(db.Tool.id))) or 0
    )
    unresolved = (
        repo.session.scalar(
            __import__("sqlalchemy")
            .select(__import__("sqlalchemy").func.count(db.ImportIssue.id))
            .where(db.ImportIssue.resolved_at.is_(None))
        )
        or 0
    )
    return {
        "eoats": eoats_count,
        "machines": machines_count,
        "tools": tools_count,
        "unresolved_migration_issues": unresolved,
        "backend": "mysql_api",
    }


app.include_router(write_router)
