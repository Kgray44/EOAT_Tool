"""Local, sanitized receipt persistence and discovery."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deployment.common import write_json_atomic

from .models import OperationResult
from .redaction import sanitize


class ReceiptStore:
    def __init__(self, root: Path) -> None:
        self.directory = root / ".local" / "release-tools-gui-receipts"

    def save(self, result: OperationResult) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = self.directory / f"{timestamp}-{result.tool}-{result.operation.replace(' ', '-')}.json"
        payload: dict[str, Any] = {
            "schema_version": 1,
            "tool": result.tool,
            "operation": result.operation,
            "status": result.status.value,
            "summary": result.summary,
            "blockers": list(result.blockers),
            "warnings": list(result.warnings),
            "started_at_utc": result.started_at_utc,
            "ended_at_utc": result.ended_at_utc,
            "details": result.details,
        }
        write_json_atomic(destination, sanitize(payload))
        return destination

    def list(self) -> list[Path]:
        return sorted(self.directory.glob("*.json"), reverse=True) if self.directory.is_dir() else []

    def load(self, path: Path) -> dict[str, Any]:
        return sanitize(json.loads(path.read_text(encoding="utf-8")))
