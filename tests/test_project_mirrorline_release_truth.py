from __future__ import annotations

import json
from pathlib import Path

from release_tools.versioning import Version, read_canonical_version, validate_version_sources


ROOT = Path(__file__).resolve().parents[1]


def test_accepted_project_mirrorline_has_one_finalized_023_release() -> None:
    documentation = (ROOT / "docs" / "PROJECT_MIRRORLINE.md").read_text(encoding="utf-8")
    ledger = json.loads((ROOT / "release_history.json").read_text(encoding="utf-8"))
    finalized_023 = [
        entry
        for entry in ledger["releases"]
        if entry.get("application_version") == "0.23.0" and entry.get("state") == "finalized"
    ]
    assert "**Current state: Phase 2 acceptance-complete" in documentation
    assert len(finalized_023) == 1
    assert read_canonical_version(ROOT) == Version.parse("0.23.0")
    assert validate_version_sources(ROOT) == read_canonical_version(ROOT)
