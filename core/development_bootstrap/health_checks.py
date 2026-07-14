from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def get_json(url: str, *, timeout: float = 2.0) -> dict | None:
    try:
        with urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed localhost development URL
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, HTTPError, URLError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def wait_for(check, *, timeout: float, interval: float = 0.25):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = check()
        if last:
            return last
        time.sleep(interval)
    return last
