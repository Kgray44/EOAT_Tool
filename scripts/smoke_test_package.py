from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    exe = ROOT / "dist" / "EOAT Command Center" / "EOAT Command Center.exe"
    if not exe.exists():
        print(f"Packaged executable not found: {exe}")
        return 1
    env = os.environ.copy()
    env["EOAT_COMMAND_CENTER_SMOKE_TEST"] = "1"
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    timeout_seconds = int(os.environ.get("EOAT_COMMAND_CENTER_PACKAGE_SMOKE_TIMEOUT_SECONDS", "90"))
    try:
        completed = subprocess.run([str(exe), "--smoke-test"], cwd=Path.home(), env=env, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        print(f"Packaged app did not exit within {timeout_seconds} seconds.")
        return 1
    print(f"Smoke test exit code: {completed.returncode}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
