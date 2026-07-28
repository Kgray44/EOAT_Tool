"""EOAT Atlas bootstrapper: stable launcher selection and recovery only."""

from __future__ import annotations

import json
from pathlib import Path

BOOTSTRAP_NAME = "EOAT Atlas Bootstrap"
BOOTSTRAP_VERSION = str(
    json.loads(Path(__file__).with_name("bootstrap_version.json").read_text(encoding="utf-8"))["bootstrap_version"]
)

__all__ = ["BOOTSTRAP_NAME", "BOOTSTRAP_VERSION"]
