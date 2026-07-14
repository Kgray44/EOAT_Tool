from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
raise SystemExit(subprocess.run([
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
    "--distpath", str(ROOT / "dist" / "launcher"),
    "--workpath", str(ROOT / "build" / "launcher"),
    str(ROOT / "EOAT_Atlas_Launcher.spec"),
], cwd=ROOT).returncode)
