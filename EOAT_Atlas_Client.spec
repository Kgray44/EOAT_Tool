# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path.cwd()
datas = []
binaries = []
hiddenimports = collect_submodules("app.atlas")


def add_tree(folder_name: str, destination: str, suffixes: set[str] | None = None) -> None:
    source = ROOT / folder_name
    if not source.exists():
        return
    for path in source.rglob("*"):
        if path.is_file() and (suffixes is None or path.suffix.casefold() in suffixes):
            datas.append((str(path), str(Path(destination) / path.relative_to(source).parent)))


add_tree("data_templates", "data_templates")
add_tree("templates", "templates")
add_tree("docs", "docs", {".md", ".txt"})
if (ROOT / "config/config.example.json").exists():
    datas.append((str(ROOT / "config/config.example.json"), "config"))
if (ROOT / "app/atlas/version.json").exists():
    datas.append((str(ROOT / "app/atlas/version.json"), "app/atlas"))
hiddenimports += collect_submodules("pillow_heif")
datas += collect_data_files("pillow_heif")
binaries += collect_dynamic_libs("pillow_heif")
hiddenimports += ["matplotlib.backends.backend_qtagg"]

a = Analysis(
    ["run_atlas.py"], pathex=[str(ROOT)], binaries=binaries, datas=datas,
    hiddenimports=sorted(set(hiddenimports)), hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="EOAT Atlas", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=True, console=False,
    disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
    codesign_identity=None, entitlements_file=None, icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, upx_exclude=[], name="EOAT Atlas")
