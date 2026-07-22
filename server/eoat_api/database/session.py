from __future__ import annotations

import os
from collections.abc import Iterator
from threading import RLock

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from .config import DatabaseSettings


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().casefold() in {"1", "true", "yes", "on"}


_LOCK = RLock()
_ENGINES: dict[bool, Engine] = {}
_FACTORIES: dict[bool, sessionmaker[Session]] = {}
_REQUEST_SESSION_ATTRIBUTE = "_eoat_write_session"


def create_database_engine(*, migration: bool = False, pool_pre_ping: bool | None = None) -> Engine:
    """Return one bounded engine per credential purpose for the lifetime of the process."""
    with _LOCK:
        if migration not in _ENGINES:
            settings = DatabaseSettings.from_environment(migration=migration)
            _ENGINES[migration] = create_engine(
                settings.sqlalchemy_url,
                pool_pre_ping=_bool_env("EOAT_DB_POOL_PRE_PING", True) if pool_pre_ping is None else pool_pre_ping,
                pool_size=int(os.getenv("EOAT_DB_POOL_SIZE", "5")),
                max_overflow=int(os.getenv("EOAT_DB_MAX_OVERFLOW", "10")),
                pool_recycle=int(os.getenv("EOAT_DB_POOL_RECYCLE_SECONDS", "1800")),
                pool_timeout=float(os.getenv("EOAT_DB_POOL_TIMEOUT_SECONDS", "30")),
                future=True,
            )
        return _ENGINES[migration]


def create_session_factory(*, migration: bool = False) -> sessionmaker[Session]:
    with _LOCK:
        if migration not in _FACTORIES:
            _FACTORIES[migration] = sessionmaker(
                bind=create_database_engine(migration=migration), expire_on_commit=False, future=True
            )
        return _FACTORIES[migration]


def dispose_database_engines() -> None:
    """Dispose all process pools; safe to call repeatedly during shutdown and tests."""
    with _LOCK:
        for engine in _ENGINES.values():
            engine.dispose()
        _FACTORIES.clear()
        _ENGINES.clear()


def session_scope(*, migration: bool = False) -> Iterator[Session]:
    factory = create_session_factory(migration=migration)
    with factory() as session, session.begin():
        yield session


def get_runtime_session() -> Iterator[Session]:
    factory = create_session_factory(migration=False)
    with factory() as session:
        try:
            yield session
        finally:
            session.rollback()


def get_write_session(request: Request) -> Iterator[Session]:
    """Yield one request session; middleware commits successful HTTP writes first.

    FastAPI's yielded dependencies are finalized after it has prepared the
    response.  Storing the session on the request lets the HTTP middleware
    commit before that response is released, so a 200 write cannot be followed
    by a stale authoritative status read.
    """
    factory = create_session_factory(migration=False)
    session = factory()
    setattr(request.state, _REQUEST_SESSION_ATTRIBUTE, session)
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        # The normal path is finalized by ``finalize_request_write_session``.
        # Keep this rollback as the exception/streaming safety net.
        if session.in_transaction():
            session.rollback()
        session.close()


def finalize_request_write_session(request: Request, *, commit: bool) -> None:
    """Finish a request session before its HTTP response is returned."""
    session = getattr(request.state, _REQUEST_SESSION_ATTRIBUTE, None)
    if session is None or not session.in_transaction():
        return
    if commit:
        session.commit()
    else:
        session.rollback()
