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
