from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_browser_theme_tokens_match_minimalist_authority() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/export_minimalist_theme_tokens.py", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
