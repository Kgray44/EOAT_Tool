from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    pyinstaller = shutil.which("pyinstaller")
    if not pyinstaller:
        print("PyInstaller is not installed. Install it with:")
        print("python -m pip install pyinstaller")
        print("Then rerun: python scripts/build_package.py")
        return 1
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(ROOT / "EOAT_Command_Center.spec"),
    ]
    print("Running:", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, shell=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
