from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_BACKENDS = {"legacy", "mysql_api"}


@dataclass(frozen=True)
class GatewayConfiguration:
    backend: str = "mysql_api"
    api_base_url: str = "http://127.0.0.1:8765"
    timeout_seconds: float = 10.0
    cache_path: Path = Path.home() / "AppData" / "Local" / "EOAT Atlas Development" / "eoat_atlas_api_cache_dev.db"
    supported_api_major: int = 1
    expected_schema_revision: str = "20260714_0005"
    writes_enabled: bool = True
    environment: str = "development"
    development_identity: str = ""
    application_instance_id: str = ""
    client_version: str = ""

    @classmethod
    def from_environment(cls) -> GatewayConfiguration:
        backend = os.getenv("EOAT_ATLAS_DATA_BACKEND", "mysql_api").strip().casefold()
        if backend not in SUPPORTED_BACKENDS:
            raise ValueError(f"Unsupported EOAT_ATLAS_DATA_BACKEND '{backend}'. Expected legacy or mysql_api.")
        cache = (
            Path(os.getenv("EOAT_ATLAS_API_CACHE", "")).expanduser()
            if os.getenv("EOAT_ATLAS_API_CACHE")
            else cls.cache_path
        )
        return cls(
            backend=backend,
            api_base_url=os.getenv("EOAT_ATLAS_API_URL", "http://127.0.0.1:8765").rstrip("/"),
            timeout_seconds=float(os.getenv("EOAT_ATLAS_API_TIMEOUT", "10")),
            cache_path=cache,
            writes_enabled=os.getenv("EOAT_ATLAS_WRITES_ENABLED", "true").strip().casefold()
            in {"1", "true", "yes", "on"},
            environment=os.getenv("EOAT_ATLAS_ENVIRONMENT", "development").strip().casefold(),
            development_identity=os.getenv("EOAT_ATLAS_DEV_IDENTITY", "").strip(),
            application_instance_id=os.getenv("EOAT_ATLAS_INSTANCE_ID", "").strip(),
            client_version=os.getenv("EOAT_ATLAS_CLIENT_VERSION", "").strip(),
        )
