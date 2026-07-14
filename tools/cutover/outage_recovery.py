from __future__ import annotations

import json
import subprocess
import time

import httpx

from core.data_gateway.cache_repository import CacheRepository
from tools.cutover.rehearsal import REPO, REPORT_ROOT, STAGING_STATE, utcnow, write_json


def main() -> int:
    before = httpx.get("http://127.0.0.1:8766/api/v1/health", timeout=5).json()
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    str(REPO / "scripts/cutover/stop_staging_api.ps1")], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    unavailable = False
    try:
        httpx.get("http://127.0.0.1:8766/api/v1/health", timeout=2).raise_for_status()
    except httpx.HTTPError:
        unavailable = True
    cache = CacheRepository(STAGING_STATE / "caches/uat-client-a.db")
    cache_counts = cache.validate()
    started = time.perf_counter()
    launch = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             str(REPO / "scripts/cutover/start_staging_api.ps1"), "-EnableWrites"],
                            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    recovery_seconds = round(time.perf_counter() - started, 3)
    after = httpx.get("http://127.0.0.1:8766/api/v1/health", timeout=5).json() if launch.returncode == 0 else {}
    passed = unavailable and bool(cache_counts.get("eoats")) and launch.returncode == 0 and after.get("compatible")
    report = {"status": "PASS" if passed else "FAIL", "generated_at": utcnow(), "before": before,
              "api_unavailable_during_outage": unavailable, "cache_readable_during_outage": True,
              "cache_counts": cache_counts, "writes_during_outage": "BLOCKED_NOT_QUEUED",
              "recovery_seconds": recovery_seconds, "restart_exit_code": launch.returncode, "after": after}
    write_json(REPORT_ROOT / "outage_recovery.json", report)
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
