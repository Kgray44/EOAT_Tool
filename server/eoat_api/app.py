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
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.versioning import configure_release_logging, get_release_info

from .authentication.audit import record_auth_event
from .authentication.configuration import AuthenticationConfiguration
from .authentication.routes import router as authentication_router
from .contracts import (
    FitCheckRequest,
    HealthResult,
    PaginatedEOATs,
    PaginatedHistory,
    PaginatedMachines,
    PaginatedTools,
)
from .database import models as db
from .database.session import create_session_factory, dispose_database_engines, get_runtime_session, get_write_session
from .errors import APIError
from .repositories import LOOKUP_MODELS, AtlasRepository
from .security import actor_context
from .services import API_VERSION, EXPECTED_SCHEMA_REVISION, SERVER_REVISION, AtlasService
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
async def request_logging(request: Request, call_next):
    started = datetime.now(timezone.utc)
    request.state.request_id = request.headers.get("X-Request-ID") or str(uuid4())
    status: int | str = "UNHANDLED_EXCEPTION"
    try:
        environment = os.getenv("EOAT_API_ENVIRONMENT", "development").strip().casefold()
        protected = request.url.path.startswith("/api/v1/") and request.url.path not in {
            "/api/v1/health",
            "/api/v1/version",
        }
        if environment == "production" and protected:
            configured_token = os.getenv("EOAT_API_DEVICE_TOKEN", "")
            supplied_token = request.headers.get("X-EOAT-Device-Token", "")
            if not configured_token:
                status = 503
                return JSONResponse(
                    status_code=503,
                    content={"error_code": "DEVICE_AUTH_NOT_CONFIGURED", "message": "Production read authentication is not configured.", "request_id": request.state.request_id},
                    headers={"X-Request-ID": request.state.request_id},
                )
            if not supplied_token or not secrets.compare_digest(supplied_token, configured_token):
                status = 401
                return JSONResponse(
                    status_code=401,
                    content={"error_code": "DEVICE_AUTH_REQUIRED", "message": "An approved device credential is required.", "request_id": request.state.request_id},
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
                        "SETTINGS_ADMIN_LOGIN_FAILED"
                        if exc.status_code == 401
                        else "SETTINGS_ADMIN_ACCESS_DENIED",
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
    repo: AtlasRepository = Depends(repository),
):
    items, pagination = repo.list_eoats(
        search=search,
        page=page,
        page_size=page_size,
        sort=sort,
        active=active,
        eoat_type=eoat_type,
        area=area,
        cleanroom=cleanroom,
    )
    return PaginatedEOATs(items=items, pagination=pagination)


@app.get("/api/v1/eoats/{identifier}")
def eoat(identifier: str, repo: AtlasRepository = Depends(repository)):
    value = repo.eoat(identifier)
    if value is None:
        raise not_found("EOAT", identifier)
    return value


@app.get("/api/v1/eoats/{identifier}/relationships")
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
    entity = repo.session.scalar(
        __import__("sqlalchemy").select(db.EOAT).where(db.EOAT.business_identifier == identifier)
    )
    if entity is None:
        raise not_found("EOAT", identifier)
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
    entity = repo.session.scalar(
        __import__("sqlalchemy").select(db.EOAT).where(db.EOAT.business_identifier == identifier)
    )
    if entity is None:
        raise not_found("EOAT", identifier)
    return repo.documents("eoat", entity.id)


@app.get("/api/v1/eoats/{identifier}/photos")
def eoat_photos(identifier: str, repo: AtlasRepository = Depends(repository)):
    entity = repo.session.scalar(
        __import__("sqlalchemy").select(db.EOAT).where(db.EOAT.business_identifier == identifier)
    )
    if entity is None:
        raise not_found("EOAT", identifier)
    return repo.documents("eoat", entity.id, photos_only=True)


@app.get("/api/v1/machines", response_model=PaginatedMachines)
def machines(
    search: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    active: bool | None = True,
    repo: AtlasRepository = Depends(repository),
):
    items, pagination = repo.list_machines(search=search, page=page, page_size=page_size, active=active)
    return PaginatedMachines(items=items, pagination=pagination)


@app.get("/api/v1/machines/{number}")
def machine(number: str, repo: AtlasRepository = Depends(repository)):
    value = repo.machine(number)
    if value is None:
        raise not_found("Machine", number)
    return value


@app.get("/api/v1/machines/{number}/relationships")
def machine_relationships(number: str, repo: AtlasRepository = Depends(repository)):
    value = repo.machine(number)
    if value is None:
        raise not_found("Machine", number)
    return value.relationships + value.robots


@app.get("/api/v1/machines/{number}/current-setup")
def machine_current_setup(number: str, repo: AtlasRepository = Depends(repository)):
    value = repo.machine(number)
    if value is None:
        raise not_found("Machine", number)
    return {
        "machine_number": number,
        "current_eoat": "UNKNOWN_NOT_VERIFIED",
        "current_tool": "UNKNOWN_NOT_VERIFIED",
        "verified": False,
    }


@app.get("/api/v1/machines/{number}/history")
def machine_history(number: str, repo: AtlasRepository = Depends(repository)):
    entity = repo.session.scalar(__import__("sqlalchemy").select(db.Machine).where(db.Machine.machine_number == number))
    if entity is None:
        raise not_found("Machine", number)
    return repo.history("machine", entity.id)


@app.get("/api/v1/tools", response_model=PaginatedTools)
def tools(
    search: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    active: bool | None = True,
    repo: AtlasRepository = Depends(repository),
):
    items, pagination = repo.list_tools(search=search, page=page, page_size=page_size, active=active)
    return PaginatedTools(items=items, pagination=pagination)


@app.get("/api/v1/tools/{identifier}")
def tool(identifier: str, repo: AtlasRepository = Depends(repository)):
    value = repo.tool(identifier)
    if value is None:
        raise not_found("Tool", identifier)
    return value


@app.get("/api/v1/tools/{identifier}/relationships")
def tool_relationships(identifier: str, repo: AtlasRepository = Depends(repository)):
    value = repo.tool(identifier)
    if value is None:
        raise not_found("Tool", identifier)
    return value.relationships


@app.get("/api/v1/tools/{identifier}/history")
def tool_history(identifier: str, repo: AtlasRepository = Depends(repository)):
    entity = repo.session.scalar(
        __import__("sqlalchemy").select(db.Tool).where(db.Tool.business_identifier == identifier)
    )
    if entity is None:
        raise not_found("Tool", identifier)
    return repo.history("tool", entity.id)


@app.get("/api/v1/search")
def search(
    q: str = Query(..., min_length=1), limit: int = Query(50, ge=1, le=250), repo: AtlasRepository = Depends(repository)
):
    return repo.search(q, limit=limit)


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
    machine_value = repo.machine(machine_number)
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
