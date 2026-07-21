from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from .api_client import AtlasApiClient
from .cache_repository import CacheRepository
from .configuration import GatewayConfiguration
from .connectivity import check_connectivity
from .exceptions import (
    ApiUnavailableError,
    CacheUnavailableError,
    ConcurrencyConflictError,
    IncompatibleServerError,
    WriteBlockedError,
)
from .mappings import snapshot_to_bundle
from .models import ConnectivityMode
from .sync_coordinator import SyncCoordinator


class AtlasDataGateway:
    def __init__(self, configuration: GatewayConfiguration | None = None, *, client=None, cache=None):
        self.configuration = configuration or GatewayConfiguration.from_environment()
        if self.configuration.backend != "mysql_api":
            raise ValueError("AtlasDataGateway is available only when backend=mysql_api.")
        self.client = client or AtlasApiClient(
            self.configuration.api_base_url,
            timeout=self.configuration.timeout_seconds,
            identity=self.configuration.development_identity,
            application_instance_id=self.configuration.application_instance_id,
            client_version=self.configuration.client_version,
        )
        self.cache = cache or CacheRepository(self.configuration.cache_path)
        self.sync = SyncCoordinator(self.client, self.cache, self.configuration)
        self._status = check_connectivity(self.client, self.configuration)
        self.last_write: dict = {}
        self.last_conflict: dict = {}
        self.last_server_failure: str = ""

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def get_connection_status(self):
        self._status = check_connectivity(self.client, self.configuration)
        return self._status

    def get_cache_status(self):
        return self.cache.status()

    def diagnostics(self) -> dict:
        started = perf_counter()
        health: dict = {}
        version: dict = {}
        server: dict = {}
        try:
            health = self.client.health()
            version = self.client.version()
            server = self.client.server_status()
            api_online = bool(health.get("api_reachable") and health.get("database_reachable"))
        except ApiUnavailableError as exc:
            api_online = False
            self.last_server_failure = str(exc)
        cache = self.get_cache_status() if self.cache.path.exists() else None
        return {
            "backend": "mysql_api",
            "operational_authority": "MySQL/API",
            "api_online": api_online,
            "api_url": self.configuration.api_base_url,
            "api_version": str(health.get("api_version") or version.get("api_version") or ""),
            "required_api_version": self.configuration.expected_api_version,
            "api_response_ms": round((perf_counter() - started) * 1000, 1),
            "database_connected": bool(health.get("database_reachable")),
            "mysql_version": str(health.get("database_server_version") or ""),
            "schema_revision": str(health.get("current_schema_revision") or ""),
            "required_schema_revision": self.configuration.expected_schema_revision,
            "server_revision": str(version.get("server_revision") or (cache.server_revision if cache else "")),
            "change_feed_cursor": int(server.get("cursor") or (cache.last_change_cursor if cache else 0)),
            "cache_path": str(self.configuration.cache_path),
            "cache_schema_version": str(cache.schema_version if cache else ""),
            "cached_counts": dict(cache.entity_counts if cache else {}),
            "last_successful_api_contact": str(cache.last_successful_sync_at if cache else ""),
            "last_incremental_refresh": str(cache.last_successful_sync_at if cache else ""),
            "last_deep_refresh": str(cache.last_full_refresh_at if cache else ""),
            "offline_read_only": not api_online,
            "writes_enabled": bool(self.configuration.writes_enabled and health.get("writes_enabled")),
            "identity": self.configuration.development_identity,
            "role": {
                "dev.viewer": "VIEWER",
                "dev.technician": "TECHNICIAN",
                "dev.engineer": "ENGINEER",
                "dev.admin": "ADMINISTRATOR",
            }.get(self.configuration.development_identity, "Server-resolved"),
            "application_instance_id": self.configuration.application_instance_id,
            "client_version": self.configuration.client_version,
            "legacy_fallback": False,
        }

    def data_source_status(self) -> dict:
        """Return UI-safe source truth without presenting cache data as live data."""

        connection = self.get_connection_status()
        cache = self.get_cache_status() if self.cache.path.exists() else None
        last_refresh = str(cache.last_successful_sync_at if cache else "")
        cached_records = sum((cache.entity_counts or {}).values()) if cache else 0
        if connection.mode == ConnectivityMode.ONLINE:
            return {
                "state": "Server connected",
                "detail": connection.message,
                "last_successful_server_refresh": last_refresh,
                "using_cached_data": False,
            }
        if cached_records:
            return {
                "state": "Using cached data",
                "detail": f"Server unavailable: {connection.message}",
                "last_successful_server_refresh": last_refresh,
                "using_cached_data": True,
            }
        return {
            "state": "Server unavailable",
            "detail": connection.message,
            "last_successful_server_refresh": last_refresh,
            "using_cached_data": False,
        }

    def _online_or_cache(self, online, cached):
        status = self.get_connection_status()
        if status.mode == ConnectivityMode.INCOMPATIBLE_SERVER:
            raise IncompatibleServerError(status.message)
        if status.mode == ConnectivityMode.ONLINE:
            return online()
        value = cached()
        if value in (None, [], {}):
            raise CacheUnavailableError("Offline read-only cache does not contain the requested data.")
        return value

    def get_home_summary(self):
        return self._online_or_cache(
            self.client.home_summary,
            lambda: {
                "eoats": len(self.cache.list("eoats")),
                "machines": len(self.cache.list("machines")),
                "tools": len(self.cache.list("tools")),
                "backend": "mysql_api",
                "mode": "OFFLINE_READ_ONLY",
            },
        )

    def search(self, query: str, filters=None):
        return self._online_or_cache(lambda: self.client.search(query), lambda: self.cache.search(query))

    def list_eoats(self, filters=None, page=None, page_size=None, sort=None):
        params = {
            **(filters or {}),
            "page": page or 1,
            "page_size": page_size or 50,
            "sort": sort or "business_identifier",
        }
        return self._online_or_cache(
            lambda: self.client.list_eoats(**params),
            lambda: {
                "items": self.cache.list("eoats"),
                "pagination": {
                    "page": 1,
                    "page_size": len(self.cache.list("eoats")),
                    "total": len(self.cache.list("eoats")),
                    "pages": 1,
                },
            },
        )

    def get_eoat(self, identifier):
        return self._online_or_cache(
            lambda: self.client.get_eoat(identifier), lambda: self.cache.get("eoats", identifier)
        )

    def get_eoat_history(self, identifier):
        return self._online_or_cache(
            lambda: self._fetch_and_cache_eoat_history(identifier),
            lambda: self._cached_eoat_history(identifier),
        )

    def _fetch_and_cache_eoat_history(self, identifier: str) -> list[dict]:
        page = 1
        events: list[dict] = []
        while True:
            response = self.client.get_eoat_history(identifier, page=page, page_size=200, sort_order="desc")
            items = list(response.get("items", []))
            events.extend(items)
            pagination = response.get("pagination", {})
            if page >= int(pagination.get("pages") or 0):
                break
            page += 1
        self.cache.replace_eoat_history(identifier, events)
        return events

    def _cached_eoat_history(self, identifier: str) -> list[dict]:
        timestamp = self.cache.metadata().get("last_history_sync_at") or self.cache.metadata().get("last_full_refresh_at", "")
        events = []
        for payload in self.cache.get_eoat_history(identifier):
            metadata = dict(payload.get("metadata") or {})
            metadata.update({"delivery_mode": "offline_cache", "cache_timestamp": timestamp})
            events.append({**payload, "metadata": metadata})
        return events

    def get_eoat_documents(self, identifier):
        return self._online_or_cache(
            lambda: self.client.get_eoat_documents(identifier),
            lambda: self.cache.linked_documents("eoat", identifier),
        )

    def get_eoat_photos(self, identifier):
        return self._online_or_cache(
            lambda: self.client.get_eoat_photos(identifier),
            lambda: self.cache.linked_documents("eoat", identifier, photos_only=True),
        )

    def list_machines(self, filters=None, page=None, page_size=None, sort=None):
        return self._online_or_cache(
            lambda: self.client.list_machines(**(filters or {}), page=page or 1, page_size=page_size or 50),
            lambda: {"items": self.cache.list("machines")},
        )

    def get_machine(self, number, plant_code=None):
        return self._online_or_cache(
            lambda: self.client.get_machine(number, plant_code=plant_code),
            lambda: self.cache.get_machine(number, plant_code=plant_code),
        )

    def list_tools(self, filters=None, page=None, page_size=None, sort=None):
        return self._online_or_cache(
            lambda: self.client.list_tools(**(filters or {}), page=page or 1, page_size=page_size or 50),
            lambda: {"items": self.cache.list("tools")},
        )

    def get_tool(self, number):
        return self._online_or_cache(lambda: self.client.get_tool(number), lambda: self.cache.get("tools", number))

    def evaluate_fit_check(self, machine_number, tool_number, eoat_identifier):
        return self._online_or_cache(
            lambda: self.client.evaluate_fit_check(machine_number, tool_number, eoat_identifier),
            lambda: {
                "overall_result": "NEEDS_REVIEW",
                "warnings": ["Offline read-only mode cannot evaluate uncached compatibility."],
                "stored": False,
            },
        )

    def get_fit_check_alternatives(self, machine_number, tool_number, eoat_identifier):
        return self._online_or_cache(
            lambda: self.client.alternatives(machine_number, tool_number, eoat_identifier), lambda: {"alternatives": []}
        )

    def get_setup_packet_data(self, machine_number, tool_number, eoat_identifier):
        def unavailable_offline_packet():
            raise CacheUnavailableError(
                "Offline setup packet generation is blocked because compatibility cannot be revalidated. "
                "Reconnect to the authoritative MySQL/API service."
            )

        return self._online_or_cache(
            lambda: self.client.setup_packet_data(machine_number, tool_number, eoat_identifier),
            unavailable_offline_packet,
        )

    def refresh(self):
        return self.sync.standard_refresh()

    def deep_refresh(self):
        return self.sync.deep_refresh()

    def _server_first_write(self, method, path, payload=None, *, idempotency_key=None, params=None):
        if not self.configuration.writes_enabled or self.configuration.environment != "development":
            raise WriteBlockedError("Server writes are disabled in this production client; no server edit was saved.")
        status = self.get_connection_status()
        if status.mode == ConnectivityMode.INCOMPATIBLE_SERVER:
            raise IncompatibleServerError(status.message)
        if status.mode != ConnectivityMode.ONLINE:
            raise WriteBlockedError("Offline mode is read-only; the write was not queued.")
        try:
            authoritative = self.client.write(
                method,
                path,
                payload or {},
                idempotency_key=idempotency_key,
                params=params,
            )
        except ConcurrencyConflictError as exc:
            self.last_conflict = {
                "path": path,
                "message": str(exc),
                "current_record_version": exc.current_record_version,
            }
            self.cache.update_diagnostics(
                {
                    "last_conflict": str(exc),
                    "last_write_request_id": getattr(self.client, "last_request_id", ""),
                }
            )
            raise
        except Exception as exc:
            self.last_server_failure = str(exc)
            self.cache.update_diagnostics(
                {
                    "last_server_failure": self.last_server_failure,
                    "last_write_request_id": getattr(self.client, "last_request_id", ""),
                }
            )
            raise
        self.last_write = {"path": path, "result": authoritative}
        self.last_conflict = {}
        self.last_server_failure = ""
        self.cache.update_diagnostics(
            {
                "last_successful_write": datetime.now(timezone.utc).isoformat(),
                "last_write_path": path,
                "last_write_request_id": getattr(self.client, "last_request_id", ""),
                "last_conflict": "",
                "last_server_failure": "",
            }
        )
        try:
            self.sync.standard_refresh()
        except Exception as exc:
            authoritative = {**authoritative, "cache_refresh_required": True, "cache_refresh_error": str(exc)}
        return authoritative

    @staticmethod
    def _key(value=None):
        return value or str(uuid4())

    def create_eoat(self, request, *, idempotency_key=None):
        return self._server_first_write("POST", "/api/v1/eoats", request, idempotency_key=self._key(idempotency_key))

    def update_eoat(self, identifier, changes, expected_version):
        return self._server_first_write(
            "PATCH", f"/api/v1/eoats/{identifier}", {**changes, "expected_row_version": expected_version}
        )

    def archive_eoat(self, identifier, expected_version, reason=None):
        return self._server_first_write(
            "POST", f"/api/v1/eoats/{identifier}/archive", {"expected_row_version": expected_version, "reason": reason}
        )

    def restore_eoat(self, identifier, expected_version, reason=None):
        return self._server_first_write(
            "POST", f"/api/v1/eoats/{identifier}/restore", {"expected_row_version": expected_version, "reason": reason}
        )

    def create_machine(self, request, *, idempotency_key=None):
        return self._server_first_write("POST", "/api/v1/machines", request, idempotency_key=self._key(idempotency_key))

    def update_machine(self, identifier, changes, expected_version):
        return self._server_first_write(
            "PATCH", f"/api/v1/machines/{identifier}", {**changes, "expected_row_version": expected_version}
        )

    def archive_machine(self, identifier, expected_version, reason=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/machines/{identifier}/archive",
            {"expected_row_version": expected_version, "reason": reason},
        )

    def restore_machine(self, identifier, expected_version, reason=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/machines/{identifier}/restore",
            {"expected_row_version": expected_version, "reason": reason},
        )

    def create_tool(self, request, *, idempotency_key=None):
        return self._server_first_write("POST", "/api/v1/tools", request, idempotency_key=self._key(idempotency_key))

    def update_tool(self, identifier, changes, expected_version):
        return self._server_first_write(
            "PATCH", f"/api/v1/tools/{identifier}", {**changes, "expected_row_version": expected_version}
        )

    def archive_tool(self, identifier, expected_version, reason=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/tools/{identifier}/archive",
            {"expected_row_version": expected_version, "reason": reason},
        )

    def restore_tool(self, identifier, expected_version, reason=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/tools/{identifier}/restore",
            {"expected_row_version": expected_version, "reason": reason},
        )

    def create_robot(self, request, *, idempotency_key=None):
        return self._server_first_write("POST", "/api/v1/robots", request, idempotency_key=self._key(idempotency_key))

    def update_robot(self, identifier, changes, expected_version):
        return self._server_first_write(
            "PATCH", f"/api/v1/robots/{identifier}", {**changes, "expected_row_version": expected_version}
        )

    def archive_robot(self, identifier, expected_version, reason=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/robots/{identifier}/archive",
            {"expected_row_version": expected_version, "reason": reason},
        )

    def restore_robot(self, identifier, expected_version, reason=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/robots/{identifier}/restore",
            {"expected_row_version": expected_version, "reason": reason},
        )

    def set_compatibility(self, relationship_type, request, relationship_id=None):
        path = f"/api/v1/compatibility/{relationship_type}"
        method = "POST"
        if relationship_id is not None:
            path += f"/{relationship_id}"
            method = "PATCH"
        return self._server_first_write(method, path, request)

    def archive_compatibility(self, relationship_type, relationship_id, expected_version, reason=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/compatibility/{relationship_type}/{relationship_id}/archive",
            {"expected_row_version": expected_version, "reason": reason},
        )

    def move_eoat_to_machine(self, identifier, request, *, idempotency_key=None):
        return self._server_first_write(
            "POST", f"/api/v1/eoats/{identifier}/move-to-machine", request, idempotency_key=self._key(idempotency_key)
        )

    def move_eoat_to_storage(self, identifier, request, *, idempotency_key=None):
        return self._server_first_write(
            "POST", f"/api/v1/eoats/{identifier}/move-to-storage", request, idempotency_key=self._key(idempotency_key)
        )

    def mark_eoat_location_unknown(self, identifier, expected_version, reason, *, idempotency_key=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/eoats/{identifier}/mark-location-unknown",
            {"expected_row_version": expected_version, "reason": reason, "confirm": True},
            idempotency_key=self._key(idempotency_key),
        )

    def create_installation(self, request, *, idempotency_key=None):
        return self._server_first_write(
            "POST",
            "/api/v1/installations",
            request,
            idempotency_key=self._key(idempotency_key),
        )

    def close_installation(self, installation_id, request, *, idempotency_key=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/installations/{installation_id}/close",
            request,
            idempotency_key=self._key(idempotency_key),
        )

    def create_audit(self, request, *, idempotency_key=None):
        return self._server_first_write("POST", "/api/v1/audits", request, idempotency_key=self._key(idempotency_key))

    def update_audit(self, audit_id, changes, expected_version):
        return self._server_first_write(
            "PATCH", f"/api/v1/audits/{audit_id}", {**changes, "expected_row_version": expected_version}
        )

    def complete_audit(self, audit_id, expected_version, reason=None, *, idempotency_key=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/audits/{audit_id}/complete",
            {"expected_row_version": expected_version, "reason": reason},
            idempotency_key=self._key(idempotency_key),
        )

    def archive_audit(self, audit_id, expected_version, reason=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/audits/{audit_id}/archive",
            {"expected_row_version": expected_version, "reason": reason},
        )

    def create_maintenance_event(self, request, *, idempotency_key=None):
        return self._server_first_write(
            "POST", "/api/v1/maintenance-events", request, idempotency_key=self._key(idempotency_key)
        )

    def update_maintenance_event(self, event_id, changes, expected_version):
        return self._server_first_write(
            "PATCH",
            f"/api/v1/maintenance-events/{event_id}",
            {**changes, "expected_row_version": expected_version},
        )

    def complete_maintenance_event(self, event_id, expected_version, reason=None, *, idempotency_key=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/maintenance-events/{event_id}/complete",
            {"expected_row_version": expected_version, "reason": reason},
            idempotency_key=self._key(idempotency_key),
        )

    def add_document(self, request, *, idempotency_key=None):
        return self._server_first_write(
            "POST", "/api/v1/documents", request, idempotency_key=self._key(idempotency_key)
        )

    def update_document(self, document_id, changes, expected_version):
        return self._server_first_write(
            "PATCH", f"/api/v1/documents/{document_id}", {**changes, "expected_row_version": expected_version}
        )

    def archive_document(self, document_id, expected_version, reason=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/documents/{document_id}/archive",
            {"expected_row_version": expected_version, "reason": reason},
        )

    def supersede_document(self, document_id, replacement, expected_version, reason=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/documents/{document_id}/supersede",
            replacement,
            params={"expected_row_version": expected_version, "reason": reason},
        )

    def add_photo(self, request, *, idempotency_key=None):
        return self._server_first_write("POST", "/api/v1/photos", request, idempotency_key=self._key(idempotency_key))

    def update_photo(self, photo_id, changes, expected_version):
        return self._server_first_write(
            "PATCH", f"/api/v1/photos/{photo_id}", {**changes, "expected_row_version": expected_version}
        )

    def archive_photo(self, photo_id, expected_version, reason=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/photos/{photo_id}/archive",
            {"expected_row_version": expected_version, "reason": reason},
        )

    def set_profile_photo(self, photo_id, expected_version, reason=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/photos/{photo_id}/set-profile",
            {"expected_row_version": expected_version, "reason": reason},
        )

    def create_tag(self, request):
        return self._server_first_write("POST", "/api/v1/tags", request)

    def update_tag(self, tag_id, changes, expected_version):
        return self._server_first_write(
            "PATCH",
            f"/api/v1/tags/{tag_id}",
            {**changes, "expected_row_version": expected_version},
        )

    def archive_tag(self, tag_id, expected_version, reason=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/tags/{tag_id}/archive",
            {"expected_row_version": expected_version, "reason": reason},
        )

    def assign_tag(self, entity_type, entity_id, tag_id, comment=None):
        return self._server_first_write(
            "POST", f"/api/v1/entities/{entity_type}/{entity_id}/tags/{tag_id}", {"comment": comment}
        )

    def remove_tag(self, entity_type, entity_id, tag_id, expected_version=None):
        return self._server_first_write(
            "DELETE",
            f"/api/v1/entities/{entity_type}/{entity_id}/tags/{tag_id}",
            {"expected_row_version": expected_version} if expected_version else {},
        )

    def create_annotation(self, entity_type, entity_id, request, *, idempotency_key=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/entities/{entity_type}/{entity_id}/annotations",
            request,
            idempotency_key=self._key(idempotency_key),
        )

    def update_annotation(self, annotation_id, changes, expected_version):
        return self._server_first_write(
            "PATCH", f"/api/v1/annotations/{annotation_id}", {**changes, "expected_row_version": expected_version}
        )

    def archive_annotation(self, annotation_id, expected_version, reason=None):
        return self._server_first_write(
            "POST",
            f"/api/v1/annotations/{annotation_id}/archive",
            {"expected_row_version": expected_version, "reason": reason},
        )

    def link_annotation_target(self, annotation_id, target_id, expected_version):
        return self._server_first_write(
            "POST",
            f"/api/v1/annotations/{annotation_id}/targets/{target_id}",
            {"expected_row_version": expected_version},
        )

    def unlink_annotation_target(self, annotation_id, target_id, expected_version):
        return self._server_first_write(
            "DELETE",
            f"/api/v1/annotations/{annotation_id}/targets/{target_id}",
            {"expected_row_version": expected_version},
        )

    def archive_tag_assignments(self, assignment_ids):
        return self._server_first_write(
            "POST",
            "/api/v1/tag-assignments/archive",
            {"assignment_ids": [int(value) for value in assignment_ids]},
        )

    def evaluate_and_store_fit_check(self, request):
        return self._server_first_write(
            "POST",
            "/api/v1/fit-checks/evaluate",
            {**request, "persist": True},
        )

    def register_application_instance(self, request):
        from core.versioning import get_release_info

        release = get_release_info()
        enriched = dict(request)
        for key, value in release.provenance().items():
            enriched.setdefault(key, value)
        return self._server_first_write("POST", "/api/v1/application-instances/register", enriched)

    def heartbeat_application_instance(self, instance_uuid):
        return self._server_first_write(
            "POST",
            "/api/v1/application-instances/heartbeat",
            {"instance_uuid": instance_uuid},
        )

    def load_bundle(self, project_root: str = ""):
        status = self.get_connection_status()
        if self.cache.path.exists():
            snapshot = {
                "eoats": self.cache.list("eoats"),
                "machines": self.cache.list("machines"),
                "tools": self.cache.list("tools"),
                "photos": self.cache.list("photos"),
                "schema_revision": self.cache.metadata().get("server_schema_revision", ""),
                "server_revision": self.cache.metadata().get("server_revision", ""),
                "generated_at": self.cache.metadata().get("last_successful_sync_at", ""),
            }
        elif status.mode == ConnectivityMode.ONLINE:
            snapshot = self.client.snapshot()
        else:
            raise ApiUnavailableError(status.message)
        bundle = snapshot_to_bundle(snapshot, project_root)
        metadata = self.cache.metadata()
        cache_status = self.get_cache_status() if self.cache.path.exists() else None
        identity = self.configuration.development_identity
        role = {
            "dev.viewer": "VIEWER",
            "dev.technician": "TECHNICIAN",
            "dev.engineer": "ENGINEER",
            "dev.admin": "ADMINISTRATOR",
        }.get(identity, "Server-resolved" if identity else "Not configured")
        source_status = self.data_source_status()
        bundle.metrics.update(
            {
                "api_version": cache_status.api_version if cache_status else "",
                "environment": self.configuration.environment,
                "writes_enabled": self.configuration.writes_enabled,
                "identity": identity,
                "role": role,
                "application_instance_id": self.configuration.application_instance_id,
                "last_successful_write": metadata.get("last_successful_write", ""),
                "last_write_request_id": metadata.get("last_write_request_id", ""),
                "last_conflict": metadata.get("last_conflict", ""),
                "last_server_failure": metadata.get("last_server_failure", ""),
                "cache_status": "Ready" if cache_status and cache_status.exists else "Not built",
                "last_change_cursor": cache_status.last_change_cursor if cache_status else 0,
                "data_source_status": source_status["state"],
                "server_status_detail": source_status["detail"],
                "last_successful_server_refresh": source_status["last_successful_server_refresh"],
                "using_cached_data": source_status["using_cached_data"],
            }
        )
        bundle.metrics.update(self.diagnostics())
        return bundle
