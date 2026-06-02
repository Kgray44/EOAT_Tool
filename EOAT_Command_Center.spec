# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path.cwd()

datas = []
binaries = []
hiddenimports = []


def add_tree(folder_name: str, destination: str, *, suffixes: set[str] | None = None) -> None:
    source = ROOT / folder_name
    if not source.exists():
        return
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        if suffixes is not None and path.suffix.casefold() not in suffixes:
            continue
        relative_parent = path.relative_to(source).parent
        datas.append((str(path), str(Path(destination) / relative_parent)))


add_tree("data_templates", "data_templates")
add_tree("templates", "templates")
add_tree("docs", "docs", suffixes={".md", ".txt"})

config_example = ROOT / "config" / "config.example.json"
if config_example.exists():
    datas.append((str(config_example), "config"))

hiddenimports += collect_submodules("app.pages")
hiddenimports += collect_submodules("app.settings_page")
hiddenimports += collect_submodules("app.widgets")
hiddenimports += [
    "daily_status_summary",
    "matplotlib.backends.backend_qtagg",
]
hiddenimports = sorted(set(hiddenimports))


a = Analysis(
    ["app/main.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["build_tools/pyi_smoke_runtime.py"],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EOAT Command Center",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="EOAT Command Center",
)
