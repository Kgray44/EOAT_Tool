from __future__ import annotations

import json
from pathlib import Path

from release_tools.versioning import Version, read_canonical_version, validate_version_sources


ROOT = Path(__file__).resolve().parents[1]


def test_exhaustive_project_mirrorline_review_has_one_finalized_patch_release() -> None:
    documentation = (ROOT / "docs" / "PROJECT_MIRRORLINE.md").read_text(encoding="utf-8")
    ledger = json.loads((ROOT / "release_history.json").read_text(encoding="utf-8"))
    finalized_023 = [
        entry
        for entry in ledger["releases"]
        if entry.get("application_version") == "0.23.0" and entry.get("state") == "finalized"
    ]
    finalized_0231 = [
        entry
        for entry in ledger["releases"]
        if entry.get("application_version") == "0.23.1" and entry.get("state") == "finalized"
    ]
    assert "**Current state: the exhaustive Mirrorline review candidate is validated" in documentation
    assert len(finalized_023) == 1
    assert len(finalized_0231) == 1
    assert finalized_0231[0].get("task_id") == "codex-project-mirrorline-exhaustive-parity-20260727"
    assert read_canonical_version(ROOT) == Version.parse("0.23.1")
    assert validate_version_sources(ROOT) == read_canonical_version(ROOT)
