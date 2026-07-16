from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from core.versioning import EXPECTED_API_VERSION, EXPECTED_MYSQL_VERSION, EXPECTED_SCHEMA_REVISION, get_version_info
from core.versioning.compatibility import DEFAULT_API_URL, EXPECTED_DATABASE

from .api_manager import APIManager, APIStatus
from .exceptions import BootstrapError
from .mysql_manager import MySQLManager, MySQLStatus

CANONICAL_MARKER = "EOAT_ATLAS_CANONICAL_DEVELOPMENT_ROOT"


@dataclass(frozen=True)
class BootstrapConfiguration:
    repository_root: Path
    environment: str = "development"
    backend: str = "mysql_api"
    api_url: str = DEFAULT_API_URL
    writes_enabled: bool = True
    development_identity: str = ""
    auto_start_services: bool = True

    @classmethod
    def resolve(
        cls,
        repository_root: Path,
        *,
        backend: str | None = None,
        environment: str | None = None,
        no_auto_start_services: bool = False,
    ) -> BootstrapConfiguration:
        path = repository_root / "config" / "development.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        selected_backend = (backend or os.getenv("EOAT_ATLAS_DATA_BACKEND") or payload.get("backend") or "mysql_api")
        selected_environment = (
            environment or os.getenv("EOAT_ATLAS_ENVIRONMENT") or payload.get("environment") or "development"
        )
        selected_backend = str(selected_backend).strip().casefold()
        selected_environment = str(selected_environment).strip().casefold()
        if selected_backend not in {"mysql_api", "legacy"}:
            raise BootstrapError(f"Unsupported backend: {selected_backend}")
        if selected_environment != "development":
            raise BootstrapError("The canonical source launcher supports only environment=development.")
        return cls(
            repository_root=repository_root.resolve(),
            environment=selected_environment,
            backend=selected_backend,
            api_url=str(os.getenv("EOAT_ATLAS_API_URL") or payload.get("api_url") or DEFAULT_API_URL).rstrip("/"),
            writes_enabled=str(os.getenv("EOAT_ATLAS_WRITES_ENABLED") or payload.get("writes_enabled", True)).casefold()
            in {"1", "true", "yes", "on"},
            development_identity=str(
                os.environ.get("EOAT_ATLAS_DEV_IDENTITY", payload.get("development_identity", ""))
            ),
            auto_start_services=not no_auto_start_services,
        )


@dataclass(frozen=True)
class StartupReport:
    configuration: BootstrapConfiguration
    mysql: MySQLStatus | None
    api: APIStatus | None
    mysql_started: bool = False
    api_started: bool = False


class DevelopmentServiceManager:
    def __init__(self, configuration: BootstrapConfiguration):
        self.configuration = configuration
        self.mysql = MySQLManager()
        self.api = APIManager(configuration.repository_root, api_url=configuration.api_url)

    def verify_canonical_repository(self) -> None:
        root = self.configuration.repository_root
        marker = root / CANONICAL_MARKER
        configured = os.getenv("EOAT_ATLAS_CANONICAL_DEVELOPMENT_ROOT", "").strip()
        if configured and root != Path(configured).expanduser().resolve():
            raise BootstrapError("Repository does not match EOAT_ATLAS_CANONICAL_DEVELOPMENT_ROOT.")
        required = (
            marker,
            root / "release_defaults.json",
            root / "app" / "atlas" / "version.json",
            root / "app" / "atlas" / "main.py",
            root / "server",
        )
        missing = [path.name for path in required if not path.exists()]
        if missing:
            raise BootstrapError("Repository is missing canonical marker/layout entries: " + ", ".join(missing))
        info = get_version_info(root)
        if info.branch_name and info.branch_name != "development/mysql-api-consolidated":
            raise BootstrapError(f"Release metadata identifies an unexpected development branch: {info.branch_name}")

    def configure_client_environment(self) -> None:
        info = get_version_info(self.configuration.repository_root)
        os.environ.update(
            {
                "EOAT_ATLAS_ENVIRONMENT": self.configuration.environment,
                "EOAT_ATLAS_DATA_BACKEND": self.configuration.backend,
                "EOAT_ATLAS_API_URL": self.configuration.api_url,
                "EOAT_ATLAS_WRITES_ENABLED": "true" if self.configuration.writes_enabled else "false",
                "EOAT_ATLAS_DEV_IDENTITY": self.configuration.development_identity,
                "EOAT_ATLAS_INSTANCE_ID": os.environ.get("EOAT_ATLAS_INSTANCE_ID") or str(uuid4()),
                "EOAT_ATLAS_CLIENT_VERSION": info.application_version,
            }
        )

    def prepare(self) -> StartupReport:
        self.verify_canonical_repository()
        self.configure_client_environment()
        if self.configuration.backend == "legacy":
            return StartupReport(self.configuration, None, None)
        mysql, mysql_started = self.mysql.ensure_running(auto_start=self.configuration.auto_start_services)
        api, api_started = self.api.ensure_running(
            auto_start=self.configuration.auto_start_services,
            writes_enabled=self.configuration.writes_enabled,
        )
        return StartupReport(self.configuration, mysql, api, mysql_started, api_started)

    @staticmethod
    def print_banner(report: StartupReport) -> None:
        info = get_version_info(report.configuration.repository_root)
        mysql = report.mysql
        api = report.api
        lines = [
            "=" * 60,
            "EOAT Atlas Development Bootstrap",
            "=" * 60,
            f"Canonical repository: {report.configuration.repository_root}",
            f"Application version: {info.application_version}",
            f"Release ID: {info.release_id}",
            f"Build ID: {info.build_id}",
            f"Environment: {report.configuration.environment}",
            f"Backend: {report.configuration.backend}",
            f"API: {report.configuration.api_url if api else 'Not used (explicit legacy mode)'}",
            f"API version: {api.api_version if api else 'N/A'}",
            f"API status: {'Online' if api and api.healthy else 'N/A'}",
            f"MySQL: {'Connected' if mysql and mysql.connected else 'N/A'}",
            f"MySQL version: {mysql.version if mysql else 'N/A'}",
            f"Database: {mysql.database if mysql else 'N/A'}",
            f"Schema revision: {mysql.schema_revision if mysql else 'N/A'}",
            "Cache: Disposable API cache" if api else "Cache: Legacy mode selected explicitly",
            "Legacy fallback: Disabled" if api else "Legacy fallback: Explicit legacy mode",
            f"Application module: {report.configuration.repository_root / 'app' / 'atlas' / 'main.py'}",
            "=" * 60,
        ]
        print("\n".join(lines), flush=True)


def expected_versions() -> dict[str, str]:
    return {
        "api": EXPECTED_API_VERSION,
        "mysql": EXPECTED_MYSQL_VERSION,
        "schema": EXPECTED_SCHEMA_REVISION,
        "database": EXPECTED_DATABASE,
    }


def assert_module_is_canonical(module, repository_root: Path) -> None:
    path = Path(str(getattr(module, "__file__", ""))).resolve()
    try:
        path.relative_to(repository_root.resolve())
    except ValueError as exc:
        raise BootstrapError(f"Refusing to launch module outside the canonical repository: {path}") from exc
