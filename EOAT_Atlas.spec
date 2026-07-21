# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build_tools.version_metadata import write_windows_version_file

metadata_override = os.environ.get("EOAT_ATLAS_BUILD_METADATA", "").strip()
if not metadata_override:
    raise RuntimeError("EOAT_ATLAS_BUILD_METADATA must name generated release metadata")
METADATA_PATH = Path(metadata_override)
VERSION_FILE = write_windows_version_file(ROOT, ROOT / "build" / "eoat_atlas_version_info.txt")
datas = [(str(METADATA_PATH), ".")]
for configuration_file in (ROOT / "config" / "production.json",):
    if not configuration_file.is_file():
        raise RuntimeError(f"Required packaged configuration is missing: {configuration_file}")
    datas.append((str(configuration_file), "config"))
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


add_tree("app/atlas/logo", "app/atlas/logo")
add_tree("assets/icons", "assets/icons", suffixes={".png", ".ico", ".svg", ".md"})

hiddenimports += collect_submodules("app.atlas.minimalist")
hiddenimports += collect_submodules("core.globalization")
hiddenimports += collect_submodules("core.reporting")
hiddenimports += collect_submodules("pillow_heif")
datas += collect_data_files("pillow_heif")
binaries += collect_dynamic_libs("pillow_heif")
hiddenimports += [
    "matplotlib.backends.backend_qtagg",
]
hiddenimports = sorted(set(hiddenimports))


a = Analysis(
    ["packaging/eoat_atlas_entry.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name="EOAT Atlas",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "app" / "atlas" / "logo" / "EOAT Atlas Logo Rounded.png"),
    version=str(VERSION_FILE),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="EOAT Atlas",
)
