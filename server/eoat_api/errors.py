from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class APIError(Exception):
    status_code: int
    error_code: str
    message: str
    details: Any = None
    retryable: bool = False
    current_record_version: int | None = None

    def __str__(self) -> str:
        return self.message


def not_found(entity: str, identifier: object) -> APIError:
    return APIError(404, "NOT_FOUND", f"{entity} '{identifier}' was not found.")


def conflict(current_version: int) -> APIError:
    return APIError(
        409,
        "STALE_RECORD_VERSION",
        "This record was changed by another user.",
        current_record_version=current_version,
    )
