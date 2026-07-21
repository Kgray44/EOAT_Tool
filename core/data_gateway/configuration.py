from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from core.globalization.runtime_paths import ensure_runtime_layout, get_runtime_paths
from core.resources import resource_path
from core.versioning import EXPECTED_API_VERSION, EXPECTED_SCHEMA_REVISION, get_app_version

SUPPORTED_BACKENDS = {"legacy", "mysql_api"}
PRODUCTION_PROFILE_FILE = "config/production.json"


def load_production_profile(path: str | Path | None = None) -> dict[str, object]:
    """Load the read-only production profile bundled with the desktop client."""

    profile_path = Path(path) if path is not None else resource_path(PRODUCTION_PROFILE_FILE)
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"EOAT Atlas production profile is unavailable: {profile_path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("EOAT Atlas production profile must be a JSON object.")
    required = {
        "environment": "production",
        "backend": "mysql_api",
        "api_url": None,
        "writes_enabled": False,
        "expected_api_version": None,
        "expected_schema_revision": None,
        "cache_filename": None,
    }
    for key, expected in required.items():
        value = payload.get(key)
        if value in (None, "") or (expected is not None and value != expected):
            raise RuntimeError(f"EOAT Atlas production profile has an invalid {key!r} value.")
    api_url = str(payload["api_url"]).rstrip("/")
    if not api_url.startswith(("http://", "https://")):
        raise RuntimeError("EOAT Atlas production profile has an invalid API URL.")
    return payload


def configure_packaged_production_environment(path: str | Path | None = None) -> dict[str, object]:
    """Force a frozen client onto the bundled production API profile.

    The ordinary desktop package must not inherit an old local-development URL,
    a development identity, or a writable mode from the parent process.
    ``EOAT_ATLAS_PACKAGED_TEST_MODE`` is intentionally the sole test-only
    escape hatch used by the package smoke harness.
    """

    if os.getenv("EOAT_ATLAS_PACKAGED_TEST_MODE") == "1":
        return {}
    payload = load_production_profile(path)
    os.environ["EOAT_ATLAS_RUNTIME_FOLDER_NAME"] = "EOAT_Atlas"
    runtime = ensure_runtime_layout(get_runtime_paths())
    cache_path = runtime.data_dir / str(payload["cache_filename"])
    os.environ.update(
        {
            "EOAT_ATLAS_DATA_BACKEND": str(payload["backend"]),
            "EOAT_ATLAS_API_URL": str(payload["api_url"]).rstrip("/"),
            "EOAT_ATLAS_ENVIRONMENT": str(payload["environment"]),
            "EOAT_ATLAS_WRITES_ENABLED": "false",
            "EOAT_ATLAS_EXPECTED_API_VERSION": str(payload["expected_api_version"]),
            "EOAT_ATLAS_EXPECTED_SCHEMA_REVISION": str(payload["expected_schema_revision"]),
            "EOAT_ATLAS_API_CACHE": str(cache_path),
        }
    )
    os.environ.pop("EOAT_ATLAS_DEV_IDENTITY", None)
    return payload


@dataclass(frozen=True)
class GatewayConfiguration:
    backend: str = "mysql_api"
    api_base_url: str = "http://127.0.0.1:8765"
    timeout_seconds: float = 10.0
    cache_path: Path = Path.home() / "AppData" / "Local" / "EOAT Atlas Development" / "eoat_atlas_api_cache_dev.db"
    supported_api_major: int = 1
    expected_api_version: str = EXPECTED_API_VERSION
    expected_schema_revision: str = EXPECTED_SCHEMA_REVISION
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
            expected_api_version=os.getenv("EOAT_ATLAS_EXPECTED_API_VERSION", EXPECTED_API_VERSION).strip(),
            expected_schema_revision=os.getenv(
                "EOAT_ATLAS_EXPECTED_SCHEMA_REVISION", EXPECTED_SCHEMA_REVISION
            ).strip(),
            writes_enabled=os.getenv("EOAT_ATLAS_WRITES_ENABLED", "true").strip().casefold()
            in {"1", "true", "yes", "on"},
            environment=os.getenv("EOAT_ATLAS_ENVIRONMENT", "development").strip().casefold(),
            development_identity=os.getenv("EOAT_ATLAS_DEV_IDENTITY", "").strip(),
            application_instance_id=os.getenv("EOAT_ATLAS_INSTANCE_ID", "").strip(),
            client_version=os.getenv("EOAT_ATLAS_CLIENT_VERSION", "").strip() or get_app_version(),
        )
