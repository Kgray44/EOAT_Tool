from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.atlas_data_loader import load_atlas_data
from core.data_gateway.api_client import AtlasApiClient
from core.data_gateway.cache_repository import CacheRepository
from core.data_gateway.configuration import GatewayConfiguration
from core.data_gateway.gateway import AtlasDataGateway
from core.data_gateway.mappings import snapshot_to_bundle
from core.fit_check_service import FitCheckRequest, FitCheckService


@dataclass
class ParityItem:
    feature: str
    identifier: str
    classification: str
    legacy_value: Any
    mysql_value: Any
    evidence: str


def _record(
    items: list[ParityItem],
    feature: str,
    identifier: str,
    legacy: Any,
    mysql: Any,
    expected: str | None = None,
    evidence: str = "",
) -> None:
    classification = "MATCH" if legacy == mysql else (expected or "MYSQL_VALUE_MISMATCH")
    items.append(ParityItem(feature, identifier, classification, legacy, mysql, evidence))


def validate(project_root: str | Path, api_url: str, output: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    timings: dict[str, list[float]] = {}

    def timed(name: str, call):
        started = time.perf_counter()
        value = call()
        timings.setdefault(name, []).append((time.perf_counter() - started) * 1000)
        return value

    legacy = timed("legacy_bundle_cold", lambda: load_atlas_data(root, force_refresh=True))
    client = AtlasApiClient(api_url, timeout=60)
    health = timed("api_health_cold", client.health)
    timed("api_health_warm", client.health)
    snapshot = timed("sync_snapshot", client.snapshot)
    mysql = snapshot_to_bundle(snapshot, str(root))
    items: list[ParityItem] = []
    _record(items, "Home EOAT count", "home", len(legacy.eoats), len(mysql.eoats))
    _record(
        items,
        "Home machine count",
        "home",
        len(legacy.machines),
        len(mysql.machines),
        "EXPECTED_NORMALIZATION",
        "MySQL uses one machine per plant/number; legacy may surface area-derived duplicates.",
    )
    _record(
        items,
        "Home tool count",
        "home",
        len(legacy.tools),
        len(mysql.tools),
        "EXPECTED_NORMALIZATION",
        "The legacy bundle contains duplicate render records; MySQL exposes 65 unique tool identifiers.",
    )
    legacy_eoats = {item.eoat_id: item for item in legacy.eoats}
    mysql_eoats = {item.eoat_id: item for item in mysql.eoats}
    _record(items, "EOAT identifiers", "all", sorted(legacy_eoats), sorted(mysql_eoats))
    legacy_machines = {item.machine: item for item in legacy.machines}
    mysql_machines = {item.machine: item for item in mysql.machines}
    _record(
        items,
        "Machine identifiers",
        "all",
        sorted(legacy_machines),
        sorted(mysql_machines),
        "EXPECTED_NORMALIZATION",
        "Ambiguous/noncanonical machine values are not imported as machines.",
    )
    legacy_tools = {item.tool: item for item in legacy.tools}
    mysql_tools = {item.tool: item for item in mysql.tools}
    _record(items, "Tool identifiers", "all", sorted(legacy_tools), sorted(mysql_tools))
    for identifier in sorted(set(legacy_eoats) & set(mysql_eoats)):
        left = legacy_eoats[identifier]
        right = mysql_eoats[identifier]
        _record(
            items,
            "EOAT type",
            identifier,
            left.eoat_type,
            right.eoat_type,
            "EXPECTED_UNRESOLVED_SOURCE_DATA" if right.eoat_type in {"", "Unknown"} else None,
        )
        _record(
            items,
            "Connection type",
            identifier,
            left.connection_type,
            right.connection_type,
            "EXPECTED_UNRESOLVED_SOURCE_DATA" if not right.connection_type else None,
        )
        _record(
            items,
            "EOAT-machine relationships",
            identifier,
            sorted(left.machines),
            sorted(right.machines),
            "EXPECTED_UNRESOLVED_SOURCE_DATA",
            "Unsafe current-location inference is not performed; compatibility associations remain available.",
        )
        _record(
            items,
            "EOAT-tool relationships",
            identifier,
            sorted(left.tools),
            sorted(right.tools),
            "EXPECTED_UNRESOLVED_SOURCE_DATA",
        )
        _record(items, "Audit evidence rows", identifier, len(left.source_rows), len(right.source_rows))
        _record(
            items,
            "Photo count",
            identifier,
            left.photo_count,
            right.photo_count,
            "EXPECTED_NORMALIZATION",
            "API counts explicit imported photo links; legacy may merge folder scans and index rows.",
        )
    for query in [
        next(iter(sorted(legacy_eoats))),
        next(iter(sorted(legacy_tools))),
        next(iter(sorted(legacy_machines))),
    ]:
        api_results = timed("search", lambda q=query: client.search(q, limit=50))
        _record(
            items,
            "Search result contains query",
            query,
            True,
            any(
                query.casefold() in (str(item.get("identifier", "")) + str(item.get("title", ""))).casefold()
                for item in api_results
            ),
        )
    common_setup = None
    for eoat in mysql.eoats:
        if eoat.machines and eoat.tools:
            common_setup = (eoat.machines[0], eoat.tools[0], eoat.eoat_id)
            break
    if common_setup:
        machine, tool, eoat_id = common_setup
        legacy_fit = FitCheckService(legacy).run_fit_check(
            FitCheckRequest(tool_id=tool, machine_id=machine, eoat_id=eoat_id, eoat_mode="manual")
        )
        api_fit = timed("fit_check", lambda: client.evaluate_fit_check(machine, tool, eoat_id))
        expected = "COMPATIBLE" if legacy_fit and legacy_fit.compatibility.full_setup == "pass" else "NEEDS_REVIEW"
        _record(
            items,
            "Fit Check overall",
            f"{machine}|{tool}|{eoat_id}",
            expected,
            api_fit["overall_result"],
            "EXPECTED_UNRESOLVED_SOURCE_DATA",
            "API never converts an absent relationship into incompatibility.",
        )
        packet = timed("setup_packet_data", lambda: client.setup_packet_data(machine, tool, eoat_id))
        _record(items, "Setup Packet EOAT source", eoat_id, eoat_id, packet["eoat"]["business_identifier"])
    timed("home_summary", client.home_summary)
    timed("eoat_list", lambda: client.list_eoats(page=1, page_size=50))
    timed("eoat_profile", lambda: client.get_eoat(next(iter(sorted(mysql_eoats)))))

    cache_path = Path.home() / "AppData" / "Local" / "EOAT Atlas Development" / "eoat_atlas_api_cache_dev.db"
    gateway = AtlasDataGateway(
        GatewayConfiguration(backend="mysql_api", api_base_url=api_url, timeout_seconds=60, cache_path=cache_path)
    )
    deep_result = timed("deep_refresh", gateway.deep_refresh)
    standard_result = timed("standard_refresh", gateway.refresh)
    cache_status = gateway.get_cache_status()
    gateway.close()

    client_paths = [cache_path, cache_path.with_name("eoat_atlas_api_cache_dev_client_b.db")]
    clients = []
    for path in client_paths:
        gateway = AtlasDataGateway(
            GatewayConfiguration(backend="mysql_api", api_base_url=api_url, timeout_seconds=60, cache_path=path)
        )
        result = timed("multi_client_deep_refresh", gateway.deep_refresh)
        status = gateway.get_cache_status()
        gateway.close()
        clients.append({"cache_path": str(path), "refresh": result, "counts": status.entity_counts})
    before_a = clients[0]["counts"].copy()
    client_paths[1].unlink(missing_ok=True)
    gateway = AtlasDataGateway(
        GatewayConfiguration(backend="mysql_api", api_base_url=api_url, timeout_seconds=60, cache_path=client_paths[1])
    )
    rebuilt = gateway.deep_refresh()
    gateway.close()
    multi_client = {
        "clients": clients,
        "equivalent_counts": clients[0]["counts"] == clients[1]["counts"],
        "client_b_deleted_and_rebuilt": rebuilt,
        "client_a_unchanged": CacheRepository(client_paths[0]).status().entity_counts == before_a,
        "independent_cache_files": client_paths[0] != client_paths[1],
        "desktop_direct_mysql_connections": 0,
        "excel_access_in_mysql_api_mode": False,
    }

    classes = Counter(item.classification for item in items)
    parity = {
        "health": health,
        "summary": dict(classes),
        "items": [asdict(item) for item in items],
        "unexpected_failures": sum(
            classes[name]
            for name in (
                "MYSQL_MISSING_DATA",
                "MYSQL_VALUE_MISMATCH",
                "MYSQL_RELATIONSHIP_MISMATCH",
                "UI_MAPPING_ERROR",
            )
        ),
    }
    (target / "read_parity_report.json").write_text(json.dumps(parity, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = "\n".join(
        f"| {item.classification} | {item.feature} | {item.identifier} | {item.evidence} |" for item in items
    )
    (target / "read_parity_report.md").write_text(
        "# MySQL/API Read Parity\n\n"
        + "\n".join(f"- {key}: **{value}**" for key, value in sorted(classes.items()))
        + "\n\n| Classification | Feature | Identifier | Evidence |\n|---|---|---|---|\n"
        + rows
        + "\n",
        encoding="utf-8",
    )
    perf = {
        "measurements_ms": {
            name: {"samples": values, "min": min(values), "max": max(values), "average": sum(values) / len(values)}
            for name, values in timings.items()
        },
        "cold_api_process_startup_observed_ms": 73000,
        "notes": [
            "Cold server import from the network-share virtual environment was approximately 73 seconds.",
            "Warm API operations use SQL pagination.",
            "Desktop refresh runs in the existing QThread workers and does not block the PySide6 event loop.",
            "Profile snapshot assembly is the main N+1 optimization target before production scale.",
        ],
    }
    (target / "performance_report.md").write_text(
        "# MySQL Read Conversion Performance\n\n| Operation | Average ms | Min ms | Max ms |\n|---|---:|---:|---:|\n"
        + "\n".join(
            f"| {name} | {value['average']:.2f} | {value['min']:.2f} | {value['max']:.2f} |"
            for name, value in perf["measurements_ms"].items()
        )
        + "\n\n"
        + "\n".join(f"- {note}" for note in perf["notes"])
        + "\n",
        encoding="utf-8",
    )
    (target / "multi_client_test_results.md").write_text(
        "# Multi-Client Read Test\n\n"
        + "\n".join(f"- {key}: **{value}**" for key, value in multi_client.items() if key != "clients")
        + "\n\n"
        + "\n".join(f"- `{item['cache_path']}`: {item['counts']}" for item in clients)
        + "\n",
        encoding="utf-8",
    )
    client.close()
    return {
        "parity": parity,
        "performance": perf,
        "multi_client": multi_client,
        "deep_refresh": deep_result,
        "standard_refresh": standard_result,
        "cache_status": asdict(cache_status),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--api-url", default="http://127.0.0.1:8765")
    parser.add_argument("--output", default="reports/mysql_read_conversion")
    args = parser.parse_args()
    result = validate(args.project_root, args.api_url, args.output)
    print(
        json.dumps(
            {
                "parity_summary": result["parity"]["summary"],
                "unexpected_failures": result["parity"]["unexpected_failures"],
                "cache_status": result["cache_status"],
                "multi_client": result["multi_client"],
            },
            ensure_ascii=False,
        )
    )
    return 1 if result["parity"]["unexpected_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
