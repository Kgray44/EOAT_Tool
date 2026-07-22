from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from server.eoat_api.app import app
from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory
from server.eoat_api.security import ActorContext
from server.eoat_api.write_services import move_to_machine
from tests.fixtures.mysql_sanctioned import deterministic_uuid, reset_and_load_sanctioned_fixture

pytestmark = pytest.mark.skipif(
    os.getenv("EOAT_DB_NAME") != "eoat_atlas_test",
    reason="Data freshness MySQL integration tests require EOAT_DB_NAME=eoat_atlas_test",
)

ENGINEER = {"X-EOAT-Identity": "dev.engineer"}
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", autouse=True)
def sanctioned_database():
    reset_and_load_sanctioned_fixture()


@pytest.fixture(scope="module", autouse=True)
def explicit_development_write_environment():
    names = {"EOAT_API_ENVIRONMENT": "development", "EOAT_API_WRITES_ENABLED": "true"}
    previous = {name: os.environ.get(name) for name in names}
    os.environ.update(names)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as client:
        yield client


def _status(api: TestClient) -> dict:
    response = api.get("/api/v1/data-status")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {
        "status",
        "data_revision",
        "data_last_modified_at",
        "last_import_at",
        "last_import_source",
        "server_time",
        "source",
        "environment",
    }
    return payload


def _fixture_actor() -> ActorContext:
    factory = create_session_factory(migration=True)
    with factory() as session:
        user = session.scalar(select(db.User).where(db.User.username == "demo.engineer"))
        instance = session.scalar(
            select(db.ApplicationInstance).where(
                db.ApplicationInstance.instance_uuid == deterministic_uuid("application-instance")
            )
        )
        assert user is not None and instance is not None
        return ActorContext(
            user_id=user.id,
            identity=user.external_identity,
            display_name=user.display_name,
            role="ENGINEER",
            request_id=str(uuid4()),
            application_instance_id=instance.id,
            client_version="0.18.0-test",
        )


def _move_payload(row_version: int) -> dict:
    return {
        "plant_code": "DEMO-P4",
        "machine_number": "042",
        "tool_identifier": "DEMO-TOOL-0003",
        "expected_row_version": row_version,
        "reason": "Data freshness transactional test",
    }


def _live_json(base_url: str, path: str, *, payload: dict | None = None, headers: dict[str, str] | None = None):
    request = UrlRequest(
        base_url + path,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=headers or {},
        method="POST" if payload is not None else "GET",
    )
    with urlopen(request, timeout=5) as response:  # noqa: S310 - local disposable test API only
        return response.status, json.loads(response.read().decode("utf-8"))


@pytest.fixture(scope="module")
def live_api():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.eoat_api.app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _attempt in range(30):
            try:
                _live_json(base_url, "/api/v1/data-status")
                break
            except OSError as exc:
                if process.poll() is not None:
                    raise RuntimeError(process.stderr.read()) from exc
                time.sleep(0.25)
        else:
            raise RuntimeError("Disposable live API did not start in time.")
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def test_data_status_is_anonymous_and_only_successful_api_writes_advance_it(api: TestClient):
    before = _status(api)
    identifier = f"FRESH-API-{uuid4().hex[:12]}"
    create = api.post(
        "/api/v1/eoats",
        headers={**ENGINEER, "Idempotency-Key": f"freshness-{uuid4()}"},
        json={"business_identifier": identifier, "display_name": "Freshness API write"},
    )
    assert create.status_code == 200, create.text

    after = _status(api)
    repeated = _status(api)
    assert after["data_revision"] == before["data_revision"] + 1
    assert after["data_last_modified_at"] != before["data_last_modified_at"]
    assert after["source"] == "mysql"
    assert after["environment"] == "development"
    assert repeated["data_revision"] == after["data_revision"]
    assert repeated["data_last_modified_at"] == after["data_last_modified_at"]


def test_rolled_back_canonical_write_does_not_advance_data_status(api: TestClient):
    before = _status(api)
    factory = create_session_factory(migration=True)
    with factory() as session:
        eoat = session.scalar(select(db.EOAT).where(db.EOAT.business_identifier == "DEMO-P4-EOAT-0003"))
        assert eoat is not None
        row_version = eoat.row_version

    def inject(stage: str) -> None:
        if stage == "history_creation":
            raise RuntimeError("intentional freshness rollback")

    with pytest.raises(RuntimeError, match="intentional freshness rollback"), factory() as session, session.begin():
        move_to_machine(
            session, _fixture_actor(), "DEMO-P4-EOAT-0003", _move_payload(row_version), fault_injector=inject
        )

    after = _status(api)
    assert after["data_revision"] == before["data_revision"]
    assert after["data_last_modified_at"] == before["data_last_modified_at"]


def test_multi_audit_logical_write_advances_exactly_once(api: TestClient):
    before = _status(api)
    factory = create_session_factory(migration=True)
    with factory() as session:
        eoat = session.scalar(select(db.EOAT).where(db.EOAT.business_identifier == "DEMO-P4-EOAT-0003"))
        assert eoat is not None
        row_version = eoat.row_version

    with factory() as session, session.begin():
        move_to_machine(session, _fixture_actor(), "DEMO-P4-EOAT-0003", _move_payload(row_version))

    after = _status(api)
    assert after["data_revision"] == before["data_revision"] + 1


def test_concurrent_real_api_writes_receive_distinct_monotonic_revisions(api: TestClient):
    before = _status(api)

    def create(index: int):
        return api.post(
            "/api/v1/eoats",
            headers={**ENGINEER, "Idempotency-Key": f"freshness-concurrent-{uuid4()}"},
            json={"business_identifier": f"FRESH-CONCURRENT-{index}-{uuid4().hex[:10]}"},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(create, range(2)))
    assert all(response.status_code == 200 for response in responses), [response.text for response in responses]

    after = _status(api)
    assert after["data_revision"] == before["data_revision"] + 2


def test_live_http_write_response_commits_before_data_status_is_read(live_api: str):
    _status_code, before = _live_json(live_api, "/api/v1/data-status")
    headers = {**ENGINEER, "Idempotency-Key": f"freshness-live-{uuid4()}", "Content-Type": "application/json"}
    status_code, _created = _live_json(
        live_api,
        "/api/v1/eoats",
        payload={"business_identifier": f"FRESH-LIVE-{uuid4().hex[:12]}"},
        headers=headers,
    )
    _status_code, after = _live_json(live_api, "/api/v1/data-status")
    assert status_code == 200
    assert after["data_revision"] == before["data_revision"] + 1
