from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy import or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .admin.corporate_user_routes import router as admin_corporate_user_router
from .admin.mutation_routes import router as admin_mutation_router
from .admin.operation_routes import router as admin_operation_router
from .admin.routes import router as admin_router
from .contracts import (
    CurrentEOATLocation,
    DataStatus,
    EOATProfile,
    FitCheckOption,
    FitCheckRequest,
    FitCheckResult,
    HealthResult,
    MachineProfile,
    PaginatedEOATs,
    PaginatedHistory,
    PaginatedMachines,
    PaginatedTools,
    RelationshipSummary,
    ToolProfile,
    WebDocumentMetadata,
    WebFitCheckOptions,
    WebPhotoMetadata,
)
from .corporate_auth_routes import router as corporate_auth_router
from .database import models as db
from .database.session import get_runtime_session, get_write_session
from .errors import APIError
from .repositories import LOOKUP_MODELS, AtlasRepository
from .qr_label_pdf import generate_eoat_qr_label_pdf
from .security import actor_context
from .services import (
    API_VERSION,
    EXPECTED_SCHEMA_REVISION,
    SELECTABLE_COMPATIBILITY_STATUS_CODES,
    SERVER_REVISION,
    AtlasService,
)
from .web_content import content_is_available, content_response, thumbnail_response
from .write_routes import router as write_router

logging.basicConfig(
    level=os.getenv("EOAT_API_LOG_LEVEL", "INFO"),
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)
LOGGER = logging.getLogger("eoat_api")
app = FastAPI(title="EOAT Atlas API", version=API_VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json")


_FORWARDED_HOST = re.compile(r"^[A-Za-z0-9.-]+(?::[0-9]{1,5})?$")


def _external_request_origin(request: Request) -> str:
    """Use the proxy's complete validated host when a non-default port matters."""
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    forwarded_scheme = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    if _FORWARDED_HOST.fullmatch(forwarded_host) and forwarded_scheme in {"http", "https"}:
        return f"{forwarded_scheme}://{forwarded_host}"
    return str(request.base_url).rstrip("/")


def _browser_safe_documents(rows):
    """Remove storage/internal fields before normal browser serialization."""
    safe = []
    for row in rows:
        values = row.model_dump(exclude={"storage_path", "path_available"})
        values["content_delivery_state"] = (
            "AVAILABLE"
            if content_is_available(
                row.storage_path,
                document_uuid=row.document_uuid,
                photo="photo_view_type" in values,
            )
            else "NOT_AVAILABLE_THROUGH_WEB"
        )
        safe.append(WebPhotoMetadata(**values) if "photo_view_type" in values else WebDocumentMetadata(**values))
    return safe


@app.middleware("http")
async def request_logging(request: Request, call_next):
    started = datetime.now(timezone.utc)
    request.state.request_id = request.headers.get("X-Request-ID") or str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    elapsed = (datetime.now(timezone.utc) - started).total_seconds() * 1000
    LOGGER.info(
        "method=%s path=%s status=%s elapsed_ms=%.2f", request.method, request.url.path, response.status_code, elapsed
    )
    return response


@app.exception_handler(APIError)
async def api_error(request: Request, exc: APIError):
    if exc.status_code in {401, 403}:
        LOGGER.warning(
            "security_denial request_id=%s code=%s identity=%s",
            getattr(request.state, "request_id", ""),
            exc.error_code,
            request.headers.get("X-EOAT-Identity", "<missing>"),
        )
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
        server_timestamp=datetime.now(timezone.utc),
    )


@app.get("/api/v1/data-status", response_model=DataStatus)
def data_status(svc: AtlasService = Depends(service)):
    return svc.data_status()


@app.get("/api/v1/version")
def version():
    return {"api_version": API_VERSION, "server_revision": SERVER_REVISION}


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
    page_size: int | None = Query(None, ge=1, le=250),
    sort: str = Query(
        "natural_identifier",
        pattern="^(natural_identifier|updated_desc|status|business_identifier_desc|machine_number_desc|mold)$",
    ),
    active: bool | None = True,
    eoat_type: str | None = None,
    area: str | None = None,
    cleanroom: str | None = None,
    repo: AtlasRepository = Depends(repository),
):
    items, pagination = repo.list_eoats(
        search=search,
        page=page,
        page_size=_catalog_page_size(repo, page_size),
        sort=sort,
        active=active,
        eoat_type=eoat_type,
        area=area,
        cleanroom=cleanroom,
    )
    return PaginatedEOATs(items=items, pagination=pagination)


