from __future__ import annotations

import argparse
import builtins
import io
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.data_gateway.api_client import AtlasApiClient
from core.data_gateway.cache_repository import CacheRepository
from core.data_gateway.configuration import GatewayConfiguration
from core.data_gateway.exceptions import ApiUnavailableError
from core.data_gateway.gateway import AtlasDataGateway
from core.eoat_history import EOATHistoryService, GatewayEOATHistoryRepository
from core.library_data_service import LibraryDataService
from core.reporting.eoat_history_pdf import export_eoat_history_pdf


class OfflineClient:
    def health(self):
        raise ApiUnavailableError("controlled offline validation")

    def close(self):
        pass


def measured(callable_):
    started = time.perf_counter()
    value = callable_()
    return value, round((time.perf_counter() - started) * 1000, 3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8765")
    parser.add_argument("--eoat", default="P4-EOAT-0001")
    parser.add_argument("--cache", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pdf-output", required=True)
    args = parser.parse_args()

    cache_path = Path(args.cache)
    for candidate in (cache_path, Path(str(cache_path) + ".previous"), Path(str(cache_path) + ".building")):
        candidate.unlink(missing_ok=True)
    config = GatewayConfiguration(backend="mysql_api", api_base_url=args.api_url, cache_path=cache_path)
    excel_attempts: list[str] = []
    real_open = builtins.open
    real_io_open = io.open

    def guarded_open(file, *open_args, **open_kwargs):
        if str(file).casefold().endswith((".xlsx", ".xlsm", ".xls")):
            excel_attempts.append(str(file))
            raise AssertionError("History validation attempted to open Excel")
        return real_open(file, *open_args, **open_kwargs)

    def guarded_io_open(file, *open_args, **open_kwargs):
        if str(file).casefold().endswith((".xlsx", ".xlsm", ".xls")):
            excel_attempts.append(str(file))
            raise AssertionError("History validation attempted to open Excel")
        return real_io_open(file, *open_args, **open_kwargs)

    builtins.open = guarded_open
    io.open = guarded_io_open
    try:
        client = AtlasApiClient(args.api_url)
        first_page, api_page_ms = measured(lambda: client.get_eoat_history(args.eoat, page=1, page_size=5))
        searched_page, api_search_ms = measured(
            lambda: client.get_eoat_history(args.eoat, page=1, page_size=5, search="audit")
        )
        client.close()
        gateway = AtlasDataGateway(config, cache=CacheRepository(cache_path))
        online_events, gateway_all_pages_ms = measured(lambda: gateway.get_eoat_history(args.eoat))
        online_ids = [item["event_id"] for item in online_events]
        cache_path.unlink(missing_ok=True)
        deep_result, cache_rebuild_ms = measured(gateway.deep_refresh)
        standard_result, standard_refresh_ms = measured(gateway.refresh)
        rebuilt_events = gateway.cache.get_eoat_history(args.eoat)
        rebuilt_ids = [item["event_id"] for item in rebuilt_events]
        bundle, bundle_mapping_ms = measured(lambda: gateway.load_bundle(str(ROOT)))
        library_root = cache_path.parent / "eoat_history_library_validation"
        library_root.mkdir(parents=True, exist_ok=True)
        library = LibraryDataService(library_root)
        library.rebuild_index_from_bundle(replace(bundle, project_root=str(library_root)))
        detail = library.get_record_detail_data("eoat", args.eoat)
        gateway.close()

        offline = AtlasDataGateway(config, client=OfflineClient(), cache=CacheRepository(cache_path))
        offline_events, offline_read_ms = measured(lambda: offline.get_eoat_history(args.eoat))
        offline.close()

        os.environ.update(
            {
                "EOAT_ATLAS_DATA_BACKEND": "mysql_api",
                "EOAT_ATLAS_API_URL": args.api_url,
                "EOAT_ATLAS_API_CACHE": str(cache_path),
            }
        )
        view, service_mapping_ms = measured(
            lambda: EOATHistoryService(GatewayEOATHistoryRepository()).history_for(args.eoat)
        )
        service = EOATHistoryService(GatewayEOATHistoryRepository())
        filtered, filter_ms = measured(lambda: service.filter_events(view.events, search="audit"))
        _, selection_ms = measured(lambda: view.events[0] if view.events else None)
        export_model = service.export_model(args.eoat, view.events)
        pdf_path = Path(args.pdf_output)
        pdf_result, pdf_ms = measured(lambda: export_eoat_history_pdf(detail, export_model, pdf_path))

        try:
            import pypdf

            pdf_pages = len(pypdf.PdfReader(str(pdf_result)).pages)
        except ImportError:
            pdf_pages = None
    finally:
        builtins.open = real_open
        io.open = real_io_open

    result = {
        "status": "PASS" if online_ids == rebuilt_ids and online_ids else "FAIL",
        "api_url": args.api_url,
        "eoat_identifier": args.eoat,
        "api_page": first_page.get("pagination", {}),
        "online_event_count": len(online_events),
        "rebuilt_event_count": len(rebuilt_events),
        "offline_event_count": len(offline_events),
        "history_survives_cache_deletion": online_ids == rebuilt_ids and bool(online_ids),
        "offline_delivery_marked": bool(offline_events) and offline_events[0].get("metadata", {}).get("delivery_mode") == "offline_cache",
        "excel_open_attempts": excel_attempts,
        "deep_refresh": deep_result,
        "standard_refresh": standard_result,
        "filter_match_count": len(filtered),
        "api_search_match_count": searched_page.get("pagination", {}).get("total", 0),
        "pdf": {"path": str(pdf_result), "pages": pdf_pages, "event_count": export_model.total_events},
        "timings_ms": {
            "api_first_page": api_page_ms,
            "api_search": api_search_ms,
            "gateway_all_pages": gateway_all_pages_ms,
            "cache_rebuild": cache_rebuild_ms,
            "standard_refresh": standard_refresh_ms,
            "bundle_mapping": bundle_mapping_ms,
            "offline_cache_read": offline_read_ms,
            "service_mapping": service_mapping_ms,
            "filter": filter_ms,
            "event_selection": selection_ms,
            "pdf_generation": pdf_ms,
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" and not excel_attempts else 1


if __name__ == "__main__":
    raise SystemExit(main())
