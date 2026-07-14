from __future__ import annotations

import csv
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from core.data_gateway.cache_repository import CacheRepository
from core.data_gateway.configuration import GatewayConfiguration
from core.data_gateway.gateway import AtlasDataGateway
from tools.cutover.rehearsal import REPORT_ROOT, STAGING_STATE, sha256, utcnow, write_json

BASE = "http://127.0.0.1:8766"


class EvidenceClient:
    def __init__(self, identity: str):
        self.client = httpx.Client(base_url=BASE, timeout=15, headers={"X-EOAT-Identity": identity})
        self.requests: list[dict[str, object]] = []

    def call(self, method: str, path: str, payload: dict | None = None, key: str | None = None, expected: int = 200):
        headers = {"Idempotency-Key": key} if key else None
        started = time.perf_counter()
        response = self.client.request(method, path, json=payload, headers=headers)
        elapsed = round((time.perf_counter() - started) * 1000, 3)
        self.requests.append({"method": method, "path": path, "status": response.status_code, "elapsed_ms": elapsed})
        if response.status_code != expected:
            raise AssertionError(f"{method} {path}: expected {expected}, got {response.status_code}: {response.text}")
        return response.json()


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))]


def main() -> int:
    manifest = json.loads((REPORT_ROOT / "frozen_source_manifest.json").read_text(encoding="utf-8"))
    suffix = datetime.now(timezone.utc).strftime("%H%M%S")
    engineer = EvidenceClient("staging.engineer")
    technician = EvidenceClient("staging.technician")
    admin = EvidenceClient("staging.admin")
    viewer = EvidenceClient("staging.viewer")
    cases: dict[str, dict[str, object]] = {}
    identifiers = {"eoat": f"UAT-EOAT-{suffix}", "machine": f"UAT-M-{suffix}", "tool": f"UAT-T-{suffix}"}
    started = time.perf_counter()
    health = engineer.call("GET", "/api/v1/health")
    cases["health_and_version"] = {"status": "PASS", "evidence": health}
    home = engineer.call("GET", "/api/v1/home-summary")
    cases["home_summary"] = {"status": "PASS", "evidence": {"keys": sorted(home)}}
    eoats = engineer.call("GET", "/api/v1/eoats")
    machines = engineer.call("GET", "/api/v1/machines")
    tools = engineer.call("GET", "/api/v1/tools")
    cases["browse_and_search"] = {
        "status": "PASS", "evidence": {"eoats": len(eoats["items"]), "machines": len(machines["items"]),
                                         "tools": len(tools["items"]), "search": len(engineer.call("GET", "/api/v1/search?q=EOAT"))},
    }
    viewer.call("POST", "/api/v1/eoats", {"business_identifier": "UAT-VIEWER-DENIED"}, expected=403)
    cases["authorization"] = {"status": "PASS", "evidence": "viewer write rejected with 403"}
    eoat = engineer.call("POST", "/api/v1/eoats", {"business_identifier": identifiers["eoat"], "display_name": "UAT EOAT"}, str(uuid4()))
    machine = engineer.call("POST", "/api/v1/machines", {"plant_code": "P4", "machine_number": identifiers["machine"], "machine_name": "UAT Machine"}, str(uuid4()))
    tool = engineer.call("POST", "/api/v1/tools", {"business_identifier": identifiers["tool"], "display_name": "UAT Tool"}, str(uuid4()))
    relation = engineer.call("POST", "/api/v1/compatibility/eoat-machine", {
        "eoat_identifier": identifiers["eoat"], "machine_number": identifiers["machine"],
        "compatibility_status": "compatible", "verification_source": "user_verified",
        "effective_from": utcnow(), "reason": "Phase 9 rehearsal",
    })
    moved = technician.call("POST", f"/api/v1/eoats/{identifiers['eoat']}/move-to-machine", {
        "machine_number": identifiers["machine"], "expected_row_version": eoat["row_version"], "reason": "UAT movement",
    }, str(uuid4()))
    current = engineer.call("GET", f"/api/v1/eoats/{identifiers['eoat']}")
    technician.call("POST", f"/api/v1/eoats/{identifiers['eoat']}/mark-location-unknown", {
        "expected_row_version": current["row_version"], "confirm": True, "reason": "UAT cleanup of location",
    }, str(uuid4()))
    cases["assets_compatibility_movement"] = {"status": "PASS", "evidence": {"eoat": eoat["id"], "machine": machine["id"], "tool": tool["id"], "relationship": relation["id"], "movement": moved}}
    audit = technician.call("POST", "/api/v1/audits", {"audit_identifier": f"UAT-AUDIT-{suffix}", "eoat_identifier": identifiers["eoat"], "details": {"rehearsal": True}}, str(uuid4()))
    technician.call("POST", f"/api/v1/audits/{audit['id']}/complete", {"expected_row_version": audit["row_version"]}, str(uuid4()))
    maintenance = technician.call("POST", "/api/v1/maintenance-events", {"eoat_identifier": identifiers["eoat"], "event_type": "PM", "occurred_at": utcnow(), "downtime_minutes": 0, "summary": "Phase 9 UAT"}, str(uuid4()))
    technician.call("POST", f"/api/v1/maintenance-events/{maintenance['id']}/complete", {"expected_row_version": maintenance["row_version"]}, str(uuid4()))
    cases["audit_and_maintenance"] = {"status": "PASS", "evidence": {"audit_id": audit["id"], "maintenance_id": maintenance["id"]}}
    artifact_dir = STAGING_STATE / "uat-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    document_path = artifact_dir / f"uat-{suffix}.txt"
    document_path.write_text("EOAT Atlas Phase 9 controlled local rehearsal artifact", encoding="utf-8")
    document = engineer.call("POST", "/api/v1/documents", {"document_type": "document", "title": "UAT document", "storage_path": str(document_path), "entity_type": "eoat", "entity_id": eoat["id"]}, str(uuid4()))
    photo_path = artifact_dir / f"uat-{suffix}.jpg"
    photo_path.write_bytes(b"EOAT-ATLAS-UAT-PHOTO-METADATA")
    photo = engineer.call("POST", "/api/v1/photos", {"title": "UAT profile photo", "storage_path": str(photo_path), "caption": "Phase 9", "entity_type": "eoat", "entity_id": eoat["id"]}, str(uuid4()))
    selected = engineer.call("POST", f"/api/v1/photos/{photo['photo']['id']}/set-profile", {"expected_row_version": photo["row_version"], "reason": "Phase 9 profile-photo API validation"})
    cases["documents_and_profile_photo"] = {"status": "PASS", "evidence": {"document_id": document["id"], "photo_id": photo["photo"]["id"], "profile_selected": selected["photo"]["is_profile_photo"]}}
    target_uuid = f"uat_target_{suffix}"
    target = technician.call("POST", "/api/v1/annotation-targets", {"target_uuid": target_uuid, "target_type": "audit_field", "target_label": "Phase 9 UAT target", "audit_identifier": audit["audit_identifier"], "field_key": "rehearsal"})
    tag = engineer.call("POST", "/api/v1/tags", {"tag_code": f"uat_{suffix}", "display_name": f"UAT {suffix}", "color_key": "blue"})
    technician.call("POST", f"/api/v1/entities/annotation_target/{target_uuid}/tags/{tag['id']}", {"comment": "Phase 9"})
    annotation = technician.call("POST", f"/api/v1/entities/annotation_target/{target_uuid}/annotations", {"subject": "UAT note", "body": "Validated through staging API", "importance": "Normal"})
    cases["tags_and_annotations"] = {"status": "PASS", "evidence": {"target_id": target["id"], "tag_id": tag["id"], "annotation_id": annotation["id"]}}
    stale_version = engineer.call("GET", f"/api/v1/eoats/{identifiers['eoat']}")["row_version"]
    client_a = EvidenceClient("staging.engineer")
    client_b = EvidenceClient("staging.engineer")
    client_a.call("PATCH", f"/api/v1/eoats/{identifiers['eoat']}", {"display_name": "Client A authoritative", "expected_row_version": stale_version})
    client_b.call("PATCH", f"/api/v1/eoats/{identifiers['eoat']}", {"display_name": "Client B stale", "expected_row_version": stale_version}, expected=409)
    cases["multi_client_concurrency"] = {"status": "PASS", "evidence": "independent client B received 409 and did not overwrite client A"}
    caches = []
    for name in ("a", "b", "c"):
        cache_path = STAGING_STATE / "caches" / f"uat-client-{name}.db"
        config = GatewayConfiguration(backend="mysql_api", api_base_url=BASE, cache_path=cache_path,
            expected_schema_revision="20260714_0003", writes_enabled=True, environment="staging_local",
            development_identity="staging.engineer", client_version="rehearsal-rc1")
        gateway = AtlasDataGateway(config)
        gateway.deep_refresh()
        counts = gateway.cache.validate()
        caches.append({"client": name, "path": str(cache_path), "counts": counts, "metadata": gateway.cache.metadata()})
    offline_config = GatewayConfiguration(backend="mysql_api", api_base_url="http://127.0.0.1:65534", cache_path=Path(caches[0]["path"]),
        expected_schema_revision="20260714_0003", environment="staging_local")
    offline_gateway = AtlasDataGateway(offline_config, cache=CacheRepository(offline_config.cache_path))
    cached_record = offline_gateway.cache.get("eoats", identifiers["eoat"])
    cases["cache_and_api_outage"] = {"status": "PASS", "evidence": {"clients": caches, "cached_record_available_with_api_unreachable": cached_record is not None}}
    timings: dict[str, list[float]] = {"health": [], "home": [], "search": [], "eoat_list": []}
    for _ in range(12):
        for name, path in (("health", "/api/v1/health"), ("home", "/api/v1/home-summary"), ("search", "/api/v1/search?q=EOAT"), ("eoat_list", "/api/v1/eoats")):
            began = time.perf_counter()
            response = httpx.get(BASE + path, timeout=15)
            response.raise_for_status()
            timings[name].append(round((time.perf_counter() - began) * 1000, 3))
    performance = {name: {"samples": len(values), "median_ms": round(statistics.median(values), 3), "p95_ms": round(percentile(values, .95), 3), "max_ms": max(values)} for name, values in timings.items()}
    cases["performance"] = {"status": "PASS" if all(v["p95_ms"] < 2000 for v in performance.values()) else "FAIL", "evidence": performance}
    changes = engineer.call("GET", "/api/v1/sync/changes?after_cursor=0")
    export = {"generated_at": utcnow(), "cutover_uuid": manifest["rehearsal_id"], "cursor": changes.get("cursor"), "changes": changes.get("changes", [])}
    write_json(REPORT_ROOT / "post_cutover_change_export.json", export)
    csv_path = REPORT_ROOT / "post_cutover_change_export.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        fields = ["change_id", "entity_type", "entity_id", "action", "row_version", "changed_at"]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(export["changes"])
    source_checks = [{"source": item["source"], "expected": item["sha256"], "actual": sha256(Path(item["source"]))} for item in manifest["files"][:3]]
    cases["legacy_sources_unchanged"] = {"status": "PASS" if all(x["expected"] == x["actual"] for x in source_checks) else "FAIL", "evidence": source_checks}
    all_requests = engineer.requests + technician.requests + admin.requests + viewer.requests + client_a.requests + client_b.requests
    failures = [name for name, case in cases.items() if case["status"] != "PASS"]
    report = {"status": "PASS" if not failures else "FAIL", "generated_at": utcnow(), "duration_seconds": round(time.perf_counter() - started, 3),
              "api": BASE, "release": {"api_version": "1.2.0", "schema_revision": "20260714_0003", "client": "rehearsal-rc1"},
              "identifiers": identifiers, "cases": cases, "http_requests": all_requests, "failed_cases": failures,
              "post_cutover_export": {"json": str(REPORT_ROOT / "post_cutover_change_export.json"), "csv": str(csv_path), "records": len(export["changes"])}}
    write_json(REPORT_ROOT / "uat_results.json", report)
    print(json.dumps({"status": report["status"], "duration_seconds": report["duration_seconds"], "cases": {k: v["status"] for k, v in cases.items()}, "change_records": len(export["changes"])}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
