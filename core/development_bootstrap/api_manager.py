from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from core.versioning.compatibility import EXPECTED_API_VERSION, EXPECTED_SCHEMA_REVISION

from .exceptions import BootstrapError
from .health_checks import get_json, wait_for
from .process_tracking import StatePaths, listener_pid, load_environment_file, process_info, write_json_atomic


@dataclass(frozen=True)
class APIStatus:
    running: bool
    healthy: bool
    canonical: bool
    pid: int | None
    api_version: str
    schema_revision: str
    server_revision: str
    database_reachable: bool
    writes_enabled: bool
    log_path: str
    message: str = ""


class APIManager:
    def __init__(self, repository_root: Path, *, state: StatePaths | None = None, api_url: str = "http://127.0.0.1:8765"):
        self.repository_root = repository_root.resolve()
        self.state = state or StatePaths.local()
        self.api_url = api_url.rstrip("/")
        self.port = int(self.api_url.rsplit(":", 1)[-1])

    def _metadata(self) -> dict:
        try:
            payload = json.loads(self.state.api_metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _process_is_api(self, pid: int) -> bool:
        info = process_info(pid)
        if info is None:
            return False
        return info.name.casefold().startswith("python") and "server.eoat_api" in info.command_line

    def status(self) -> APIStatus:
        pid = listener_pid(self.port)
        if pid is None:
            return APIStatus(False, False, False, None, "", "", "", False, False, str(self.state.api_log), "Stopped")
        info = process_info(pid)
        if info is None or not self._process_is_api(pid):
            name = info.name if info else "unknown"
            path = info.executable_path if info else "unknown"
            return APIStatus(True, False, False, pid, "", "", "", False, False, str(self.state.api_log), f"Unexpected listener: {name} ({path})")
        health = get_json(f"{self.api_url}/api/v1/health") or {}
        version = get_json(f"{self.api_url}/api/v1/version") or {}
        metadata = self._metadata()
        canonical = (
            int(metadata.get("pid") or 0) == pid
            and str(metadata.get("repository_root") or "").casefold() == str(self.repository_root).casefold()
        )
        return APIStatus(
            True,
            bool(health.get("api_reachable") and health.get("database_reachable")),
            canonical,
            pid,
            str(health.get("api_version") or version.get("api_version") or ""),
            str(health.get("current_schema_revision") or ""),
            str(version.get("server_revision") or ""),
            bool(health.get("database_reachable")),
            bool(health.get("writes_enabled")),
            str(self.state.api_log),
            "" if health else "Health endpoint unavailable",
        )

    def verify(self, status: APIStatus | None = None, *, require_canonical: bool = True, writes_enabled: bool = True) -> APIStatus:
        current = status or self.status()
        if not current.running or not current.healthy:
            raise BootstrapError(
                f"Local EOAT Atlas API is not ready: {current.message or 'not running'}",
                log_path=current.log_path,
                hint="Run .\\Get_Local_EOAT_API_Status.ps1.",
            )
        if require_canonical and not current.canonical:
            raise BootstrapError(
                f"Port {self.port} is occupied by an untracked or noncanonical EOAT Atlas API (PID {current.pid}).",
                hint="Stop it with its approved script, then run .\\Start_Local_EOAT_API.ps1 from the canonical repository.",
            )
        if current.api_version != EXPECTED_API_VERSION:
            raise BootstrapError(f"API version mismatch. Expected {EXPECTED_API_VERSION}; detected {current.api_version}.")
        if current.schema_revision != EXPECTED_SCHEMA_REVISION:
            raise BootstrapError(
                f"API schema mismatch. Expected {EXPECTED_SCHEMA_REVISION}; detected {current.schema_revision}.",
                hint="Review and run the approved database upgrade command; startup never migrates automatically.",
            )
        if writes_enabled and not current.writes_enabled:
            raise BootstrapError("The API is healthy but development writes are disabled; writable startup is blocked.")
        return current

    def ensure_running(self, *, auto_start: bool = True, writes_enabled: bool = True) -> tuple[APIStatus, bool]:
        current = self.status()
        if current.running:
            return self.verify(current, writes_enabled=writes_enabled), False
        if not auto_start:
            raise BootstrapError("The local EOAT Atlas API is stopped and automatic service startup is disabled.")
        return self.verify(self.start(writes_enabled=writes_enabled), writes_enabled=writes_enabled), True

    def start(self, *, writes_enabled: bool = True) -> APIStatus:
        current = self.status()
        if current.running:
            return self.verify(current, writes_enabled=writes_enabled)
        self.state.root.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update(load_environment_file(self.state.database_environment))
        environment.update(
            {
                "EOAT_API_HOST": "127.0.0.1",
                "EOAT_API_PORT": str(self.port),
                "EOAT_API_ENVIRONMENT": "development",
                "EOAT_API_WRITES_ENABLED": "true" if writes_enabled else "false",
            }
        )
        stdout_log = self.state.api_log.open("a", encoding="utf-8")
        stderr_log = self.state.api_log.with_suffix(".log.err").open("a", encoding="utf-8")
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        process = subprocess.Popen(
            [sys.executable, "-m", "server.eoat_api"],
            cwd=str(self.repository_root),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout_log,
            stderr=stderr_log,
            creationflags=flags,
        )
        stdout_log.close()
        stderr_log.close()
        write_json_atomic(
            self.state.api_metadata,
            {
                "pid": process.pid,
                "repository_root": str(self.repository_root),
                "python": sys.executable,
                "api_url": self.api_url,
            },
        )
        self.state.api_pid.write_text(f"{process.pid}\n", encoding="utf-8")

        def ready():
            if process.poll() is not None:
                return None
            status = self.status()
            return status if status.healthy else None

        status = wait_for(ready, timeout=30)
        if not status:
            if process.poll() is None:
                process.terminate()
            raise BootstrapError(
                f"EOAT Atlas API failed to start (exit code {process.poll()}).",
                log_path=str(self.state.api_log),
                hint="Run .\\Get_Local_EOAT_API_Status.ps1.",
            )
        return status

    def stop(self) -> None:
        current = self.status()
        if not current.running:
            return
        if not current.canonical or current.pid is None or not self._process_is_api(current.pid):
            raise BootstrapError(f"Refusing to stop unverified API process on port {self.port} (PID {current.pid}).")
        try:
            os.kill(current.pid, signal.SIGTERM)
        except OSError as exc:
            raise BootstrapError(f"Could not stop canonical API PID {current.pid}: {exc}") from exc
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and listener_pid(self.port) is not None:
            time.sleep(0.25)
        if listener_pid(self.port) is not None:
            raise BootstrapError(f"Canonical API PID {current.pid} remains running after shutdown request.")
        self.state.api_pid.unlink(missing_ok=True)
        self.state.api_metadata.unlink(missing_ok=True)
