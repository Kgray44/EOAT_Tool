from __future__ import annotations

import json
from pathlib import Path

from release_tools.versioning import Version, read_canonical_version, validate_version_sources


ROOT = Path(__file__).resolve().parents[1]


def test_incomplete_project_mirrorline_never_claims_a_finalized_023_release() -> None:
    documentation = (ROOT / "docs" / "PROJECT_MIRRORLINE.md").read_text(encoding="utf-8")
    ledger = json.loads((ROOT / "release_history.json").read_text(encoding="utf-8"))
    finalized_023 = [
        entry
        for entry in ledger["releases"]
        if entry.get("application_version") == "0.23.0" and entry.get("state") == "finalized"
    ]
    assert "**Current state: implementation candidate, not an accepted or deployed" in documentation
    assert finalized_023 == []
    assert read_canonical_version(ROOT) == Version.parse("0.22.12")
    assert validate_version_sources(ROOT) == read_canonical_version(ROOT)
