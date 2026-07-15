# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

ROOT = Path.cwd()

datas = [
    (str(ROOT / "launcher" / "default_config.json"), "launcher"),
    (str(ROOT / "launcher" / "launcher_version.json"), "launcher"),
    (str(ROOT / "app" / "atlas" / "version.json"), "app/atlas"),
]

a = Analysis(
    ["packaging/eoat_atlas_launcher_entry.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="EOAT Atlas Launcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
