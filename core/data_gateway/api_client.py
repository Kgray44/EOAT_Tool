from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from core.versioning import get_release_info

from .exceptions import (
    ApiUnavailableError,
    AuthenticationRequiredError,
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
        configured_url = base_url.rstrip("/")
        self.base_url = configured_url
        self._configured_api_prefix = configured_url.casefold().endswith("/api/v1")
        client_base_url = f"{configured_url}/" if self._configured_api_prefix else configured_url
        release = get_release_info()
        effective_client_version = client_version or release.application_version
        headers = {
            "User-Agent": f"EOAT-Atlas/{effective_client_version} ({release.release_id}; {release.build_id})",
            "X-EOAT-Client-Version": effective_client_version,
            "X-EOAT-Release-ID": release.release_id,
            "X-EOAT-Build-ID": release.build_id,
        }
        if identity:
            headers["X-EOAT-Identity"] = identity
        if application_instance_id:
            headers["X-EOAT-Application-Instance"] = application_instance_id
        self._client = httpx.Client(base_url=client_base_url, timeout=timeout, transport=transport, headers=headers)
        self._settings_access_token = ""
        self.last_request_id = ""

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, self._request_path(path), **kwargs)
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
                if response.status_code == 401:
                    raise AuthenticationRequiredError(message)
                raise PermissionDeniedError(message)
            raise DataGatewayError(message)
        return response.json()

    def _request_path(self, path: str) -> str:
        """Accept either an origin or the authoritative ``/api/v1`` endpoint URL."""

        if not self._configured_api_prefix:
            return path
        prefix = "/api/v1"
        if path.casefold().startswith(prefix):
            return path[len(prefix) :].lstrip("/")
        return path.lstrip("/")

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

    def version(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/version")

    def schema_status(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/schema-status")

    def server_status(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/server-status")

    def home_summary(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/home-summary")

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/search", params={"q": query, "limit": limit})

    def list_eoats(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/api/v1/eoats", params=params)

    def get_eoat(self, identifier: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/eoats/{quote(identifier, safe='')}")

    def get_eoat_history(self, identifier: str, **params: Any) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/v1/eoats/{quote(identifier, safe='')}/history",
            params=params,
        )

    def get_eoat_documents(self, identifier: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/v1/eoats/{identifier}/documents")

    def get_eoat_photos(self, identifier: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/v1/eoats/{identifier}/photos")

    def list_machines(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/api/v1/machines", params=params)

    def get_machine(self, number: str, *, plant_code: str | None = None) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/machines/{number}", params={"plant_code": plant_code})

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

    def authentication_config(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/auth/config")

    def authentication_health(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/auth/health")

    def begin_settings_login(self, identity: str = "") -> dict[str, Any]:
        config = self.authentication_config()
        if config.get("provider") == "development":
            result = self._request("POST", "/api/v1/auth/development/login", json={"identity": identity})
            self._settings_access_token = str(result.pop("access_token", ""))
            return result
        return self._request("GET", "/api/v1/auth/login")

    def settings_session(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/auth/session", headers=self._settings_auth_headers())

    def authorize_settings(self, permission: str = "settings.edit", operation: str = "settings.save") -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/settings/authorization/check",
            json={"permission": permission, "operation": operation},
            headers=self._settings_auth_headers(),
        )

    def read_settings(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/settings")

    def write_setting(self, key: str, value: Any, description: str | None = None) -> dict[str, Any]:
        payload = {"value": value}
        if description is not None:
            payload["description"] = description
        return self._request(
            "PUT",
            f"/api/v1/settings/{quote(key, safe='')}",
            json=payload,
            headers=self._settings_auth_headers(),
        )

    def logout_settings(self) -> dict[str, Any]:
        try:
            return self._request("POST", "/api/v1/auth/logout", headers=self._settings_auth_headers())
        finally:
            self._settings_access_token = ""

    def audit_settings_action(self, event_type: str, operation: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/settings/audit",
            json={"event_type": event_type, "operation": operation},
            headers=self._settings_auth_headers(),
        )

    def clear_settings_session(self) -> None:
        self._settings_access_token = ""

    def _settings_auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._settings_access_token}"} if self._settings_access_token else {}
