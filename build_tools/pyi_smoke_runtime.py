from __future__ import annotations

import os
import sys
import threading


def _smoke_requested() -> bool:
    return "--smoke-test" in sys.argv or os.environ.get("EOAT_COMMAND_CENTER_SMOKE_TEST") == "1"


if _smoke_requested():
    timeout_seconds = float(os.environ.get("EOAT_COMMAND_CENTER_SMOKE_FORCE_EXIT_SECONDS", "45"))
    timer = threading.Timer(timeout_seconds, lambda: os._exit(0))
    timer.daemon = True
    timer.start()
