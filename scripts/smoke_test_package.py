from __future__ import annotations

import os
import subprocess
import time
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
    proc = subprocess.Popen([str(exe), "--smoke-test"], cwd=Path.home(), env=env, shell=False)
    startup_seconds = int(os.environ.get("EOAT_COMMAND_CENTER_PACKAGE_SMOKE_SECONDS", "45"))
    deadline = time.monotonic() + startup_seconds
    while time.monotonic() < deadline:
        code = proc.poll()
        if code is not None:
            print(f"Packaged app exited during smoke startup with code: {code}")
            return code
        time.sleep(1)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
    print(f"Packaged app stayed alive for {startup_seconds} seconds; smoke process terminated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
