from __future__ import annotations

from pathlib import Path

from .connectivity import check_connectivity
from .exceptions import ApiUnavailableError, IncompatibleServerError
from .models import ConnectivityMode


class SyncCoordinator:
    def __init__(self, client, cache, configuration):
        self.client = client
        self.cache = cache
        self.configuration = configuration

    def standard_refresh(self) -> dict:
        status = check_connectivity(self.client, self.configuration)
        if status.mode == ConnectivityMode.INCOMPATIBLE_SERVER:
            raise IncompatibleServerError(status.message)
        if status.mode != ConnectivityMode.ONLINE:
            raise ApiUnavailableError(status.message)
        cursor = self.cache.status().last_change_cursor if self.cache.path.exists() else 0
        changes = self.client.changes(cursor)
        if changes.get("changes"):
            result = self.deep_refresh()
            result["mode"] = "incremental_snapshot_reconciliation"
            return result
        self.cache.initialize()
        self.cache.apply_change_cursor(changes)
        return {"mode": "incremental", "changes_applied": 0, "cursor": changes.get("next_cursor", cursor)}

    def deep_refresh(self) -> dict:
        status = check_connectivity(self.client, self.configuration)
        if status.mode == ConnectivityMode.INCOMPATIBLE_SERVER:
            raise IncompatibleServerError(status.message)
        if status.mode != ConnectivityMode.ONLINE:
            raise ApiUnavailableError(status.message)
        snapshot = self.client.snapshot()
        temporary = Path(str(self.cache.path) + ".building")
        self.cache.build_snapshot(snapshot, temporary)
        counts = self.cache.validate(temporary)
        self.cache.replace_with(temporary)
        return {"mode": "full", "cursor": snapshot.get("cursor", 0), "counts": counts}
