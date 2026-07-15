from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError

from server.eoat_api.database.session import (
    create_database_engine,
    create_session_factory,
    dispose_database_engines,
)

pytestmark = pytest.mark.skipif(
    os.getenv("EOAT_DB_NAME") != "eoat_atlas_test",
    reason="Connection lifecycle tests require EOAT_DB_NAME=eoat_atlas_test",
)


@pytest.fixture(autouse=True)
def clean_process_pool():
    dispose_database_engines()
    yield
    dispose_database_engines()


def test_engine_is_process_wide_while_one_hundred_sessions_are_request_scoped():
    engine = create_database_engine()
    factory = create_session_factory()
    session_ids: set[int] = set()
    connection_ids: set[int] = set()
    for _ in range(100):
        with factory() as session:
            session_ids.add(id(session))
            connection_ids.add(session.scalar(text("SELECT CONNECTION_ID()")))
            assert session.scalar(text("SELECT 1")) == 1
        assert create_database_engine() is engine
    assert len(session_ids) > 1
    assert len(connection_ids) <= engine.pool.size() + engine.pool._max_overflow
    assert engine.pool.checkedout() == 0


def test_twenty_concurrent_sessions_remain_bounded_and_return_connections():
    engine = create_database_engine()
    factory = create_session_factory()

    def query() -> tuple[int, int]:
        with factory() as session:
            return id(session), session.scalar(text("SELECT CONNECTION_ID()"))

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(lambda _index: query(), range(20)))
    assert len({session_id for session_id, _connection_id in results}) > 1
    assert len({connection_id for _session_id, connection_id in results}) <= 15
    assert engine.pool.checkedout() == 0


def test_pre_ping_recovers_a_stale_pooled_connection():
    engine = create_database_engine(pool_pre_ping=True)
    connection = engine.connect()
    raw = connection.connection.driver_connection
    raw.close()
    connection.close()
    with engine.connect() as recovered:
        assert recovered.scalar(text("SELECT 1")) == 1


def test_pool_timeout_is_bounded_and_release_allows_later_request(monkeypatch):
    monkeypatch.setenv("EOAT_DB_POOL_SIZE", "2")
    monkeypatch.setenv("EOAT_DB_MAX_OVERFLOW", "0")
    monkeypatch.setenv("EOAT_DB_POOL_TIMEOUT_SECONDS", "0.1")
    engine = create_database_engine()
    first = engine.connect()
    second = engine.connect()
    try:
        with pytest.raises(TimeoutError):
            engine.connect()
    finally:
        first.close()
        second.close()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1
    assert engine.pool.checkedout() == 0


def test_rollback_does_not_poison_later_session_and_shutdown_rebuilds_engine():
    engine = create_database_engine()
    factory = create_session_factory()
    with pytest.raises(RuntimeError), factory() as session, session.begin():
        assert session.scalar(text("SELECT 1")) == 1
        raise RuntimeError("synthetic transaction failure")
    with factory() as session:
        assert session.scalar(text("SELECT 1")) == 1
    dispose_database_engines()
    replacement = create_database_engine()
    assert replacement is not engine
    assert replacement.pool.checkedout() == 0
