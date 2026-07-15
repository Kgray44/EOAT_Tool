from __future__ import annotations

import logging
import os
from typing import Any

from .version_info import get_release_info


def release_log_context(*, client_installation_id: str | None = None) -> dict[str, str]:
    info = get_release_info()
    return {
        "application_version": info.application_version,
        "release_id": info.release_id,
        "build_id": info.build_id,
        "client_installation_id": client_installation_id
        if client_installation_id is not None
        else os.getenv("EOAT_ATLAS_INSTANCE_ID", ""),
        "database_schema_revision": info.database_schema_revision,
        "api_contract_version": info.api_contract_version,
    }


class ReleaseContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in release_log_context().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


def configure_release_logging(logger: logging.Logger | None = None) -> None:
    target = logger or logging.getLogger()
    release_filter = ReleaseContextFilter()
    for handler in target.handlers:
        if not any(isinstance(item, ReleaseContextFilter) for item in handler.filters):
            handler.addFilter(release_filter)


def release_extra(**values: Any) -> dict[str, Any]:
    return release_log_context() | values


__all__ = ["ReleaseContextFilter", "configure_release_logging", "release_extra", "release_log_context"]
