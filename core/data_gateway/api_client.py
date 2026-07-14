from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from .exceptions import (
    ApiUnavailableError,
    ConcurrencyConflictError,
    DataGatewayError,
    PermissionDeniedError,
    ValidationError,
    WriteBlockedError,
)


class AtlasApiClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        identity: str = "",
        application_instance_id: str = "",
        client_version: str = "",
    ):
        self.base_url = base_url.rstrip("/")
        headers = {}
        if identity:
            headers["X-EOAT-Identity"] = identity
        if application_instance_id:
            headers["X-EOAT-Application-Instance"] = application_instance_id
        if client_version:
            headers["X-EOAT-Client-Version"] = client_version
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport, headers=headers)
        self.last_request_id = ""

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ApiUnavailableError(f"EOAT Atlas API is unavailable: {exc}") from exc
        self.last_request_id = response.headers.get("X-Request-ID", "")
        if response.status_code >= 500:
            raise ApiUnavailableError("EOAT Atlas server or database is unavailable.")
        if response.status_code >= 400:
            try:
                error = response.json()
            except ValueError:
                error = {"message": response.text}
            if "detail" in error and isinstance(error["detail"], dict):
                error = error["detail"]
            message = str(error.get("message") or error.get("detail") or "The request failed.")
            code = str(error.get("error_code") or error.get("code") or "API_ERROR")
            if response.status_code == 409 and code == "STALE_RECORD_VERSION":
                raise ConcurrencyConflictError(
                    message,
                    current_record_version=error.get("current_record_version"),
                    details=error.get("details"),
                )
            if response.status_code == 422:
                raise ValidationError(message, details=error.get("details"))
            if response.status_code in {401, 403}:
                if code in {"WRITES_DISABLED", "DEVELOPMENT_AUTH_FORBIDDEN"}:
                    raise WriteBlockedError(message)
                raise PermissionDeniedError(message)
            raise DataGatewayError(message)
        return response.json()

    def write(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._request(method, path, json=payload, headers=headers, params=params)

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/health")

    def home_summary(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/home-summary")

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/search", params={"q": query, "limit": limit})

    def list_eoats(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/api/v1/eoats", params=params)

    def get_eoat(self, identifier: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/eoats/{quote(identifier, safe='')}")

    def get_eoat_history(self, identifier: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/v1/eoats/{identifier}/history")

    def get_eoat_documents(self, identifier: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/v1/eoats/{identifier}/documents")

    def get_eoat_photos(self, identifier: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/v1/eoats/{identifier}/photos")

    def list_machines(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/api/v1/machines", params=params)

    def get_machine(self, number: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/machines/{number}")

    def list_tools(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/api/v1/tools", params=params)

    def get_tool(self, number: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/tools/{number}")

    def evaluate_fit_check(self, machine_number: str, tool_number: str, eoat_identifier: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/fit-checks/evaluate",
            json={"machine_number": machine_number, "tool_number": tool_number, "eoat_identifier": eoat_identifier},
        )

    def alternatives(self, machine_number: str, tool_number: str, eoat_identifier: str) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v1/compatibility/alternatives",
            params={"machine_number": machine_number, "tool_number": tool_number, "eoat_identifier": eoat_identifier},
        )

    def setup_packet_data(self, machine_number: str, tool_number: str, eoat_identifier: str) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v1/setup-packets/data",
            params={"machine_number": machine_number, "tool_number": tool_number, "eoat_identifier": eoat_identifier},
        )

    def sync_status(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/sync/status")

    def changes(self, after_cursor: int) -> dict[str, Any]:
        return self._request("GET", "/api/v1/sync/changes", params={"after_cursor": after_cursor})

    def snapshot(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/sync/snapshot", timeout=60.0)