@app.get("/api/v1/eoats/{identifier}", response_model=EOATProfile)
def eoat(identifier: str, repo: AtlasRepository = Depends(repository)):
    value = repo.eoat(identifier)
    if value is None:
        raise not_found("EOAT", identifier)
    return value


@app.get(
    "/api/v1/eoats/{identifier}/qr-label.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)


def eoat_qr_label_pdf(identifier: str, request: Request, repo: AtlasRepository = Depends(repository)):
    """Return a single, print-ready 4x3-inch EOAT label PDF from in-memory data."""
    profile = repo.eoat(identifier)
    if profile is None:
        raise not_found("EOAT", identifier)
    origin = _external_request_origin(request)
    payload, _canonical_url = generate_eoat_qr_label_pdf(profile.business_identifier, origin)
    safe_filename = "".join(character if character.isalnum() or character in "-_." else "_" for character in identifier)
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="EOAT_Atlas_Label_{safe_filename}.pdf"'},
    )


@app.get("/api/v1/eoats/{identifier}/current-location", response_model=CurrentEOATLocation)
def eoat_current_location(identifier: str, repo: AtlasRepository = Depends(repository)):
    value = repo.current_eoat_location(identifier)
    if value is None:
        raise not_found("EOAT", identifier)
    return value


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


@app.get("/api/v1/eoats/{identifier}/documents", response_model=list[WebDocumentMetadata])
def eoat_documents(identifier: str, repo: AtlasRepository = Depends(repository)):
    entity = repo.session.scalar(
        __import__("sqlalchemy").select(db.EOAT).where(db.EOAT.business_identifier == identifier)
    )
    if entity is None:
        raise not_found("EOAT", identifier)
    return _browser_safe_documents(repo.documents("eoat", entity.id))


@app.get("/api/v1/eoats/{identifier}/photos", response_model=list[WebPhotoMetadata])
def eoat_photos(identifier: str, repo: AtlasRepository = Depends(repository)):
    entity = repo.session.scalar(
        __import__("sqlalchemy").select(db.EOAT).where(db.EOAT.business_identifier == identifier)
    )
    if entity is None:
        raise not_found("EOAT", identifier)
    return _browser_safe_documents(repo.documents("eoat", entity.id, photos_only=True))


@app.get("/api/v1/machines", response_model=PaginatedMachines)
def machines(
    search: str = "",
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=250),
    active: bool | None = True,
    sort: str = Query(
        "natural_identifier",
        pattern="^(natural_identifier|updated_desc|status|business_identifier_desc|machine_number_desc|mold)$",
    ),
    repo: AtlasRepository = Depends(repository),
):
    items, pagination = repo.list_machines(
        search=search,
        page=page,
        page_size=_catalog_page_size(repo, page_size),
        active=active,
        sort=sort,
    )
    return PaginatedMachines(items=items, pagination=pagination)


@app.get("/api/v1/machines/{number}", response_model=MachineProfile)
def machine(number: str, repo: AtlasRepository = Depends(repository)):
    value = repo.machine(number)
    if value is None:
        raise not_found("Machine", number)
    return value


@app.get("/api/v1/machines/{number}/relationships", response_model=list[RelationshipSummary])
def machine_relationships(number: str, repo: AtlasRepository = Depends(repository)):
    value = repo.machine(number)
    if value is None:
        raise not_found("Machine", number)
    return value.relationships + value.robots


@app.get("/api/v1/machines/{number}/documents", response_model=list[WebDocumentMetadata])
def machine_documents(number: str, repo: AtlasRepository = Depends(repository)):
    entity = repo.session.scalar(__import__("sqlalchemy").select(db.Machine).where(db.Machine.machine_number == number))
    if entity is None:
        raise not_found("Machine", number)
    return _browser_safe_documents(repo.documents("machine", entity.id))


