from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import DatabaseSettings


def create_database_engine(*, migration: bool = False, pool_pre_ping: bool = True) -> Engine:
    settings = DatabaseSettings.from_environment(migration=migration)
    return create_engine(settings.sqlalchemy_url, pool_pre_ping=pool_pre_ping, future=True)


def create_session_factory(*, migration: bool = False) -> sessionmaker[Session]:
    return sessionmaker(bind=create_database_engine(migration=migration), expire_on_commit=False, future=True)


def session_scope(*, migration: bool = False) -> Iterator[Session]:
    factory = create_session_factory(migration=migration)
    with factory() as session, session.begin():
        yield session


def get_runtime_session() -> Iterator[Session]:
    factory = create_session_factory(migration=False)
    with factory() as session:
        yield session


def get_write_session() -> Iterator[Session]:
    """Yield one transaction for an entire server-first write request."""
    factory = create_session_factory(migration=False)
    with factory() as session:
        try:
            with session.begin():
                yield session
        except Exception:
            session.rollback()
            raise
