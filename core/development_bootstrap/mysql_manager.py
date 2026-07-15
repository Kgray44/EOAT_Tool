from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from core.versioning.compatibility import EXPECTED_DATABASE, EXPECTED_MYSQL_VERSION, EXPECTED_SCHEMA_REVISION

from .exceptions import BootstrapError
from .process_tracking import StatePaths, listener_pid, load_environment_file, process_info, read_pid


@dataclass(frozen=True)
class MySQLStatus:
    running: bool
    connected: bool
    pid: int | None
    version: str
    database: str
    schema_revision: str
    table_count: int
    log_path: str
    message: str = ""


class MySQLManager:
    def __init__(self, *, state: StatePaths | None = None, host: str = "127.0.0.1", port: int = 3306):
        self.state = state or StatePaths.local()
        self.host = host
        self.port = port

    def _expected_process(self, pid: int):
        info = process_info(pid)
        if info is None:
            raise BootstrapError(f"Port {self.port} is occupied by PID {pid}, but process details are unavailable.")
        expected = str(self.state.mysql_executable.resolve()).casefold()
        actual = str(Path(info.executable_path).resolve()).casefold() if info.executable_path else ""
        if actual != expected:
            raise BootstrapError(
                f"Port {self.port} is occupied by an unexpected process (PID {pid}, {info.name}, {info.executable_path}).",
                hint="Stop or reconfigure that process; EOAT Atlas will not kill it automatically.",
            )
        return info

    def _database_values(self) -> dict[str, str]:
        values = load_environment_file(self.state.database_environment)
        if not values:
            raise BootstrapError(
                f"Local database configuration was not found: {self.state.database_environment}",
                hint="Run the approved local MySQL setup or repair the configuration file.",
            )
        return values

    def _query(self) -> tuple[str, str, str, int]:
        values = self._database_values()
        database = values.get("EOAT_DB_NAME", EXPECTED_DATABASE)
        environment = os.environ.copy()
        environment["MYSQL_PWD"] = values.get("EOAT_DB_PASSWORD", "")
        sql = (
            "SELECT VERSION(), DATABASE(), "
            "(SELECT version_num FROM alembic_version LIMIT 1), "
            "(SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE());"
        )
        result = subprocess.run(
            [
                str(self.state.mysql_client),
                f"--host={values.get('EOAT_DB_HOST', self.host)}",
                f"--port={values.get('EOAT_DB_PORT', self.port)}",
                f"--user={values.get('EOAT_DB_USER', 'eoat_atlas_app')}",
                f"--database={database}",
                "--batch",
                "--skip-column-names",
                "--execute",
                sql,
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        environment.pop("MYSQL_PWD", None)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "MySQL connectivity query failed")
        fields = result.stdout.strip().split("\t")
        if len(fields) != 4:
            raise RuntimeError("MySQL verification returned an unexpected result")
        version, selected_database, revision, table_count = fields
        return version, selected_database, revision, int(table_count)

    def status(self) -> MySQLStatus:
        pid = listener_pid(self.port)
        if pid is None:
            return MySQLStatus(False, False, None, "", EXPECTED_DATABASE, "", 0, str(self.state.mysql_log), "Stopped")
        self._expected_process(pid)
        try:
            version, database, revision, table_count = self._query()
        except Exception as exc:
            return MySQLStatus(True, False, pid, "", EXPECTED_DATABASE, "", 0, str(self.state.mysql_log), str(exc))
        return MySQLStatus(True, True, pid, version, database, revision, table_count, str(self.state.mysql_log))

    def verify(self, status: MySQLStatus | None = None) -> MySQLStatus:
        current = status or self.status()
        if not current.running or not current.connected:
            raise BootstrapError(
                f"Local MySQL is not ready: {current.message or 'not running'}",
                log_path=current.log_path,
                hint="Run .\\Get_Local_MySQL_Status.ps1 and inspect the MySQL log.",
            )
        if not current.version.startswith(EXPECTED_MYSQL_VERSION):
            raise BootstrapError(f"MySQL version mismatch. Expected {EXPECTED_MYSQL_VERSION}; detected {current.version}.")
        if current.database != EXPECTED_DATABASE:
            raise BootstrapError(f"Database mismatch. Expected {EXPECTED_DATABASE}; detected {current.database}.")
        if current.schema_revision != EXPECTED_SCHEMA_REVISION:
            raise BootstrapError(
                "EOAT Atlas cannot start writable development mode.\n\n"
                f"Expected schema: {EXPECTED_SCHEMA_REVISION}\nDetected schema: {current.schema_revision or 'unavailable'}",
                hint=(
                    "An authorized migrator must run "
                    ".\\scripts\\database\\upgrade_database.ps1 -DatabaseName eoat_atlas_dev "
                    "after reviewing the migration; runtime credentials never migrate schemas."
                ),
            )
        return current

    def ensure_running(self, *, auto_start: bool = True) -> tuple[MySQLStatus, bool]:
        current = self.status()
        if current.running:
            return self.verify(current), False
        if not auto_start:
            raise BootstrapError("Local MySQL is stopped and automatic service startup is disabled.")
        return self.verify(self.start()), True

    def start(self) -> MySQLStatus:
        existing = listener_pid(self.port)
        if existing is not None:
            self._expected_process(existing)
            return self.verify(self.status())
        if not self.state.mysql_executable.is_file() or not self.state.mysql_data.is_dir():
            raise BootstrapError(
                "Local MySQL was not found.",
                hint=f"Expected portable installation: {self.state.mysql_executable}",
            )
        self.state.root.mkdir(parents=True, exist_ok=True)
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        process = subprocess.Popen(
            [
                str(self.state.mysql_executable),
                f"--basedir={self.state.mysql_base}",
                f"--datadir={self.state.mysql_data}",
                "--bind-address=127.0.0.1",
                f"--port={self.port}",
                "--mysqlx=OFF",
                f"--log-error={self.state.mysql_log}",
                f"--pid-file={self.state.mysql_pid}",
            ],
            cwd=str(self.state.root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise BootstrapError(
                    f"MySQL failed to start (exit code {process.returncode}).",
                    log_path=str(self.state.mysql_log),
                    hint="Run .\\Get_Local_MySQL_Status.ps1.",
                )
            current = self.status()
            if current.connected:
                return current
            time.sleep(0.5)
        raise BootstrapError(
            "MySQL did not become ready within 30 seconds.",
            log_path=str(self.state.mysql_log),
            hint="Run .\\Get_Local_MySQL_Status.ps1.",
        )

    def stop(self) -> None:
        pid = listener_pid(self.port) or read_pid(self.state.mysql_pid)
        if pid is None:
            return
        self._expected_process(pid)
        values = self._database_values()
        environment = os.environ.copy()
        environment["MYSQL_PWD"] = values.get("EOAT_DB_ROOT_PASSWORD", "")
        result = subprocess.run(
            [
                str(self.state.mysql_admin),
                f"--host={values.get('EOAT_DB_HOST', self.host)}",
                f"--port={values.get('EOAT_DB_PORT', self.port)}",
                "--user=root",
                "shutdown",
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        environment.pop("MYSQL_PWD", None)
        if result.returncode:
            raise BootstrapError(
                f"MySQL graceful shutdown failed; PID {pid} remains under review.",
                log_path=str(self.state.mysql_log),
            )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and listener_pid(self.port) is not None:
            time.sleep(0.25)
        if listener_pid(self.port) is not None:
            raise BootstrapError(f"MySQL PID {pid} remains running after graceful shutdown.")