@app.get("/api/v1/machines/{number}/photos", response_model=list[WebPhotoMetadata])
def machine_photos(number: str, repo: AtlasRepository = Depends(repository)):
    entity = repo.session.scalar(__import__("sqlalchemy").select(db.Machine).where(db.Machine.machine_number == number))
    if entity is None:
        raise not_found("Machine", number)
    return _browser_safe_documents(repo.documents("machine", entity.id, photos_only=True))


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
    page_size: int | None = Query(None, ge=1, le=250),
    active: bool | None = True,
    sort: str = Query(
        "natural_identifier",
        pattern="^(natural_identifier|updated_desc|status|business_identifier_desc|machine_number_desc|mold)$",
    ),
    repo: AtlasRepository = Depends(repository),
):
    items, pagination = repo.list_tools(
        search=search,
        page=page,
        page_size=_catalog_page_size(repo, page_size),
        active=active,
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


@app.get("/api/v1/tools/{identifier}/documents", response_model=list[WebDocumentMetadata])
def tool_documents(identifier: str, repo: AtlasRepository = Depends(repository)):
    entity = repo.session.scalar(
        __import__("sqlalchemy").select(db.Tool).where(db.Tool.business_identifier == identifier)
    )
    if entity is None:
        raise not_found("Tool", identifier)
    return _browser_safe_documents(repo.documents("tool", entity.id))


@app.get("/api/v1/tools/{identifier}/photos", response_model=list[WebPhotoMetadata])
def tool_photos(identifier: str, repo: AtlasRepository = Depends(repository)):
    entity = repo.session.scalar(
        __import__("sqlalchemy").select(db.Tool).where(db.Tool.business_identifier == identifier)
    )
    if entity is None:
        raise not_found("Tool", identifier)
    return _browser_safe_documents(repo.documents("tool", entity.id, photos_only=True))


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


@app.get("/api/v1/web-fit-checks/options", response_model=WebFitCheckOptions)
def web_fit_check_options(
    machine_number: str | None = None,
    plant_code: str | None = None,
    tool_number: str | None = None,
    eoat_identifier: str | None = None,
    search: str = Query("", max_length=120),
    search_slot: str | None = Query(None, pattern="^(machine|tool|eoat)$"),
    session: Session = Depends(get_runtime_session),
):
    """Return browser-safe, currently-effective Fit Check candidates.

    This is a normal-app read endpoint. It never persists a Fit Check and it
    only suggests explicit compatible relationships; a missing relationship is
    not treated as compatibility.
    """
    now = datetime.now(timezone.utc)
    archived_status_ids = select(db.AssetStatus.id).where(db.AssetStatus.code == "archived")

    def available(model):
        return (
            model.is_active.is_(True),
            or_(model.status_id.is_(None), model.status_id.not_in(archived_status_ids)),
        )

    def available_value(value) -> bool:
        if value is None or not value.is_active:
            return False
        status = (
            session.scalar(select(db.AssetStatus.code).where(db.AssetStatus.id == value.status_id))
            if value.status_id is not None
            else None
        )
        return (status or "").strip().casefold() != "archived"

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
                    db.CompatibilityStatus.code.in_(SELECTABLE_COMPATIBILITY_STATUS_CODES),
                )
            )
        )

    machine_query = select(db.Machine).where(db.Machine.machine_number == machine_number) if machine_number else None
    if machine_query is not None and plant_code:
        machine_query = machine_query.join(db.Plant, db.Plant.id == db.Machine.plant_id).where(
            db.Plant.plant_code == plant_code,
            db.Plant.is_active.is_(True),
        )
    machine_matches = (
        [value for value in session.scalars(machine_query.order_by(db.Machine.id)).all() if available_value(value)]
        if machine_query is not None
        else []
    )
    machine = machine_matches[0] if len(machine_matches) == 1 else None
    tool_matches = (
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
    tool = tool_matches[0] if len(tool_matches) == 1 and available_value(tool_matches[0]) else None
    eoat_matches = (
        list(
            session.scalars(
                select(db.EOAT)
                .where(
                    or_(db.EOAT.business_identifier == eoat_identifier, db.EOAT.legacy_identifier == eoat_identifier)
                )
                .order_by(db.EOAT.id)
            ).all()
        )
        if eoat_identifier
        else []
    )
    eoat = eoat_matches[0] if len(eoat_matches) == 1 and available_value(eoat_matches[0]) else None
    machine_ids: set[int] | None = None
    tool_ids: set[int] | None = None
    eoat_ids: set[int] | None = None

    def intersect(current: set[int] | None, values: set[int]) -> set[int]:
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
                db.EOATToolCompatibility, db.EOATToolCompatibility.eoat_id, db.EOATToolCompatibility.tool_id == tool.id
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
                db.EOATToolCompatibility, db.EOATToolCompatibility.tool_id, db.EOATToolCompatibility.eoat_id == eoat.id
            ),
        )

    machine_filters = [*available(db.Machine)]
    tool_filters = [*available(db.Tool)]
    eoat_filters = [*available(db.EOAT)]
    if machine_ids is not None:
        machine_filters.append(db.Machine.id.in_(machine_ids))
    if tool_ids is not None:
        tool_filters.append(db.Tool.id.in_(tool_ids))
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

    # A typed query deliberately uses the normal authoritative catalog for
    # just that selector. Compatibility remains a recommendation for an empty
    # selector and an evaluation rule after selection; it must not censor an
    # operator who needs to check an unfamiliar or incompatible combination.
    catalog_search = search.strip()
    global_machines = None
    global_tools = None
    global_eoats = None
    if catalog_search and search_slot:
        catalog = AtlasRepository(session)
        if search_slot == "machine":
            global_machines = catalog.list_machines(search=catalog_search, page_size=50, active=True)[0]
        elif search_slot == "tool":
            global_tools = catalog.list_tools(search=catalog_search, page_size=50, active=True)[0]
        else:
            global_eoats = catalog.list_eoats(search=catalog_search, page_size=50, active=True)[0]
    warnings: list[str] = []
    unresolved: list[str] = []
    if machine_number and len(machine_matches) != 1:
        warnings.append("Machine selection is unknown, unavailable, or ambiguous; choose a plant code when necessary.")
        unresolved.append("machine")
    if tool_number and tool is None:
        warnings.append("Tool selection is unknown, unavailable, or ambiguous; use its business identifier.")
        unresolved.append("tool")
    if eoat_identifier and eoat is None:
        warnings.append("EOAT selection is unknown or unavailable.")
        unresolved.append("eoat")
    return WebFitCheckOptions(
        machines=(
            [
                FitCheckOption(
                    identifier=value.machine_number,
                    label=value.machine_name or value.machine_number,
                    plant_code=value.plant_code,
                )
                for value in global_machines
            ]
            if global_machines is not None
            else [
                FitCheckOption(
                    identifier=value.machine_number, label=value.machine_name or value.machine_number, plant_code=plant
                )
                for value, plant in machines
            ]
        ),
        tools=(
            [
                FitCheckOption(
                    identifier=value.business_identifier,
                    label=value.display_name or value.tool_number or value.business_identifier,
                )
                for value in global_tools
            ]
            if global_tools is not None
            else [
                FitCheckOption(
                    identifier=value.business_identifier,
                    label=value.display_name or value.tool_number or value.business_identifier,
                )
                for value in tools
            ]
        ),
        eoats=(
            [
                FitCheckOption(
                    identifier=value.business_identifier, label=value.display_name or value.business_identifier
                )
                for value in global_eoats
            ]
            if global_eoats is not None
            else [
                FitCheckOption(
                    identifier=value.business_identifier, label=value.display_name or value.business_identifier
                )
                for value in eoats
            ]
        ),
        warnings=warnings,
        unresolved_inputs=unresolved,
        query_mode="global_catalog" if catalog_search and search_slot else "recommendations",
        query_slot=search_slot if catalog_search and search_slot else None,
    )


@app.post("/api/v1/fit-checks/evaluate", response_model=FitCheckResult)
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
            machine_number=machine_number,
            plant_code=plant_code,
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
                machine_number=machine_number,
                plant_code=plant_code,
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
app.include_router(corporate_auth_router)
app.include_router(admin_router)
app.include_router(admin_mutation_router)
app.include_router(admin_corporate_user_router)
app.include_router(admin_operation_router)


def _catalog_page_size(repo: AtlasRepository, requested: int | None) -> int:
    """Use the governed global default only when a caller did not choose one."""

    if requested is not None:
        return requested
    record = repo.session.scalar(
        select(db.SystemSetting).where(db.SystemSetting.setting_key == "app.default_catalog_page_size")
    )
    # Lightweight read-contract repositories intentionally do not materialize
    # every settings column; fall back to the governed default there as well.
    value = getattr(record, "setting_value_json", 50) if record is not None else 50
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 250 else 50
