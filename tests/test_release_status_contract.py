from __future__ import annotations

from fastapi.testclient import TestClient

from server.eoat_api.app import app


def test_release_status_is_safe_and_reports_product_identity(monkeypatch) -> None:
    monkeypatch.setenv("EOAT_MINIMUM_SUPPORTED_DESKTOP_VERSION", "0.24.0")
    response = TestClient(app).get("/api/v1/release-status", headers={"X-EOAT-Client-Version": "0.23.0"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_version"] == "0.24.0"
    assert payload["release_id"] == "eoat-atlas-0.24.0"
    assert payload["client_supported"] is False
    assert "path" not in payload and "secret" not in payload


def test_release_status_and_protected_routes_fail_closed_for_release_identity_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("EOAT_REQUIRE_CLIENT_RELEASE_PARITY", "true")
    monkeypatch.setenv("EOAT_RELEASE_SET_DIGEST", "a" * 64)
    client = TestClient(app)
    status = client.get(
        "/api/v1/release-status",
        headers={
            "X-EOAT-Client-Version": "0.24.0",
            "X-EOAT-Client-Release-ID": "wrong",
            "X-EOAT-Client-Build-ID": "wrong",
            "X-EOAT-Client-Release-Set-Digest": "b" * 64,
        },
    )
    assert status.status_code == 200
    assert status.json()["client_compatibility"] == "MISMATCH"
    response = client.get(
        "/api/v1/lookups",
        headers={
            "X-EOAT-Client-Version": "0.24.0",
            "X-EOAT-Client-Release-ID": "wrong",
            "X-EOAT-Client-Build-ID": "wrong",
            "X-EOAT-Client-Release-Set-Digest": "b" * 64,
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "CLIENT_RELEASE_MISMATCH"
    write = client.post(
        "/api/v1/eoats",
        json={"description": "must never reach authorization or a write session"},
        headers={"X-EOAT-Client-Version": "0.24.0"},
    )
    assert write.status_code == 409
    assert write.json()["error_code"] == "CLIENT_RELEASE_MISMATCH"
