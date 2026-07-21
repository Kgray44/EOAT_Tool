from __future__ import annotations

from datetime import datetime, timezone

from .configuration import GatewayConfiguration
from .exceptions import ApiUnavailableError
from .models import ConnectionStatus, ConnectivityMode


def check_connectivity(client, configuration: GatewayConfiguration) -> ConnectionStatus:
    checked = datetime.now(timezone.utc).isoformat()
    try:
        health = client.health()
    except ApiUnavailableError as exc:
        return ConnectionStatus(ConnectivityMode.OFFLINE_READ_ONLY, str(exc), last_checked_at=checked)
    api_version = str(health.get("api_version", ""))
    schema = str(health.get("current_schema_revision", ""))
    try:
        major = int(api_version.split(".", 1)[0])
    except ValueError:
        major = -1
    if (
        major != configuration.supported_api_major
        or api_version != configuration.expected_api_version
        or schema != configuration.expected_schema_revision
        or not health.get("compatible", False)
    ):
        return ConnectionStatus(
            ConnectivityMode.INCOMPATIBLE_SERVER,
            "Server API/schema is incompatible "
            f"(API {api_version}, schema {schema}; expected API {configuration.expected_api_version}, "
            f"schema {configuration.expected_schema_revision}).",
            api_version,
            schema,
            checked,
        )
    return ConnectionStatus(ConnectivityMode.ONLINE, "Connected to the EOAT Atlas API.", api_version, schema, checked)
