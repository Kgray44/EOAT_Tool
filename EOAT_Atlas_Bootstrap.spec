# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path.cwd()
a = Analysis(["packaging/eoat_atlas_bootstrap_entry.py"], pathex=[str(ROOT)], binaries=[], datas=[(str(ROOT / "bootstrap" / "bootstrap_version.json"), "bootstrap"), (str(ROOT / "release_trust" / "production_manifest_keys.json"), "release_trust")], hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="EOAT Atlas Bootstrap", debug=False, bootloader_ignore_signals=False, strip=False, upx=False, upx_exclude=[], console=False)
