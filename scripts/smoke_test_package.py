from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    exe = ROOT / "dist" / "EOAT_Command_Center" / "EOAT_Command_Center.exe"
    if not exe.exists():
        print(f"Packaged executable not found: {exe}")
        return 1
    env = os.environ.copy()
    env["EOAT_COMMAND_CENTER_SMOKE_TEST"] = "1"
    proc = subprocess.run([str(exe)], cwd=Path.home(), env=env, timeout=60, shell=False)
    print(f"Smoke test exit code: {proc.returncode}")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
