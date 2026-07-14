# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).resolve()
a = Analysis(["launcher/eoat_atlas_launcher.py"], pathex=[str(ROOT)], datas=[], hiddenimports=["release_tools.launcher", "release_tools.manifest", "release_tools.versioning"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="EOAT Atlas Launcher", console=True, debug=False, strip=False, upx=True)
